import hashlib
import os
import re
import stat
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

from fastapi import HTTPException, status
from sqlalchemy import and_, func, or_, text
from sqlalchemy.orm import Session

import models

UPLOAD_QUOTA_BYTES = 1024 * 1024 * 1024
UPLOAD_RATE_LIMIT = 20
UPLOAD_RATE_WINDOW = timedelta(minutes=5)
PENDING_LIFETIME = timedelta(hours=24)
DELETED_TOMBSTONE_LIFETIME = timedelta(hours=24)
ORPHAN_GRACE_PERIOD = timedelta(hours=24)
RECONCILE_BATCH_SIZE = 100

COUNTED_QUOTA_STATES = ("PENDING", "ACTIVE", "DELETE_PENDING")
OBJECT_KEY_PATTERN = re.compile(
    r"^objects/(?P<prefix>[0-9a-f]{2})/(?P<object_id>[0-9a-f]{32})"
    r"(?P<extension>\.[a-z0-9]{1,10})$"
)


def _as_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def canonical_object_key(reference: str) -> str:
    if not isinstance(reference, str) or len(reference) > 2048:
        raise ValueError("Invalid upload reference")
    prefix = "/api/uploads/"
    if not reference.startswith(prefix):
        raise ValueError("Invalid upload reference")
    key = reference.removeprefix(prefix)
    match = OBJECT_KEY_PATTERN.fullmatch(key)
    if match is None or match.group("prefix") != match.group("object_id")[:2]:
        raise ValueError("Invalid upload reference")
    return key


def object_url(storage_key: str) -> str:
    match = OBJECT_KEY_PATTERN.fullmatch(storage_key)
    if match is None or match.group("prefix") != match.group("object_id")[:2]:
        raise ValueError("Invalid storage key")
    return f"/api/uploads/{storage_key}"


def registered_object_path(upload_root: Path, storage_key: str) -> Path:
    """Resolve a canonical registry key without following it outside the root."""

    object_url(storage_key)
    configured_root = Path(upload_root)
    if _is_link(configured_root):
        raise ValueError("Invalid storage key")
    root = configured_root.resolve(strict=True)
    candidate = root
    for part in Path(storage_key).parts:
        candidate /= part
        if _is_link(candidate):
            raise ValueError("Invalid storage key")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("Invalid storage key") from exc
    return candidate


def _registered_object_is_file(upload_root: Path, storage_key: str) -> bool:
    try:
        return registered_object_path(upload_root, storage_key).is_file()
    except (OSError, ValueError):
        return False


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


@dataclass
class OpenedRegisteredObject:
    descriptor: int | None
    stat_result: os.stat_result
    size_bytes: int
    sha256_digest: str

    def close(self) -> None:
        descriptor = self.descriptor
        if descriptor is None:
            return
        self.descriptor = None
        os.close(descriptor)

    def __del__(self) -> None:
        try:
            self.close()
        except OSError:
            pass


def _open_stable_file(path: Path) -> OpenedRegisteredObject | None:
    """Open and hash a stable, non-linked regular file without releasing its inode."""

    descriptor = None
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or _is_link(path):
            return None
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            os.close(descriptor)
            return None
        digest = hashlib.sha256()
        size_bytes = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        final_path = os.lstat(path)
        if (
            not os.path.samestat(opened, after)
            or not os.path.samestat(after, final_path)
            or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or size_bytes != opened.st_size
        ):
            os.close(descriptor)
            return None
        os.lseek(descriptor, 0, os.SEEK_SET)
        return OpenedRegisteredObject(
            descriptor=descriptor,
            stat_result=opened,
            size_bytes=size_bytes,
            sha256_digest=digest.hexdigest(),
        )
    except OSError:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        return None


def _stable_file_facts(path: Path) -> tuple[int, str] | None:
    """Return size/digest only for a stable, non-linked regular file."""

    opened = _open_stable_file(path)
    if opened is None:
        return None
    try:
        return opened.size_bytes, opened.sha256_digest
    finally:
        opened.close()


def open_verified_registered_object(
    upload_root: Path,
    *,
    storage_key: str,
    size_bytes: int,
    sha256_digest: str,
) -> OpenedRegisteredObject | None:
    """Return a pinned descriptor only when the registered object matches exactly."""

    try:
        path = registered_object_path(upload_root, storage_key)
    except (OSError, ValueError):
        return None
    opened = _open_stable_file(path)
    if opened is None:
        return None
    if (opened.size_bytes, opened.sha256_digest) != (size_bytes, sha256_digest):
        opened.close()
        return None
    return opened


def object_matches_registration(
    upload_root: Path,
    *,
    storage_key: str,
    size_bytes: int,
    sha256_digest: str,
) -> bool:
    try:
        path = registered_object_path(upload_root, storage_key)
    except (OSError, ValueError):
        return False
    return _stable_file_facts(path) == (size_bytes, sha256_digest)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _registered_staging_path(upload_root: Path, storage_key: str) -> Path:
    match = OBJECT_KEY_PATTERN.fullmatch(storage_key)
    if match is None or match.group("prefix") != match.group("object_id")[:2]:
        raise ValueError("Invalid storage key")
    configured_root = Path(upload_root)
    if _is_link(configured_root):
        raise ValueError("Invalid storage key")
    root = configured_root.resolve(strict=True)
    incoming_root = root / ".incoming"
    if _is_link(incoming_root):
        raise ValueError("Invalid storage key")
    candidate = incoming_root / f"{match.group('object_id')}.part"
    if _is_link(candidate):
        raise ValueError("Invalid storage key")
    try:
        candidate.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError("Invalid storage key") from exc
    return candidate


def _promote_registered_staging(upload_root: Path, asset: models.UploadAsset) -> None:
    match = OBJECT_KEY_PATTERN.fullmatch(asset.storage_key)
    if match is None:
        return
    final_path = registered_object_path(upload_root, asset.storage_key)
    staging_path = _registered_staging_path(upload_root, asset.storage_key)
    expected_facts = (asset.size_bytes, asset.sha256_digest)
    if _stable_file_facts(final_path) == expected_facts:
        if staging_path.is_file() and not _is_link(staging_path):
            staging_path.unlink(missing_ok=True)
        return
    if _stable_file_facts(staging_path) != expected_facts:
        return
    shard_created = False
    try:
        final_path.parent.mkdir(mode=0o700)
    except FileExistsError:
        pass
    else:
        shard_created = True
    if _is_link(final_path.parent):
        return
    if shard_created:
        _fsync_directory(final_path.parents[1])
    staging_path.replace(final_path)
    if os.name == "posix":
        final_path.chmod(0o600)
    os.utime(final_path, None)
    _fsync_directory(final_path.parent)


def _sweep_orphan_objects(db: Session, upload_root: Path, *, now: datetime) -> None:
    root = Path(upload_root)
    cutoff = (now - ORPHAN_GRACE_PERIOD).timestamp()
    registered_keys = {
        storage_key
        for (storage_key,) in db.query(models.UploadAsset.storage_key).all()
    }
    objects_root = root / "objects"
    if objects_root.is_dir() and not _is_link(objects_root):
        deleted_count = 0
        for path in sorted(objects_root.glob("*/*")):
            try:
                relative_key = path.relative_to(root).as_posix()
                safe_path = registered_object_path(root, relative_key)
                if not safe_path.is_file() or safe_path.stat().st_mtime > cutoff:
                    continue
            except (OSError, ValueError):
                continue
            if relative_key in registered_keys:
                continue
            db.expire_all()
            registered = (
                db.query(models.UploadAsset.id)
                .filter(models.UploadAsset.storage_key == relative_key)
                .first()
            )
            if registered is None:
                safe_path.unlink(missing_ok=True)
                deleted_count += 1
                if deleted_count >= RECONCILE_BATCH_SIZE:
                    break

    incoming_root = root / ".incoming"
    if incoming_root.is_dir() and not _is_link(incoming_root):
        registered_object_ids = {
            match.group("object_id")
            for key in registered_keys
            if (match := OBJECT_KEY_PATTERN.fullmatch(key)) is not None
        }
        deleted_count = 0
        for path in sorted(incoming_root.glob("*.part")):
            if _is_link(path) or not path.is_file():
                continue
            object_id = path.stem
            if not re.fullmatch(r"[0-9a-f]{32}", object_id):
                continue
            try:
                if path.stat().st_mtime > cutoff:
                    continue
            except OSError:
                continue
            if object_id in registered_object_ids:
                continue
            key_pattern = f"objects/{object_id[:2]}/{object_id}.%"
            db.expire_all()
            registered = (
                db.query(models.UploadAsset.storage_key)
                .filter(models.UploadAsset.storage_key.like(key_pattern))
                .first()
            )
            if registered is None:
                path.unlink(missing_ok=True)
                deleted_count += 1
                if deleted_count >= RECONCILE_BATCH_SIZE:
                    break


class _PostAssetReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        self._collect(tag, attrs)

    def handle_startendtag(self, tag: str, attrs) -> None:
        self._collect(tag, attrs)

    def _collect(self, tag: str, attrs) -> None:
        attributes = dict(attrs)
        if tag in {"img", "source", "video"} and attributes.get("src"):
            self.references.append(attributes["src"])
        for attribute_name in ("data-file-url", "data-video-url"):
            if attributes.get(attribute_name):
                self.references.append(attributes[attribute_name])
        class_names = set((attributes.get("class") or "").split())
        if tag == "a" and "file-attachment" in class_names and attributes.get("href"):
            self.references.append(attributes["href"])


def post_asset_keys(sanitized_content: str) -> list[str]:
    references = []
    parser = _PostAssetReferenceParser()
    parser.feed(sanitized_content)
    parser.close()
    references.extend(parser.references)

    keys = []
    for reference in references:
        try:
            key = canonical_object_key(reference)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid upload reference",
            ) from exc
        if key not in keys:
            keys.append(key)
    return sorted(keys)


def validate_structured_upload_references(post) -> None:
    """Reject noncanonical structured URLs without using them for binding."""

    references = [media.url for media in (post.media or [])]
    references.extend(file.url for file in (post.files or []))
    for reference in references:
        try:
            canonical_object_key(reference)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid upload reference",
            ) from exc


def lock_owner(db: Session, owner_user_id: int) -> models.User:
    owner = (
        db.query(models.User)
        .filter(models.User.id == owner_user_id)
        .with_for_update(of=models.User)
        .first()
    )
    if owner is None:
        raise HTTPException(status_code=404, detail="User not found")
    return owner


def enforce_rate_limit(db: Session, owner_user_id: int, *, now: datetime) -> None:
    now = _as_aware_utc(now)
    recent = (
        db.query(models.UploadAsset.id)
        .filter(
            models.UploadAsset.owner_user_id == owner_user_id,
            models.UploadAsset.created_at >= now - UPLOAD_RATE_WINDOW,
        )
        .count()
    )
    if recent >= UPLOAD_RATE_LIMIT:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Upload rate limit exceeded",
        )


def enforce_quota(db: Session, owner_user_id: int, incoming_bytes: int) -> None:
    used_bytes = (
        db.query(func.coalesce(func.sum(models.UploadAsset.size_bytes), 0))
        .filter(
            models.UploadAsset.owner_user_id == owner_user_id,
            models.UploadAsset.state.in_(COUNTED_QUOTA_STATES),
        )
        .scalar()
    )
    if int(used_bytes or 0) + incoming_bytes > UPLOAD_QUOTA_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail="Upload quota exceeded",
        )


def configure_upload_transaction(db: Session) -> None:
    """Bound the post-scan PostgreSQL transaction below the orphan grace."""

    if db.bind is None or db.bind.dialect.name != "postgresql":
        return
    for statement in (
        "SET LOCAL lock_timeout = '10s'",
        "SET LOCAL statement_timeout = '30s'",
        "SET LOCAL idle_in_transaction_session_timeout = '30s'",
    ):
        db.execute(text(statement))


def add_pending_asset(db: Session, *, owner_user_id: int, stored, now: datetime) -> models.UploadAsset:
    now = _as_aware_utc(now)
    asset = models.UploadAsset(
        storage_key=stored.storage_key,
        owner_user_id=owner_user_id,
        blog_id=None,
        purpose="POST",
        state="PENDING",
        original_filename=stored.original_filename[:255],
        media_type=stored.spec.media_type,
        size_bytes=stored.size,
        sha256_digest=stored.sha256_digest,
        created_at=now,
        expires_at=now + PENDING_LIFETIME,
        scan_completed_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def add_active_profile_asset(
    db: Session,
    *,
    owner_user_id: int,
    purpose: str,
    stored,
    now: datetime,
) -> models.UploadAsset:
    now = _as_aware_utc(now)
    if purpose not in {"PROFILE_IMAGE", "COVER_IMAGE"}:
        raise ValueError("Invalid profile upload purpose")
    existing = (
        db.query(models.UploadAsset)
        .filter(
            models.UploadAsset.owner_user_id == owner_user_id,
            models.UploadAsset.purpose == purpose,
            models.UploadAsset.state == "ACTIVE",
        )
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    queue_assets(existing, now=now)
    asset = models.UploadAsset(
        storage_key=stored.storage_key,
        owner_user_id=owner_user_id,
        blog_id=None,
        purpose=purpose,
        state="ACTIVE",
        original_filename=stored.original_filename[:255],
        media_type=stored.spec.media_type,
        size_bytes=stored.size,
        sha256_digest=stored.sha256_digest,
        created_at=now,
        bound_at=now,
        scan_completed_at=now,
    )
    db.add(asset)
    db.flush()
    return asset


def queue_assets(assets: Iterable[models.UploadAsset], *, now: datetime) -> None:
    now = _as_aware_utc(now)
    for asset in sorted(assets, key=lambda candidate: candidate.storage_key):
        if asset.state in {"DELETE_PENDING", "DELETED"}:
            continue
        asset.state = "DELETE_PENDING"
        asset.blog_id = None
        asset.expires_at = None
        asset.delete_after = now


def lock_blog(db: Session, blog_id: int) -> models.Blog:
    return (
        db.query(models.Blog)
        .filter(models.Blog.id == blog_id)
        .with_for_update(of=models.Blog)
        .one()
    )


def bind_post_assets(
    db: Session,
    *,
    blog: models.Blog,
    actor_user_id: int,
    storage_keys: list[str],
    upload_root: Path,
    now: datetime,
) -> None:
    now = _as_aware_utc(now)
    # The caller locks the post owner first. Lock the Blog second and assets
    # last in stable storage-key order so PostgreSQL follows one order.
    locked_blog = lock_blog(db, blog.id)
    asset_filters = [
        and_(
            models.UploadAsset.blog_id == locked_blog.id,
            models.UploadAsset.state == "ACTIVE",
            models.UploadAsset.purpose == "POST",
        )
    ]
    if storage_keys:
        asset_filters.append(models.UploadAsset.storage_key.in_(storage_keys))
    locked_assets = (
        db.query(models.UploadAsset)
        .filter(or_(*asset_filters))
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    existing = [
        asset
        for asset in locked_assets
        if asset.blog_id == locked_blog.id
        and asset.state == "ACTIVE"
        and asset.purpose == "POST"
    ]
    desired_by_key = {asset.storage_key: asset for asset in locked_assets}
    requested_keys = sorted(storage_keys)
    desired = [desired_by_key[key] for key in requested_keys if key in desired_by_key]
    if [asset.storage_key for asset in desired] != requested_keys:
        raise HTTPException(status_code=400, detail="Invalid upload reference")

    for asset in desired:
        if asset.state == "ACTIVE" and asset.blog_id == locked_blog.id:
            continue
        if (
            asset.state != "PENDING"
            or asset.purpose != "POST"
            or asset.owner_user_id != locked_blog.owner_id
            or actor_user_id != locked_blog.owner_id
            or asset.expires_at is None
            or _as_aware_utc(asset.expires_at) <= now
            or asset.scan_completed_at is None
            or not _registered_object_is_file(upload_root, asset.storage_key)
        ):
            raise HTTPException(status_code=409, detail="Upload cannot be bound")

    desired_keys = set(storage_keys)
    queue_assets(
        (asset for asset in existing if asset.storage_key not in desired_keys),
        now=now,
    )
    for asset in desired:
        if asset.state == "PENDING":
            asset.state = "ACTIVE"
            asset.blog_id = locked_blog.id
            asset.expires_at = None
            asset.bound_at = now
    db.flush()


def queue_blog_assets(db: Session, blog_ids: Iterable[int], *, now: datetime) -> None:
    ids = sorted(set(blog_ids))
    if not ids:
        return
    assets = (
        db.query(models.UploadAsset)
        .filter(
            models.UploadAsset.blog_id.in_(ids),
            models.UploadAsset.state == "ACTIVE",
        )
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    queue_assets(assets, now=now)


def queue_owner_assets(db: Session, owner_user_id: int, *, now: datetime) -> None:
    assets = (
        db.query(models.UploadAsset)
        .filter(
            models.UploadAsset.owner_user_id == owner_user_id,
            models.UploadAsset.state.in_(("PENDING", "ACTIVE")),
        )
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    queue_assets(assets, now=now)


def _registered_staging_object_ids(upload_root: Path) -> list[str]:
    incoming_root = Path(upload_root) / ".incoming"
    if not incoming_root.is_dir() or _is_link(incoming_root):
        return []
    object_ids = []
    try:
        entries = os.scandir(incoming_root)
    except OSError:
        return []
    with entries:
        for entry in entries:
            if not re.fullmatch(r"[0-9a-f]{32}\.part", entry.name):
                continue
            candidate = Path(entry.path)
            try:
                if entry.is_symlink() or _is_link(candidate) or not entry.is_file(follow_symlinks=False):
                    continue
            except OSError:
                continue
            object_ids.append(entry.name.removesuffix(".part"))
    return sorted(set(object_ids))


def reconcile(db: Session, *, upload_root: Path, now: datetime) -> dict[str, int]:
    now = _as_aware_utc(now)
    staged_object_ids = _registered_staging_object_ids(upload_root)
    for offset in range(0, len(staged_object_ids), RECONCILE_BATCH_SIZE):
        object_id_batch = staged_object_ids[offset:offset + RECONCILE_BATCH_SIZE]
        live_assets = (
            db.query(models.UploadAsset)
            .filter(
                models.UploadAsset.state.in_(("PENDING", "ACTIVE")),
                func.substr(models.UploadAsset.storage_key, 12, 32).in_(object_id_batch),
            )
            .order_by(models.UploadAsset.storage_key)
            .with_for_update(of=models.UploadAsset)
            .all()
        )
        for asset in live_assets:
            try:
                _promote_registered_staging(upload_root, asset)
            except (OSError, ValueError):
                # A missing or corrupt ACTIVE object remains fail-closed at read
                # time and must be restored from the coupled object-store snapshot.
                continue

    expired = (
        db.query(models.UploadAsset)
        .filter(
            models.UploadAsset.state == "PENDING",
            models.UploadAsset.expires_at <= now,
        )
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    queue_assets(expired, now=now)
    db.flush()

    due = (
        db.query(models.UploadAsset)
        .filter(
            models.UploadAsset.state == "DELETE_PENDING",
            models.UploadAsset.delete_after <= now,
        )
        .order_by(models.UploadAsset.storage_key)
        .with_for_update(of=models.UploadAsset)
        .all()
    )
    deleted = 0
    failed = 0
    for asset in due:
        try:
            final_path = registered_object_path(upload_root, asset.storage_key)
            staging_path = _registered_staging_path(upload_root, asset.storage_key)
            final_path.unlink(missing_ok=True)
            staging_path.unlink(missing_ok=True)
            if final_path.parent.is_dir():
                _fsync_directory(final_path.parent)
            if staging_path.parent.is_dir():
                _fsync_directory(staging_path.parent)
        except (OSError, ValueError):
            failed += 1
            continue
        asset.state = "DELETED"
        asset.blog_id = None
        asset.expires_at = None
        asset.delete_after = None
        asset.original_filename = None
        asset.deleted_at = now
        deleted += 1

    db.query(models.UploadAsset).filter(
        models.UploadAsset.state == "DELETED",
        models.UploadAsset.deleted_at < now - DELETED_TOMBSTONE_LIFETIME,
    ).delete(synchronize_session=False)
    db.flush()
    _sweep_orphan_objects(db, upload_root, now=now)
    db.flush()
    return {"queued": len(expired) + len([asset for asset in due if asset not in expired]), "deleted": deleted, "failed": failed}


__all__ = [
    "add_active_profile_asset",
    "add_pending_asset",
    "bind_post_assets",
    "canonical_object_key",
    "configure_upload_transaction",
    "enforce_quota",
    "enforce_rate_limit",
    "lock_owner",
    "open_verified_registered_object",
    "object_url",
    "object_matches_registration",
    "post_asset_keys",
    "queue_blog_assets",
    "queue_owner_assets",
    "queue_assets",
    "registered_object_path",
    "reconcile",
    "validate_structured_upload_references",
]

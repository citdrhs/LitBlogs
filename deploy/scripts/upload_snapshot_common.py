#!/usr/bin/env python3
"""Shared fail-closed primitives for coupled database/upload recovery sets."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import stat
import tarfile
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

LIVE_ASSET_STATES = frozenset({"PENDING", "ACTIVE", "DELETE_PENDING"})
KNOWN_ASSET_STATES = LIVE_ASSET_STATES | {"DELETED"}
STORAGE_KEY = re.compile(
    r"^objects/(?P<prefix>[0-9a-f]{2})/(?P<object_id>[0-9a-f]{32})"
    r"\.[a-z0-9]{1,10}$"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
INVENTORY_KEYS = frozenset(
    {"asset_id", "storage_key", "state", "size_bytes", "sha256_digest"}
)
MAX_INVENTORY_BYTES = 64 * 1024 * 1024
MAX_INVENTORY_RECORDS = 1_000_000
MAX_MANIFEST_BYTES = 32 * 1024
COUPLED_MANIFEST_FORMAT = "litblogs-coupled-recovery-v1"
MANIFEST_KEYS = frozenset(
    {
        "artifacts",
        "asset_records",
        "created_at",
        "file_backed_assets",
        "format",
        "writes_quiesced",
    }
)
ARTIFACT_KEYS = frozenset({"format", "name", "sha256", "size_bytes"})
SYNTHETIC_UPLOAD_ROOT = re.compile(r"^litblog_restore_uploads_[a-z0-9_]{1,40}$")
UTC_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$"
)
PRODUCTION_UPLOAD_ROOT = Path("/var/lib/litblogs/uploads")
PRODUCTION_UPLOAD_USER = "litblogs"
PRODUCTION_UPLOAD_GROUP = "litblogs"
PRODUCTION_UPLOAD_ROOT_MODE = 0o750
SYNTHETIC_UPLOAD_ROOT_MODE = 0o700
UPLOAD_ROOT_ENTRIES = frozenset({"objects", ".incoming"})


class UploadSnapshotError(RuntimeError):
    """Bounded operator-safe failure for upload snapshot processing."""


@dataclass(frozen=True)
class AssetRecord:
    asset_id: int
    storage_key: str
    state: str
    size_bytes: int
    sha256_digest: str

    def as_json_object(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "sha256_digest": self.sha256_digest,
            "size_bytes": self.size_bytes,
            "state": self.state,
            "storage_key": self.storage_key,
        }


@dataclass(frozen=True)
class CoupledRecoverySet:
    manifest: Path
    database_archive: Path
    upload_archive: Path
    asset_inventory: Path
    inventory: tuple[AssetRecord, ...]
    created_at: str


@dataclass(frozen=True)
class UploadRootCustody:
    """Exact POSIX owner/group/mode contract for one upload root."""

    owner_uid: int | None
    group_gid: int | None
    root_mode: int
    ancestor_owner_uids: frozenset[int]
    allow_root_owned_sticky_ancestors: bool


@dataclass
class _PinnedDirectory:
    path: Path
    metadata: os.stat_result
    descriptor: int | None

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def synthetic_upload_custody() -> UploadRootCustody:
    """Return the exact private-root contract for operator-owned rehearsals."""

    return UploadRootCustody(
        owner_uid=os.geteuid() if os.name == "posix" else None,
        group_gid=os.getegid() if os.name == "posix" else None,
        root_mode=SYNTHETIC_UPLOAD_ROOT_MODE,
        ancestor_owner_uids=(
            frozenset({0, os.geteuid()}) if os.name == "posix" else frozenset()
        ),
        allow_root_owned_sticky_ancestors=True,
    )


def production_upload_custody() -> UploadRootCustody:
    """Resolve the reviewed litblogs service identity without accepting the leaf owner."""

    if os.name != "posix":
        return UploadRootCustody(
            owner_uid=None,
            group_gid=None,
            root_mode=PRODUCTION_UPLOAD_ROOT_MODE,
            ancestor_owner_uids=frozenset({0}),
            allow_root_owned_sticky_ancestors=False,
        )
    try:
        import grp
        import pwd

        owner_uid = pwd.getpwnam(PRODUCTION_UPLOAD_USER).pw_uid
        group_gid = grp.getgrnam(PRODUCTION_UPLOAD_GROUP).gr_gid
    except (ImportError, KeyError) as exc:
        raise UploadSnapshotError(
            "The approved upload service identity is unavailable"
        ) from exc
    return UploadRootCustody(
        owner_uid=owner_uid,
        group_gid=group_gid,
        root_mode=PRODUCTION_UPLOAD_ROOT_MODE,
        ancestor_owner_uids=frozenset({0}),
        allow_root_owned_sticky_ancestors=False,
    )


def _mapping_from_row(row: object) -> Mapping[str, object]:
    if isinstance(row, Mapping):
        return row
    mapping = getattr(row, "_mapping", None)
    if isinstance(mapping, Mapping):
        return mapping
    raise UploadSnapshotError("The upload asset registry inventory is invalid")


def _asset_record(row: object) -> AssetRecord:
    mapping = _mapping_from_row(row)
    if set(mapping) != INVENTORY_KEYS:
        raise UploadSnapshotError("The upload asset registry inventory is invalid")
    asset_id = mapping["asset_id"]
    storage_key = mapping["storage_key"]
    state = mapping["state"]
    size_bytes = mapping["size_bytes"]
    sha256_digest = mapping["sha256_digest"]
    match = STORAGE_KEY.fullmatch(storage_key) if isinstance(storage_key, str) else None
    if (
        type(asset_id) is not int
        or asset_id <= 0
        or match is None
        or match.group("prefix") != match.group("object_id")[:2]
        or state not in KNOWN_ASSET_STATES
        or type(size_bytes) is not int
        or size_bytes <= 0
        or not isinstance(sha256_digest, str)
        or SHA256.fullmatch(sha256_digest) is None
    ):
        raise UploadSnapshotError("The upload asset registry inventory is invalid")
    return AssetRecord(
        asset_id=asset_id,
        storage_key=storage_key,
        state=state,
        size_bytes=size_bytes,
        sha256_digest=sha256_digest,
    )


def registry_inventory(rows: Iterable[object]) -> tuple[AssetRecord, ...]:
    """Normalize every registry row into one stable, canonical inventory."""

    records = [_asset_record(row) for row in rows]
    if len({record.asset_id for record in records}) != len(records) or len(
        {record.storage_key for record in records}
    ) != len(records):
        raise UploadSnapshotError("The upload asset registry inventory is invalid")
    return tuple(sorted(records, key=lambda record: record.storage_key))


def file_backed_inventory(
    inventory: Iterable[AssetRecord],
) -> tuple[AssetRecord, ...]:
    """Select rows whose exact objects must be present in an upload snapshot."""

    records = _canonical_inventory(inventory)
    return tuple(record for record in records if record.state in LIVE_ASSET_STATES)


def require_stable_registry(
    before: tuple[AssetRecord, ...],
    after: tuple[AssetRecord, ...],
) -> None:
    """Fail if any file-backed registry fact changed across the checkpoint."""

    if before != after:
        raise UploadSnapshotError(
            "The upload asset registry changed while the recovery set was created"
        )


def _canonical_inventory(inventory: Iterable[AssetRecord]) -> tuple[AssetRecord, ...]:
    records = tuple(inventory)
    if len(records) > MAX_INVENTORY_RECORDS:
        raise UploadSnapshotError("The upload asset inventory file is invalid")
    try:
        normalized = tuple(_asset_record(record.as_json_object()) for record in records)
    except (AttributeError, TypeError) as exc:
        raise UploadSnapshotError("The upload asset inventory file is invalid") from exc
    if len({record.asset_id for record in normalized}) != len(normalized) or len(
        {record.storage_key for record in normalized}
    ) != len(normalized):
        raise UploadSnapshotError("The upload asset inventory file is invalid")
    if normalized != tuple(sorted(normalized, key=lambda record: record.storage_key)):
        raise UploadSnapshotError("The upload asset inventory file is invalid")
    return normalized


def _inventory_bytes(inventory: Iterable[AssetRecord]) -> bytes:
    records = _canonical_inventory(inventory)
    payload = "".join(
        json.dumps(
            record.as_json_object(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        )
        + "\n"
        for record in records
    ).encode("ascii")
    if len(payload) > MAX_INVENTORY_BYTES:
        raise UploadSnapshotError("The upload asset inventory file is invalid")
    return payload


def write_asset_inventory(
    inventory_path: str | Path,
    inventory: Iterable[AssetRecord],
) -> None:
    """Exclusively create a canonical sorted JSONL inventory at mode 0600."""

    path = Path(inventory_path)
    payload = _inventory_bytes(inventory)
    descriptor: int | None = None
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            destination.write(payload)
            destination.flush()
            os.fsync(destination.fileno())
        path.chmod(0o600)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise UploadSnapshotError(
            "The upload asset inventory file could not be created"
        ) from exc


def _json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def load_asset_inventory(
    inventory_path: str | Path,
) -> tuple[AssetRecord, ...]:
    """Load only the exact canonical JSONL representation written above."""

    path = Path(inventory_path)
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise OSError
        if metadata.st_size > MAX_INVENTORY_BYTES:
            raise ValueError
        payload = path.read_bytes()
        payload.decode("ascii")
        lines = payload.splitlines(keepends=True)
        if any(not line.endswith(b"\n") for line in lines):
            raise ValueError
        if len(lines) > MAX_INVENTORY_RECORDS:
            raise ValueError
        decoded = [
            json.loads(line, object_pairs_hook=_json_object)
            for line in lines
        ]
        records = registry_inventory(decoded)
        if len(records) != len(decoded) or _inventory_bytes(records) != payload:
            raise ValueError
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        UploadSnapshotError,
    ) as exc:
        raise UploadSnapshotError("The upload asset inventory file is invalid") from exc
    return records


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _ancestor_metadata_matches_contract(
    metadata: os.stat_result,
    custody: UploadRootCustody,
) -> bool:
    """Return whether one existing ancestor satisfies the selected custody."""

    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid not in custody.ancestor_owner_uids
    ):
        return False
    if not metadata.st_mode & 0o022:
        return True
    return (
        custody.allow_root_owned_sticky_ancestors
        and metadata.st_uid == 0
        and bool(metadata.st_mode & stat.S_ISVTX)
    )


def _validated_directory_fact(
    directory: str | Path,
    custody: UploadRootCustody,
    *,
    operator_message: str,
) -> tuple[Path, os.stat_result]:
    path = Path(directory)
    try:
        if not path.is_absolute():
            raise OSError
        absolute = path.absolute()
        for candidate in (*reversed(absolute.parents), absolute):
            if candidate.exists() and _is_link(candidate):
                raise OSError
        resolved = path.resolve(strict=True)
        if os.path.normcase(str(resolved)) != os.path.normcase(str(absolute)):
            raise OSError
        metadata = resolved.stat(follow_symlinks=False)
        if not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        if os.name == "posix":
            if (
                custody.owner_uid is None
                or custody.group_gid is None
                or metadata.st_uid != custody.owner_uid
                or metadata.st_gid != custody.group_gid
                or stat.S_IMODE(metadata.st_mode) != custody.root_mode
            ):
                raise OSError
            for ancestor in resolved.parents:
                ancestor_metadata = ancestor.stat(follow_symlinks=False)
                if (
                    _is_link(ancestor)
                    or not _ancestor_metadata_matches_contract(
                        ancestor_metadata, custody
                    )
                ):
                    raise OSError
    except OSError as exc:
        raise UploadSnapshotError(operator_message) from exc
    return resolved, metadata


def _open_pinned_directory(
    directory: str | Path,
    custody: UploadRootCustody,
    *,
    operator_message: str,
) -> _PinnedDirectory:
    path, metadata = _validated_directory_fact(
        directory,
        custody,
        operator_message=operator_message,
    )
    descriptor: int | None = None
    try:
        if os.name == "posix":
            descriptor = os.open(
                path,
                os.O_RDONLY
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0),
            )
            if not os.path.samestat(metadata, os.fstat(descriptor)):
                raise OSError
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise UploadSnapshotError(operator_message) from exc
    return _PinnedDirectory(path=path, metadata=metadata, descriptor=descriptor)


def _require_pinned_directory(
    pinned: _PinnedDirectory,
    custody: UploadRootCustody,
    *,
    operator_message: str,
) -> None:
    path, metadata = _validated_directory_fact(
        pinned.path,
        custody,
        operator_message=operator_message,
    )
    try:
        if path != pinned.path or not os.path.samestat(pinned.metadata, metadata):
            raise OSError
        if pinned.descriptor is not None and not os.path.samestat(
            pinned.metadata, os.fstat(pinned.descriptor)
        ):
            raise OSError
    except OSError as exc:
        raise UploadSnapshotError(operator_message) from exc


def _canonical_upload_root(
    upload_root: str | Path,
    custody: UploadRootCustody,
) -> _PinnedDirectory:
    return _open_pinned_directory(
        upload_root,
        custody,
        operator_message="The upload root custody is invalid",
    )


def _require_directory_custody(
    path: Path,
    *,
    owner_uid: int,
    group_gid: int,
) -> None:
    try:
        metadata = path.stat(follow_symlinks=False)
        if _is_link(path) or not stat.S_ISDIR(metadata.st_mode):
            raise OSError
        if os.name == "posix" and (
            metadata.st_uid != owner_uid
            or metadata.st_gid != group_gid
            or stat.S_IMODE(metadata.st_mode) != 0o700
        ):
            raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The upload store custody is invalid") from exc


def _require_file_custody(
    path: Path,
    *,
    owner_uid: int,
    group_gid: int,
) -> os.stat_result:
    try:
        metadata = path.stat(follow_symlinks=False)
        if _is_link(path) or not stat.S_ISREG(metadata.st_mode):
            raise OSError
        if os.name == "posix" and (
            metadata.st_uid != owner_uid
            or metadata.st_gid != group_gid
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The upload store custody is invalid") from exc
    return metadata


@dataclass
class _OpenedObject:
    descriptor: int | None
    metadata: os.stat_result

    def close(self) -> None:
        if self.descriptor is not None:
            os.close(self.descriptor)
            self.descriptor = None


def _open_verified_object(
    path: Path,
    record: AssetRecord,
    *,
    owner_uid: int,
    group_gid: int,
) -> _OpenedObject:
    descriptor: int | None = None
    try:
        before = _require_file_custody(
            path,
            owner_uid=owner_uid,
            group_gid=group_gid,
        )
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
            raise OSError
        digest = hashlib.sha256()
        size_bytes = 0
        while chunk := os.read(descriptor, 1024 * 1024):
            size_bytes += len(chunk)
            digest.update(chunk)
        after = os.fstat(descriptor)
        final_path = path.stat(follow_symlinks=False)
        if (
            not os.path.samestat(opened, after)
            or not os.path.samestat(after, final_path)
            or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
            or size_bytes != record.size_bytes
            or digest.hexdigest() != record.sha256_digest
        ):
            raise OSError
        os.lseek(descriptor, 0, os.SEEK_SET)
        return _OpenedObject(descriptor=descriptor, metadata=opened)
    except (OSError, UploadSnapshotError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, UploadSnapshotError) and "custody" in str(exc):
            raise
        raise UploadSnapshotError(
            "The upload store does not match the registry inventory"
        ) from exc


def _actual_upload_keys(objects_root: Path) -> tuple[str, ...]:
    actual: list[str] = []
    try:
        for shard in sorted(objects_root.iterdir(), key=lambda path: path.name):
            if _is_link(shard) or not shard.is_dir() or not re.fullmatch(r"[0-9a-f]{2}", shard.name):
                raise OSError
            for candidate in sorted(shard.iterdir(), key=lambda path: path.name):
                if _is_link(candidate) or not candidate.is_file():
                    raise OSError
                actual.append(candidate.relative_to(objects_root.parent).as_posix())
    except OSError as exc:
        raise UploadSnapshotError(
            "The upload store does not match the registry inventory"
        ) from exc
    return tuple(actual)


def verify_upload_tree(
    upload_root: str | Path,
    inventory: Iterable[AssetRecord],
    *,
    custody: UploadRootCustody | None = None,
) -> None:
    """Require exact registry/filesystem equality, hashes, paths, and custody."""

    required_custody = custody or synthetic_upload_custody()
    pinned = _canonical_upload_root(upload_root, required_custody)
    try:
        root = pinned.path
        owner_uid = pinned.metadata.st_uid
        group_gid = pinned.metadata.st_gid
        objects_root = root / "objects"
        incoming_root = root / ".incoming"
        try:
            root_entries = set(
                os.listdir(pinned.descriptor)
                if pinned.descriptor is not None
                else os.listdir(root)
            )
            if root_entries != UPLOAD_ROOT_ENTRIES:
                raise OSError
        except OSError as exc:
            raise UploadSnapshotError(
                "The upload store does not match the registry inventory"
            ) from exc
        _require_directory_custody(
            objects_root,
            owner_uid=owner_uid,
            group_gid=group_gid,
        )
        _require_directory_custody(
            incoming_root,
            owner_uid=owner_uid,
            group_gid=group_gid,
        )
        try:
            if any(incoming_root.iterdir()):
                raise OSError
        except OSError as exc:
            raise UploadSnapshotError(
                "The upload store does not match the registry inventory"
            ) from exc

        file_records = file_backed_inventory(inventory)
        expected_keys = tuple(record.storage_key for record in file_records)
        actual_keys = _actual_upload_keys(objects_root)
        if actual_keys != expected_keys:
            raise UploadSnapshotError(
                "The upload store does not match the registry inventory"
            )

        expected_shards = {Path(record.storage_key).parts[1] for record in file_records}
        try:
            actual_shards = {candidate.name for candidate in objects_root.iterdir()}
        except OSError as exc:
            raise UploadSnapshotError(
                "The upload store does not match the registry inventory"
            ) from exc
        if actual_shards != expected_shards:
            raise UploadSnapshotError(
                "The upload store does not match the registry inventory"
            )
        for shard_name in expected_shards:
            _require_directory_custody(
                objects_root / shard_name,
                owner_uid=owner_uid,
                group_gid=group_gid,
            )
        for record in file_records:
            opened = _open_verified_object(
                root / Path(record.storage_key),
                record,
                owner_uid=owner_uid,
                group_gid=group_gid,
            )
            opened.close()
        _require_pinned_directory(
            pinned,
            required_custody,
            operator_message="The upload root custody is invalid",
        )
    finally:
        pinned.close()


def create_upload_archive(
    archive_path: str | Path,
    upload_root: str | Path,
    inventory: Iterable[AssetRecord],
    *,
    custody: UploadRootCustody | None = None,
) -> None:
    """Create an exclusive deterministic, uncompressed USTAR upload archive."""

    records = _canonical_inventory(inventory)
    required_custody = custody or synthetic_upload_custody()
    verify_upload_tree(upload_root, records, custody=required_custody)
    pinned = _canonical_upload_root(upload_root, required_custody)
    root = pinned.path
    owner_uid = pinned.metadata.st_uid
    group_gid = pinned.metadata.st_gid
    destination_path = Path(archive_path)
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination_path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
            0o600,
        )
        with os.fdopen(descriptor, "w+b") as destination:
            descriptor = None
            with tarfile.open(
                fileobj=destination,
                mode="w:",
                format=tarfile.USTAR_FORMAT,
            ) as archive:
                for record in file_backed_inventory(records):
                    path = root / Path(record.storage_key)
                    opened = _open_verified_object(
                        path,
                        record,
                        owner_uid=owner_uid,
                        group_gid=group_gid,
                    )
                    try:
                        info = tarfile.TarInfo(record.storage_key)
                        info.size = record.size_bytes
                        info.mode = 0o600
                        info.uid = 0
                        info.gid = 0
                        info.mtime = 0
                        info.uname = ""
                        info.gname = ""
                        with os.fdopen(os.dup(opened.descriptor), "rb") as source:
                            archive.addfile(info, source)
                        after = os.fstat(opened.descriptor)
                        current = path.stat(follow_symlinks=False)
                        if (
                            not os.path.samestat(opened.metadata, after)
                            or not os.path.samestat(after, current)
                            or opened.metadata.st_size != after.st_size
                            or opened.metadata.st_mtime_ns != after.st_mtime_ns
                        ):
                            raise OSError
                    finally:
                        opened.close()
            destination.flush()
            os.fsync(destination.fileno())
        destination_path.chmod(0o600)
        _require_pinned_directory(
            pinned,
            required_custody,
            operator_message="The upload root custody is invalid",
        )
    except (OSError, tarfile.TarError, UploadSnapshotError) as exc:
        if descriptor is not None:
            os.close(descriptor)
        if isinstance(exc, UploadSnapshotError):
            raise
        raise UploadSnapshotError(
            "The upload archive could not be created safely"
        ) from exc
    finally:
        pinned.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _valid_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or UTC_TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError:
        return False
    return parsed.tzinfo == UTC


def _expected_recovery_paths(manifest_path: Path) -> tuple[Path, Path, Path]:
    suffix = ".manifest.json"
    if not manifest_path.name.endswith(suffix):
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    base_name = manifest_path.name[: -len(suffix)]
    if not base_name or Path(base_name).name != base_name:
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    return (
        manifest_path.with_name(f"{base_name}.dump"),
        manifest_path.with_name(f"{base_name}.uploads.tar"),
        manifest_path.with_name(f"{base_name}.assets.jsonl"),
    )


def coupled_recovery_artifact_paths(
    manifest_path: str | Path,
) -> tuple[Path, Path, Path]:
    """Return the three same-directory artifacts implied by a manifest name."""

    return _expected_recovery_paths(Path(manifest_path))


def _regular_artifact(path: Path) -> os.stat_result:
    try:
        metadata = path.stat(follow_symlinks=False)
        if _is_link(path) or not stat.S_ISREG(metadata.st_mode):
            raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The coupled recovery manifest is invalid") from exc
    return metadata


def _artifact_fact(path: Path, artifact_format: str) -> dict[str, object]:
    metadata = _regular_artifact(path)
    try:
        checksum = _sha256(path)
    except OSError as exc:
        raise UploadSnapshotError("The coupled recovery manifest is invalid") from exc
    return {
        "format": artifact_format,
        "name": path.name,
        "sha256": checksum,
        "size_bytes": metadata.st_size,
    }


def _validate_tar_structure(
    archive: tarfile.TarFile,
    records: tuple[AssetRecord, ...],
) -> list[tarfile.TarInfo]:
    members = archive.getmembers()
    if [member.name for member in members] != [record.storage_key for record in records]:
        raise UploadSnapshotError("The upload archive is invalid")
    for member, record in zip(members, records, strict=True):
        if (
            not member.isfile()
            or member.linkname
            or member.pax_headers
            or member.size != record.size_bytes
            or member.mode != 0o600
            or member.uid != 0
            or member.gid != 0
            or member.mtime != 0
            or member.uname
            or member.gname
        ):
            raise UploadSnapshotError("The upload archive is invalid")
    return members


def _require_ustar_envelope(path: Path, *, empty: bool) -> None:
    try:
        size_bytes = path.stat().st_size
        with path.open("rb") as source:
            header = source.read(512)
        if size_bytes == 0 or size_bytes % tarfile.RECORDSIZE != 0:
            raise OSError
        if empty:
            if header != b"\0" * 512:
                raise OSError
        elif header[257:265] != b"ustar\x0000":
            raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The upload archive is invalid") from exc


def verify_upload_archive(
    archive_path: str | Path,
    inventory: Iterable[AssetRecord],
) -> None:
    """Verify exact USTAR membership, normalized metadata, sizes, and hashes."""

    path = Path(archive_path)
    _regular_artifact(path)
    records = file_backed_inventory(inventory)
    _require_ustar_envelope(path, empty=not records)
    try:
        with tarfile.open(path, mode="r:") as archive:
            members = _validate_tar_structure(archive, records)
            for member, record in zip(members, records, strict=True):
                source = archive.extractfile(member)
                if source is None:
                    raise UploadSnapshotError("The upload archive is invalid")
                digest = hashlib.sha256()
                size_bytes = 0
                with source:
                    while chunk := source.read(1024 * 1024):
                        size_bytes += len(chunk)
                        digest.update(chunk)
                if (
                    size_bytes != record.size_bytes
                    or not hmac.compare_digest(digest.hexdigest(), record.sha256_digest)
                ):
                    raise UploadSnapshotError("The upload archive is invalid")
    except (OSError, tarfile.TarError) as exc:
        raise UploadSnapshotError("The upload archive is invalid") from exc


def write_coupled_manifest(
    manifest_path: str | Path,
    *,
    published_manifest_path: str | Path | None = None,
    database_path: str | Path,
    upload_archive_path: str | Path,
    asset_inventory_path: str | Path,
    inventory: Iterable[AssetRecord],
    created_at: str,
) -> None:
    """Write a private canonical manifest binding the other three artifacts."""

    manifest = Path(manifest_path)
    published_manifest = (
        manifest if published_manifest_path is None else Path(published_manifest_path)
    )
    database = Path(database_path)
    uploads = Path(upload_archive_path)
    assets = Path(asset_inventory_path)
    expected_database, expected_uploads, expected_assets = _expected_recovery_paths(
        published_manifest
    )
    records = _canonical_inventory(inventory)
    if (
        (database, uploads, assets)
        != (expected_database, expected_uploads, expected_assets)
        or not _valid_utc_timestamp(created_at)
    ):
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    try:
        with database.open("rb") as source:
            if source.read(5) != b"PGDMP":
                raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The coupled recovery manifest is invalid") from exc
    if load_asset_inventory(assets) != records:
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    verify_upload_archive(uploads, records)
    payload = {
        "artifacts": {
            "assets": _artifact_fact(assets, "canonical-jsonl"),
            "database": _artifact_fact(database, "postgresql-custom"),
            "uploads": _artifact_fact(uploads, "ustar"),
        },
        "asset_records": len(records),
        "created_at": created_at,
        "file_backed_assets": len(file_backed_inventory(records)),
        "format": COUPLED_MANIFEST_FORMAT,
        "writes_quiesced": True,
    }
    encoded = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")
    if len(encoded) > MAX_MANIFEST_BYTES:
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    descriptor: int | None = None
    try:
        descriptor = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            descriptor = None
            destination.write(encoded)
            destination.flush()
            os.fsync(destination.fileno())
        manifest.chmod(0o600)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise UploadSnapshotError(
            "The coupled recovery manifest could not be created"
        ) from exc


def _load_manifest_payload(manifest: Path) -> dict[str, object]:
    try:
        metadata = _regular_artifact(manifest)
        if metadata.st_size > MAX_MANIFEST_BYTES:
            raise ValueError
        payload = json.loads(
            manifest.read_text(encoding="ascii"),
            object_pairs_hook=_json_object,
        )
    except (
        OSError,
        UnicodeError,
        ValueError,
        json.JSONDecodeError,
        UploadSnapshotError,
    ) as exc:
        raise UploadSnapshotError("The coupled recovery manifest is invalid") from exc
    if not isinstance(payload, dict) or set(payload) != MANIFEST_KEYS:
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    return payload


def load_coupled_recovery_set(manifest_path: str | Path) -> CoupledRecoverySet:
    """Load and cryptographically bind one complete four-file recovery set."""

    manifest = Path(manifest_path)
    database, uploads, assets = _expected_recovery_paths(manifest)
    payload = _load_manifest_payload(manifest)
    artifacts = payload.get("artifacts")
    created_at = payload.get("created_at")
    if (
        payload.get("format") != COUPLED_MANIFEST_FORMAT
        or payload.get("writes_quiesced") is not True
        or not _valid_utc_timestamp(created_at)
        or not isinstance(artifacts, dict)
        or set(artifacts) != {"assets", "database", "uploads"}
    ):
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    expected = {
        "assets": (assets, "canonical-jsonl"),
        "database": (database, "postgresql-custom"),
        "uploads": (uploads, "ustar"),
    }
    for role, (path, artifact_format) in expected.items():
        fact = artifacts.get(role)
        if (
            not isinstance(fact, dict)
            or set(fact) != ARTIFACT_KEYS
            or fact.get("name") != path.name
            or fact.get("format") != artifact_format
            or not isinstance(fact.get("sha256"), str)
            or SHA256.fullmatch(fact["sha256"]) is None
            or type(fact.get("size_bytes")) is not int
            or fact["size_bytes"] < 0
        ):
            raise UploadSnapshotError("The coupled recovery manifest is invalid")
        actual = _artifact_fact(path, artifact_format)
        if actual != fact:
            raise UploadSnapshotError("The coupled recovery manifest is invalid")
    try:
        with database.open("rb") as source:
            if source.read(5) != b"PGDMP":
                raise OSError
    except OSError as exc:
        raise UploadSnapshotError("The coupled recovery manifest is invalid") from exc
    inventory = load_asset_inventory(assets)
    if (
        type(payload.get("asset_records")) is not int
        or payload["asset_records"] != len(inventory)
        or type(payload.get("file_backed_assets")) is not int
        or payload["file_backed_assets"] != len(file_backed_inventory(inventory))
    ):
        raise UploadSnapshotError("The coupled recovery manifest is invalid")
    verify_upload_archive(uploads, inventory)
    return CoupledRecoverySet(
        manifest=manifest,
        database_archive=database,
        upload_archive=uploads,
        asset_inventory=assets,
        inventory=inventory,
        created_at=created_at,
    )


def _open_synthetic_restore_root(
    destination_root: str | Path,
    *,
    require_empty: bool,
) -> _PinnedDirectory:
    destination = Path(destination_root)
    pinned: _PinnedDirectory | None = None
    try:
        if (
            not destination.is_absolute()
            or SYNTHETIC_UPLOAD_ROOT.fullmatch(destination.name) is None
        ):
            raise ValueError
        custody = synthetic_upload_custody()
        pinned = _open_pinned_directory(
            destination,
            custody,
            operator_message="The upload restore target must be a private synthetic root",
        )
        if pinned.path == PRODUCTION_UPLOAD_ROOT:
            raise ValueError
        if require_empty:
            entries = os.listdir(
                pinned.descriptor if pinned.descriptor is not None else pinned.path
            )
            if entries:
                raise UploadSnapshotError(
                    "The synthetic upload restore root must be empty"
                )
        _require_pinned_directory(
            pinned,
            custody,
            operator_message="The upload restore target must be a private synthetic root",
        )
    except UploadSnapshotError:
        if pinned is not None:
            pinned.close()
        raise
    except (OSError, ValueError) as exc:
        if pinned is not None:
            pinned.close()
        raise UploadSnapshotError(
            "The upload restore target must be a private synthetic root"
        ) from exc
    return pinned


def _synthetic_restore_root(
    destination_root: str | Path,
    *,
    require_empty: bool,
) -> Path:
    pinned = _open_synthetic_restore_root(
        destination_root,
        require_empty=require_empty,
    )
    try:
        return pinned.path
    finally:
        pinned.close()


def validate_synthetic_upload_restore_root(destination_root: str | Path) -> Path:
    """Validate a fresh, empty, private non-production extraction root."""

    return _synthetic_restore_root(destination_root, require_empty=True)


def validate_existing_synthetic_upload_root(destination_root: str | Path) -> Path:
    """Validate a private synthetic root that already contains restored files."""

    return _synthetic_restore_root(destination_root, require_empty=False)


def _fsync_directory(path: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def extract_upload_archive(
    archive_path: str | Path,
    destination_root: str | Path,
    inventory: Iterable[AssetRecord],
) -> Path:
    """Strictly extract into a fresh synthetic root without cleanup on failure."""

    path = Path(archive_path)
    records = file_backed_inventory(inventory)
    _regular_artifact(path)
    _require_ustar_envelope(path, empty=not records)
    pinned = _open_synthetic_restore_root(destination_root, require_empty=True)
    destination = pinned.path
    try:
        with tarfile.open(path, mode="r:") as archive:
            members = _validate_tar_structure(archive, records)
            objects = destination / "objects"
            incoming = destination / ".incoming"
            objects.mkdir(mode=0o700)
            incoming.mkdir(mode=0o700)
            if os.name == "posix":
                objects.chmod(0o700)
                incoming.chmod(0o700)
            _fsync_directory(destination)
            for member, record in zip(members, records, strict=True):
                source = archive.extractfile(member)
                if source is None:
                    raise UploadSnapshotError("The upload archive is invalid")
                relative = Path(record.storage_key)
                shard = destination / relative.parent
                if not shard.exists():
                    shard.mkdir(mode=0o700)
                    if os.name == "posix":
                        shard.chmod(0o700)
                    _fsync_directory(objects)
                final = destination / relative
                partial = final.with_name(f".{final.name}.restore-partial")
                descriptor = os.open(
                    partial,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0),
                    0o600,
                )
                digest = hashlib.sha256()
                size_bytes = 0
                # A failure deliberately leaves any exact private partial or
                # published object in place for operator investigation.
                with os.fdopen(descriptor, "wb") as output, source:
                    while chunk := source.read(1024 * 1024):
                        size_bytes += len(chunk)
                        digest.update(chunk)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                partial.chmod(0o600)
                if (
                    size_bytes != record.size_bytes
                    or not hmac.compare_digest(
                        digest.hexdigest(), record.sha256_digest
                    )
                ):
                    raise UploadSnapshotError("The upload archive is invalid")
                os.link(partial, final)
                partial.unlink()
                _fsync_directory(shard)
        _require_pinned_directory(
            pinned,
            synthetic_upload_custody(),
            operator_message="The upload restore target must be a private synthetic root",
        )
    except UploadSnapshotError:
        raise
    except (OSError, tarfile.TarError) as exc:
        raise UploadSnapshotError("The upload archive is invalid") from exc
    finally:
        pinned.close()
    verify_upload_tree(
        destination,
        inventory,
        custody=synthetic_upload_custody(),
    )
    return destination

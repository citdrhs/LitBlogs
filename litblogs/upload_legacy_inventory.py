import hashlib
import os
import stat
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


class LegacyInventoryError(RuntimeError):
    pass


@dataclass(frozen=True)
class LegacyUploadRecord:
    path: str
    owner_user_id: int
    blog_id: int | None
    purpose: str
    original_filename: str
    media_type: str
    size_bytes: int
    sha256_digest: str


LEGACY_TYPES = {
    ".jpg": ("image/jpeg", "jpeg"),
    ".jpeg": ("image/jpeg", "jpeg"),
    ".png": ("image/png", "png"),
    ".gif": ("image/gif", "gif"),
    ".webp": ("image/webp", "webp"),
    ".bmp": ("image/bmp", "bmp"),
    ".pdf": ("application/pdf", "pdf"),
    ".mp4": ("video/mp4", "mp4"),
    ".m4v": ("video/x-m4v", "mp4"),
    ".webm": ("video/webm", "ebml"),
    ".mkv": ("video/x-matroska", "ebml"),
    ".ogg": ("video/ogg", "ogg"),
    ".avi": ("video/x-msvideo", "avi"),
}


def _valid_signature(signature: str, header: bytes) -> bool:
    checks = {
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "bmp": header.startswith(b"BM"),
        "pdf": header.startswith(b"%PDF-"),
        "mp4": len(header) >= 12 and header[4:8] == b"ftyp",
        "ebml": header.startswith(b"\x1aE\xdf\xa3"),
        "ogg": header.startswith(b"OggS"),
        "avi": len(header) >= 12 and header.startswith(b"RIFF") and header[8:12] == b"AVI ",
    }
    return checks.get(signature, False)


def _normalize_relative_path(value: str) -> str:
    candidate = PurePosixPath(str(value).replace("\\", "/"))
    if candidate.is_absolute() or not candidate.parts or any(
        part in {"", ".", ".."} for part in candidate.parts
    ):
        raise LegacyInventoryError("Legacy binding contains an invalid path")
    return candidate.as_posix()


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _read_regular_file_once(path: Path, root: Path) -> tuple[bytes, int, str]:
    """Read and hash one stable, in-root regular file through one descriptor."""

    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode) or _is_link(path):
            raise LegacyInventoryError("Legacy upload link is not allowed")
        resolved = path.resolve(strict=True)
        resolved.relative_to(root)

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) or not os.path.samestat(before, opened):
                raise LegacyInventoryError("Legacy upload changed during inventory")
            digest = hashlib.sha256()
            size_bytes = 0
            header = b""
            while chunk := os.read(descriptor, 1024 * 1024):
                if len(header) < 512:
                    header += chunk[: 512 - len(header)]
                size_bytes += len(chunk)
                digest.update(chunk)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)

        final_path = os.lstat(path)
        if (
            not os.path.samestat(opened, after)
            or not os.path.samestat(after, final_path)
            or opened.st_size != after.st_size
            or opened.st_mtime_ns != after.st_mtime_ns
        ):
            raise LegacyInventoryError("Legacy upload changed during inventory")
        return header, size_bytes, digest.hexdigest()
    except LegacyInventoryError:
        raise
    except (OSError, ValueError) as exc:
        raise LegacyInventoryError("Legacy upload could not be read safely") from exc


def _path_owner(relative_path: str) -> int | None:
    parts = PurePosixPath(relative_path).parts
    for candidate in (
        parts[1] if len(parts) >= 3 and parts[0] in {"images", "videos", "files"} else None,
        parts[0] if len(parts) >= 2 and parts[0].isdigit() else None,
    ):
        if candidate and candidate.isdigit():
            return int(candidate)
    if parts and parts[0] in {"profile_images", "cover_images"}:
        stem_parts = PurePosixPath(parts[-1]).stem.split("_")
        if len(stem_parts) >= 2 and stem_parts[1].isdigit():
            return int(stem_parts[1])
    return None


def _purpose(relative_path: str, blog_id: int | None) -> str:
    bucket = PurePosixPath(relative_path).parts[0]
    if bucket == "profile_images":
        if blog_id is not None:
            raise LegacyInventoryError("Profile upload cannot be bound to a blog")
        return "PROFILE_IMAGE"
    if bucket == "cover_images":
        if blog_id is not None:
            raise LegacyInventoryError("Cover upload cannot be bound to a blog")
        return "COVER_IMAGE"
    if blog_id is None:
        raise LegacyInventoryError("Post upload is missing an unambiguous blog binding")
    return "POST"


def inventory_legacy_uploads(
    upload_root: Path,
    *,
    bindings: Iterable[dict],
) -> list[dict]:
    configured_root = Path(upload_root).absolute()
    if _is_link(configured_root) or not configured_root.is_dir():
        raise LegacyInventoryError("Legacy upload root does not exist")
    root = configured_root.resolve(strict=True)

    binding_by_path = {}
    for raw_binding in bindings:
        relative_path = _normalize_relative_path(raw_binding.get("path", ""))
        if relative_path in binding_by_path:
            raise LegacyInventoryError("Legacy upload has multiple bindings")
        binding_by_path[relative_path] = raw_binding

    legacy_files = []
    for path in root.rglob("*"):
        relative_parts = path.relative_to(root).parts
        if relative_parts and relative_parts[0] == "objects":
            if len(relative_parts) == 1 and _is_link(path):
                raise LegacyInventoryError("Legacy upload link is not allowed")
            continue
        if _is_link(path):
            raise LegacyInventoryError("Legacy upload link is not allowed")
        if path.is_file():
            legacy_files.append(path)
    legacy_files.sort()
    discovered = {path.relative_to(root).as_posix(): path for path in legacy_files}
    if set(discovered) != set(binding_by_path):
        raise LegacyInventoryError("Every legacy object must have exactly one binding")

    records = []
    for relative_path, path in discovered.items():
        binding = binding_by_path[relative_path]
        owner_user_id = binding.get("owner_user_id")
        if not isinstance(owner_user_id, int) or isinstance(owner_user_id, bool) or owner_user_id <= 0:
            raise LegacyInventoryError("Legacy upload has an invalid owner")
        inferred_owner = _path_owner(relative_path)
        if inferred_owner is None or inferred_owner != owner_user_id:
            raise LegacyInventoryError("Legacy upload ownership is ambiguous")
        blog_id = binding.get("blog_id")
        if blog_id is not None and (
            not isinstance(blog_id, int) or isinstance(blog_id, bool) or blog_id <= 0
        ):
            raise LegacyInventoryError("Legacy upload has an invalid blog binding")

        file_type = LEGACY_TYPES.get(path.suffix.lower())
        if file_type is None:
            raise LegacyInventoryError("Legacy upload type is unsupported")
        media_type, signature = file_type
        header, size_bytes, sha256_digest = _read_regular_file_once(path, root)
        if not _valid_signature(signature, header):
            raise LegacyInventoryError("Legacy upload signature is invalid")
        if size_bytes <= 0:
            raise LegacyInventoryError("Legacy upload is empty")

        records.append(
            asdict(
                LegacyUploadRecord(
                    path=relative_path,
                    owner_user_id=owner_user_id,
                    blog_id=blog_id,
                    purpose=_purpose(relative_path, blog_id),
                    original_filename=path.name[:255],
                    media_type=media_type,
                    size_bytes=size_bytes,
                    sha256_digest=sha256_digest,
                )
            )
        )
    return records


__all__ = ["LegacyInventoryError", "LegacyUploadRecord", "inventory_legacy_uploads"]

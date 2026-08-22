#!/usr/bin/env python3
"""Atomically activate or roll back a versioned LitBlogs release."""

from __future__ import annotations

import argparse
import hmac
import os
import re
import secrets
import subprocess
import sys
from collections.abc import Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

RELEASE_ID = re.compile(r"^litblogs-[0-9a-f]{12}$")
COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
BUILD_EPOCH = re.compile(r"^[1-9][0-9]{9,12}$")
MANIFEST_NAME = "RELEASE-MANIFEST"
PYTHON_VERSION = re.compile(r"^Python 3\.13\.[0-9]+$")
ALLOWED_RELEASE_SYMLINKS = frozenset(
    {
        ".venv/bin/python",
        ".venv/bin/python3",
        ".venv/bin/python3.13",
        ".venv/lib64",
    }
)


class ReleaseSwitchError(RuntimeError):
    """An operator-safe versioned-release validation failure."""


@dataclass(frozen=True)
class SwitchResult:
    active_release: str
    previous_release: str | None


def validate_release_id(release_id: str) -> str:
    if not RELEASE_ID.fullmatch(release_id):
        raise ReleaseSwitchError(
            "Release identifiers must be litblogs- followed by a 12-character commit prefix"
        )
    return release_id


def is_immutable_release_mode(mode: int) -> bool:
    """Return whether group and other users cannot mutate an artifact."""

    return mode & 0o022 == 0


def _validate_immutable_path(path: Path, description: str) -> None:
    if os.name != "posix":
        return
    path_status = path.stat(follow_symlinks=False)
    if not is_immutable_release_mode(path_status.st_mode):
        raise ReleaseSwitchError(
            f"The {description} must not be writable by group or other users"
        )
    get_effective_user = getattr(os, "geteuid", None)
    if (
        get_effective_user is not None
        and get_effective_user() == 0
        and path_status.st_uid != 0
    ):
        raise ReleaseSwitchError(
            f"The {description} must be owned by root during a root deployment"
        )


def _trusted_python() -> Path:
    try:
        executable = Path(sys.executable).resolve(strict=True)
        metadata = executable.stat()
    except OSError as exc:
        raise ReleaseSwitchError("The trusted Python 3.13 runtime is unavailable") from exc
    if not executable.is_file() or (
        os.name == "posix" and metadata.st_mode & 0o022
    ):
        raise ReleaseSwitchError("The trusted Python 3.13 runtime has unsafe custody")
    if os.name == "posix" and getattr(os, "geteuid", lambda: -1)() == 0:
        if metadata.st_uid != 0:
            raise ReleaseSwitchError("The trusted Python 3.13 runtime must be root-owned")
    try:
        result = subprocess.run(
            [str(executable), "--version"],
            env={"LANG": "C", "LC_ALL": "C", "PATH": "/usr/bin:/bin"},
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseSwitchError("The trusted Python 3.13 runtime could not be verified") from exc
    version = (result.stdout or result.stderr or "").strip()
    if result.returncode != 0 or PYTHON_VERSION.fullmatch(version) is None:
        raise ReleaseSwitchError("Release activation requires reviewed Python 3.13")
    return executable


def _validate_release_symlink(path: Path, release: Path, trusted_python: Path) -> None:
    relative = path.relative_to(release).as_posix()
    if relative not in ALLOWED_RELEASE_SYMLINKS:
        raise ReleaseSwitchError("Release artifacts must not contain symlinks")
    try:
        target = path.resolve(strict=True)
        target.relative_to(release)
    except ValueError:
        if relative.startswith(".venv/bin/python") and target == trusted_python:
            return
        raise ReleaseSwitchError("A release symlink has an untrusted target") from None
    except OSError as exc:
        raise ReleaseSwitchError("A release symlink is invalid") from exc
    if relative == ".venv/lib64" and target == release / ".venv" / "lib":
        return
    if relative.startswith(".venv/bin/python") and target == trusted_python:
        return
    raise ReleaseSwitchError("A release symlink has an untrusted target")


def _validate_release_tree(release: Path) -> None:
    """Reject mutable/unowned files and all but reviewed venv symlinks."""

    trusted_python = _trusted_python()
    pending = [release]
    while pending:
        directory = pending.pop()
        try:
            entries = tuple(directory.iterdir())
        except OSError as exc:
            raise ReleaseSwitchError("The release tree could not be inspected") from exc
        for path in entries:
            if path.is_symlink():
                _validate_release_symlink(path, release, trusted_python)
                continue
            _validate_immutable_path(path, "release artifact")
            if path.is_dir():
                pending.append(path)
            elif not path.is_file():
                raise ReleaseSwitchError("The release contains an unsupported artifact")
    if os.name == "posix":
        python_link = release / ".venv" / "bin" / "python"
        if not python_link.is_symlink():
            raise ReleaseSwitchError("The release-local Python symlink is missing")


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    descriptor = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def _release_lock(root: Path):
    """Serialize pointer changes with a root-owned non-following advisory lock."""

    if os.name != "posix":
        yield
        return
    import fcntl

    lock_path = root / ".release-switch.lock"
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
        metadata = os.fstat(descriptor)
        if metadata.st_uid != 0 or metadata.st_mode & 0o077:
            raise ReleaseSwitchError("The release activation lock has unsafe custody")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ReleaseSwitchError("Another release switch is already in progress") from None
        _fsync_directory(root)
        yield
    except OSError as exc:
        raise ReleaseSwitchError("The release activation lock could not be acquired") from exc
    finally:
        if "descriptor" in locals():
            os.close(descriptor)


def _validate_root(root: str | Path) -> tuple[Path, Path]:
    root_path = Path(root)
    if not root_path.is_absolute():
        raise ReleaseSwitchError("The release root must be an absolute path")
    if root_path.is_symlink() or not root_path.is_dir():
        raise ReleaseSwitchError("The release root must be an existing real directory")
    _validate_immutable_path(root_path, "release root")
    releases = root_path / "releases"
    if releases.is_symlink() or not releases.is_dir():
        raise ReleaseSwitchError(
            "The releases directory must be an existing real directory"
        )
    _validate_immutable_path(releases, "releases directory")
    return root_path, releases


def _validate_manifest(release: Path, release_id: str) -> str:
    manifest = release / MANIFEST_NAME
    if (
        manifest.is_symlink()
        or not manifest.is_file()
        or manifest.stat().st_size > 4096
    ):
        raise ReleaseSwitchError("The release manifest is missing or invalid")
    _validate_immutable_path(manifest, "release manifest")
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise ReleaseSwitchError("The release manifest could not be read") from exc
    fields: dict[str, str] = {}
    for line in lines:
        if "=" not in line:
            raise ReleaseSwitchError("The release manifest is invalid")
        key, value = line.split("=", 1)
        if key in fields:
            raise ReleaseSwitchError("The release manifest is invalid")
        fields[key] = value
    if set(fields) != {"commit", "built_at_epoch"}:
        raise ReleaseSwitchError("The release manifest is invalid")
    commit = fields["commit"]
    if (
        not COMMIT_SHA.fullmatch(commit)
        or not BUILD_EPOCH.fullmatch(fields["built_at_epoch"])
        or release_id != f"litblogs-{commit[:12]}"
    ):
        raise ReleaseSwitchError(
            "The release manifest does not match the release identifier"
        )
    return commit


def _validate_release(
    releases: Path,
    release_id: str,
    *,
    expected_commit: str | None = None,
) -> Path:
    validated_id = validate_release_id(release_id)
    release = releases / validated_id
    if release.is_symlink() or not release.is_dir():
        raise ReleaseSwitchError(
            "The selected release must be an existing real directory"
        )
    _validate_immutable_path(release, "release directory")
    manifest_commit = _validate_manifest(release, validated_id)
    _validate_release_tree(release)
    if expected_commit is not None and not hmac.compare_digest(
        manifest_commit, expected_commit
    ):
        raise ReleaseSwitchError(
            "The release manifest commit does not match the reviewed main SHA"
        )
    return release


def _read_pointer(root: Path, releases: Path, name: str) -> tuple[str, Path] | None:
    pointer = root / name
    if not pointer.is_symlink():
        if pointer.exists():
            raise ReleaseSwitchError(f"The {name} path must be a symlink")
        return None
    try:
        target = pointer.resolve(strict=True)
        releases_root = releases.resolve(strict=True)
    except OSError as exc:
        raise ReleaseSwitchError(f"The {name} release pointer is invalid") from exc
    if target.parent != releases_root:
        raise ReleaseSwitchError(
            f"The {name} release pointer resolves outside releases"
        )
    release_id = validate_release_id(target.name)
    _validate_release(releases, release_id)
    return release_id, target


def _atomic_pointer(root: Path, name: str, release_id: str) -> None:
    destination = root / name
    if not destination.is_symlink() and destination.exists():
        raise ReleaseSwitchError(f"The {name} path must be a symlink")
    temporary = root / f".{name}.{secrets.token_hex(8)}.tmp"
    try:
        temporary.symlink_to(Path("releases") / release_id, target_is_directory=True)
        os.replace(temporary, destination)
        _fsync_directory(root)
    finally:
        if temporary.is_symlink():
            temporary.unlink()


def activate_release(
    root: str | Path,
    release_id: str,
    *,
    confirmation: str,
    expected_commit: str,
) -> SwitchResult:
    """Atomically point ``current`` at a verified immutable release."""

    validated_id = validate_release_id(release_id)
    if not hmac.compare_digest(confirmation, validated_id):
        raise ReleaseSwitchError(
            "The release confirmation must exactly match the release identifier"
        )
    if not COMMIT_SHA.fullmatch(expected_commit):
        raise ReleaseSwitchError(
            "The reviewed main SHA must be exactly 40 lowercase hex characters"
        )
    root_path, _releases = _validate_root(root)
    with _release_lock(root_path):
        root_path, releases = _validate_root(root_path)
        _validate_release(
            releases,
            validated_id,
            expected_commit=expected_commit,
        )
        current = _read_pointer(root_path, releases, "current")
        previous = _read_pointer(root_path, releases, "previous")
        if current is None and previous is not None:
            raise ReleaseSwitchError(
                "The previous pointer cannot exist without a current pointer"
            )
        if current is not None and current[0] == validated_id:
            return SwitchResult(
                active_release=validated_id,
                previous_release=previous[0] if previous else None,
            )
        if current is not None:
            _atomic_pointer(root_path, "previous", current[0])
        _atomic_pointer(root_path, "current", validated_id)
        return SwitchResult(
            active_release=validated_id,
            previous_release=current[0] if current else None,
        )


def rollback_release(
    root: str | Path,
    *,
    confirmation: str,
) -> SwitchResult:
    """Atomically move ``current`` to the validated last-known release."""

    root_path, _releases = _validate_root(root)
    with _release_lock(root_path):
        root_path, releases = _validate_root(root_path)
        current = _read_pointer(root_path, releases, "current")
        previous = _read_pointer(root_path, releases, "previous")
        if current is None or previous is None:
            raise ReleaseSwitchError(
                "Both current and previous release pointers are required"
            )
        if not hmac.compare_digest(confirmation, previous[0]):
            raise ReleaseSwitchError(
                "The rollback confirmation must exactly match the previous release"
            )
        _atomic_pointer(root_path, "current", previous[0])
        return SwitchResult(
            active_release=previous[0],
            previous_release=previous[0],
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomically switch LitBlogs versioned release symlinks."
    )
    parser.add_argument("--root", default="/opt/litblogs")
    commands = parser.add_subparsers(dest="command", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("release_id")
    activate.add_argument("--confirm-release", required=True)
    activate.add_argument("--expected-commit", required=True)
    rollback = commands.add_parser("rollback")
    rollback.add_argument("--confirm-release", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "activate":
            result = activate_release(
                args.root,
                args.release_id,
                confirmation=args.confirm_release,
                expected_commit=args.expected_commit,
            )
        else:
            result = rollback_release(
                args.root,
                confirmation=args.confirm_release,
            )
    except ReleaseSwitchError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Active release: {result.active_release}")
    if (
        result.previous_release is not None
        and result.previous_release != result.active_release
    ):
        print(f"Previous release: {result.previous_release}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Create a guarded PostgreSQL backup and checksum manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_common import (
    PostgresOperatorError,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
    validate_postgres_client_installation,
    validate_postgres_tls_custody,
    validate_private_operator_directory,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
MANIFEST_FORMAT = "litblogs-postgresql-custom-v1"


@dataclass(frozen=True)
class BackupResult:
    archive: Path
    manifest: Path
    created_at: str


def is_private_directory_mode(mode: int) -> bool:
    """Return whether the directory has exact owner-only POSIX custody."""

    return mode & 0o777 == 0o700


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as backup_file:
        for chunk in iter(lambda: backup_file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _remove_owned_file(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        # Preserve the original operator-safe failure; cleanup is best effort.
        pass


def _fsync_file(path: Path) -> None:
    """Flush a completed regular file before publishing its name."""

    # A writable descriptor is required by fsync on Windows; production POSIX
    # behavior is identical and the work files are operator-owned mode 0600.
    with path.open("r+b") as source:
        os.fsync(source.fileno())


def _fsync_directory(path: Path) -> None:
    """Persist same-directory link/unlink operations on production POSIX hosts."""

    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def create_backup(
    output_directory: str | Path,
    database_url: str,
    *,
    runner: CommandRunner = subprocess.run,
    tls_custody_validator=None,
) -> BackupResult:
    """Create and atomically publish a PostgreSQL custom-format backup."""

    output_path = Path(output_directory)
    if not output_path.is_absolute():
        raise PostgresOperatorError(
            "The backup output directory must be an absolute path"
        )
    if output_path.is_symlink() or not output_path.is_dir():
        raise PostgresOperatorError("The backup output directory must already exist")
    validate_private_operator_directory(
        output_path, purpose="backup output directory"
    )
    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)

    now = datetime.now(UTC)
    created_at = now.isoformat().replace("+00:00", "Z")
    unique_name = f"litblogs-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}.dump"
    archive = output_path / unique_name
    partial = output_path / f".{unique_name}.partial"
    manifest = output_path / f"{unique_name}.manifest.json"
    manifest_partial = output_path / f".{unique_name}.manifest.json.partial"

    partial_created = False
    manifest_partial_created = False
    archive_published = False
    manifest_published = False
    descriptor: int | None = None
    try:
        descriptor = os.open(
            partial,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        partial_created = True
        os.close(descriptor)
        descriptor = None
        partial.chmod(0o600)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if partial_created:
            _remove_owned_file(partial)
        raise PostgresOperatorError(
            "A private backup work file could not be created; no backup was published"
        ) from exc

    command = [
        postgres_executable("pg_dump"),
        "--format=custom",
        "--compress=6",
        "--no-owner",
        "--no-acl",
        "--no-password",
        "--file",
        str(partial),
    ]
    environment = build_pg_environment(connection)
    try:
        result = runner(
            command,
            env=environment,
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        _remove_owned_file(partial)
        raise PostgresOperatorError(
            "Backup command could not be started; no backup was published"
        ) from exc
    if result.returncode != 0:
        _remove_owned_file(partial)
        raise PostgresOperatorError("Backup failed; no backup was published")

    try:
        _fsync_file(partial)
        with partial.open("rb") as backup_file:
            magic = backup_file.read(5)
        if magic != b"PGDMP":
            raise PostgresOperatorError(
                "Backup output was not a PostgreSQL custom-format archive"
            )
        manifest_payload = {
            "archive": archive.name,
            "created_at": created_at,
            "format": MANIFEST_FORMAT,
            "sha256": _sha256(partial),
            "size_bytes": partial.stat().st_size,
        }
        descriptor = os.open(
            manifest_partial,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        manifest_partial_created = True
        with os.fdopen(
            descriptor, "w", encoding="utf-8", newline="\n"
        ) as manifest_file:
            descriptor = None
            json.dump(manifest_payload, manifest_file, sort_keys=True)
            manifest_file.write("\n")
            manifest_file.flush()
        manifest_partial.chmod(0o600)
        _fsync_file(manifest_partial)

        partial.chmod(0o600)
        os.link(partial, archive)
        archive_published = True
        os.link(manifest_partial, manifest)
        manifest_published = True
        _fsync_directory(output_path)

        partial.unlink()
        partial_created = False
        manifest_partial.unlink()
        manifest_partial_created = False
        _fsync_directory(output_path)
    except PostgresOperatorError:
        if partial_created:
            _remove_owned_file(partial)
        if manifest_partial_created:
            _remove_owned_file(manifest_partial)
        if archive_published:
            _remove_owned_file(archive)
        if manifest_published:
            _remove_owned_file(manifest)
        raise
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        if partial_created:
            _remove_owned_file(partial)
        if manifest_partial_created:
            _remove_owned_file(manifest_partial)
        if archive_published:
            _remove_owned_file(archive)
        if manifest_published:
            _remove_owned_file(manifest)
        try:
            _fsync_directory(output_path)
        except OSError:
            pass
        raise PostgresOperatorError(
            "Backup files could not be published safely; no backup was retained"
        ) from exc

    return BackupResult(archive=archive, manifest=manifest, created_at=created_at)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a PostgreSQL custom-format backup and SHA-256 manifest."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Existing private directory on encrypted backup storage.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = subprocess.run,
    client_validator=None,
    tls_custody_validator=None,
) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL is required in the operator environment",
            file=sys.stderr,
        )
        return 2
    try:
        (client_validator or validate_postgres_client_installation)()
        result = create_backup(
            args.output_dir,
            database_url,
            runner=runner,
            tls_custody_validator=tls_custody_validator,
        )
    except PostgresOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Backup archive: {result.archive}")
    print(f"Checksum manifest: {result.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Root-only, authenticated encrypted backups of the fixed CIT Compose project.

Import create_backup(lock_held=True, resume=False) only while holding operation.lock.
verified_archive(path) yields a private, validated directory for isolated restore;
it removes its decrypted temporary files on exit. This module never restores data.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

STATE = Path("/home/litblogs/.local/state/cit-deploy")
REPO = Path("/home/litblogs/www/LitBlogs")
PROJECT = "litblogs-cit"
KEY = STATE / "backup.key"
WRITERS = ("web", "app", "email", "reconcile")
OPERATORS = ("migrate", "bootstrap-admin", "invitation", "account")
VOLUMES = ("uploads", "postgres-tls", "postgres-ca")
REQUIRED_MEMBERS = frozenset({"database.dump", "roles.sql", "uploads.tar", "postgres-tls.tar", "postgres-ca.tar", "environment", "manifest.json"})
OPTIONAL_MEMBERS = frozenset({"compose.yaml", "haproxy.cfg", "haproxy.pem"})
FORMAT = "litblogs-cit-backup-v1"
AUTH_CONTEXT = b"litblogs-cit-backup-auth-v1\0"
MAX_BUNDLE_BYTES = 1024 ** 4
DOCKER = ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock"]


class BackupError(RuntimeError):
    """Only fixed, non-sensitive messages may cross the command boundary."""


def run_command(arguments, *, output=None, timeout=1800):
    try:
        environment = {"PATH": "/usr/sbin:/usr/bin:/sbin:/bin", "LANG": "C.UTF-8"}
        if os.name != "posix":  # Unit tests may exercise OpenSSL on Windows.
            environment = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "TEMP") if name in os.environ}
        result = subprocess.run(arguments, stdin=subprocess.DEVNULL,
                                stdout=output if output is not None else subprocess.PIPE,
                                stderr=subprocess.PIPE, check=False, timeout=timeout, env=environment)
    except Exception:  # noqa: BLE001 - subprocess failures can contain sensitive command output
        raise BackupError("A backup command could not complete.") from None
    if result.returncode:
        raise BackupError("A backup command failed; sensitive output was suppressed.")
    return result.stdout or b""


def compose(arguments, *, output=None):
    return run_command([*DOCKER, "compose", "--project-name", PROJECT,
                        "--project-directory", str(REPO), "--env-file", str(STATE / ".env"),
                        "-f", str(REPO / "docker-compose.yml"), "-f", str(STATE / "compose.yaml"),
                        *arguments], output=output)


def private_file(path):
    path = Path(path)
    info = path.lstat()
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
            or stat.S_IMODE(info.st_mode) != 0o600):
        raise BackupError("A private backup file has unexpected custody.")
    return path


def private_directory(path):
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise BackupError("A backup directory path is not canonical.")
    info = path.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
        raise BackupError("A private backup directory has unexpected custody.")
    return path


def require_host():
    if os.name != "posix" or os.geteuid() != 0:
        raise BackupError("This operation requires the trusted Linux root account.")
    private_directory(STATE)
    private_file(STATE / ".env")
    if REPO.resolve() != REPO or not (REPO / "docker-compose.yml").is_file():
        raise BackupError("The fixed deployment checkout is unavailable.")


@contextmanager
def operation_lock(lock_held=False):
    if lock_held:
        yield
        return
    import fcntl
    descriptor = os.open(STATE / "operation.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        private_file(STATE / "operation.lock")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise BackupError("Another deployment operation holds the lock.") from None
        yield
    finally:
        os.close(descriptor)


def _json_records(raw):
    text = raw.decode("utf-8").strip()
    value = json.loads(text) if text.startswith("[") else [json.loads(line) for line in text.splitlines()]
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise BackupError("Docker returned an unexpected service inventory.")
    return value


def service_states():
    rows = _json_records(compose(["ps", "--all", "--format", "json"]))
    result = {}
    for row in rows:
        service, state = row.get("Service"), row.get("State")
        if (not isinstance(service, str) or not isinstance(state, str)
                or (service in result and result[service] != state)):
            raise BackupError("The deployment service inventory is ambiguous.")
        result[service] = state
    return result


@contextmanager
def quiesced(*, resume=True):
    states = service_states()
    if states.get("postgres") != "running":
        raise BackupError("PostgreSQL must already be running for a logical backup.")
    if any(states.get(name) in {"running", "restarting", "paused"} for name in OPERATORS):
        raise BackupError("An active database operator prevents a consistent backup.")
    if any(states.get(name) in {"restarting", "paused"} for name in WRITERS):
        raise BackupError("A writer has an unexpected state; backup was not started.")
    previous = [name for name in WRITERS if states.get(name) == "running"]
    try:
        if previous:
            compose(["stop", "--timeout", "60", *previous])
        stopped = service_states()
        if any(stopped.get(name) in {"running", "restarting", "paused"} for name in (*WRITERS, *OPERATORS)):
            raise BackupError("Database and upload writers did not stop.")
        if stopped.get("postgres") != "running":
            raise BackupError("PostgreSQL stopped before backup.")
        yield
    finally:
        if resume and previous:
            compose(["start", *previous])


def validate_volume_record(volume, row):
    if volume not in VOLUMES:
        raise BackupError("An unapproved volume was requested.")
    expected = f"{PROJECT}_{volume}"
    labels = row.get("Labels") or {}
    source = PurePosixPath(row.get("Mountpoint", ""))
    if (row.get("Name") != expected or row.get("Driver") != "local" or row.get("Options")
            or labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.volume") != volume
            or not source.is_absolute() or ".." in source.parts or source.name != "_data"
            or source.parent.name != expected or source.parent.parent.name != "volumes"):
        raise BackupError("A volume did not match the exact deployment identity.")
    return Path(str(source))


def volume_path(volume):
    raw = run_command([*DOCKER, "volume", "inspect", f"{PROJECT}_{volume}"], timeout=30)
    records = _json_records(raw)
    if len(records) != 1:
        raise BackupError("The deployment volume could not be identified.")
    source = validate_volume_record(volume, records[0])
    if source.resolve() != source or not source.is_dir():
        raise BackupError("The deployment volume path is not canonical.")
    return source


def _sync(path):
    with Path(path).open("r+b") as handle:
        os.fsync(handle.fileno())


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def hash_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def archive_volume(source, destination):
    source = Path(source)
    with tarfile.open(destination, "w", dereference=False) as archive:
        def add(path):
            info = path.lstat()
            if not stat.S_ISDIR(info.st_mode) and (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1):
                raise BackupError("A volume contains an unsupported filesystem object.")
            archive.add(path, arcname=path.relative_to(source).as_posix(), recursive=False)
            if stat.S_ISDIR(info.st_mode):
                for child in sorted(path.iterdir()):
                    add(child)
        add(source)
    Path(destination).chmod(0o600)


def _key_bytes():
    source = private_file(KEY)
    if source.stat().st_size > 97:
        raise BackupError("The encryption key file has an invalid format.")
    raw = source.read_bytes()
    if re.fullmatch(rb"[a-fA-F0-9]{96}\n?", raw) is None:
        raise BackupError("The encryption key file has an invalid format.")
    return raw.strip()


def ensure_key():
    if not KEY.exists():
        descriptor = os.open(KEY, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(secrets.token_hex(48).encode("ascii") + b"\n")
            handle.flush()
            os.fsync(handle.fileno())
        _sync_directory(STATE)
    _key_bytes()


def _authentication(path):
    key = hmac.new(_key_bytes(), AUTH_CONTEXT, hashlib.sha256).digest()
    digest = hmac.new(key, AUTH_CONTEXT, hashlib.sha256)
    size = 0
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
            size += len(block)
    return {"format": FORMAT, "size_bytes": size, "hmac_sha256": digest.hexdigest()}


def encrypt_file(source, destination):
    _key_bytes()
    run_command(["openssl", "enc", "-aes-256-cbc", "-salt", "-pbkdf2", "-iter", "200000", "-md", "sha256",
                 "-pass", f"file:{KEY}", "-in", str(source), "-out", str(destination)])
    Path(destination).chmod(0o600)
    return _authentication(destination)


def authenticate_file(path, metadata):
    if (not isinstance(metadata, dict) or set(metadata) != {"format", "size_bytes", "hmac_sha256"}
            or metadata.get("format") != FORMAT or type(metadata.get("size_bytes")) is not int
            or not 0 < metadata["size_bytes"] <= MAX_BUNDLE_BYTES
            or not isinstance(metadata.get("hmac_sha256"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", metadata["hmac_sha256"])):
        raise BackupError("The encrypted archive metadata is invalid.")
    actual = _authentication(path)
    if metadata["size_bytes"] != actual["size_bytes"] or not hmac.compare_digest(metadata["hmac_sha256"], actual["hmac_sha256"]):
        raise BackupError("Archive authentication failed; no data was decrypted.")


def decrypt_file(source, destination, metadata):
    authenticate_file(source, metadata)
    run_command(["openssl", "enc", "-d", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-md", "sha256",
                 "-pass", f"file:{KEY}", "-in", str(source), "-out", str(destination)])
    Path(destination).chmod(0o600)


def validate_volume_tar(path):
    seen = {}
    required_directories = set()
    total = 0
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            name = PurePosixPath(member.name)
            total += member.size
            canonical = name.as_posix()
            if (name.is_absolute() or ".." in name.parts or "\\" in member.name or canonical in seen
                    or not (member.isdir() or member.isfile()) or member.size < 0 or total > MAX_BUNDLE_BYTES):
                raise BackupError("A volume archive has an unsafe member.")
            if any(seen.get(parent.as_posix()) == "file" for parent in name.parents):
                raise BackupError("A volume archive contains conflicting filesystem objects.")
            if member.isfile() and canonical in required_directories:
                raise BackupError("A volume archive contains conflicting filesystem objects.")
            seen[canonical] = "directory" if member.isdir() else "file"
            required_directories.update(parent.as_posix() for parent in name.parents)
        if not seen:
            raise BackupError("A volume archive is empty or invalid.")


def validate_bundle(path):
    seen = set()
    total = 0
    with tarfile.open(path, "r:") as archive:
        for member in archive:
            total += member.size
            if (member.name not in REQUIRED_MEMBERS | OPTIONAL_MEMBERS or member.name in seen
                    or not member.isfile() or member.size < 0 or total > MAX_BUNDLE_BYTES
                    or (member.name == "manifest.json" and member.size > 1024 * 1024)):
                raise BackupError("The backup bundle has an unsafe member.")
            seen.add(member.name)
    if not REQUIRED_MEMBERS <= seen:
        raise BackupError("The backup bundle is incomplete.")
    return seen


def _extract_bundle(bundle, directory):
    members = validate_bundle(bundle)
    with tarfile.open(bundle, "r:") as archive:
        for member in archive:
            source = archive.extractfile(member)
            descriptor = os.open(directory / member.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with source, os.fdopen(descriptor, "wb") as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("format") != FORMAT or manifest.get("project") != PROJECT
            or not isinstance(manifest.get("files"), dict)
            or set(manifest["files"]) != members - {"manifest.json"}):
        raise BackupError("The backup manifest is invalid.")
    for name, description in manifest["files"].items():
        if description != {"sha256": hash_file(directory / name), "size_bytes": (directory / name).stat().st_size}:
            raise BackupError("A restored backup member does not match its checksum.")
    with (directory / "database.dump").open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise BackupError("The backup database is not a custom PostgreSQL archive.")
    for volume in VOLUMES:
        validate_volume_tar(directory / f"{volume}.tar")
    return manifest


@contextmanager
def verified_archive(path):
    require_host()
    path = private_directory(Path(path))
    if {child.name for child in path.iterdir()} != {"archive.enc", "authentication.json"}:
        raise BackupError("The backup directory has unexpected contents.")
    encrypted = private_file(path / "archive.enc")
    auth = private_file(path / "authentication.json")
    if auth.stat().st_size > 4096:
        raise BackupError("The archive authentication record is too large.")
    metadata = json.loads(auth.read_text(encoding="utf-8"))
    with tempfile.TemporaryDirectory(prefix=".verify-", dir=STATE) as temporary:
        stage = Path(temporary)
        decrypt_file(encrypted, stage / "bundle.tar", metadata)
        unpacked = stage / "contents"
        unpacked.mkdir(mode=0o700)
        _extract_bundle(stage / "bundle.tar", unpacked)
        yield unpacked


def verify_archive(path):
    with verified_archive(path) as directory:
        return json.loads((directory / "manifest.json").read_text(encoding="utf-8"))


def _snapshot(stage):
    for filename, executable, arguments in (
        ("database.dump", "pg_dump", ["--format=custom", "--dbname=litblogs"]),
        ("roles.sql", "pg_dumpall", ["--roles-only"]),
    ):
        with (stage / filename).open("xb") as output:
            os.chmod(stage / filename, 0o600)
            compose(["exec", "-T", "--user", "postgres", "postgres", executable,
                     "--no-password", "--host=/var/run/postgresql", "--username=postgres", *arguments], output=output)
    with (stage / "database.dump").open("rb") as handle:
        if handle.read(5) != b"PGDMP":
            raise BackupError("The database dump was not a custom archive.")
    for volume in VOLUMES:
        archive_volume(volume_path(volume), stage / f"{volume}.tar")
    shutil.copyfile(private_file(STATE / ".env"), stage / "environment")
    (stage / "environment").chmod(0o600)
    for name in OPTIONAL_MEMBERS:
        source = STATE / "https" / name if name == "haproxy.pem" else STATE / name
        if source.exists():
            metadata = source.lstat()
            expected_custody = ((metadata.st_uid, metadata.st_gid, stat.S_IMODE(metadata.st_mode)) == (99, 99, 0o400)
                                if name == "haproxy.pem" else metadata.st_uid == 0 and not metadata.st_mode & 0o022)
            if not stat.S_ISREG(metadata.st_mode) or not expected_custody or metadata.st_nlink != 1 or source.resolve() != source:
                raise BackupError("A deployment support file has unexpected custody.")
            shutil.copyfile(source, stage / name)
            (stage / name).chmod(0o600)
    revision = run_command(["git", "-c", f"safe.directory={REPO}", "-C", str(REPO), "rev-parse", "HEAD"], timeout=30).decode("ascii").strip()
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise BackupError("The deployment commit could not be identified.")
    images = {}
    for row in _json_records(compose(["ps", "--all", "--format", "json"])):
        identifier, service = row.get("ID"), row.get("Service")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9]{12,64}", identifier) or not isinstance(service, str):
            raise BackupError("A deployment image could not be identified.")
        image = run_command([*DOCKER, "container", "inspect", "--format", "{{.Image}}", identifier], timeout=30).decode("ascii").strip()
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise BackupError("A deployment image digest was invalid.")
        if service in images and images[service] != image:
            raise BackupError("Service replicas have different images; backup was not published.")
        images[service] = image
    manifest = {"format": FORMAT, "project": PROJECT, "created_at": datetime.now(UTC).isoformat(),
                "commit": revision, "images": images,
                "files": {file.name: {"sha256": hash_file(file), "size_bytes": file.stat().st_size}
                          for file in sorted(stage.iterdir())}}
    (stage / "manifest.json").write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    (stage / "manifest.json").chmod(0o600)


def create_backup(*, lock_held=False, resume=True):
    require_host()
    with operation_lock(lock_held):
        ensure_key()
        backups = STATE / "backups"
        backups.mkdir(mode=0o700, exist_ok=True)
        private_directory(backups)
        name = "backup-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "-" + secrets.token_hex(8)
        published = backups / name
        with tempfile.TemporaryDirectory(prefix=".backup-", dir=STATE) as temporary:
            root = Path(temporary)
            stage = root / "contents"
            stage.mkdir(mode=0o700)
            with quiesced(resume=resume):
                _snapshot(stage)
            bundle = root / "bundle.tar"
            with tarfile.open(bundle, "w") as archive:
                for file in sorted(stage.iterdir()):
                    archive.add(file, arcname=file.name, recursive=False)
            bundle.chmod(0o600)
            validate_bundle(bundle)
            result = root / "result"
            result.mkdir(mode=0o700)
            authentication = encrypt_file(bundle, result / "archive.enc")
            (result / "authentication.json").write_text(json.dumps(authentication, sort_keys=True) + "\n", encoding="utf-8")
            (result / "authentication.json").chmod(0o600)
            # Read/decrypt/check the complete candidate before atomic publication.
            verify_archive(result)
            for file in result.iterdir():
                _sync(file)
            _sync_directory(result)
            if published.exists():
                raise BackupError("An existing backup will not be replaced.")
            os.rename(result, published)
            _sync_directory(backups)
        return published


def main(argv=None):
    parser = argparse.ArgumentParser(description="Back up the fixed private CIT deployment.")
    commands = parser.add_subparsers(dest="command", required=True)
    backup = commands.add_parser("backup")
    backup.add_argument("--leave-stopped", action="store_true")
    verify = commands.add_parser("verify-archive")
    verify.add_argument("archive", type=Path)
    arguments = parser.parse_args(argv)
    try:
        os.umask(0o077)
        if arguments.command == "backup":
            archive = create_backup(resume=not arguments.leave_stopped)
            print(f"Backup created and authenticated: {archive}")
        else:
            require_host()
            with operation_lock():
                verify_archive(arguments.archive)
            print("Backup authentication, checksums, and archive structure verified.")
    except (Exception, KeyboardInterrupt):  # noqa: BLE001 - sanitize every failure at the CLI boundary
        print("Backup operation failed; sensitive details were suppressed.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

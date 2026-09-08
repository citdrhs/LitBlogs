"""One-shot root initialization of dedicated container volumes, never a repair tool."""

import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

UPLOAD_ROOT = Path("/var/lib/litblogs/uploads")
TLS_ROOT = Path("/var/lib/litblogs/postgres-tls")
CA_ROOT = Path("/etc/litblogs")
APP_UID = APP_GID = 10001
POSTGRES_UID = POSTGRES_GID = 999


class BootstrapError(RuntimeError):
    """An operator-safe initialization failure without sensitive diagnostics."""


def _metadata(path, *, directory, uid, gid, modes):
    metadata = path.lstat()
    expected_type = stat.S_ISDIR if directory else stat.S_ISREG
    if (
        not expected_type(metadata.st_mode)
        or metadata.st_uid != uid
        or metadata.st_gid != gid
        or stat.S_IMODE(metadata.st_mode) not in modes
        or (not directory and metadata.st_nlink != 1)
    ):
        raise BootstrapError("Volume custody is unexpected; no automatic repair was attempted.")


def _check_parents(path):
    if not path.is_absolute() or ".." in path.parts:
        raise BootstrapError("Volume paths must be absolute and canonical.")
    for parent in path.parents:
        metadata = parent.lstat()
        if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise BootstrapError("Volume parents must be root-owned, non-writable directories without symlinks.")


def _check_upload_tree(path):
    # Do not follow links or change custody of an existing application object.
    for child in path.iterdir():
        if stat.S_ISDIR(child.lstat().st_mode):
            _metadata(child, directory=True, uid=APP_UID, gid=APP_GID, modes={0o700})
            _check_upload_tree(child)
        else:
            _metadata(child, directory=False, uid=APP_UID, gid=APP_GID, modes={0o600})


def _uploads_are_new(root):
    metadata = root.lstat()
    if stat.S_ISDIR(metadata.st_mode) and metadata.st_uid == 0:
        _metadata(root, directory=True, uid=0, gid=0, modes={0o700, 0o755})
        if any(root.iterdir()):
            raise BootstrapError("An uninitialized upload volume is not empty; existing data was preserved.")
        return True
    _metadata(root, directory=True, uid=APP_UID, gid=APP_GID, modes={0o750})
    if {child.name for child in root.iterdir()} != {"objects", ".incoming"}:
        raise BootstrapError("The upload volume is partial or contains unexpected top-level entries.")
    for name in ("objects", ".incoming"):
        _metadata(root / name, directory=True, uid=APP_UID, gid=APP_GID, modes={0o700})
        _check_upload_tree(root / name)
    return False


def _openssl(*arguments):
    # OpenSSL error text can include input material. Never relay it to container logs.
    result = subprocess.run(
        ["openssl", *map(str, arguments)], stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False, timeout=60,
    )
    if result.returncode:
        raise BootstrapError("PostgreSQL TLS material is invalid or could not be generated.")
    return result.stdout


def _validate_tls(certificate, key):
    _openssl("x509", "-in", certificate, "-noout", "-checkend", "0")
    _openssl("verify", "-purpose", "sslserver", "-verify_hostname", "postgres.internal",
             "-CAfile", certificate, certificate)
    _openssl("pkey", "-in", key, "-check", "-noout")
    if _openssl("x509", "-in", certificate, "-pubkey", "-noout") != _openssl("pkey", "-in", key, "-pubout"):
        raise BootstrapError("The PostgreSQL certificate and private key do not match.")


def _tls_is_new(tls_root, ca_root):
    for root in (tls_root, ca_root):
        _metadata(root, directory=True, uid=0, gid=0, modes={0o700, 0o755})
    tls_entries = {child.name for child in tls_root.iterdir()}
    ca_entries = {child.name for child in ca_root.iterdir()}
    if not tls_entries and not ca_entries:
        return True
    for root in (tls_root, ca_root):
        _metadata(root, directory=True, uid=0, gid=0, modes={0o755})
    if tls_entries != {"server.crt", "server.key"} or ca_entries != {"postgres-root-ca.pem"}:
        raise BootstrapError("TLS volumes are partial or unexpected; no credentials were regenerated.")
    certificate, key, public_ca = tls_root / "server.crt", tls_root / "server.key", ca_root / "postgres-root-ca.pem"
    _metadata(certificate, directory=False, uid=0, gid=0, modes={0o644})
    _metadata(key, directory=False, uid=POSTGRES_UID, gid=POSTGRES_GID, modes={0o600})
    _metadata(public_ca, directory=False, uid=0, gid=0, modes={0o644})
    if public_ca.read_bytes() != certificate.read_bytes():
        raise BootstrapError("The trusted PostgreSQL certificate does not match the private TLS volume.")
    _validate_tls(certificate, key)
    return False


def _sync_directory(path):
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _generate_tls(tls_root, ca_root):
    # Staging is private. Exclusive links/creation cannot overwrite existing files.
    # A crash between volumes leaves a partial state that the next run rejects.
    with tempfile.TemporaryDirectory(prefix=".initialize-", dir=tls_root) as temporary:
        certificate, key = Path(temporary) / "server.crt", Path(temporary) / "server.key"
        _openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "3650", "-sha256",
                 "-subj", "/CN=postgres.internal", "-addext", "subjectAltName=DNS:postgres.internal",
                 "-addext", "basicConstraints=critical,CA:TRUE",
                 "-addext", "keyUsage=critical,digitalSignature,keyEncipherment,keyCertSign",
                 "-addext", "extendedKeyUsage=serverAuth", "-keyout", key, "-out", certificate)
        _validate_tls(certificate, key)
        os.chown(key, POSTGRES_UID, POSTGRES_GID)
        key.chmod(0o600)
        certificate.chmod(0o644)
        for source in (key, certificate):
            with source.open("rb") as handle:
                os.fsync(handle.fileno())
            os.link(source, tls_root / source.name, follow_symlinks=False)
        with (ca_root / "postgres-root-ca.pem").open("xb") as handle:
            os.fchmod(handle.fileno(), 0o644)
            handle.write(certificate.read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
    _sync_directory(tls_root)
    _sync_directory(ca_root)


def initialize(upload_root=UPLOAD_ROOT, tls_root=TLS_ROOT, ca_root=CA_ROOT):
    if os.name != "posix" or os.geteuid() != 0:
        raise BootstrapError("Container initialization must run once as Linux root.")
    roots = tuple(map(Path, (upload_root, tls_root, ca_root)))
    try:
        for root in roots:
            _check_parents(root)
        upload_root, tls_root, ca_root = roots
        new_uploads = _uploads_are_new(upload_root)
        new_tls = _tls_is_new(tls_root, ca_root)
        if new_uploads:
            for name in ("objects", ".incoming"):
                child = upload_root / name
                child.mkdir(mode=0o700)
                os.chown(child, APP_UID, APP_GID)
            upload_root.chmod(0o750)
            os.chown(upload_root, APP_UID, APP_GID)
            _sync_directory(upload_root)
        if new_tls:
            # PostgreSQL and the non-root application must traverse these roots.
            tls_root.chmod(0o755)
            ca_root.chmod(0o755)
            _generate_tls(tls_root, ca_root)
    except BootstrapError:
        raise
    except Exception:
        raise BootstrapError("Container volume initialization failed; existing data was not repaired or replaced.") from None


def main():
    try:
        initialize()
    except BootstrapError as error:
        print(str(error), file=sys.stderr)
        return 1
    print("Container storage and PostgreSQL TLS are initialized and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

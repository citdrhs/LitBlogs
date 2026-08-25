import os
from pathlib import Path

TEST_PRODUCTION_UPLOAD_ROOT = (
    Path.home() / ".cache" / "litblogs-settings-tests" / str(os.getpid())
)


def production_upload_settings() -> dict:
    upload_root = TEST_PRODUCTION_UPLOAD_ROOT
    upload_root.mkdir(parents=True, exist_ok=True)
    if os.name == "posix":
        upload_root.chmod(0o700)
    return {
        "upload_root": upload_root,
        "upload_scanner_required": True,
        "upload_scanner_host": "clamd",
        "upload_scanner_allowed_hosts": ("clamd",),
        "upload_registry_schema_ready": True,
        "upload_legacy_import_complete": True,
        "upload_backup_restore_verified": True,
    }

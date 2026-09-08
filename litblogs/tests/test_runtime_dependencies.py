"""Keep unconditional application imports available in the runtime-only lock."""

import os
import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]


def test_runtime_lock_includes_the_unconditional_google_requests_transport():
    runtime_lock = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
    # Development tools also install requests, masking this omission in the
    # ordinary test environment. The container installs only the runtime lock.
    assert re.search(r"^requests==", runtime_lock, re.MULTILINE), (
        "oauth_security imports Google's requests transport even when OAuth is disabled; "
        "requests must be included in requirements.txt"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c",
         f"import sys; sys.path.insert(0, {str(BACKEND)!r}); import oauth_security"],
        cwd=BACKEND,
        env={key: os.environ[key] for key in ("PATH", "SYSTEMROOT", "WINDIR") if key in os.environ},
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr

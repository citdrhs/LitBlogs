#!/usr/bin/env python3
"""Run the canonical LitBlog backend Bandit gate on every platform."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PATHS = (
    "litblogs/tests/*",
    "litblogs/.venv/*",
    "*/__pycache__/*",
    "*/.pytest_cache/*",
    "*/.ruff_cache/*",
)


def main() -> int:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "bandit",
            "-r",
            "litblogs",
            "deploy/scripts",
            "-x",
            ",".join(EXCLUDED_PATHS),
            "-ll",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

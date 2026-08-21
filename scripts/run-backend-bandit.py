#!/usr/bin/env python3
"""Run the canonical LitBlog backend Bandit gate on every platform."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "litblogs"
EXCLUDED_PATHS = (
    "./tests/*",
    "./.venv/*",
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
            ".",
            "-x",
            ",".join(EXCLUDED_PATHS),
            "-ll",
        ],
        cwd=BACKEND_ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

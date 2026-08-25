#!/usr/bin/env python3
"""Run Ruff from the backend project root for stable import classification."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1] / "litblogs"


def main() -> int:
    result = subprocess.run(
        [sys.executable, "-m", "ruff", "check", "."],
        cwd=BACKEND_ROOT,
        check=False,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

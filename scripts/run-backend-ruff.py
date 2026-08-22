#!/usr/bin/env python3
"""Run the canonical Ruff gate over backend and operator Python."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPOSITORY_ROOT / "litblogs"


def main() -> int:
    checks = (
        (
            [sys.executable, "-m", "ruff", "check", "."],
            BACKEND_ROOT,
        ),
        (
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--config",
                "litblogs/pyproject.toml",
                "deploy/scripts",
            ],
            REPOSITORY_ROOT,
        ),
    )
    for command, working_directory in checks:
        result = subprocess.run(command, cwd=working_directory, check=False)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())

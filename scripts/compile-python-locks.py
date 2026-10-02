#!/usr/bin/env python3
"""Regenerate the reviewed Python locks on the canonical production platform."""

from __future__ import annotations

import importlib.metadata
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "litblogs"
EXPECTED_PYTHON = (3, 13)
EXPECTED_PACKAGES = {"pip": "26.2.1", "pip-tools": "7.6.1"}


def _verify_toolchain() -> None:
    if sys.version_info[:2] != EXPECTED_PYTHON:
        raise SystemExit("lock generation requires Python 3.13")
    if sys.platform != "linux" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("lock generation requires the Linux x86_64 production platform")
    for distribution, expected in EXPECTED_PACKAGES.items():
        actual = importlib.metadata.version(distribution)
        if actual != expected:
            raise SystemExit(
                f"lock generation requires {distribution}=={expected}; found {actual}"
            )


def _compile(source: str, output: str, *, allow_unsafe: bool = False) -> None:
    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--quiet",
        "--generate-hashes",
        "--strip-extras",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
    ]
    if allow_unsafe:
        command.append("--allow-unsafe")
    command.extend((f"--output-file={output}", source))
    subprocess.run(command, cwd=BACKEND_ROOT, check=True)


def main() -> int:
    _verify_toolchain()
    _compile("requirements.in", "requirements.txt")
    _compile("requirements-dev.in", "requirements-dev.txt", allow_unsafe=True)
    _compile("requirements-lock.in", "requirements-lock.txt", allow_unsafe=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

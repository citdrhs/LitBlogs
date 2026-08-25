#!/usr/bin/env python3
"""Scan the tracked proposed tree for high-confidence credential formats.

The scanner deliberately reads only paths returned by ``git ls-files``. It does
not inspect Git history, patches, or deleted content, and findings never include
the matched credential value.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2 * 1024 * 1024
SECRET_PATTERNS = {
    "AWS_ACCESS_KEY": re.compile(rb"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"),
    "GITHUB_TOKEN": re.compile(
        rb"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{82,255})\b"
    ),
    "GOOGLE_API_KEY": re.compile(rb"\bAIza[0-9A-Za-z_-]{35}\b"),
    "PRIVATE_KEY": re.compile(rb"-----BEGIN (?:[A-Z0-9]+ )?PRIVATE KEY-----"),
    "SLACK_TOKEN": re.compile(rb"\bxox[baprs]-[0-9A-Za-z-]{20,}\b"),
    "STRIPE_LIVE_KEY": re.compile(rb"\b(?:sk|rk)_live_[0-9A-Za-z]{16,}\b"),
}


def tracked_paths() -> list[Path]:
    result = subprocess.run(
        ["git", "-C", str(ROOT), "ls-files", "-z"],
        check=False,
        capture_output=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise RuntimeError("git ls-files failed")
    return [Path(raw.decode("utf-8")) for raw in result.stdout.split(b"\0") if raw]


def line_number(content: bytes, match_start: int) -> int:
    return content.count(b"\n", 0, match_start) + 1


def main() -> int:
    findings: set[tuple[str, str, int]] = set()
    try:
        paths = tracked_paths()
    except (OSError, subprocess.SubprocessError, RuntimeError):
        print("ERROR: unable to enumerate the proposed tree.")
        return 2

    for relative_path in paths:
        full_path = ROOT / relative_path
        try:
            if not full_path.is_file() or full_path.stat().st_size > MAX_FILE_BYTES:
                continue
            content = full_path.read_bytes()
        except OSError:
            print(f"ERROR: unable to inspect tracked path {relative_path.as_posix()}.")
            return 2
        if b"\0" in content:
            continue
        for rule_name, pattern in SECRET_PATTERNS.items():
            for match in pattern.finditer(content):
                findings.add((rule_name, relative_path.as_posix(), line_number(content, match.start())))

    if findings:
        print("Generic secret policy violations:")
        for rule_name, path, location in sorted(findings, key=lambda item: (item[1], item[2], item[0])):
            print(f"{rule_name} {path}:{location}")
        return 1

    print("No generic secrets detected in the tracked proposed tree.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

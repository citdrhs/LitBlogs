#!/usr/bin/env python3
"""Regression tests for the proposed-tree generic secret scanner."""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCANNER = Path(__file__).with_name("check-generic-secrets.py")


class GenericSecretScannerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.assertTrue(SCANNER.is_file(), "generic secret scanner must exist")
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="litblog-generic-secret-tests-")
        self.repository = Path(self.temporary_directory.name)
        (self.repository / "scripts").mkdir()
        shutil.copy2(SCANNER, self.repository / "scripts" / SCANNER.name)
        self.git("init", "-q")
        self.git("config", "user.email", "tests@example.invalid")
        self.git("config", "user.name", "LitBlog tests")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def git(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", "-C", str(self.repository), *arguments],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def run_scanner(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(self.repository / "scripts" / SCANNER.name)],
            cwd=self.repository,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )

    def track(self, relative_path: str, content: str) -> None:
        path = self.repository / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        self.git("add", "--", relative_path)

    def test_clean_proposed_tree_passes(self) -> None:
        self.track("settings.py", 'TOKEN = os.getenv("TOKEN")\n')

        result = self.run_scanner()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("No generic secrets detected", result.stdout)

    def test_detects_token_without_echoing_value(self) -> None:
        synthetic_token = "ghp_" + ("A" * 36)
        self.track("settings.txt", f"token={synthetic_token}\n")

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("GITHUB_TOKEN settings.txt:1", result.stdout)
        self.assertNotIn(synthetic_token, result.stdout)
        self.assertNotIn(synthetic_token, result.stderr)

    def test_scans_tracked_worktree_only(self) -> None:
        synthetic_key = "AKIA" + ("A" * 16)
        self.track("safe.txt", "no credential here\n")
        self.git("commit", "-qm", "safe baseline")
        (self.repository / "untracked.txt").write_text(synthetic_key, encoding="utf-8")

        result = self.run_scanner()

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_detects_private_key_header_without_printing_material(self) -> None:
        private_key_header = "-----BEGIN " + "PRIVATE KEY-----"
        self.track("credential.pem", private_key_header + "\nopaque\n")

        result = self.run_scanner()

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("PRIVATE_KEY credential.pem:1", result.stdout)
        self.assertNotIn(private_key_header, result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)

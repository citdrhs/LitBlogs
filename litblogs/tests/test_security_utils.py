import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from security_utils import secure_code_matches


class SecureCodeMatchesTests(unittest.TestCase):
    def test_rejects_missing_values(self):
        configured = "configured-test-code"

        self.assertFalse(secure_code_matches(None, configured))
        self.assertFalse(secure_code_matches(configured, None))
        self.assertFalse(secure_code_matches(None, None))

    def test_rejects_empty_values(self):
        configured = "configured-test-code"

        self.assertFalse(secure_code_matches("", configured))
        self.assertFalse(secure_code_matches(configured, ""))
        self.assertFalse(secure_code_matches("", ""))

    def test_rejects_whitespace_only_values(self):
        configured = "configured-test-code"

        self.assertFalse(secure_code_matches("   ", configured))
        self.assertFalse(secure_code_matches(configured, "\t\r\n"))
        self.assertFalse(secure_code_matches(" ", "\t"))

    def test_rejects_wrong_value(self):
        self.assertFalse(secure_code_matches("wrong-test-code", "configured-test-code"))

    def test_accepts_correct_value(self):
        self.assertTrue(secure_code_matches("configured-test-code", "configured-test-code"))

    def test_compares_unicode_as_utf8_bytes(self):
        configured = "café-🔐"

        self.assertTrue(secure_code_matches(configured, configured))
        self.assertFalse(secure_code_matches("cafe-🔐", configured))

    def test_rejects_non_string_values(self):
        configured = "configured-test-code"

        for supplied in (123, b"configured-test-code", [], {}, object()):
            with self.subTest(supplied_type=type(supplied).__name__):
                self.assertFalse(secure_code_matches(supplied, configured))

        for configured_value in (123, b"configured-test-code", [], {}, object()):
            with self.subTest(configured_type=type(configured_value).__name__):
                self.assertFalse(secure_code_matches(configured, configured_value))


if __name__ == "__main__":
    unittest.main()

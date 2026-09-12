"""Administrator verification uses runtime cookies and internal loopback paths."""

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AdministratorProbeTests(unittest.TestCase):
    def test_root_and_public_prefix_use_runtime_cookie_names_and_public_origin(self):
        for base, origin, host, prefix, stem in (("", "https://litblogs.cit.internal:18443", "litblogs.cit.internal:18443", "__Host-", "litblogs"), ("/dren", "https://drhscit.org", "drhscit.org", "__Secure-", "litblogs"), ("/dren", "https://drhscit.org", "drhscit.org", "__Secure-", "configured-litblogs")):
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temporary:
                verify = load("verify")
                self.assertTrue(hasattr(verify, "load_settings"))
                with patch.dict(sys.modules, {"verify": verify}):
                    module = load("admin_probe")
                root = Path(temporary)
                credentials = root / "admin.json"
                credentials.write_text(json.dumps({"email": "admin@example.test", "password": "synthetic-only", "username": "fixture-admin"}))
                session = prefix + stem + "-session"
                csrf = prefix + stem + "-csrf"
                cookie_path = base + "/"
                config = {"session_cookie_name": session, "csrf_cookie_name": csrf, "cookie_path": cookie_path}
                account = {"role": "ADMIN", "is_admin": True, "username": "fixture-admin"}
                responses = [
                    (200, config, []), (401, {}, []),
                    (200, account, [("Set-Cookie", f"{session}=session-value; Path={cookie_path}; Secure; HttpOnly"), ("Set-Cookie", f"{csrf}=csrf-value; Path={cookie_path}; Secure")]),
                    (200, account, []), (403, {}, []),
                    (204, None, [("Set-Cookie", f"{session}=; Path={cookie_path}; Secure; HttpOnly"), ("Set-Cookie", f"{csrf}=; Path={cookie_path}; Secure")]),
                    (401, {}, []),
                ]
                connections = []
                for status, body, headers in responses:
                    connection = Mock()
                    response = connection.getresponse.return_value
                    response.status = status
                    response.read.return_value = json.dumps(body).encode() if body is not None else b""
                    response.getheaders.return_value = headers
                    connections.append(connection)
                settings = {"origin": origin, "host": host, "base_path": base, "cookie_path": cookie_path}
                with patch.object(module, "STATE", root), patch.object(module, "load_settings", return_value=settings, create=True), patch.object(module.ssl, "create_default_context"), patch.object(module.http.client, "HTTPSConnection", side_effect=connections), patch.object(sys, "argv", ["admin_probe.py", "--credentials", str(credentials)]):
                    module.main()
                paths = [connection.request.call_args.args[1] for connection in connections]
                self.assertEqual(paths[0], "/api/runtime-config")
                self.assertTrue(all(path.startswith("/api/") for path in paths))
                for connection in connections:
                    headers = connection.request.call_args.kwargs["headers"]
                    self.assertEqual(headers["Host"], host)
                    self.assertEqual(headers["Origin"], origin)
                    connection.close.assert_called_once_with()
                self.assertEqual(connections[-2].request.call_args.kwargs["headers"]["X-CSRF-Token"], "csrf-value")
                record = json.loads((root / "admin-verification.json").read_text())
                self.assertTrue(record["secure_host_cookies"])
                self.assertNotIn("synthetic-only", repr(record))


if __name__ == "__main__":
    unittest.main()

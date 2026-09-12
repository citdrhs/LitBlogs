"""Loopback verifier transport and Docker targeting; no server is contacted."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class VerifyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "verify.py"
        spec = importlib.util.spec_from_file_location("cit_verify", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)
        self.settings = {"origin": "https://litblogs.cit.internal:18443", "host": "litblogs.cit.internal:18443", "base_path": "", "cookie_path": "/"}

    def test_tls_keeps_expected_hostname_but_connects_only_to_loopback(self):
        module = self.module
        connection = Mock()
        response = connection.getresponse.return_value
        response.status = 200
        response.getheaders.return_value = [("Content-Type", "application/json")]
        response.read.return_value = b'{"status":"ready"}'
        with patch.object(module.ssl, "create_default_context") as context, \
                patch.object(module.http.client, "HTTPSConnection", return_value=connection) as factory, \
                patch.object(module.socket, "create_connection") as connect:
            result = module.request("/api/health/ready", settings=self.settings)
            connection._create_connection(("unexpected.example", 443), timeout=1)
        self.assertEqual(result, (200, {"content-type": "application/json"}, b'{"status":"ready"}'))
        context.assert_called_once_with(cafile=str(module.STATE / "https/server.crt"))
        factory.assert_called_once_with(module.HOST, 18443, timeout=20, context=context.return_value)
        connect.assert_called_once_with(("127.0.0.1", 18443), timeout=20)
        connection.request.assert_called_once_with("GET", "/api/health/ready", body=None, headers={"Host": "litblogs.cit.internal:18443"})
        connection.close.assert_called_once_with()

    def test_response_failure_closes_the_connection(self):
        module = self.module
        connection = Mock()
        connection.getresponse.side_effect = OSError("synthetic failure")
        with (
            patch.object(module.ssl, "create_default_context"),
            patch.object(module.http.client, "HTTPSConnection", return_value=connection),
            self.assertRaises(OSError),
        ):
            module.request("/api/health/ready", settings=self.settings)
        connection.close.assert_called_once_with()

    def test_public_host_uses_private_tls_sni_and_stripped_internal_path(self):
        module = self.module
        self.assertTrue(hasattr(module, "load_settings"), "Probes must read public deployment settings")
        with tempfile.TemporaryDirectory() as temporary, patch.object(module, "STATE", Path(temporary)):
            (Path(temporary) / ".env").write_text("LITBLOGS_ORIGIN='https://drhscit.org'\nLITBLOGS_BASE_PATH='/dren'\nLITBLOGS_GATEWAY_HOST='drhscit.org'\nSECRET_KEY='not-public'\n")
            settings = module.load_settings()
        self.assertEqual(settings, {"origin": "https://drhscit.org", "host": "drhscit.org", "base_path": "/dren", "cookie_path": "/dren/"})
        connection = Mock()
        connection.getresponse.return_value.getheaders.return_value = []
        with patch.object(module.ssl, "create_default_context"), patch.object(module.http.client, "HTTPSConnection", return_value=connection) as factory:
            module.request("/api/runtime-config", settings=settings)
        self.assertEqual(factory.call_args.args, (module.HOST, 18443))
        connection.request.assert_called_once_with("GET", "/api/runtime-config", body=None, headers={"Host": "drhscit.org"})

    def test_settings_reject_unsafe_origin_prefix_and_mismatched_gateway_host(self):
        module = self.module
        self.assertTrue(hasattr(module, "load_settings"), "Settings need fail-closed validation")
        for contents in (
            "LITBLOGS_ORIGIN='https://drhscit.org/dren'\n",
            "LITBLOGS_ORIGIN='http://drhscit.org'\n",
            "LITBLOGS_ORIGIN='https://user@drhscit.org'\n",
            "LITBLOGS_ORIGIN='https://drhscit.org:99999'\n",
            "LITBLOGS_ORIGIN='https://drhscit.org'\nLITBLOGS_GATEWAY_HOST='other.example'\n",
            "LITBLOGS_BASE_PATH='/dren/'\n",
            "LITBLOGS_BASE_PATH='/%2e'\n",
            "LITBLOGS_BASE_PATH='/dren'\nLITBLOGS_BASE_PATH=''\n",
        ):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as temporary, patch.object(module, "STATE", Path(temporary)):
                (Path(temporary) / ".env").write_text(contents)
                with self.assertRaises(ValueError):
                    module.load_settings()

    def test_compose_uses_fixed_local_socket_project_and_environment(self):
        module = self.module
        with patch.object(module.subprocess, "run", return_value=Mock(stdout=b"fixture")) as run:
            self.assertEqual(module.compose("ps", "--format", "json"), b"fixture")
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "compose", "--project-name", "litblogs-cit"])
        self.assertEqual(command[-3:], ["ps", "--format", "json"])
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "HOME", "LANG"})

    def run_public_verifier(self, asset_prefix, cookie_stem="litblogs"):
        module = self.module
        settings = {"origin": "https://drhscit.org", "host": "drhscit.org", "base_path": "/dren", "cookie_path": "/dren/"}
        config = {"local_password_registration_enabled": True, "google_oauth_enabled": False, "microsoft_oauth_enabled": False, "cookie_path": "/dren/", "session_cookie_name": f"__Secure-{cookie_stem}-session", "csrf_cookie_name": f"__Secure-{cookie_stem}-csrf"}
        html = f'<html><script type="module" src="{asset_prefix}/assets/index-hash.js"></script><link rel="stylesheet" href="{asset_prefix}/assets/index-hash.css"></html>'.encode()
        html_headers = {"cache-control": "no-store", "x-content-type-options": "nosniff", "content-security-policy": "default-src 'self'"}

        def request(path, **kwargs):
            if kwargs.get("headers", {}).get("Host") == "unapproved.invalid":
                return 421, {}, b""
            if path == "/api/health/ready":
                return 200, {}, b'{"status":"ready"}'
            if path == "/api/runtime-config":
                return 200, {}, json.dumps(config).encode()
            if path in ("/", "/index.html", "/help", "/sign-in"):
                return 200, html_headers, html
            if path == "/assets/video.mp4":
                return 206, {"content-range": "bytes 0-1023/2048"}, b"x" * 1024
            if path == "/assets/index-hash.js":
                return 200, {"content-type": "application/javascript"}, b"runtime-config"
            if path == "/assets/index-hash.css":
                return 200, {"content-type": "text/css"}, b"body {}"
            return 404, {}, b""

        with patch.object(module, "REPO", Path(__file__).resolve().parents[3]), patch.object(module, "load_settings", return_value=settings), patch.object(module, "request", side_effect=request) as requests, patch.object(module, "compose", return_value=b'{"video":"/assets/video.mp4"}'):
            result = module.main()
        return result, requests.call_args_list

    def test_runtime_verifier_checks_prefixed_build_with_stripped_asset_requests(self):
        result, requests = self.run_public_verifier("/dren")
        self.assertTrue(result.get("frontend_asset_prefix_and_delivery"), "Verifier must inspect actual built asset URLs")
        self.assertIn("/assets/index-hash.js", [call.args[0] for call in requests])
        self.assertNotIn("/dren/assets/index-hash.js", [call.args[0] for call in requests])

    def test_runtime_verifier_rejects_a_root_build_for_public_prefix(self):
        with self.assertRaises(ValueError):
            self.run_public_verifier("")

    def test_runtime_cookie_names_can_be_configured_with_the_correct_prefix(self):
        self.assertTrue(self.run_public_verifier("/dren", cookie_stem="configured-litblogs")[0]["password_registration_and_disabled_oauth"])

    def test_runtime_cookie_contract_rejects_insecure_names_and_wrong_scope(self):
        settings = {"base_path": "/dren", "cookie_path": "/dren/"}
        valid = {"session_cookie_name": "__Secure-litblogs-session", "csrf_cookie_name": "__Secure-litblogs-csrf", "cookie_path": "/dren/"}
        for changes in ({"session_cookie_name": "plain-session"}, {"csrf_cookie_name": "__Host-litblogs-csrf"}, {"cookie_path": "/"}, {"csrf_cookie_name": valid["session_cookie_name"]}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.module.runtime_cookies({**valid, **changes}, settings)


if __name__ == "__main__":
    unittest.main()

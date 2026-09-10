"""Loopback verifier transport and Docker targeting; no server is contacted."""

import importlib.util
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


class VerifyTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "verify.py"
        spec = importlib.util.spec_from_file_location("cit_verify", path)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

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
            result = module.request("/api/health/ready")
            connection._create_connection(("unexpected.example", 443), timeout=1)
        self.assertEqual(result, (200, {"content-type": "application/json"}, b'{"status":"ready"}'))
        context.assert_called_once_with(cafile=str(module.STATE / "https/server.crt"))
        factory.assert_called_once_with(module.HOST, 18443, timeout=20, context=context.return_value)
        connect.assert_called_once_with(("127.0.0.1", 18443), timeout=20)
        connection.request.assert_called_once_with("GET", "/api/health/ready", body=None, headers={})
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
            module.request("/api/health/ready")
        connection.close.assert_called_once_with()

    def test_compose_uses_fixed_local_socket_project_and_environment(self):
        module = self.module
        with patch.object(module.subprocess, "run", return_value=Mock(stdout=b"fixture")) as run:
            self.assertEqual(module.compose("ps", "--format", "json"), b"fixture")
        command = run.call_args.args[0]
        self.assertEqual(command[:6], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "compose", "--project-name", "litblogs-cit"])
        self.assertEqual(command[-3:], ["ps", "--format", "json"])
        self.assertEqual(set(run.call_args.kwargs["env"]), {"PATH", "HOME", "LANG"})


if __name__ == "__main__":
    unittest.main()

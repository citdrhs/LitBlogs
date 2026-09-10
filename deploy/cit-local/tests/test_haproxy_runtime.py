"""Optional disposable gateway integration test; never starts the real app.

Linux/WSL: LITBLOGS_TEST_HAPROXY_RUNTIME=1 python3 -m unittest discover \
    -s deploy/cit-local/tests -p test_haproxy_runtime.py -v
Requires a local Docker daemon, Compose, and openssl. Uses the pinned gateway
image for synthetic backends too; publishes only a random loopback test port.
"""

import http.client
import os
import socket
import ssl
import subprocess
import tempfile
import time
import unittest
import uuid
from pathlib import Path

from test_compose import OVERLAY, ROOT, compose_config


@unittest.skipUnless(os.environ.get("LITBLOGS_TEST_HAPROXY_RUNTIME") == "1", "Opt-in local Docker integration test")
class GatewayRuntimeTests(unittest.TestCase):
    @classmethod
    def docker(cls, *arguments, check=True):
        result = subprocess.run(["docker", *arguments], capture_output=True, text=True, timeout=120, check=False)
        if check and result.returncode:
            raise AssertionError(f"Disposable gateway Docker operation failed: {result.stderr}")
        return result.stdout.strip()

    @classmethod
    def setUpClass(cls):
        cls.sandbox = tempfile.TemporaryDirectory(prefix="litblogs-gateway-test-")
        cls.addClassCleanup(cls.sandbox.cleanup)
        cls.directory = Path(cls.sandbox.name)
        cls.network = "litblogs-gateway-test-" + uuid.uuid4().hex[:12]
        cls.containers = []
        cls.image = compose_config(ROOT / "docker-compose.yml", OVERLAY)["services"]["web"]["image"]
        cls.docker("image", "inspect", cls.image)
        subprocess.run([
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=litblogs.cit.internal", "-addext", "subjectAltName=DNS:litblogs.cit.internal",
            "-keyout", str(cls.directory / "key.pem"), "-out", str(cls.directory / "cert.pem"),
        ], check=True, capture_output=True, timeout=30)
        pem = cls.directory / "haproxy.pem"
        pem.write_bytes((cls.directory / "cert.pem").read_bytes() + (cls.directory / "key.pem").read_bytes())
        # This is a disposable generated test key; real deployment keys are 0400.
        pem.chmod(0o444)
        cls.docker("network", "create", cls.network)
        cls.addClassCleanup(cls.cleanup_docker)
        cls.start_backend(1)
        cls.gateway = cls.network + "-gateway"
        cls.containers.append(cls.gateway)
        cls.docker(
            "run", "-d", "--name", cls.gateway, "--network", cls.network,
            "--user", "99:99", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--memory", "256m", "--cpus", "0.5", "--pids-limit", "64",
            "-p", "127.0.0.1::5443",
            "--mount", f"type=bind,src={ROOT / 'deploy/cit-local/haproxy.cfg'},dst=/usr/local/etc/haproxy/haproxy.cfg,readonly",
            "--mount", f"type=bind,src={pem},dst=/usr/local/etc/haproxy/haproxy.pem,readonly",
            cls.image, "haproxy", "-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg",
        )
        try:
            binding = cls.docker("port", cls.gateway, "5443/tcp")
        except AssertionError as error:
            logs = subprocess.run(["docker", "logs", cls.gateway], capture_output=True, text=True, timeout=10, check=False)
            raise AssertionError(logs.stdout + logs.stderr) from error
        if not binding.startswith("127.0.0.1:"):
            raise AssertionError("Test gateway must bind only to loopback")
        cls.port = int(binding.rsplit(":", 1)[1])
        cls.context = ssl.create_default_context(cafile=str(cls.directory / "cert.pem"))
        cls.context.minimum_version = ssl.TLSVersion.TLSv1_2
        cls.wait_for_replicas({"replica-1"})

    @classmethod
    def cleanup_docker(cls):
        for name in reversed(cls.containers):
            cls.docker("rm", "-f", name, check=False)
        cls.docker("network", "rm", cls.network, check=False)

    @classmethod
    def start_backend(cls, number):
        name = cls.network + f"-app-{number}"
        config = cls.directory / f"backend-{number}.cfg"
        config.write_text(
            "global\n    maxconn 64\n    nbthread 1\n"
            "defaults\n    mode http\n    timeout connect 3s\n    timeout client 10s\n    timeout server 10s\n"
            "frontend app\n    bind :5000\n"
            "    http-request deny deny_status 421 unless { req.hdr(host) -i litblogs.cit.internal:18443 }\n"
            "    http-request deny deny_status 403 if { req.hdr(Forwarded) -m found }\n"
            "    http-request deny deny_status 403 if { req.hdr(X-Forwarded-For) -m found }\n"
            "    http-request return status 206 content-type text/plain string data hdr Content-Range bytes\\ 0-3/100 "
            "hdr Cache-Control private hdr Content-Security-Policy sandbox if { req.hdr(Range) -m str bytes=0-3 }\n"
            f"    http-request return status 200 content-type text/plain string replica-{number}\n"
        )
        config.chmod(0o444)
        cls.containers.append(name)
        cls.docker(
            "run", "-d", "--name", name, "--network", cls.network, "--network-alias", "app",
            "--user", "99:99", "--read-only", "--cap-drop", "ALL", "--memory", "64m", "--cpus", "0.25", "--pids-limit", "32",
            "--mount", f"type=bind,src={config},dst=/usr/local/etc/haproxy/haproxy.cfg,readonly",
            cls.image, "haproxy", "-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg",
        )

    @classmethod
    def request(cls, *, path="/api/health/ready", headers=None, method="GET", body=None):
        # Connect to the fixed test port but verify TLS using the actual name;
        # no machine DNS or hosts-file change is made.
        connection = http.client.HTTPSConnection("127.0.0.1", cls.port, timeout=5, context=cls.context)
        connection.sock = cls.context.wrap_socket(socket.create_connection(("127.0.0.1", cls.port), timeout=5), server_hostname="litblogs.cit.internal")
        try:
            request_headers = {"Host": "litblogs.cit.internal:18443"}
            request_headers.update(headers or {})
            connection.request(method, path, body=body, headers=request_headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode()
        finally:
            connection.close()

    @classmethod
    def wait_for_replicas(cls, expected):
        deadline = time.monotonic() + 35
        seen = set()
        while time.monotonic() < deadline:
            if cls.docker("inspect", "--format", "{{.State.Running}}", cls.gateway) != "true":
                logs = subprocess.run(["docker", "logs", cls.gateway], capture_output=True, text=True, timeout=10, check=False)
                raise AssertionError("Gateway stopped: " + logs.stdout + logs.stderr)
            try:
                status, _, body = cls.request()
                if status == 200:
                    seen.add(body)
                    if expected <= seen:
                        return
            except (OSError, http.client.HTTPException):
                pass
            time.sleep(0.25)
        raise AssertionError(f"Gateway never routed to all expected test replicas: expected={expected}, seen={seen}")

    def test_tls_readiness_and_actual_container_health_command(self):
        self.assertEqual(self.request()[0], 200)
        gateway = compose_config(ROOT / "docker-compose.yml", OVERLAY)["services"]["web"]
        command = gateway["healthcheck"]["test"]
        self.assertEqual(command[0], "CMD")
        self.docker("exec", self.gateway, *command[1:])

    def test_host_body_limits_and_untrusted_forwarding(self):
        self.assertEqual(self.request(headers={"Host": "unexpected.example"})[0], 421)
        self.assertEqual(self.request(path="/api/upload/video", method="POST", headers={"Content-Length": "106954753"})[0], 413)
        self.assertEqual(self.request(method="POST", headers={"Transfer-Encoding": "chunked"}, body=b"1\r\nx\r\n0\r\n\r\n")[0], 411)
        self.assertEqual(self.request(headers={"Forwarded": "for=evil", "X-Forwarded-For": "203.0.113.1"})[0], 200)

    def test_body_limit_matches_each_route_and_rejects_larger_requests(self):
        for path, limit in (
            ("/api/posts", 2 * 1024**2),
            ("/api/upload/image", 12 * 1024**2),
            ("/api/user/upload-profile-image", 12 * 1024**2),
            ("/api/user/upload-cover-image", 12 * 1024**2),
            ("/api/upload/file", 27 * 1024**2),
            ("/api/upload", 102 * 1024**2),
            ("/api/upload/video", 102 * 1024**2),
            ("/api/assignments/123/draft", 6_065_536),
            ("/api/assignments/123/submit", 6_065_536),
        ):
            with self.subTest(path=path):
                self.assertEqual(self.request(path=path, method="POST", headers={"Content-Length": str(limit)})[0], 200)
                self.assertEqual(self.request(path=path, method="POST", headers={"Content-Length": str(limit + 1)})[0], 413)

    def test_z_auth_and_api_have_separate_source_rate_limits(self):
        # Last test: deliberately exhaust the source buckets after other checks.
        # Encoded auth paths must use the same bucket as decoded application paths.
        auth = [self.request(path="/api/%61uth/login")[0] for _ in range(11)]
        self.assertEqual(auth[:10], [200] * 10)
        self.assertEqual(auth[-1], 429)
        self.assertEqual(self.request(path="/api/posts")[0], 200)
        api = [self.request(path="/api/posts")[0] for _ in range(121)]
        self.assertIn(429, api)
        self.assertEqual(api[-1], 429)
        self.assertEqual(self.request(path="/assets/example.js")[0], 200)

    def test_range_and_application_security_headers_survive(self):
        status, headers, body = self.request(headers={"Range": "bytes=0-3"})
        headers = {key.lower(): value for key, value in headers.items()}
        self.assertEqual((status, body), (206, "data"))
        self.assertEqual(headers["content-range"], "bytes 0-3/100")
        self.assertEqual(headers["cache-control"], "private")
        self.assertEqual(headers["content-security-policy"], "sandbox")
        self.assertEqual(headers["x-content-type-options"], "nosniff")

    def test_replica_discovery_without_gateway_restart(self):
        self.start_backend(2)
        self.start_backend(3)
        self.wait_for_replicas({"replica-1", "replica-2", "replica-3"})
        self.docker("rm", "-f", self.network + "-app-2", self.network + "-app-3")
        deadline = time.monotonic() + 30
        consecutive = 0
        while time.monotonic() < deadline and consecutive < 12:
            status, _, body = self.request()
            consecutive = consecutive + 1 if (status, body) == (200, "replica-1") else 0
            time.sleep(0.25)
        self.assertEqual(consecutive, 12, "Removed replicas must stop receiving requests")
        self.start_backend(4)
        self.wait_for_replicas({"replica-1", "replica-4"})


if __name__ == "__main__":
    unittest.main()

"""Check the actual Compose merge without starting containers or using secrets.

Run: python -m unittest discover -s deploy/cit-local/tests -p test_compose.py -v
Requires Docker Compose >= 2.24.4; no Docker daemon or Python packages needed.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OVERLAY = ROOT / "deploy/cit-local/compose.yaml"
ORIGIN = "https://litblogs.cit.internal:18443"


def compose_config(*files, project="litblogs-compose-test"):
    environment = dict(os.environ)
    # Override every required base input, including any real inherited secrets.
    for name in (
        "LITBLOGS_DB_PASSWORD", "EMAIL_HOST", "EMAIL_USERNAME", "EMAIL_PASSWORD",
        "EMAIL_FROM", "SECRET_KEY", "TEACHER_INVITE_HMAC_KEY", "POSTGRES_PASSWORD",
        "LITBLOGS_MIGRATOR_PASSWORD", "LITBLOGS_ACCOUNT_OPERATOR_PASSWORD",
        "LITBLOGS_INVITATION_OPERATOR_PASSWORD", "LITBLOGS_BACKUP_PASSWORD",
    ):
        environment[name] = "compose-test-placeholder"
    environment.update(
        LITBLOGS_ORIGIN="https://compose-base.example.invalid",
        ALLOWED_EMAIL_DOMAINS="example.test",
        LITBLOGS_IMAGE_TAG="compose-test",
        LITBLOGS_HTTP_PORT="54321",  # Must not survive the replacement gateway.
        EMAIL_PORT="587",
        GOOGLE_OAUTH_ENABLED="false",
        GOOGLE_CLIENT_ID="",
        UPLOAD_LEGACY_IMPORT_COMPLETE="false",
        UPLOAD_BACKUP_RESTORE_VERIFIED="false",
    )
    with tempfile.TemporaryDirectory(prefix="litblogs-compose-test-") as state:
        environment["LITBLOGS_STATE_DIR"] = state
        command = ["docker", "compose", "--env-file", os.devnull, "-p", project]
        for path in files:
            command.extend(["-f", str(path)])
        command.extend(["config", "--format", "json"])
        result = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, timeout=30, check=False)
    if result.returncode:
        raise AssertionError(f"Compose validation failed: {result.stderr}")
    return json.loads(result.stdout)


@unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
class LocalComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not OVERLAY.is_file():
            return
        cls.base = compose_config(ROOT / "docker-compose.yml")
        cls.config = compose_config(ROOT / "docker-compose.yml", OVERLAY)
        cls.services = cls.config["services"]

    def setUp(self):
        self.assertTrue(OVERLAY.is_file(), "The CIT local Compose overlay must exist")

    def test_gateway_replaces_every_inherited_nginx_setting(self):
        gateway = self.services["web"]
        self.assertRegex(gateway["image"], r"^haproxy:3\.2-alpine@sha256:[a-f0-9]{64}$")
        self.assertNotIn("nginx", json.dumps(gateway).lower())
        self.assertEqual(gateway["entrypoint"], ["haproxy", "-W", "-db", "-f", "/usr/local/etc/haproxy/haproxy.cfg"])
        self.assertEqual(gateway["command"], [])
        self.assertEqual(gateway["user"], "99:99")
        self.assertTrue(gateway["read_only"])
        self.assertEqual(len(gateway["ports"]), 1)
        port = gateway["ports"][0]
        self.assertEqual((port["host_ip"], str(port["published"]), port["target"]), ("127.0.0.1", "18443", 5443))
        mounts = gateway["volumes"]
        self.assertEqual(len(mounts), 2)
        self.assertTrue(all(mount["read_only"] for mount in mounts))
        self.assertEqual({mount["target"] for mount in mounts}, {
            "/usr/local/etc/haproxy/haproxy.cfg", "/usr/local/etc/haproxy/haproxy.pem",
        })
        config_mount = next(mount for mount in mounts if mount["target"].endswith(".cfg"))
        cert_mount = next(mount for mount in mounts if mount["target"].endswith(".pem"))
        self.assertEqual(Path(config_mount["source"]).parent, Path(cert_mount["source"]).parent.parent)
        self.assertNotIn(str(ROOT), config_mount["source"])
        self.assertIn("/api/health/ready", " ".join(gateway["healthcheck"]["test"]))
        self.assertIn("Host: litblogs.cit.internal:18443", " ".join(gateway["healthcheck"]["test"]))

    def test_overlay_preserves_private_networks_data_and_app_image(self):
        self.assertEqual(self.config["volumes"], self.base["volumes"])
        self.assertEqual(self.config["networks"], self.base["networks"])
        for name, service in self.services.items():
            if name != "web":
                self.assertFalse(service.get("ports"), name)
                self.assertEqual(service.get("volumes"), self.base["services"][name].get("volumes"), name)
            self.assertNotIn("container_name", service, name)
            self.assertNotIn("/var/run/docker.sock", json.dumps(service), name)
        for name in ("app", "email", "reconcile"):
            self.assertEqual(self.services[name]["image"], "litblogs-app:compose-test")
            self.assertEqual(self.services[name]["environment"]["LITBLOGS_ORIGIN"], ORIGIN)
        self.assertEqual(self.services["app"]["depends_on"], self.base["services"]["app"]["depends_on"])

    def test_each_service_has_enforced_limits_and_rotating_logs(self):
        for name, service in self.services.items():
            self.assertGreater(float(service["cpus"]), 0, name)
            self.assertGreater(int(service["mem_limit"]), 0, name)
            self.assertEqual(service["memswap_limit"], service["mem_limit"], name)
            self.assertGreater(int(service["pids_limit"]), 0, name)
            self.assertEqual(service["logging"], {"driver": "json-file", "options": {"max-size": "10m", "max-file": "3"}}, name)
        counts = {"app": 3, "web": 1, "postgres": 1, "clamav": 1, "email": 1, "reconcile": 1}
        memory = sum(int(self.services[name]["mem_limit"]) * count for name, count in counts.items())
        cpus = sum(float(self.services[name]["cpus"]) * count for name, count in counts.items())
        self.assertLessEqual(memory, 12 * 1024**3)
        self.assertLessEqual(cpus, 12)

    def test_gateway_has_only_edge_network_and_no_application_secrets(self):
        gateway = self.services["web"]
        self.assertEqual(set(gateway["networks"]), {"edge"})
        self.assertFalse(gateway.get("environment"))
        for name in ("app", "email", "reconcile"):
            self.assertNotIn("POSTGRES_PASSWORD", self.services[name]["environment"])


if __name__ == "__main__":
    unittest.main()

"""Restore isolation guards; no Docker or real database is contacted."""

import copy
import importlib.util
import shutil
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from test_compose import OVERLAY, ROOT, compose_config

DIRECTORY = Path(__file__).resolve().parents[1]


def load_restore():
    backup_spec = importlib.util.spec_from_file_location("backup", DIRECTORY / "backup.py")
    backup = importlib.util.module_from_spec(backup_spec)
    backup_spec.loader.exec_module(backup)
    with patch.dict(sys.modules, {"backup": backup}):
        spec = importlib.util.spec_from_file_location("cit_restore", DIRECTORY / "restore_rehearsal.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class RestoreTests(unittest.TestCase):
    def setUp(self):
        self.module = load_restore()
        self.project = "litblogs-cit-restore-0123456789ab"
        self.config = {
            "name": self.project,
            "volumes": {name: {"name": f"{self.project}_{name}"} for name in (
                "uploads", "postgres-data", "postgres-tls", "postgres-ca", "clamav-data",
            )},
            "networks": {"database": {"name": f"{self.project}_database", "internal": True}},
            "services": {
                "initialize": {"network_mode": "none", "volumes": []},
                "postgres": {"depends_on": {"initialize": {}}, "volumes": []},
                "migrate": {"depends_on": {"postgres": {}}, "volumes": []},
            },
        }

    def test_guard_exists_and_accepts_isolated_project(self):
        self.assertTrue(hasattr(self.module, "validate_restore_compose"))
        self.module.validate_restore_compose(self.config, self.project)

    @unittest.skipUnless(shutil.which("docker"), "Docker Compose is required")
    def test_guard_accepts_actual_compose_merge(self):
        config = compose_config(ROOT / "docker-compose.yml", OVERLAY, project=self.project)
        self.module.validate_restore_compose(config, self.project)

    def test_original_or_external_resources_rejected_before_restore(self):
        for resource, name in (("volumes", "uploads"), ("networks", "database")):
            for replacement in ({"name": "litblogs-cit_uploads"}, {"name": f"{self.project}_{name}", "external": True}):
                with self.subTest(resource=resource, replacement=replacement):
                    config = copy.deepcopy(self.config)
                    config[resource][name] = replacement
                    with self.assertRaises(ValueError):
                        self.module.validate_restore_compose(config, self.project)

    def test_ports_writer_dependencies_and_writable_host_mounts_are_rejected(self):
        for field, value in (
            ("ports", [{"published": "5432"}]),
            ("depends_on", {"app": {}}),
            ("volumes", [{"type": "bind", "source": "/production/data", "target": "/data"}]),
            ("container_name", "litblogs-cit-postgres-1"),
            ("network_mode", "host"),
        ):
            with self.subTest(field=field):
                config = copy.deepcopy(self.config)
                config["services"]["postgres"][field] = value
                with self.assertRaises(ValueError):
                    self.module.validate_restore_compose(config, self.project)

    def test_only_known_create_role_lines_removed(self):
        prefix = "-- fixture\n"
        statements = "".join(f"CREATE ROLE {role};\nALTER ROLE {role} NOINHERIT;\n" for role in sorted(self.module.ROLES))
        result = self.module.restore_roles_sql(prefix + statements).decode()
        self.assertNotIn("CREATE ROLE", result)
        self.assertTrue(result.startswith(prefix))
        self.assertEqual(result.count("ALTER ROLE"), 7)
        for suffix in ("CREATE ROLE unexpected;\n", "CREATE ROLE postgres;\n"):
            with self.assertRaises(ValueError):
                self.module.restore_roles_sql(statements + suffix)
        with self.assertRaises(ValueError):
            self.module.restore_roles_sql(statements.replace("CREATE ROLE postgres;\n", ""))


if __name__ == "__main__":
    unittest.main()

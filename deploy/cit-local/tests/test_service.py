"""Exercise scoped service lifecycle without Docker or systemd mutations."""

import importlib.util
import json
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / "service.py"


class ServiceTests(unittest.TestCase):
    def setUp(self):
        specification = importlib.util.spec_from_file_location("cit_service", MODULE)
        self.service = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.service)

    def test_boot_starts_existing_named_services_without_migrations_or_recreation(self):
        self.assertTrue(hasattr(self.service, "wait_ready"), "Startup needs a bounded readiness gate")
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            state = Path(temporary)
            (state / "logs").mkdir()
            stack.enter_context(patch.object(self.service, "STATE", state))
            stack.enter_context(patch.object(self.service.os, "geteuid", return_value=0, create=True))
            stack.enter_context(patch.dict(sys.modules, {"fcntl": SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=Mock())}))
            stack.enter_context(patch.object(sys, "argv", ["service.py", "start"]))
            command = stack.enter_context(patch.object(self.service.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=b"")))
            waiter = stack.enter_context(patch.object(self.service, "wait_ready"))
            self.service.main()
            arguments = command.call_args.args[0]
            tail = arguments[len(self.service.PREFIX):]
            self.assertEqual(tail, ["start", "postgres", "clamav", "app", "email", "reconcile", "web"])
            self.assertNotIn("up", arguments)
            self.assertNotIn("migrate", arguments)
            self.assertNotIn("initialize", arguments)
            waiter.assert_called_once()

    def test_busy_operation_does_not_wait_or_invoke_docker(self):
        with tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
            state = Path(temporary)
            flock = Mock(side_effect=BlockingIOError)
            stack.enter_context(patch.object(self.service, "STATE", state))
            stack.enter_context(patch.object(self.service.os, "geteuid", return_value=0, create=True))
            stack.enter_context(patch.dict(sys.modules, {"fcntl": SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=flock)}))
            stack.enter_context(patch.object(sys, "argv", ["service.py", "stop"]))
            command = stack.enter_context(patch.object(self.service.subprocess, "run"))
            with self.assertRaises(Exception) as failure:
                self.service.main()
            self.assertIsInstance(failure.exception, RuntimeError)
            self.assertIn("busy", str(failure.exception))
            self.assertEqual(flock.call_args.args[1], 6)
            command.assert_not_called()

    def test_health_gate_requires_all_singletons_and_every_app_replica(self):
        self.assertTrue(hasattr(self.service, "services_ready"), "Readiness must check all replicas")
        rows = [{"Service": name, "State": "running", "Health": "healthy"}
                for name in ("postgres", "clamav", "app", "app", "email", "reconcile", "web")]
        self.assertTrue(self.service.services_ready(json.dumps(rows).encode()))
        rows[3]["Health"] = "starting"
        self.assertFalse(self.service.services_ready(json.dumps(rows).encode()))
        rows[3]["Health"] = "healthy"
        rows.append({"Service": "postgres", "State": "running", "Health": "healthy"})
        self.assertFalse(self.service.services_ready(json.dumps(rows).encode()))
        self.assertFalse(self.service.services_ready(b"[]"))


if __name__ == "__main__":
    unittest.main()

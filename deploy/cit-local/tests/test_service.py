"""Exercise scoped service lifecycle without Docker or systemd mutations."""

import importlib.util
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from lifecycle_fixture import DockerFixture, load_lifecycle

MODULE = Path(__file__).resolve().parents[1] / "service.py"


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.lifecycle = load_lifecycle()
        self.engine = DockerFixture()
        specification = importlib.util.spec_from_file_location("cit_service", MODULE)
        self.service = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.service)
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.state = Path(directory)
        (self.state / "logs").mkdir()
        self.stack.enter_context(patch.object(self.service, "STATE", self.state))
        self.stack.enter_context(patch.object(self.service.os, "geteuid", return_value=0, create=True))
        self.flock = Mock()
        self.stack.enter_context(patch.dict(sys.modules, {"fcntl": SimpleNamespace(LOCK_EX=2, LOCK_NB=4, flock=self.flock)}))
        self.stack.enter_context(patch.object(self.lifecycle, "run", side_effect=self.engine.run))

    def call(self, operation):
        with patch.object(sys, "argv", ["service.py", operation]):
            self.service.main()

    def test_boot_starts_existing_ids_without_migrations_or_recreation(self):
        for key in self.engine.ids(*self.lifecycle.SERVICES):
            self.engine.records[key].update(State="exited", Health=None)
        before = self.engine.snapshot()
        self.call("start")
        starts = [command[2:] for command in self.engine.mutations()]
        self.assertEqual(starts, [self.engine.ids("postgres", "clamav"), self.engine.ids("app", "email", "reconcile"), self.engine.ids("web")])
        for key in self.engine.ids("migrate", "initialize"):
            self.assertEqual(before[key], self.engine.records[key])
        self.assertIn("start completed", (self.state / "logs/service-start.log").read_text())

    def test_busy_operation_does_not_wait_or_invoke_docker(self):
        self.flock.side_effect = BlockingIOError
        with self.assertRaisesRegex(RuntimeError, "busy"):
            self.call("stop")
        self.assertEqual(self.flock.call_args.args[1], 6)
        self.assertEqual(self.engine.commands, [])

    def test_writer_stop_failure_leaves_database_and_scanner_running(self):
        self.engine.fail_stop = True
        before = self.engine.snapshot()
        with self.assertRaisesRegex(RuntimeError, "partial Docker stop"):
            self.call("stop")
        for key in self.engine.ids("postgres", "clamav"):
            self.assertEqual(before[key], self.engine.records[key])
        self.assertIn("sensitive details suppressed", (self.state / "logs/service-stop.log").read_text())

    def test_start_readiness_failure_is_logged_without_claiming_success(self):
        with (
            patch.object(self.lifecycle, "wait_healthy", side_effect=self.lifecycle.LifecycleError("Readiness deadline expired.")),
            self.assertRaises(self.lifecycle.LifecycleError),
        ):
            self.call("start")
        log = (self.state / "logs/service-start.log").read_text()
        self.assertIn("Readiness deadline expired", log)
        self.assertNotIn("completed", log)

    def test_update_latch_prevents_start_before_docker_access(self):
        (self.state / "update-blocked.json").write_text("{}")
        with self.assertRaisesRegex(RuntimeError, "operator review"):
            self.call("start")
        self.assertEqual(self.engine.commands, [])


if __name__ == "__main__":
    unittest.main()

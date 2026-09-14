"""Operator entrypoint boundaries; no Docker or systemd mutations."""

import importlib.util
import io
import json
import os
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "operator.py"


class OperatorTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SOURCE.exists(), "The permanent operator command must exist")
        specification = importlib.util.spec_from_file_location("cit_operator", SOURCE)
        self.operator = importlib.util.module_from_spec(specification)
        specification.loader.exec_module(self.operator)

    def test_environment_cannot_redirect_docker_or_override_private_settings(self):
        malicious = {"LITBLOGS_ORIGIN": "https://wrong.invalid/dren", "LITBLOGS_STATE_DIR": "/tmp/wrong",
                     "COMPOSE_FILE": "/tmp/evil.yml", "COMPOSE_PROJECT_NAME": "other-project",
                     "DOCKER_HOST": "tcp://wrong.invalid:2375", "PYTHONPATH": "/tmp/evil"}
        result = SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")
        with patch.dict(os.environ, malicious), patch.object(self.operator.subprocess, "run", return_value=result) as command:
            self.operator.run(self.operator.compose("ps", "--all", "--format", "json"))
        arguments = command.call_args.args[0]
        self.assertEqual(arguments[:4], ["/usr/bin/docker", "--host", "unix:///var/run/docker.sock", "compose"])
        for flag, value in (("--project-name", "litblogs-cit"), ("--project-directory", str(self.operator.REPO)),
                            ("--env-file", str(self.operator.STATE / ".env"))):
            self.assertEqual(arguments[arguments.index(flag) + 1], value)
        self.assertEqual([arguments[index + 1] for index, value in enumerate(arguments) if value == "-f"],
                         [str(self.operator.REPO / "docker-compose.yml"), str(self.operator.STATE / "compose.yaml")])
        self.assertFalse(set(malicious) & set(command.call_args.kwargs["env"]))
        self.assertEqual(command.call_args.kwargs["cwd"], str(self.operator.STATE))
        self.assertEqual(command.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_active_oneshot_starts_through_corrected_installed_helper(self):
        with patch.object(self.operator, "unit_state", return_value="active"), \
                patch.object(self.operator, "recovery_blocked", return_value=False), \
                patch.object(self.operator, "run", return_value=b"") as command:
            self.operator.start()
        self.assertEqual(command.call_args.args[0], ["/usr/bin/python3", "-E", "-s",
                                                    str(self.operator.STATE / "service.py"), "start"])
        self.assertNotIn("compose", command.call_args.args[0])

    def test_inactive_or_failed_unit_starts_through_systemd(self):
        for before in ("inactive", "failed"):
            with self.subTest(state=before), patch.object(self.operator, "unit_state", side_effect=[before, "active"]), \
                    patch.object(self.operator, "recovery_blocked", return_value=False), \
                    patch.object(self.operator, "run", return_value=b"") as command:
                self.operator.start()
            self.assertEqual(command.call_args.args[0], ["/usr/bin/systemctl", "start", "litblogs-cit.service"])

    def test_blocked_or_transitioning_start_never_mutates_services(self):
        for blocked, state in ((True, "active"), (False, "activating"), (False, "deactivating")):
            with self.subTest(blocked=blocked, state=state), \
                    patch.object(self.operator, "recovery_blocked", return_value=blocked), \
                    patch.object(self.operator, "unit_state", return_value=state), \
                    patch.object(self.operator, "run") as command:
                with self.assertRaises(self.operator.OperatorError):
                    self.operator.start()
                command.assert_not_called()

    def test_systemd_condition_skip_cannot_report_start_success(self):
        with patch.object(self.operator, "unit_state", side_effect=["inactive", "inactive"]), \
                patch.object(self.operator, "recovery_blocked", return_value=False), \
                patch.object(self.operator, "run", return_value=b""), \
                self.assertRaises(self.operator.OperatorError):
            self.operator.start()

    def test_private_path_rejects_wrong_owner_write_bits_links_and_noncanonical_path(self):
        location = Path("/fixed/private")
        good = {"st_mode": stat.S_IFREG | 0o600, "st_uid": 0, "st_gid": 0, "st_nlink": 1}
        for change in ({"st_uid": 1000}, {"st_gid": 1000}, {"st_mode": stat.S_IFREG | 0o622},
                       {"st_mode": stat.S_IFLNK | 0o600}, {"st_nlink": 2}):
            with self.subTest(change=change), patch.object(Path, "lstat", return_value=SimpleNamespace(**{**good, **change})), \
                    patch.object(Path, "resolve", return_value=location), \
                    self.assertRaises(self.operator.OperatorError):
                self.operator.validate_path(location, modes={0o600})
        with patch.object(Path, "lstat", return_value=SimpleNamespace(**good)), \
                patch.object(Path, "resolve", return_value=Path("/elsewhere")), \
                self.assertRaises(self.operator.OperatorError):
            self.operator.validate_path(location, modes={0o600})

    def test_validate_paths_covers_private_settings_and_installed_code(self):
        with patch.object(self.operator.os, "name", "posix"), \
                patch.object(self.operator.os, "geteuid", return_value=0, create=True), \
                patch.object(self.operator, "validate_path") as validate:
            self.operator.validate_paths()
        checked = {call.args[0] for call in validate.call_args_list}
        self.assertTrue({self.operator.STATE, self.operator.STATE / "logs", self.operator.STATE / ".env",
                         self.operator.STATE / "compose.yaml", self.operator.STATE / "service.py",
                         self.operator.STATE / "lifecycle.py", self.operator.STATE / "verify.py"} <= checked)
        self.assertIn(Path(self.operator.__file__).absolute(), checked)

    @unittest.skipUnless(os.name == "posix" and os.geteuid() == 0, "Real ownership checks require Linux root")
    def test_real_private_file_permissions_and_symlink_rejection(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            directory.chmod(0o700)
            private = directory / "private"
            private.write_text("synthetic fixture")
            private.chmod(0o600)
            self.operator.validate_path(directory, directory=True, modes={0o700})
            self.operator.validate_path(private, modes={0o600})
            alias = directory / "alias"
            alias.symlink_to(private)
            with self.assertRaises(self.operator.OperatorError):
                self.operator.validate_path(alias, modes={0o600})
            private.chmod(0o644)
            with self.assertRaises(self.operator.OperatorError):
                self.operator.validate_path(private, modes={0o600})

    def test_status_outputs_only_safe_fixed_service_aggregates(self):
        rows = [{"Service": "app", "State": "running", "Health": "healthy", "Command": "SECRET_VALUE"},
                {"Service": "app", "State": "exited", "Health": "", "Names": "SECRET_VALUE"},
                {"Service": "migrate", "State": "exited", "Health": "", "Command": "SECRET_VALUE"}]
        output = io.StringIO()
        with patch.object(self.operator, "run", return_value=json.dumps(rows).encode()), \
                patch.object(self.operator, "unit_state", return_value="active"), \
                patch.object(self.operator, "recovery_blocked", return_value=False), redirect_stdout(output):
            self.operator.status()
        result = json.loads(output.getvalue())
        self.assertEqual(result["services"]["app"], {"containers": 2, "running": 1, "healthy": 1})
        self.assertEqual(set(result["services"]), set(self.operator.SERVICES))
        self.assertNotIn("SECRET_VALUE", output.getvalue())
        self.assertNotIn("migrate", output.getvalue())

    def test_logs_are_bounded_in_private_file_and_never_echoed(self):
        output = io.StringIO()
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            (state / "logs").mkdir()
            with patch.object(self.operator, "STATE", state), \
                    patch.object(self.operator, "run", return_value=b"SECRET_VALUE\n" * 200000) as command, redirect_stdout(output):
                self.operator.logs()
            target = state / "logs" / "operator-latest.log"
            self.assertTrue(target.is_file())
            self.assertLessEqual(target.stat().st_size, self.operator.MAX_LOG_BYTES)
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertIn(str(target), output.getvalue())
            self.assertNotIn("SECRET_VALUE", output.getvalue())
        arguments = command.call_args.args[0]
        self.assertEqual(arguments[-len(self.operator.SERVICES):], list(self.operator.SERVICES))
        self.assertIn("--tail", arguments)
        self.assertNotIn("--follow", arguments)

    def test_check_uses_installed_verifier_and_does_not_echo_its_response(self):
        output = io.StringIO()
        with patch.object(self.operator, "run", return_value=b"SECRET_VALUE") as command, redirect_stdout(output):
            self.operator.check()
        self.assertEqual(command.call_args.args[0], ["/usr/bin/python3", "-E", "-s", str(self.operator.STATE / "verify.py")])
        self.assertNotIn("SECRET_VALUE", output.getvalue())

    def test_command_errors_never_expose_subprocess_output(self):
        result = SimpleNamespace(returncode=1, stdout=b"SECRET_VALUE", stderr=b"SECRET_VALUE")
        with patch.object(self.operator.subprocess, "run", return_value=result), \
                self.assertRaises(self.operator.OperatorError) as error:
            self.operator.run(["/usr/bin/false"])
        self.assertNotIn("SECRET_VALUE", str(error.exception))

    def test_extra_or_unknown_arguments_cannot_be_passed_through(self):
        for arguments in (["start", "--env-file", "/tmp/evil"], ["logs", "other-service"], ["exec"], ["down"]):
            with self.subTest(arguments=arguments), patch.object(self.operator, "validate_paths") as validate, \
                    patch.object(self.operator, "run") as command, redirect_stdout(io.StringIO()):
                with self.assertRaises(self.operator.OperatorError):
                    self.operator.main(arguments)
                validate.assert_not_called()
                command.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""CIT update admission and recovery tests without Docker, GitHub, or a server."""

import copy
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "cit_update", Path(__file__).resolve().parents[1] / "update.py"
)
update = importlib.util.module_from_spec(SPEC)
with patch.dict(sys.modules, {"fcntl": types.SimpleNamespace()}):
    SPEC.loader.exec_module(update)

SHA = "a" * 40
NEXT = "b" * 40


def config():
    services = {
        name: {"image": f"litblogs-app:{SHA}", "volumes": []}
        for name in (
            "web",
            "app",
            "postgres",
            "clamav",
            "email",
            "reconcile",
            "initialize",
            "migrate",
        )
    }
    services["web"] = {
        "image": "haproxy:3.2-alpine@sha256:" + "c" * 64,
        "ports": [{"host_ip": "127.0.0.1", "published": "18443", "target": 5443}],
        "volumes": [
            {
                "type": "bind",
                "source": update.STATE.as_posix() + "/haproxy.cfg",
                "target": "/usr/local/etc/haproxy/haproxy.cfg",
                "read_only": True,
            }
        ],
    }
    return {
        "name": "litblogs-cit",
        "services": services,
        "volumes": {"uploads": {"name": "litblogs-cit_uploads"}},
        "networks": {"edge": {"name": "litblogs-cit_edge"}},
    }


class UpdateTests(unittest.TestCase):
    def test_build_passes_only_validated_public_base_path_and_commit_tag(self):
        self.assertTrue(hasattr(update, "build_image"), "The updater must preserve the frontend public base path")
        for base_path, expected in (("", "/"), ("/dren", "/dren/"), ("/school/blogs", "/school/blogs/")):
            with self.subTest(base_path=base_path), patch.object(update.subprocess, "run") as run:
                update.build_image(SHA, Path("candidate-source"), {"LITBLOGS_BASE_PATH": base_path, "SECRET_KEY": "must-stay-private"}, object())
                command = run.call_args.args[0]
                self.assertEqual(command, ["/usr/bin/docker", "build", "--build-arg", f"VITE_APP_BASE_PATH={expected}", "-t", f"litblogs-app:{SHA}", "candidate-source"])
                self.assertNotIn("must-stay-private", repr(run.call_args))
                self.assertEqual(run.call_args.kwargs["env"], update.CLEAN_ENV)

    def test_build_rejects_noncanonical_paths_before_running_docker(self):
        self.assertTrue(hasattr(update, "build_image"), "Build inputs need validation")
        for value in ("/", "/dren/", "//evil.test", "/a/../b", "/%2e", "/a?x", "/a b", "/a\nARG X", "/_bad", "/a" * 130):
            with self.subTest(value=value), patch.object(update.subprocess, "run") as run:
                with self.assertRaises(ValueError):
                    update.build_image(SHA, Path("source"), {"LITBLOGS_BASE_PATH": value}, object())
                run.assert_not_called()

    def test_git_subprocess_keeps_public_source_readable_and_disables_hooks(self):
        with patch.object(
            update.subprocess,
            "run",
            return_value=types.SimpleNamespace(stdout=b"fixture\n"),
        ) as command:
            self.assertEqual(
                update.git("fetch", "--quiet", "origin", "main"), "fixture"
            )
        arguments = command.call_args.args[0]
        self.assertIn("core.hooksPath=/dev/null", arguments)
        self.assertIn(f"safe.directory={update.REPO}", arguments)
        self.assertEqual(command.call_args.kwargs.get("umask"), 0o022)
        self.assertEqual(command.call_args.kwargs["env"], update.CLEAN_ENV)

    @unittest.skipUnless(
        os.name == "posix" and shutil.which("git"), "Requires local Linux Git"
    )
    def test_git_head_rewrite_remains_readable_under_private_parent_umask(self):
        with tempfile.TemporaryDirectory(prefix="litblogs-git-mode-test-") as temporary:
            repository = Path(temporary)
            subprocess.run(
                ["git", "init", "--quiet", str(repository)],
                check=True,
                capture_output=True,
                timeout=30,
            )
            head = repository / ".git" / "HEAD"
            previous_mask = os.umask(0o077)
            try:
                with patch.object(update, "REPO", repository):
                    update.git("symbolic-ref", "HEAD", "refs/heads/permission-fixture")
                self.assertEqual(head.stat().st_mode & 0o777, 0o644)
                self.assertEqual(os.umask(0o077), 0o077)
            finally:
                os.umask(previous_mask)

    def test_check_lookup_rejects_non_commit_input_before_network_access(self):
        with patch.object(update.urllib.request, "urlopen") as request:
            with self.assertRaises(ValueError):
                update.fetch_checks("../unexpected-target")
            request.assert_not_called()

    def test_requires_all_eleven_latest_successful_checks_on_exact_commit(self):
        self.assertEqual(len(update.REQUIRED_CHECKS), 11)
        self.assertTrue(
            {"CodeQL analysis (python)", "CodeQL analysis (javascript-typescript)"}
            <= update.REQUIRED_CHECKS
        )
        checks = [
            {
                "id": index,
                "name": name,
                "head_sha": SHA,
                "app": {"slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
            }
            for index, name in enumerate(update.REQUIRED_CHECKS, 1)
        ]
        self.assertTrue(update.checks_pass(checks, SHA))
        self.assertFalse(update.checks_pass(checks[:-1], SHA))
        self.assertFalse(update.checks_pass(checks, NEXT))
        self.assertFalse(
            update.checks_pass(
                checks + [{**checks[0], "id": 100, "conclusion": "failure"}], SHA
            )
        )
        self.assertFalse(
            update.checks_pass(
                checks + [{**checks[0], "id": 100, "status": "in_progress"}], SHA
            )
        )

    def passing_checks(self):
        return [
            {
                "id": index,
                "name": name,
                "head_sha": SHA,
                "app": {"slug": "github-actions"},
                "status": "completed",
                "conclusion": "success",
            }
            for index, name in enumerate(update.REQUIRED_CHECKS, 1)
        ]

    def test_present_codeql_alert_failure_blocks_successful_analysis_jobs(self):
        checks = self.passing_checks()
        alert = {
            "id": 100,
            "name": "CodeQL",
            "head_sha": SHA,
            "app": {"slug": "github-advanced-security", "id": 57789},
            "status": "completed",
            "conclusion": "failure",
        }
        self.assertFalse(update.checks_pass([*checks, alert], SHA))
        self.assertTrue(update.checks_pass([*checks, {**alert, "head_sha": NEXT}], SHA))
        self.assertTrue(update.checks_pass(checks, SHA))

    def test_latest_exact_commit_codeql_alert_must_complete_successfully(self):
        checks = self.passing_checks()
        failed = {
            "id": 100,
            "name": "CodeQL",
            "head_sha": SHA,
            "app": {"slug": "github-advanced-security"},
            "status": "completed",
            "conclusion": "failure",
        }
        succeeded = {**failed, "id": 101, "conclusion": "success"}
        self.assertTrue(update.checks_pass([*checks, succeeded, failed], SHA))
        for status, conclusion in (
            ("queued", None),
            ("in_progress", None),
            ("completed", "failure"),
            ("completed", "neutral"),
            ("completed", "cancelled"),
            ("completed", "skipped"),
        ):
            latest = {
                **succeeded,
                "id": 102,
                "status": status,
                "conclusion": conclusion,
            }
            self.assertFalse(update.checks_pass([*checks, latest, succeeded], SHA))

    def test_present_cit_controls_must_pass_and_cannot_be_spoofed(self):
        checks = self.passing_checks()
        control = {
            "id": 100,
            "name": "CIT local deployment controls",
            "head_sha": SHA,
            "app": {"slug": "github-actions"},
            "status": "completed",
            "conclusion": "failure",
        }
        self.assertFalse(update.checks_pass([*checks, control], SHA))
        self.assertTrue(
            update.checks_pass([*checks, {**control, "head_sha": NEXT}], SHA)
        )
        self.assertTrue(
            update.checks_pass(
                [*checks, control, {**control, "id": 101, "conclusion": "success"}], SHA
            )
        )
        for name, slug in (
            ("CodeQL", "github-actions"),
            (control["name"], "another-app"),
        ):
            self.assertFalse(
                update.checks_pass(
                    [
                        *checks,
                        {
                            **control,
                            "name": name,
                            "app": {"slug": slug},
                            "conclusion": "success",
                        },
                    ],
                    SHA,
                )
            )

    def test_required_analysis_jobs_cannot_be_replaced_by_another_app(self):
        checks = self.passing_checks()
        for language in ("python", "javascript-typescript"):
            changed = [
                {**item, "app": {"slug": "another-app"}}
                if item["name"] == f"CodeQL analysis ({language})"
                else item
                for item in checks
            ]
            self.assertFalse(update.checks_pass(changed, SHA))

    def test_rejects_host_bind_mounts_and_unapproved_repository_mounts(self):
        for source in (
            "/",
            "/var/run/docker.sock",
            update.REPO.as_posix() + "/.git",
            update.STATE.as_posix() + "/.env",
        ):
            candidate = config()
            candidate["services"]["app"]["volumes"] = [
                {
                    "type": "bind",
                    "source": source,
                    "target": "/escape",
                    "read_only": True,
                }
            ]
            with self.assertRaises(ValueError):
                update.validate_compose(candidate)

    def test_rejects_external_resources_mount_drivers_and_host_namespaces(self):
        for setting in (
            {"pid": "host"},
            {"ipc": "host"},
            {"network_mode": "host"},
            {"devices": ["/dev/sda"]},
            {"container_name": "another-project"},
            {"use_api_socket": True},
            {"volumes_from": ["other"]},
        ):
            candidate = config()
            candidate["services"]["app"].update(setting)
            with self.assertRaises(ValueError):
                update.validate_compose(candidate)
        for setting in (
            {"external": True},
            {"name": "litblogs-cit_other"},
            {"driver_opts": {"device": "/", "type": "none", "o": "bind"}},
        ):
            candidate = config()
            candidate["volumes"]["uploads"].update(setting)
            with self.assertRaises(ValueError):
                update.validate_compose(candidate)

    def test_private_expected_gateway_and_named_volumes_are_accepted(self):
        update.validate_compose(config())
        invalid = config()
        invalid["services"]["web"]["ports"][0]["host_ip"] = "0.0.0.0"
        with self.assertRaises(ValueError):
            update.validate_compose(invalid)

    def test_infrastructure_config_changes_block_app_update(self):
        before = config()
        after = copy.deepcopy(before)
        after["services"]["app"]["image"] = f"litblogs-app:{NEXT}"
        self.assertTrue(update.infrastructure_compatible(before, after))
        after["services"]["postgres"]["image"] = "postgres:other"
        self.assertFalse(update.infrastructure_compatible(before, after))

    def test_only_added_revisions_are_automatically_migrated(self):
        self.assertTrue(
            hasattr(update, "validate_changes"),
            "Changes need an explicit migration and infrastructure gate",
        )
        self.assertFalse(
            update.validate_changes(["M\tlitblogs/main.py", "M\tREADME.md"])
        )
        self.assertTrue(
            update.validate_changes(
                ["A\tlitblogs/migrations/versions/abc_new_columns.py"]
            )
        )
        for change in (
            "M\tlitblogs/migrations/versions/abc_old.py",
            "D\tlitblogs/migrations/versions/abc_old.py",
            "M\tlitblogs/migrations/env.py",
            "M\tlitblogs/alembic.ini",
            "M\tdeploy/container/postgres-init.sh",
            "M\tdeploy/container/pg_hba.conf",
            "M\tdeploy/container/initialize.py",
        ):
            with self.assertRaises(ValueError):
                update.validate_changes([change])

    def test_backup_failure_latches_and_recovers_previous_apps_without_migration(self):
        self.assertTrue(
            hasattr(update, "deploy_candidate"),
            "Update needs a tested recovery boundary",
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(update, "STATE", Path(temporary)),
            patch.object(update, "restart_previous") as recover,
        ):
            with self.assertRaises(RuntimeError):
                update.deploy_candidate(
                    NEXT,
                    {"LITBLOGS_IMAGE_TAG": SHA},
                    Path(temporary) / ".candidate.env",
                    Path(temporary) / NEXT,
                    2,
                    "db-id",
                    has_migrations=True,
                    backup_factory=lambda **_kwargs: (_ for _ in ()).throw(
                        RuntimeError("private")
                    ),
                )
            recover.assert_called_once()
            record = json.loads((Path(temporary) / "update-blocked.json").read_text())
            self.assertFalse(record["migration_attempted"])
            self.assertNotIn("private", repr(record))

    def test_migration_failure_never_rolls_back_or_restarts_old_apps(self):
        self.assertTrue(
            hasattr(update, "deploy_candidate"),
            "Update needs a tested recovery boundary",
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(update, "STATE", Path(temporary)),
            patch.object(update, "restart_previous") as recover,
            patch.object(update, "stop_writers") as stop,
            patch.object(
                update,
                "compose",
                side_effect=RuntimeError("private migration diagnostic"),
            ),
        ):
            with self.assertRaises(RuntimeError):
                update.deploy_candidate(
                    NEXT,
                    {"LITBLOGS_IMAGE_TAG": SHA},
                    Path(temporary) / ".candidate.env",
                    Path(temporary) / NEXT,
                    2,
                    "db-id",
                    has_migrations=True,
                    backup_factory=lambda **_kwargs: "backup.enc",
                )
            recover.assert_not_called()
            stop.assert_called_once()
            record = json.loads((Path(temporary) / "update-blocked.json").read_text())
            self.assertTrue(record["migration_attempted"])
            self.assertNotIn("private", repr(record))

    def test_failed_code_only_release_can_recover_old_code_without_touching_schema(
        self,
    ):
        self.assertTrue(
            hasattr(update, "deploy_candidate"),
            "Update needs a tested recovery boundary",
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(update, "STATE", Path(temporary)),
            patch.object(update, "restart_previous") as recover,
            patch.object(update, "git"),
            patch.object(
                update, "compose", side_effect=RuntimeError("app startup failed")
            ) as compose,
        ):
            with self.assertRaises(RuntimeError):
                update.deploy_candidate(
                    NEXT,
                    {"LITBLOGS_IMAGE_TAG": SHA},
                    Path(temporary) / ".candidate.env",
                    Path(temporary) / NEXT,
                    1,
                    "db-id",
                    has_migrations=False,
                    backup_factory=lambda **_kwargs: "backup.enc",
                )
            recover.assert_called_once()
            self.assertFalse(
                any("migrate" in call.args for call in compose.call_args_list)
            )

    def test_success_keeps_database_identity_records_backup_and_clears_latch(self):
        self.assertTrue(
            hasattr(update, "deploy_candidate"),
            "Update needs a tested recovery boundary",
        )
        with (
            tempfile.TemporaryDirectory() as temporary,
            patch.object(update, "STATE", Path(temporary)),
            patch.object(update, "git"),
            patch.object(update, "run"),
            patch.object(
                update,
                "compose",
                return_value=subprocess.CompletedProcess([], 0, b"db-id\n"),
            ) as compose,
        ):
            update.deploy_candidate(
                NEXT,
                {"LITBLOGS_IMAGE_TAG": SHA, "LITBLOGS_BASE_PATH": "/dren"},
                Path(temporary) / ".candidate.env",
                Path(temporary) / NEXT,
                3,
                "db-id",
                has_migrations=False,
                backup_factory=lambda **_kwargs: "backup.enc",
            )
            self.assertFalse((Path(temporary) / "update-blocked.json").exists())
            record = json.loads((Path(temporary) / "last-update.json").read_text())
            self.assertEqual(record["commit"], NEXT)
            self.assertEqual(record["backup"], "backup.enc")
            self.assertEqual(record["frontend_base_path"], "/dren/")
            self.assertFalse(
                any(
                    "migrate" in call.args or "down" in call.args
                    for call in compose.call_args_list
                )
            )


if __name__ == "__main__":
    unittest.main()

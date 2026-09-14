"""Opt-in Docker lifecycle regression using disposable containers only.

Linux/WSL: LITBLOGS_TEST_LIFECYCLE_RUNTIME=1 python3 -m unittest discover \
    -s deploy/cit-local/tests -p test_lifecycle_runtime.py -v
The pinned gateway image supplies a shell; no database, application, host mount,
published port, or production project is used.
"""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import unittest
import uuid
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

CONTROLS = Path(__file__).resolve().parents[1]
IMAGE = "haproxy:3.2-alpine@sha256:6343ce34a132a5dceaa24767d739df2bd519f8f7c1079ae39e4821334e8eb42e"
WRITERS = {"web", "app", "email", "reconcile"}
STEADY = WRITERS | {"postgres", "clamav"}
RUNNING_COMMAND = "trap 'exit 0' TERM INT; while :; do sleep 1 & wait $!; done"
DEPENDENCIES = {
    "postgres": "initialize:service_completed_successfully:false",
    "migrate": "postgres:service_healthy:false",
    "app": "migrate:service_completed_successfully:false,clamav:service_healthy:false",
    "email": "migrate:service_completed_successfully:false",
    "reconcile": "migrate:service_completed_successfully:false,clamav:service_healthy:false",
    "web": "app:service_healthy:false",
}


@unittest.skipUnless(os.environ.get("LITBLOGS_TEST_LIFECYCLE_RUNTIME") == "1", "Opt-in isolated Docker lifecycle test")
class LifecycleRuntimeTests(unittest.TestCase):
    def docker(self, *arguments, check=True):
        result = subprocess.run([*self.docker_prefix, *arguments], stdin=subprocess.DEVNULL,
                                capture_output=True, text=True, timeout=60, check=False)
        if check and result.returncode:
            self.fail("Disposable lifecycle Docker operation failed: " + result.stderr[:1500])
        return result.stdout.strip()

    def load_module(self, name):
        path = CONTROLS / (name + ".py")
        self.assertTrue(path.is_file(), "The shared lifecycle implementation must exist")
        specification = importlib.util.spec_from_file_location("cit_runtime_" + name, path)
        module = importlib.util.module_from_spec(specification)
        self.stack.enter_context(patch.dict(sys.modules, {specification.name: module}))
        specification.loader.exec_module(module)
        return module

    def setUp(self):
        self.assertEqual(os.name, "posix", "The opt-in runtime test requires Linux or WSL")
        docker = shutil.which("docker")
        self.assertIsNotNone(docker, "The opt-in runtime test requires Docker")
        self.docker_prefix = [docker, "--host", "unix:///var/run/docker.sock"]
        self.project = "litblogs-lifecycle-test-" + uuid.uuid4().hex
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.created = []
        self.addCleanup(self.cleanup_containers)
        self.lifecycle = self.load_module("lifecycle")
        self.stack.enter_context(patch.object(self.lifecycle, "PROJECT", self.project))
        self.stack.enter_context(patch.object(self.lifecycle, "DOCKER", self.docker_prefix))
        self.stack.enter_context(patch.dict(sys.modules, {"lifecycle": self.lifecycle}))
        self.backup = self.load_module("backup")
        self.assertIs(getattr(self.backup, "lifecycle", None), self.lifecycle,
                      "Backup recovery must use the shared lifecycle helper")
        self.docker("image", "inspect", "--format", "{{.Id}}", IMAGE)

    def cleanup_containers(self):
        # Only IDs returned by this fixture's successful create calls are removed.
        for identifier in reversed(self.created):
            self.docker("container", "rm", "--force", identifier, check=False)

    def create_container(self, service, number=1, *, project=None, completed=False):
        project = project or self.project
        identifier = self.docker(
            "container", "create", "--name", f"{project}-{service}-{number}", "--pull", "never",
            "--stop-signal", "SIGTERM",
            "--network", "none", "--user", "99:99", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--memory", "32m", "--cpus", "0.25", "--pids-limit", "16",
            "--label", f"com.docker.compose.project={project}",
            "--label", f"com.docker.compose.service={service}",
            "--label", "com.docker.compose.oneoff=False",
            "--label", f"com.docker.compose.container-number={number}",
            "--label", "com.docker.compose.config-hash=disposable-lifecycle-fixture",
            "--label", f"com.docker.compose.depends_on={DEPENDENCIES.get(service, '')}",
            "--health-cmd", "true", "--health-interval", "1s", "--health-timeout", "1s", "--health-retries", "5",
            "--entrypoint", "/bin/sh", IMAGE, "-c", "exit 0" if completed else RUNNING_COMMAND,
        )
        self.assertRegex(identifier, r"^[a-f0-9]{64}$")
        self.created.append(identifier)
        if completed:
            self.docker("container", "start", identifier)
            self.assertEqual(self.docker("container", "wait", identifier), "0")
        return identifier

    def identity(self, identifier):
        projection = '{"Id":{{json .Id}},"Image":{{json .Image}},"StartedAt":{{json .State.StartedAt}}}'
        return json.loads(self.docker("container", "inspect", "--format", projection, identifier))

    def assert_preserved(self, identities):
        for identifier, identity in identities.items():
            with self.subTest(container=identifier[:12]):
                self.assertEqual(self.identity(identifier), identity)

    def assert_stopped_writers(self, snapshot):
        self.assertTrue(all(row["State"] == "exited" for row in snapshot.values() if row["Service"] in WRITERS))

    def test_boot_and_backup_resume_preserve_exact_containers_and_completed_operators(self):
        operators = [self.create_container(name, completed=True) for name in ("initialize", "migrate")]
        steady = [self.create_container(name) for name in ("postgres", "clamav", "app", "email", "reconcile", "web")]
        second_app = self.create_container("app", 2)
        steady.append(second_app)
        foreign = self.create_container("foreign", project=self.project + "-foreign")
        self.docker("container", "start", foreign)
        protected = {identifier: self.identity(identifier) for identifier in (*operators, foreign)}
        before = self.lifecycle.capture()
        self.assertEqual(set(before), set(operators + steady))

        # Boot must start the original seven service containers, leaving both
        # completed initialization/migration commands and the foreign fixture alone.
        self.lifecycle.start_existing(before, steady, timeout=60)
        running = self.lifecycle.capture()
        self.assertEqual(set(running), set(before))
        app_ids = {identifier for identifier, row in running.items() if row["Service"] == "app"}
        self.assertEqual(len(app_ids), 2)
        self.assertTrue(all(row["State"] == "running" and row["Health"] == "healthy"
                            for row in running.values() if row["Service"] in STEADY))
        self.assert_preserved(protected)
        infrastructure = {identifier: self.identity(identifier) for identifier, row in running.items()
                          if row["Service"] in {"postgres", "clamav"}}

        # Exercise the real backup context manager; no database backup is needed
        # to prove that quiesce/resume cannot run completed operator containers.
        with self.backup.quiesced():
            stopped = self.lifecycle.capture()
            self.assert_stopped_writers(stopped)
            self.lifecycle.assert_quiesced(running)
            self.assert_preserved(protected | infrastructure)
        resumed = self.lifecycle.capture()
        self.assertEqual(set(resumed), set(running))
        self.assertTrue(all(row["State"] == "running" and row["Health"] == "healthy"
                            for row in resumed.values() if row["Service"] in STEADY))
        self.assert_preserved(protected | infrastructure)

        # A previously stopped app replica must stay stopped, including when
        # the backup body fails and restoration runs from the finally block.
        self.lifecycle.stop_existing(resumed, [second_app])
        with self.assertRaisesRegex(RuntimeError, "fixture backup failure"), self.backup.quiesced():
            self.assert_stopped_writers(self.lifecycle.capture())
            raise RuntimeError("fixture backup failure")
        recovered = self.lifecycle.capture()
        self.assertEqual(set(recovered), set(running))
        self.assertEqual({identifier for identifier, row in recovered.items() if row["Service"] == "app"}, app_ids)
        self.assertEqual(recovered[second_app]["State"], "exited")
        self.assertTrue(all(row["State"] == "running" and row["Health"] == "healthy"
                            for identifier, row in recovered.items() if row["Service"] in STEADY and identifier != second_app))
        self.assert_preserved(protected | infrastructure)


if __name__ == "__main__":
    unittest.main()

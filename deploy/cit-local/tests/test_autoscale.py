"""Decision and failure tests for the CIT autoscaler; never require Docker."""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "autoscale.py"
if MODULE_PATH.exists():
    SPEC = importlib.util.spec_from_file_location("cit_autoscale", MODULE_PATH)
    autoscale = importlib.util.module_from_spec(SPEC)
    sys.modules[SPEC.name] = autoscale
    SPEC.loader.exec_module(autoscale)
else:
    autoscale = None


class AutoscalerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(autoscale, "The scoped autoscaler must be implemented")

    def sample(
        self, state, *, count=1, cpu=70, now=1000, memory=3 * 1024**3, healthy=True
    ):
        return autoscale.decide(
            state,
            count=count,
            cpu=cpu,
            available_memory=memory,
            healthy=healthy,
            now=now,
        )

    def test_scale_up_requires_two_high_samples(self):
        first, target = self.sample(autoscale.State())
        self.assertIsNone(target)
        second, target = self.sample(first, cpu=65, now=1060)
        self.assertEqual(target, 2)
        self.assertEqual(second.high, 2)

    def test_scale_down_requires_five_low_samples_and_strict_threshold(self):
        state = autoscale.State()
        for index in range(4):
            state, target = self.sample(state, count=2, cpu=19.9, now=1000 + index * 60)
            self.assertIsNone(target)
        state, target = self.sample(state, count=2, cpu=19.9, now=1240)
        self.assertEqual(target, 1)
        state, target = self.sample(state, count=2, cpu=20, now=1300)
        self.assertIsNone(target)
        self.assertEqual(state.low, 0)

    def test_middle_load_breaks_both_streaks(self):
        state = autoscale.State(high=1, last_sample=1000, replicas=1)
        state, target = self.sample(state, cpu=50, now=1060)
        self.assertIsNone(target)
        self.assertEqual((state.high, state.low), (0, 0))

    def test_cooldown_and_replica_limits(self):
        state = autoscale.State(high=1, last_sample=1000, last_scale=900, replicas=2)
        state, target = self.sample(state, count=2, now=1060)
        self.assertIsNone(target)
        state, target = self.sample(state, count=2, now=1200)
        self.assertEqual(target, 3)
        maximum = autoscale.State(high=2, last_sample=1000, replicas=3)
        self.assertIsNone(self.sample(maximum, count=3, now=1060)[1])
        minimum = autoscale.State(low=5, last_sample=1000, replicas=1)
        self.assertIsNone(self.sample(minimum, cpu=0, now=1060)[1])

    def test_low_memory_or_unhealthy_app_never_scales_in_either_direction(self):
        for cpu in (0, 99):
            for healthy, memory in ((False, 3 * 1024**3), (True, 2 * 1024**3 - 1)):
                state = autoscale.State(high=2, low=5, last_sample=1000, replicas=2)
                result, target = self.sample(
                    state, count=2, cpu=cpu, now=1060, healthy=healthy, memory=memory
                )
                self.assertIsNone(target)
                self.assertEqual((result.high, result.low), (0, 0))

    def test_missing_samples_replica_changes_and_fast_manual_runs_do_not_count(self):
        state = autoscale.State(high=1, last_sample=1000, replicas=1)
        self.assertIsNone(self.sample(state, now=1001)[1])
        self.assertIsNone(self.sample(state, now=1400)[1])
        self.assertIsNone(self.sample(state, count=2, now=1060)[1])

    def test_invalid_cpu_counts_and_clock_are_rejected_or_held(self):
        for cpu in (float("nan"), float("inf"), -1):
            with self.assertRaises(autoscale.AutoscaleError):
                self.sample(autoscale.State(), cpu=cpu)
        for count in (0, 4):
            with self.assertRaises(autoscale.AutoscaleError):
                self.sample(autoscale.State(), count=count)
        state = autoscale.State(high=2, last_sample=2000, last_scale=1900, replicas=1)
        self.assertIsNone(self.sample(state, now=1000)[1])

    def test_stats_require_exact_container_inventory_and_finite_percentages(self):
        identifiers = ["a" * 64, "b" * 64]
        lines = "\n".join(
            json.dumps({"ID": value, "CPUPerc": cpu})
            for value, cpu in zip(identifiers, ("60.0%", "80.0%"))
        )
        self.assertEqual(autoscale.parse_cpu(lines, identifiers), 70)
        for wrong in (
            lines.splitlines()[0],
            lines + "\n" + lines.splitlines()[0],
            lines.replace("80.0%", "NaN%"),
            lines.replace("b" * 64, "c" * 64),
        ):
            with self.assertRaises(autoscale.AutoscaleError):
                autoscale.parse_cpu(wrong, identifiers)

    def test_inspection_rejects_foreign_labels_image_and_cpu_allocation(self):
        identifier = "a" * 64
        valid = {
            "Id": identifier,
            "Labels": {
                "com.docker.compose.project": "litblogs-cit",
                "com.docker.compose.service": "app",
                "com.docker.compose.oneoff": "False",
            },
            "State": "running",
            "Health": "healthy",
            "Image": "litblogs-app:abc123",
            "NanoCpus": 1000000000,
        }
        self.assertTrue(autoscale.validate_container(valid, identifier, "abc123"))
        for key, value in (("Image", "other:abc123"), ("NanoCpus", 0)):
            with self.assertRaises(autoscale.AutoscaleError):
                autoscale.validate_container(
                    {**valid, key: value}, identifier, "abc123"
                )
        for key, value in (
            ("com.docker.compose.project", "another-project"),
            ("com.docker.compose.service", "postgres"),
            ("com.docker.compose.oneoff", "True"),
        ):
            with self.assertRaises(autoscale.AutoscaleError):
                autoscale.validate_container(
                    {**valid, "Labels": {**valid["Labels"], key: value}},
                    identifier,
                    "abc123",
                )
        self.assertFalse(
            autoscale.validate_container(
                {**valid, "Health": "unhealthy"}, identifier, "abc123"
            )
        )

    def test_scale_command_is_scoped_and_never_builds_or_stops_dependencies(self):
        command = autoscale.scale_command(2)
        self.assertEqual(
            command,
            [
                "/usr/bin/docker",
                "compose",
                "--project-name",
                "litblogs-cit",
                "--project-directory",
                str(autoscale.REPO),
                "--env-file",
                str(autoscale.ENV_FILE),
                "-f",
                str(autoscale.REPO / "docker-compose.yml"),
                "-f",
                str(autoscale.OVERLAY),
                "up",
                "-d",
                "--no-deps",
                "--no-build",
                "--scale",
                "app=2",
                "app",
            ],
        )
        with self.assertRaises(autoscale.AutoscaleError):
            autoscale.scale_command(4)

    def test_scaling_rechecks_memory_and_app_health_before_docker_mutation(self):
        for sample in (
            (1, 90, 3 * 1024**3, False),
            (1, 90, 1024**3, True),
            (2, 90, 3 * 1024**3, True),
        ):
            with (
                patch.object(autoscale, "read_sample", return_value=sample),
                patch.object(autoscale, "run_command") as command,
            ):
                with self.assertRaises(autoscale.AutoscaleError):
                    autoscale.scale(2)
                command.assert_not_called()

    def test_image_tag_accepts_only_one_explicit_full_commit(self):
        commit = "a" * 40
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / ".env"
            for value in (commit, f"'{commit}'"):
                path.write_text(
                    f"SECRET_KEY=private-value\nLITBLOGS_IMAGE_TAG={value}\n",
                    encoding="utf-8",
                )
                self.assertEqual(autoscale.read_image_tag(path), commit)
            for content in (
                "LITBLOGS_IMAGE_TAG=local",
                f'LITBLOGS_IMAGE_TAG="{commit}"',
                f"LITBLOGS_IMAGE_TAG={commit}\nLITBLOGS_IMAGE_TAG={commit}",
                f"LITBLOGS_IMAGE_TAG={commit} # comment",
            ):
                path.write_text(content, encoding="utf-8")
                with self.assertRaises(autoscale.AutoscaleError):
                    autoscale.read_image_tag(path)

    def test_host_memory_uses_available_memory_and_refuses_missing_measurement(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "meminfo"
            path.write_text(
                "MemFree: 9000000 kB\nMemAvailable: 2097152 kB\n", encoding="ascii"
            )
            self.assertEqual(autoscale.available_memory(path), 2 * 1024**3)
            path.write_text("MemFree: 9000000 kB\n", encoding="ascii")
            with self.assertRaises(autoscale.AutoscaleError):
                autoscale.available_memory(path)

    def test_subprocess_timeout_and_errors_do_not_expose_output(self):
        for failure in (
            subprocess.TimeoutExpired("docker", 1, output="private-value"),
            OSError("private-value"),
        ):
            with patch.object(autoscale.subprocess, "run", side_effect=failure):
                with self.assertRaises(autoscale.AutoscaleError) as raised:
                    autoscale.run_command(["/usr/bin/docker", "ps"])
                self.assertNotIn("private-value", str(raised.exception))
        with patch.object(autoscale.subprocess, "run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "ok", "")
            autoscale.run_command(["/usr/bin/docker", "ps"])
            kwargs = run.call_args.kwargs
            self.assertFalse(kwargs.get("shell", False))
            self.assertNotIn("LITBLOGS_IMAGE_TAG", kwargs["env"])
            self.assertEqual(kwargs["env"].get("DOCKER_HOST"), "unix:///var/run/docker.sock")
            self.assertNotIn("DOCKER_CONTEXT", kwargs["env"])
            self.assertGreater(kwargs["timeout"], 0)

    def test_state_round_trip_and_corruption_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "state.json"
            self.assertEqual(autoscale.load_state(path), autoscale.State())
            original = autoscale.State(
                high=1, last_sample=1000, last_scale=500, replicas=2
            )
            autoscale.save_state(original, path)
            self.assertEqual(autoscale.load_state(path), original)
            path.write_text('{"high":999}', encoding="utf-8")
            with self.assertRaises(autoscale.AutoscaleError):
                autoscale.load_state(path)

    def test_failed_scale_reserves_cooldown_before_mutation(self):
        saved = []
        initial = autoscale.State(high=1, last_sample=1000, replicas=1)

        def fail_scale(_target):
            self.assertEqual(saved[-1].last_scale, 1060)
            raise autoscale.AutoscaleError("Docker operation failed")

        with (
            patch.object(autoscale, "load_state", return_value=initial),
            patch.object(autoscale, "save_state", side_effect=saved.append),
            patch.object(
                autoscale, "read_sample", return_value=(1, 70.0, 3 * 1024**3, True)
            ),
            patch.object(autoscale, "scale", side_effect=fail_scale),
            self.assertRaises(autoscale.AutoscaleError),
        ):
            autoscale.run_once(now=1060)
        self.assertEqual((saved[-1].high, saved[-1].low), (0, 0))

    def test_dry_run_never_mutates_state_or_containers(self):
        initial = autoscale.State(high=1, last_sample=1000, replicas=1)
        with (
            patch.object(autoscale, "load_state", return_value=initial),
            patch.object(autoscale, "save_state") as save,
            patch.object(
                autoscale, "read_sample", return_value=(1, 70.0, 3 * 1024**3, True)
            ),
            patch.object(autoscale, "scale") as scale,
        ):
            self.assertEqual(
                autoscale.run_once(now=1060, dry_run=True), "would-scale-up"
            )
            save.assert_not_called()
            scale.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Existing-container recovery must never traverse Compose dependencies."""

import copy
import unittest
from unittest.mock import patch

from lifecycle_fixture import DockerFixture, load_lifecycle


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.module = load_lifecycle()
        self.engine = DockerFixture()
        self.runner = patch.object(self.module, "run", side_effect=lambda *args, **kwargs: self.engine.run(*args, **kwargs))
        self.runner.start()
        self.addCleanup(self.runner.stop)

    def test_resume_preserves_old_operator_containers_database_and_two_app_ids(self):
        before = self.module.capture()
        writers = self.engine.ids("app", "email", "reconcile", "web")
        self.module.stop_existing(before, writers)
        self.module.assert_quiesced(before)
        self.module.start_existing(before, writers)
        for key in self.engine.ids("postgres", "clamav", "migrate", "initialize"):
            self.assertEqual(before[key], self.engine.records[key])
        started = [key for command in self.engine.mutations() if command[1] == "start" for key in command[2:]]
        self.assertCountEqual(started, writers)
        self.assertEqual(len(self.engine.ids("app")), 2)

    def test_boot_orders_existing_infrastructure_then_workers_then_gateway(self):
        for key in self.engine.ids(*self.module.SERVICES):
            self.engine.records[key].update(State="exited", Health=None)
        before = self.module.capture()
        selected = self.engine.ids(*self.module.SERVICES)
        self.module.start_existing(before, selected)
        starts = [command[2:] for command in self.engine.mutations()]
        self.assertEqual(starts, [self.engine.ids("postgres", "clamav"), self.engine.ids("app", "email", "reconcile"), self.engine.ids("web")])

    def test_wrong_labels_oneoffs_counts_and_duplicate_ids_fail_before_mutation(self):
        for field, value in (("Project", "other"), ("Service", "unrelated"), ("Oneoff", "True"), ("Id", "wrong")):
            with self.subTest(field=field):
                original = self.engine.snapshot()
                self.engine.records[self.engine.ids("app")[0]][field] = value
                with self.assertRaises(self.module.LifecycleError):
                    self.module.capture()
                self.engine.records = original
        for apps in (0, 4):
            self.engine.records = DockerFixture(apps=apps).records
            with self.assertRaises(self.module.LifecycleError):
                self.module.capture()
        self.assertEqual(self.engine.mutations(), [])

    def test_replaced_missing_or_relabelled_container_blocks_start(self):
        for mutation in ("missing", "image", "label"):
            with self.subTest(mutation=mutation):
                self.engine = DockerFixture()
                before = self.module.capture()
                key = self.engine.ids("app")[0]
                if mutation == "missing":
                    del self.engine.records[key]
                elif mutation == "image":
                    self.engine.records[key]["Image"] = "sha256:" + "f" * 64
                else:
                    self.engine.records[key]["Service"] = "email"
                with self.assertRaises(self.module.LifecycleError):
                    self.module.start_existing(before, [key])
                self.assertEqual(self.engine.mutations(), [])

    def test_operator_target_is_never_mutated_and_active_initialize_blocks(self):
        before = self.module.capture()
        with self.assertRaises(self.module.LifecycleError):
            self.module.start_existing(before, self.engine.ids("migrate"))
        self.engine.records[self.engine.ids("initialize")[0]]["State"] = "running"
        with self.assertRaises(self.module.LifecycleError):
            self.module.assert_quiesced(before)
        self.assertEqual(self.engine.mutations(), [])

    def test_unhealthy_replica_times_out_without_success(self):
        before = self.module.capture()
        key = self.engine.ids("app")[1]
        self.engine.records[key]["Health"] = "unhealthy"
        with (
            patch.object(self.module.time, "monotonic", side_effect=[0, 0, 0, 1, 3]),
            patch.object(self.module.time, "sleep"), self.assertRaises(self.module.LifecycleError),
        ):
            self.module.start_existing(before, [key], timeout=2)

    def test_shutdown_uses_one_deadline_and_does_not_stop_infrastructure_after_expiry(self):
        before = self.module.capture()
        clock = [0]

        def delayed_stop(arguments, **kwargs):
            result = self.engine.run(arguments, **kwargs)
            if arguments[:2] == ["container", "stop"]:
                clock[0] = 151
            return result

        with (
            patch.object(self.module.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(self.module, "run", side_effect=delayed_stop),
            self.assertRaises(self.module.LifecycleError),
        ):
            self.module.stop_existing(before, self.engine.ids(*self.module.SERVICES))
        for key in self.engine.ids("postgres", "clamav"):
            self.assertEqual(before[key], self.engine.records[key])

    def test_identity_comparison_does_not_accept_mutated_snapshot(self):
        before = self.module.capture()
        foreign = copy.deepcopy(before)
        key = self.engine.ids("app")[0]
        foreign[key]["Project"] = "other"
        with self.assertRaises(self.module.LifecycleError):
            self.module.start_existing(foreign, [key])
        self.assertEqual(self.engine.mutations(), [])


if __name__ == "__main__":
    unittest.main()

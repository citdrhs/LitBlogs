"""Focused backup safety tests; never contacts Docker or a real database."""

import importlib.util
import io
import json
import shutil
import tarfile
import tempfile
import unittest
from contextlib import ExitStack, nullcontext
from pathlib import Path
from unittest.mock import patch

MODULE_PATH = Path(__file__).resolve().parents[1] / "backup.py"


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(MODULE_PATH.exists(), "The guarded backup implementation must exist")
        spec = importlib.util.spec_from_file_location("cit_backup", MODULE_PATH)
        self.module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.module)

    def test_partial_stop_failure_resumes_exact_previous_writers(self):
        states = {"web": "running", "app": "running", "postgres": "running", "email": "exited"}
        calls = []

        def command(arguments, **_kwargs):
            calls.append(arguments)
            if arguments[0] == "stop":
                raise self.module.BackupError("stop failed")

        with (
            patch.object(self.module, "service_states", return_value=states),
            patch.object(self.module, "compose", side_effect=command),
            self.assertRaises(self.module.BackupError),
            self.module.quiesced(resume=True),
        ):
            self.fail("Backup must not run after a failed stop")
        self.assertEqual(calls, [["stop", "--timeout", "60", "web", "app"], ["start", "web", "app"]])

    def test_backup_failure_resumes_previous_writers_and_never_postgres(self):
        states = [{"app": "running", "postgres": "running"}, {"app": "exited", "postgres": "running"}]
        with (
            patch.object(self.module, "service_states", side_effect=states),
            patch.object(self.module, "compose") as command,
            self.assertRaisesRegex(RuntimeError, "fixture"),
            self.module.quiesced(resume=True),
        ):
            raise RuntimeError("fixture")
        self.assertEqual([call.args[0] for call in command.call_args_list], [["stop", "--timeout", "60", "app"], ["start", "app"]])

    def test_running_operator_blocks_backup_before_stop(self):
        with (
            patch.object(self.module, "service_states", return_value={"app": "running", "migrate": "running", "postgres": "running"}),
            patch.object(self.module, "compose") as command,
            self.assertRaises(self.module.BackupError),
            self.module.quiesced(),
        ):
            self.fail("Concurrent migration must block backup")
        command.assert_not_called()

    def test_service_inventory_accepts_equal_replicas_and_rejects_mixed_state(self):
        rows = [{"Service": "app", "State": "running"}, {"Service": "app", "State": "running"}]
        with patch.object(self.module, "compose", return_value=json.dumps(rows).encode()):
            self.assertEqual(self.module.service_states(), {"app": "running"})
        rows[1]["State"] = "restarting"
        with patch.object(self.module, "compose", return_value=json.dumps(rows).encode()), self.assertRaises(self.module.BackupError):
            self.module.service_states()

    def test_leave_stopped_does_not_resume(self):
        with (
            patch.object(self.module, "service_states", side_effect=[{"app": "running", "postgres": "running"}, {"app": "exited", "postgres": "running"}]),
            patch.object(self.module, "compose") as command,
            self.module.quiesced(resume=False),
        ):
            pass
        self.assertEqual([call.args[0] for call in command.call_args_list], [["stop", "--timeout", "60", "app"]])

    def test_volume_identity_must_match_both_exact_compose_labels(self):
        info = {"Name": "litblogs-cit_uploads", "Driver": "local", "Options": None, "Labels": {
            "com.docker.compose.project": "other", "com.docker.compose.volume": "uploads"}, "Mountpoint": "/var/lib/docker/volumes/litblogs-cit_uploads/_data"}
        with self.assertRaises(self.module.BackupError):
            self.module.validate_volume_record("uploads", info)
        info["Labels"]["com.docker.compose.project"] = "litblogs-cit"
        self.assertEqual(self.module.validate_volume_record("uploads", info), Path(info["Mountpoint"]))
        info["Options"] = {"device": "/home", "o": "bind"}
        with self.assertRaises(self.module.BackupError):
            self.module.validate_volume_record("uploads", info)

    def test_bundle_rejects_traversal_links_duplicates_and_unknown_files(self):
        for name, kind in (("../escape", "file"), ("environment", "symlink"), ("extra", "file"), ("environment", "duplicate")):
            with self.subTest(name=name, kind=kind), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "bundle.tar"
                with tarfile.open(archive, "w") as output:
                    member = tarfile.TarInfo(name)
                    member.size = 1
                    if kind == "symlink":
                        member.type = tarfile.SYMTYPE
                        member.linkname = "/etc/passwd"
                        member.size = 0
                    output.addfile(member, io.BytesIO(b"x"))
                    if kind == "duplicate":
                        output.addfile(member, io.BytesIO(b"x"))
                with self.assertRaises(self.module.BackupError):
                    self.module.validate_bundle(archive)

    def test_volume_archive_rejects_aliases_and_file_directory_conflicts(self):
        for names in (("objects/key", "objects/./key"), ("objects", "objects/key")):
            with self.subTest(names=names), tempfile.TemporaryDirectory() as temporary:
                archive = Path(temporary) / "volume.tar"
                with tarfile.open(archive, "w") as output:
                    for name in names:
                        member = tarfile.TarInfo(name)
                        member.size = 1
                        output.addfile(member, io.BytesIO(b"x"))
                with self.assertRaises(self.module.BackupError):
                    self.module.validate_volume_tar(archive)

    def _fake_snapshot(self, stage, *, corrupt=False):
        for name in self.module.REQUIRED_MEMBERS - {"manifest.json"}:
            path = stage / name
            if name.endswith(".tar"):
                with tarfile.open(path, "w") as archive:
                    member = tarfile.TarInfo(".")
                    member.type = tarfile.DIRTYPE
                    archive.addfile(member)
            else:
                path.write_bytes(b"PGDMPsynthetic" if name == "database.dump" else b"synthetic private bytes")
        manifest = {"format": self.module.FORMAT, "project": self.module.PROJECT,
                    "files": {file.name: {"sha256": self.module.hash_file(file), "size_bytes": file.stat().st_size}
                              for file in stage.iterdir()}}
        (stage / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        if corrupt:
            (stage / "environment").write_bytes(b"changed private bytes")

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for encrypted bundle")
    def test_complete_bundle_roundtrip_and_no_publication_of_bad_checksums(self):
        for corrupt in (False, True):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as temporary, ExitStack() as stack:
                state = Path(temporary)
                key = state / "backup.key"
                key.write_bytes(b"a1" * 48 + b"\n")
                for name, value in (("STATE", state), ("KEY", key)):
                    stack.enter_context(patch.object(self.module, name, value))
                stack.enter_context(patch.object(self.module, "require_host"))
                stack.enter_context(patch.object(self.module, "private_file", side_effect=Path))
                stack.enter_context(patch.object(self.module, "private_directory", side_effect=Path))
                stack.enter_context(patch.object(self.module, "operation_lock", return_value=nullcontext()))
                stack.enter_context(patch.object(self.module, "quiesced", return_value=nullcontext()))
                stack.enter_context(patch.object(self.module, "_sync_directory"))
                stack.enter_context(patch.object(self.module, "_snapshot", side_effect=lambda stage, corrupt=corrupt: self._fake_snapshot(stage, corrupt=corrupt)))
                if corrupt:
                    with self.assertRaises(self.module.BackupError):
                        self.module.create_backup()
                    self.assertEqual(list((state / "backups").iterdir()), [])
                else:
                    published = self.module.create_backup()
                    self.assertEqual({path.name for path in published.iterdir()}, {"archive.enc", "authentication.json"})
                    self.assertEqual(self.module.verify_archive(published)["project"], "litblogs-cit")
                self.assertFalse(any(path.name.startswith((".backup-", ".verify-")) for path in state.iterdir()))

    @unittest.skipUnless(shutil.which("openssl"), "OpenSSL required for encryption round trip")
    def test_ciphertext_tampering_rejected_before_decryption(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            key = root / "key"
            key.write_bytes(b"a1" * 48 + b"\n")
            plain = root / "bundle.tar"
            plain.write_bytes(b"synthetic archive bytes" * 200)
            encrypted = root / "archive.enc"
            with patch.object(self.module, "private_file", side_effect=lambda path: Path(path)), patch.object(self.module, "KEY", key):
                metadata = self.module.encrypt_file(plain, encrypted)
                self.module.authenticate_file(encrypted, metadata)
                restored = root / "restored.tar"
                self.module.decrypt_file(encrypted, restored, metadata)
                self.assertEqual(restored.read_bytes(), plain.read_bytes())
                content = bytearray(encrypted.read_bytes())
                content[len(content) // 2] ^= 1
                encrypted.write_bytes(content)
                with patch.object(self.module, "run_command") as command:
                    with self.assertRaises(self.module.BackupError):
                        self.module.decrypt_file(encrypted, root / "bad.tar", metadata)
                    command.assert_not_called()


if __name__ == "__main__":
    unittest.main()

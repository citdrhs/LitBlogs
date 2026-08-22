import hashlib
import io
import json
import os
import stat
import sys
import tarfile
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import pytest

ROOT_DIR = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT_DIR / "deploy" / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import backup_postgres  # noqa: E402
import restore_verify_postgres  # noqa: E402
import upload_snapshot_common  # noqa: E402

DATABASE_URL = (
    "postgresql://litblogs_backup:backup-4R%21v9nK2sQ7x@db.school.edu/"
    "litblogs?sslmode=verify-full&sslrootcert="
    "%2Fetc%2Flitblogs%2Fpostgres-root-ca.pem"
)


def _asset_row(
    asset_id: int,
    storage_key: str,
    state: str,
    payload: bytes,
) -> dict[str, object]:
    return {
        "asset_id": asset_id,
        "storage_key": storage_key,
        "state": state,
        "size_bytes": len(payload),
        "sha256_digest": hashlib.sha256(payload).hexdigest(),
    }


def _upload_fixture(tmp_path):
    root = tmp_path / "uploads"
    (root / "objects").mkdir(parents=True)
    (root / ".incoming").mkdir()
    payloads = {
        "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png": b"pending-image",
        "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf": b"active-pdf",
        "objects/cc/cccccccccccccccccccccccccccccccc.mp4": b"delete-pending-video",
    }
    states = ("PENDING", "ACTIVE", "DELETE_PENDING")
    rows = []
    for asset_id, ((storage_key, payload), state) in enumerate(
        zip(payloads.items(), states, strict=True),
        start=1,
    ):
        path = root / Path(storage_key)
        path.parent.mkdir(mode=0o700)
        path.write_bytes(payload)
        if os.name == "posix":
            path.parent.chmod(0o700)
            path.chmod(0o600)
        rows.append(_asset_row(asset_id, storage_key, state, payload))
    if os.name == "posix":
        root.chmod(0o700)
        (root / "objects").chmod(0o700)
        (root / ".incoming").chmod(0o700)
    return root, upload_snapshot_common.registry_inventory(rows), payloads


def _recovery_fixture(tmp_path):
    upload_root, inventory, payloads = _upload_fixture(tmp_path)
    base = tmp_path / "litblogs-20260822T120000Z-a1b2c3d4"
    database = base.with_suffix(".dump")
    uploads = base.with_suffix(".uploads.tar")
    assets = base.with_suffix(".assets.jsonl")
    manifest = base.with_suffix(".manifest.json")
    database.write_bytes(b"PGDMP-coupled-database")
    if os.name == "posix":
        database.chmod(0o600)
    upload_snapshot_common.write_asset_inventory(assets, inventory)
    upload_snapshot_common.create_upload_archive(uploads, upload_root, inventory)
    return database, uploads, assets, manifest, inventory, payloads


class _BackupRunner:
    def __init__(self, *, backup_role_result="ok"):
        self.calls = []
        self.backup_role_result = backup_role_result

    def __call__(self, command, **kwargs):
        import subprocess

        command = [str(part) for part in command]
        self.calls.append((command, kwargs))
        if Path(command[0]).name == "psql":
            sql = command[command.index("--command") + 1]
            if sql == backup_postgres.BACKUP_ROLE_PRECHECK_SQL:
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=f"{self.backup_role_result}\n",
                    stderr="",
                )
        if Path(command[0]).name == "pg_dump":
            Path(command[command.index("--file") + 1]).write_bytes(b"PGDMP-database")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")


class _RestoreRunner:
    def __init__(
        self,
        inventory,
        *,
        current_head_integrity="ok:0",
        target_state="absent",
    ):
        self.calls = []
        self.inventory = inventory
        self.current_head_integrity = current_head_integrity
        self.target_state = target_state

    def __call__(self, command, **kwargs):
        import subprocess

        command = [str(part) for part in command]
        self.calls.append((command, kwargs))
        stdout = ""
        if Path(command[0]).name == "psql":
            sql = command[command.index("--command") + 1]
            if "FROM pg_database" in sql:
                stdout = f"{self.target_state}\n"
            elif sql == restore_verify_postgres.SCHEMA_INTEGRITY_SQL:
                stdout = "ok\n"
            elif sql == restore_verify_postgres.MIGRATION_STATE_SQL:
                stdout = "versioned\n"
            elif sql == "SELECT version_num FROM alembic_version;":
                stdout = f"{restore_verify_postgres.EXPECTED_ALEMBIC_HEAD}\n"
            elif sql == restore_verify_postgres.CORE_DATA_INTEGRITY_SQL:
                stdout = "ok\n"
            elif sql == restore_verify_postgres.IDENTITY_DATA_INTEGRITY_SQL:
                stdout = f"{self.current_head_integrity}\n"
            elif sql == restore_verify_postgres.OPERATOR_ROUTINE_CATALOG_SQL:
                records = []
                for signature, expected in (
                    restore_verify_postgres.EXPECTED_OPERATOR_ROUTINE_CONTRACT.items()
                ):
                    record = {
                        key: value
                        for key, value in expected.items()
                        if key != "source"
                    }
                    record["signature"] = signature
                    record["source_hex"] = expected["source"].encode("utf-8").hex()
                    records.append(record)
                stdout = json.dumps(records) + "\n"
            elif sql == restore_verify_postgres.UPLOAD_REGISTRY_INVENTORY_SQL:
                rows = [record.as_json_object() for record in self.inventory]
                header = "asset_id,storage_key,state,size_bytes,sha256_digest\n"
                stdout = header + "".join(
                    f"{row['asset_id']},{row['storage_key']},{row['state']},"
                    f"{row['size_bytes']},{row['sha256_digest']}\n"
                    for row in rows
                )
        return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")


def test_registry_inventory_contains_every_state_and_file_inventory_excludes_tombstones():
    rows = [
        _asset_row(4, "objects/dd/dddddddddddddddddddddddddddddddd.pdf", "DELETED", b"gone"),
        _asset_row(3, "objects/cc/cccccccccccccccccccccccccccccccc.mp4", "DELETE_PENDING", b"video"),
        _asset_row(1, "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png", "PENDING", b"pending"),
        _asset_row(2, "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf", "ACTIVE", b"active"),
    ]

    inventory = upload_snapshot_common.registry_inventory(rows)

    assert [asset.asset_id for asset in inventory] == [1, 2, 3, 4]
    assert [asset.state for asset in inventory] == [
        "PENDING",
        "ACTIVE",
        "DELETE_PENDING",
        "DELETED",
    ]
    assert [asset.asset_id for asset in upload_snapshot_common.file_backed_inventory(inventory)] == [
        1,
        2,
        3,
    ]


@pytest.mark.parametrize(
    "change",
    [
        {"asset_id": True},
        {"state": "UNKNOWN"},
        {"storage_key": "objects/aa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.png"},
        {"sha256_digest": "A" * 64},
        {"size_bytes": 0},
    ],
)
def test_registry_inventory_rejects_noncanonical_rows(change):
    row = _asset_row(
        1,
        "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
        "ACTIVE",
        b"active",
    )
    row.update(change)

    with pytest.raises(
        upload_snapshot_common.UploadSnapshotError,
        match="registry inventory is invalid",
    ):
        upload_snapshot_common.registry_inventory([row])


def test_registry_inventory_rejects_duplicate_ids_or_storage_keys():
    first = _asset_row(
        1,
        "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
        "ACTIVE",
        b"first",
    )
    duplicate = _asset_row(
        1,
        "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf",
        "PENDING",
        b"second",
    )

    with pytest.raises(upload_snapshot_common.UploadSnapshotError):
        upload_snapshot_common.registry_inventory([first, duplicate])

    duplicate["asset_id"] = 2
    duplicate["storage_key"] = first["storage_key"]
    with pytest.raises(upload_snapshot_common.UploadSnapshotError):
        upload_snapshot_common.registry_inventory([first, duplicate])


def test_registry_inventory_a_and_b_must_be_identical():
    before = upload_snapshot_common.registry_inventory(
        [
            _asset_row(
                1,
                "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "ACTIVE",
                b"active",
            )
        ]
    )
    after = upload_snapshot_common.registry_inventory(
        [
            _asset_row(
                1,
                "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "DELETE_PENDING",
                b"active",
            )
        ]
    )

    with pytest.raises(
        upload_snapshot_common.UploadSnapshotError,
        match="changed while the recovery set was created",
    ):
        upload_snapshot_common.require_stable_registry(before, after)


def test_registry_a_and_b_detect_deleted_tombstone_drift():
    deleted = _asset_row(
        9,
        "objects/dd/dddddddddddddddddddddddddddddddd.pdf",
        "DELETED",
        b"deleted",
    )
    before = upload_snapshot_common.registry_inventory([deleted])
    deleted["sha256_digest"] = "f" * 64
    after = upload_snapshot_common.registry_inventory([deleted])

    with pytest.raises(
        upload_snapshot_common.UploadSnapshotError,
        match="changed while the recovery set was created",
    ):
        upload_snapshot_common.require_stable_registry(before, after)


def test_asset_inventory_jsonl_is_sorted_canonical_and_round_trips(tmp_path):
    inventory = upload_snapshot_common.registry_inventory(
        [
            _asset_row(
                2,
                "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf",
                "DELETE_PENDING",
                b"second",
            ),
            _asset_row(
                1,
                "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png",
                "ACTIVE",
                b"first",
            ),
        ]
    )
    inventory_path = tmp_path / "assets.jsonl"

    upload_snapshot_common.write_asset_inventory(inventory_path, inventory)

    assert inventory_path.read_text(encoding="utf-8") == (
        '{"asset_id":1,"sha256_digest":"a7937b64b8caa58f03721bb6bacf5c78'
        'cb235febe0e70b1b84cd99541461a08e","size_bytes":5,"state":"ACTIVE",'
        '"storage_key":"objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"}\n'
        '{"asset_id":2,"sha256_digest":"16367aacb67a4a017c8da8ab95682ccb'
        '390863780f7114dda0a0e0c55644c7c4","size_bytes":6,"state":"DELETE_PENDING",'
        '"storage_key":"objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf"}\n'
    )
    assert upload_snapshot_common.load_asset_inventory(inventory_path) == inventory


def test_asset_inventory_loader_rejects_duplicate_json_keys_and_noncanonical_order(tmp_path):
    inventory_path = tmp_path / "assets.jsonl"
    inventory_path.write_text(
        '{"asset_id":1,"asset_id":2,"sha256_digest":"' + ("a" * 64) + '",'
        '"size_bytes":1,"state":"ACTIVE",'
        '"storage_key":"objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png"}\n',
        encoding="utf-8",
    )
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="inventory file"):
        upload_snapshot_common.load_asset_inventory(inventory_path)

    rows = [
        _asset_row(2, "objects/bb/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb.pdf", "ACTIVE", b"b"),
        _asset_row(1, "objects/aa/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.png", "ACTIVE", b"a"),
    ]
    inventory_path.write_text(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
            for row in rows
        ),
        encoding="utf-8",
    )
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="inventory file"):
        upload_snapshot_common.load_asset_inventory(inventory_path)


def test_upload_tree_must_exactly_match_the_file_backed_registry(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)

    upload_snapshot_common.verify_upload_tree(upload_root, inventory)

    orphan = upload_root / "objects/dd/dddddddddddddddddddddddddddddddd.pdf"
    orphan.parent.mkdir()
    orphan.write_bytes(b"orphan")
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)
    orphan.unlink()
    orphan.parent.rmdir()

    registered = upload_root / inventory[0].storage_key
    registered.write_bytes(b"changed")
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)


def test_upload_tree_requires_an_empty_staging_directory(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    (upload_root / ".incoming/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa.part").write_bytes(
        b"in-flight"
    )

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)


def test_upload_tree_requires_the_exact_canonical_root_layout(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    (upload_root / "unmapped-legacy-private-file").write_bytes(b"must not be omitted")

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)

    (upload_root / "unmapped-legacy-private-file").unlink()
    (upload_root / "objects" / "dd").mkdir(mode=0o700)
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)


def test_upload_archive_is_deterministic_uncompressed_ustar(tmp_path):
    upload_root, inventory, payloads = _upload_fixture(tmp_path)
    first_archive = tmp_path / "first.uploads.tar"
    second_archive = tmp_path / "second.uploads.tar"

    upload_snapshot_common.create_upload_archive(first_archive, upload_root, inventory)
    for path in upload_root.glob("objects/*/*"):
        os.utime(path, (1_800_000_000, 1_800_000_000))
    upload_snapshot_common.create_upload_archive(second_archive, upload_root, inventory)

    assert first_archive.read_bytes() == second_archive.read_bytes()
    assert first_archive.read_bytes()[257:265] == b"ustar\x0000"
    with tarfile.open(first_archive, mode="r:") as archive:
        members = archive.getmembers()
        assert [member.name for member in members] == sorted(payloads)
        assert all(member.isfile() for member in members)
        assert all(member.mode == 0o600 for member in members)
        assert all(member.uid == member.gid == member.mtime == 0 for member in members)
        assert all(member.uname == member.gname == "" for member in members)
        assert {
            member.name: archive.extractfile(member).read()  # type: ignore[union-attr]
            for member in members
        } == payloads


def test_upload_archive_rejects_a_file_changed_after_inventory(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    (upload_root / inventory[1].storage_key).write_bytes(b"wrong")

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="does not match"):
        upload_snapshot_common.create_upload_archive(
            tmp_path / "changed.uploads.tar",
            upload_root,
            inventory,
        )


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody metadata only")
def test_upload_tree_requires_exact_private_posix_custody(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    selected = upload_root / inventory[0].storage_key
    selected.chmod(0o640)

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="custody"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody metadata only")
def test_upload_tree_rejects_a_mutable_ancestor(tmp_path):
    mutable_parent = tmp_path / "mutable"
    mutable_parent.mkdir(mode=0o700)
    upload_root, inventory, _payloads = _upload_fixture(mutable_parent)
    mutable_parent.chmod(0o770)

    try:
        with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="custody"):
            upload_snapshot_common.verify_upload_tree(upload_root, inventory)
    finally:
        mutable_parent.chmod(0o700)


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody metadata only")
def test_upload_root_rejects_a_service_owned_ancestor_under_root_only_policy(tmp_path):
    if os.geteuid() == 0:
        pytest.skip("requires a non-root synthetic service identity")
    service_parent = tmp_path / "litblogs"
    upload_root = service_parent / "uploads"
    upload_root.mkdir(parents=True, mode=0o700)
    service_parent.chmod(0o700)
    upload_root.chmod(0o700)
    custody = upload_snapshot_common.UploadRootCustody(
        owner_uid=os.geteuid(),
        group_gid=os.getegid(),
        root_mode=0o700,
        ancestor_owner_uids=frozenset({0}),
        allow_root_owned_sticky_ancestors=False,
    )

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="custody"):
        upload_snapshot_common._canonical_upload_root(upload_root, custody)


def test_root_owned_sticky_ancestor_policy_is_synthetic_only():
    metadata = SimpleNamespace(st_mode=stat.S_IFDIR | 0o1777, st_uid=0)
    production = upload_snapshot_common.UploadRootCustody(
        owner_uid=1000,
        group_gid=1000,
        root_mode=0o750,
        ancestor_owner_uids=frozenset({0}),
        allow_root_owned_sticky_ancestors=False,
    )
    synthetic = upload_snapshot_common.UploadRootCustody(
        owner_uid=1000,
        group_gid=1000,
        root_mode=0o700,
        ancestor_owner_uids=frozenset({0}),
        allow_root_owned_sticky_ancestors=True,
    )

    assert not upload_snapshot_common._ancestor_metadata_matches_contract(
        metadata, production
    )
    assert upload_snapshot_common._ancestor_metadata_matches_contract(
        metadata, synthetic
    )


@pytest.mark.skipif(os.name != "posix", reason="POSIX sticky-directory custody only")
def test_only_synthetic_custody_allows_a_root_owned_sticky_ancestor():
    sticky_parent = Path("/tmp")
    try:
        parent_metadata = sticky_parent.stat(follow_symlinks=False)
    except OSError:
        pytest.skip("root-owned sticky /tmp is unavailable")
    if (
        parent_metadata.st_uid != 0
        or not parent_metadata.st_mode & stat.S_ISVTX
        or not parent_metadata.st_mode & 0o022
    ):
        pytest.skip("root-owned sticky /tmp is unavailable")

    with TemporaryDirectory(prefix="litblog-production-custody-", dir=sticky_parent) as name:
        upload_root = Path(name)
        upload_root.chmod(0o750)
        production = upload_snapshot_common.UploadRootCustody(
            owner_uid=os.geteuid(),
            group_gid=os.getegid(),
            root_mode=0o750,
            ancestor_owner_uids=frozenset({0}),
            allow_root_owned_sticky_ancestors=False,
        )
        with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="custody"):
            upload_snapshot_common._canonical_upload_root(upload_root, production)

        upload_root.chmod(0o700)
        synthetic = upload_snapshot_common.synthetic_upload_custody()
        pinned = upload_snapshot_common._canonical_upload_root(upload_root, synthetic)
        try:
            assert pinned.path == upload_root.resolve()
        finally:
            pinned.close()


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory inode pinning only")
def test_upload_tree_rejects_a_root_swap_after_validation(tmp_path, monkeypatch):
    upload_root, inventory, payloads = _upload_fixture(tmp_path)
    replacement = tmp_path / "replacement"
    (replacement / "objects").mkdir(parents=True, mode=0o700)
    (replacement / ".incoming").mkdir(mode=0o700)
    for storage_key, payload in payloads.items():
        replacement_path = replacement / storage_key
        replacement_path.parent.mkdir(mode=0o700)
        replacement_path.write_bytes(payload)
        replacement_path.chmod(0o600)
    replacement.chmod(0o700)
    (replacement / "objects").chmod(0o700)
    (replacement / ".incoming").chmod(0o700)

    original_inventory = upload_snapshot_common._actual_upload_keys
    retained = tmp_path / "retained-original"

    def swap_root(objects_root):
        upload_root.rename(retained)
        replacement.rename(upload_root)
        return original_inventory(objects_root)

    monkeypatch.setattr(upload_snapshot_common, "_actual_upload_keys", swap_root)

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="custody"):
        upload_snapshot_common.verify_upload_tree(upload_root, inventory)


def test_coupled_manifest_binds_all_three_artifacts_and_is_canonical(tmp_path):
    database, uploads, assets, manifest, inventory, _payloads = _recovery_fixture(tmp_path)

    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )

    recovery_set = upload_snapshot_common.load_coupled_recovery_set(manifest)
    assert recovery_set.database_archive == database
    assert recovery_set.upload_archive == uploads
    assert recovery_set.asset_inventory == assets
    assert recovery_set.inventory == inventory
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["format"] == "litblogs-coupled-recovery-v1"
    assert payload["writes_quiesced"] is True
    assert payload["asset_records"] == len(inventory)
    assert payload["file_backed_assets"] == 3
    assert set(payload["artifacts"]) == {"assets", "database", "uploads"}


@pytest.mark.parametrize("artifact_name", ["database", "uploads", "assets"])
def test_coupled_manifest_rejects_any_tampered_artifact(tmp_path, artifact_name):
    database, uploads, assets, manifest, inventory, _payloads = _recovery_fixture(tmp_path)
    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )
    selected = {"database": database, "uploads": uploads, "assets": assets}[artifact_name]
    selected.write_bytes(selected.read_bytes() + b"tampered")

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="recovery manifest"):
        upload_snapshot_common.load_coupled_recovery_set(manifest)


def test_upload_archive_verifier_rejects_links_and_path_traversal(tmp_path):
    _upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    malicious = tmp_path / "malicious.uploads.tar"
    with tarfile.open(malicious, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        link = tarfile.TarInfo("../outside")
        link.type = tarfile.SYMTYPE
        link.linkname = "outside"
        archive.addfile(link)

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="upload archive"):
        upload_snapshot_common.verify_upload_archive(malicious, inventory)


def test_upload_archive_extracts_only_to_an_empty_synthetic_root(tmp_path):
    _database, uploads, _assets, _manifest, inventory, payloads = _recovery_fixture(tmp_path)
    restore_root = tmp_path / "litblog_restore_uploads_20260822_a1"
    restore_root.mkdir(mode=0o700)
    if os.name == "posix":
        restore_root.chmod(0o700)

    upload_snapshot_common.extract_upload_archive(uploads, restore_root, inventory)

    assert {
        path.relative_to(restore_root).as_posix(): path.read_bytes()
        for path in restore_root.glob("objects/*/*")
    } == payloads
    assert list((restore_root / ".incoming").iterdir()) == []
    upload_snapshot_common.verify_upload_tree(restore_root, inventory)


def test_upload_archive_refuses_non_synthetic_or_nonempty_restore_roots(tmp_path):
    _database, uploads, _assets, _manifest, inventory, _payloads = _recovery_fixture(tmp_path)
    unsafe = tmp_path / "unsafe-upload-root"
    unsafe.mkdir()
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="synthetic"):
        upload_snapshot_common.extract_upload_archive(uploads, unsafe, inventory)

    restore_root = tmp_path / "litblog_restore_uploads_20260822_a1"
    restore_root.mkdir()
    if os.name == "posix":
        restore_root.chmod(0o700)
    (restore_root / "existing").write_text("retain", encoding="utf-8")
    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="empty"):
        upload_snapshot_common.extract_upload_archive(uploads, restore_root, inventory)


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody metadata only")
def test_upload_archive_rejects_a_synthetic_root_under_a_mutable_parent(tmp_path):
    _database, uploads, _assets, _manifest, inventory, _payloads = _recovery_fixture(
        tmp_path
    )
    mutable_parent = tmp_path / "mutable-restore-parent"
    mutable_parent.mkdir(mode=0o700)
    restore_root = mutable_parent / "litblog_restore_uploads_20260822_mutable"
    restore_root.mkdir(mode=0o700)
    mutable_parent.chmod(0o770)

    try:
        with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="synthetic"):
            upload_snapshot_common.extract_upload_archive(
                uploads, restore_root, inventory
            )
    finally:
        mutable_parent.chmod(0o700)


def test_failed_extraction_retains_a_private_partial_for_investigation(tmp_path):
    _upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    corrupt = tmp_path / "corrupt.uploads.tar"
    selected = upload_snapshot_common.file_backed_inventory(inventory)[0]
    with tarfile.open(corrupt, mode="w:", format=tarfile.USTAR_FORMAT) as archive:
        info = tarfile.TarInfo(selected.storage_key)
        info.size = selected.size_bytes
        info.mode = 0o600
        info.uid = info.gid = info.mtime = 0
        archive.addfile(info, io.BytesIO(b"x" * selected.size_bytes))
    restore_root = tmp_path / "litblog_restore_uploads_20260822_a2"
    restore_root.mkdir(mode=0o700)
    if os.name == "posix":
        restore_root.chmod(0o700)

    with pytest.raises(upload_snapshot_common.UploadSnapshotError, match="upload archive"):
        upload_snapshot_common.extract_upload_archive(corrupt, restore_root, (selected,))

    assert list(restore_root.glob("objects/*/.*.restore-partial"))


def test_backup_publishes_one_manifest_last_four_file_recovery_set(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    output = tmp_path / "backup-output"
    output.mkdir(mode=0o700)
    if os.name == "posix":
        output.chmod(0o700)
    runner = _BackupRunner()
    inventories = iter((inventory, inventory))

    result = backup_postgres.create_backup(
        output,
        DATABASE_URL,
        upload_root=upload_root,
        writes_quiesced=True,
        runner=runner,
        inventory_reader=lambda _connection, _runner: next(inventories),
        tls_custody_validator=lambda _connection: None,
        upload_custody=upload_snapshot_common.synthetic_upload_custody(),
    )

    assert result.database_archive.is_file()
    assert result.upload_archive.is_file()
    assert result.asset_inventory.is_file()
    assert result.manifest.is_file()
    assert sorted(path.suffixes for path in output.iterdir()) == [
        [".assets", ".jsonl"],
        [".dump"],
        [".manifest", ".json"],
        [".uploads", ".tar"],
    ]
    assert upload_snapshot_common.load_coupled_recovery_set(result.manifest).inventory == inventory
    assert [Path(call[0][0]).name for call in runner.calls] == ["psql", "pg_dump"]
    dump_command = runner.calls[1][0]
    assert "--no-owner" not in dump_command
    assert "--no-acl" not in dump_command


def test_backup_requires_explicit_quiescence_before_database_or_file_reads(tmp_path):
    upload_root, _inventory, _payloads = _upload_fixture(tmp_path)
    output = tmp_path / "backup-output"
    output.mkdir(mode=0o700)
    if os.name == "posix":
        output.chmod(0o700)
    runner = _BackupRunner()

    with pytest.raises(backup_postgres.PostgresOperatorError, match="quiesced"):
        backup_postgres.create_backup(
            output,
            DATABASE_URL,
            upload_root=upload_root,
            writes_quiesced=False,
            runner=runner,
            inventory_reader=lambda _connection, _runner: pytest.fail(
                "inventory must not be read"
            ),
            tls_custody_validator=lambda _connection: None,
        )

    assert runner.calls == []
    assert list(output.iterdir()) == []


def test_backup_production_path_uses_the_reviewed_service_custody_contract(
    monkeypatch,
):
    source = (SCRIPT_DIR / "backup_postgres.py").read_text(encoding="utf-8")

    if os.name == "posix":
        import grp
        import pwd

        monkeypatch.setattr(
            pwd,
            "getpwnam",
            lambda _name: type("PasswordEntry", (), {"pw_uid": 1200})(),
        )
        monkeypatch.setattr(
            grp,
            "getgrnam",
            lambda _name: type("GroupEntry", (), {"gr_gid": 1200})(),
        )

    assert "Path(upload_root) != PRODUCTION_UPLOAD_ROOT" in source
    assert "upload_custody or production_upload_custody()" in source
    assert upload_snapshot_common.PRODUCTION_UPLOAD_USER == "litblogs"
    assert upload_snapshot_common.PRODUCTION_UPLOAD_GROUP == "litblogs"
    assert upload_snapshot_common.PRODUCTION_UPLOAD_ROOT_MODE == 0o750
    production = upload_snapshot_common.production_upload_custody()
    assert production.ancestor_owner_uids == frozenset({0})
    assert not production.allow_root_owned_sticky_ancestors
    synthetic = upload_snapshot_common.synthetic_upload_custody()
    assert synthetic.ancestor_owner_uids == frozenset(
        {0, os.geteuid()} if os.name == "posix" else set()
    )
    assert synthetic.allow_root_owned_sticky_ancestors


def test_backup_requires_the_exact_non_admin_backup_principal_before_inventory(tmp_path):
    upload_root, _inventory, _payloads = _upload_fixture(tmp_path)
    output = tmp_path / "backup-output"
    output.mkdir(mode=0o700)
    if os.name == "posix":
        output.chmod(0o700)
    runner = _BackupRunner(backup_role_result="failed")

    with pytest.raises(backup_postgres.PostgresOperatorError, match="backup principal"):
        backup_postgres.create_backup(
            output,
            DATABASE_URL,
            upload_root=upload_root,
            writes_quiesced=True,
            runner=runner,
            inventory_reader=lambda _connection, _runner: pytest.fail(
                "registry inventory must not be read"
            ),
            tls_custody_validator=lambda _connection: None,
            upload_custody=upload_snapshot_common.synthetic_upload_custody(),
        )

    assert [Path(call[0][0]).name for call in runner.calls] == ["psql"]
    assert list(output.iterdir()) == []

    probe = backup_postgres.BACKUP_ROLE_PRECHECK_SQL
    for fragment in (
        "SESSION_USER = CURRENT_USER",
        "CURRENT_USER = 'litblogs_backup'",
        "pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]",
        "role.rolcanlogin",
        "role.rolinherit",
        "NOT role.rolsuper",
        "pg_catalog.pg_auth_members",
        "pg_read_all_data",
            "membership.admin_option",
        "has_database_privilege",
        "has_schema_privilege",
        "unexpected_database_privilege",
        "database.oid, 'CREATE'",
        "database.oid, 'TEMPORARY'",
        "expected_database_acl",
        "actual_database_acl",
        "direct_application_acl",
        "owned_application_objects",
    ):
        assert fragment in probe


def test_backup_rejects_a_runtime_or_admin_database_url_before_connecting(tmp_path):
    upload_root, _inventory, _payloads = _upload_fixture(tmp_path)
    output = tmp_path / "backup-output"
    output.mkdir(mode=0o700)
    runner = _BackupRunner()
    runtime_url = DATABASE_URL.replace("litblogs_backup", "litblogs_runtime")

    with pytest.raises(backup_postgres.PostgresOperatorError, match="backup principal"):
        backup_postgres.create_backup(
            output,
            runtime_url,
            upload_root=upload_root,
            writes_quiesced=True,
            runner=runner,
            inventory_reader=lambda _connection, _runner: pytest.fail(
                "registry inventory must not be read"
            ),
            tls_custody_validator=lambda _connection: None,
            upload_custody=upload_snapshot_common.synthetic_upload_custody(),
        )

    assert runner.calls == []


def test_backup_rejects_registry_b_drift_and_retains_unpublished_work(tmp_path):
    upload_root, inventory, _payloads = _upload_fixture(tmp_path)
    output = tmp_path / "backup-output"
    output.mkdir(mode=0o700)
    if os.name == "posix":
        output.chmod(0o700)
    changed_rows = [record.as_json_object() for record in inventory]
    changed_rows[0]["state"] = "DELETE_PENDING"
    changed = upload_snapshot_common.registry_inventory(changed_rows)
    inventories = iter((inventory, changed))

    with pytest.raises(backup_postgres.PostgresOperatorError, match="changed"):
        backup_postgres.create_backup(
            output,
            DATABASE_URL,
            upload_root=upload_root,
            writes_quiesced=True,
            runner=_BackupRunner(),
            inventory_reader=lambda _connection, _runner: next(inventories),
            tls_custody_validator=lambda _connection: None,
            upload_custody=upload_snapshot_common.synthetic_upload_custody(),
        )

    assert not list(output.glob("*.manifest.json"))
    assert list(output.glob(".*.partial"))


def test_restore_recovers_database_and_files_then_verifies_exact_registry(tmp_path):
    database, uploads, assets, manifest, inventory, payloads = _recovery_fixture(tmp_path)
    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )
    restore_root = tmp_path / "litblog_restore_uploads_20260822_a3"
    restore_root.mkdir(mode=0o700)
    if os.name == "posix":
        restore_root.chmod(0o700)
    runner = _RestoreRunner(inventory)

    result = restore_verify_postgres.restore_coupled_and_verify(
        manifest,
        "litblog_restore_verify_20260822_a3",
        upload_target=restore_root,
        confirmation="litblog_restore_verify_20260822_a3",
        database_url=DATABASE_URL,
        runner=runner,
        drift_checker=lambda _connection, _target: None,
        tls_custody_validator=lambda _connection: None,
    )

    assert result.migration_state == "current_head"
    assert {
        path.relative_to(restore_root).as_posix(): path.read_bytes()
        for path in restore_root.glob("objects/*/*")
    } == payloads
    assert any(
        call[0][call[0].index("--command") + 1]
        == restore_verify_postgres.UPLOAD_REGISTRY_INVENTORY_SQL
        for call in runner.calls
        if "--command" in call[0]
    )
    restore_command = next(
        call[0]
        for call in runner.calls
        if Path(call[0][0]).name == "pg_restore" and "--list" not in call[0]
    )
    assert "--no-owner" not in restore_command
    assert "--no-acl" not in restore_command


def test_current_head_restore_fails_closed_on_owner_or_acl_drift(tmp_path):
    database, uploads, assets, manifest, inventory, _payloads = _recovery_fixture(tmp_path)
    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )
    restore_root = tmp_path / "litblog_restore_uploads_20260822_acl"
    restore_root.mkdir(mode=0o700)
    if os.name == "posix":
        restore_root.chmod(0o700)

    with pytest.raises(
        restore_verify_postgres.PostgresOperatorError,
        match="ownership and ACL",
    ):
        restore_verify_postgres.restore_coupled_and_verify(
            manifest,
            "litblog_restore_verify_20260822_acl",
            upload_target=restore_root,
            confirmation="litblog_restore_verify_20260822_acl",
            database_url=DATABASE_URL,
            runner=_RestoreRunner(inventory, current_head_integrity="failed"),
            drift_checker=lambda _connection, _target: None,
            tls_custody_validator=lambda _connection: None,
        )

    assert not list(restore_root.glob("objects/*/*"))


def test_restore_requires_isolated_nologin_roles_before_creating_targets(tmp_path):
    database, uploads, assets, manifest, inventory, _payloads = _recovery_fixture(tmp_path)
    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )
    restore_root = tmp_path / "litblog_restore_uploads_20260822_roles"
    restore_root.mkdir(mode=0o700)
    runner = _RestoreRunner(inventory, target_state="isolated-roles-invalid")

    with pytest.raises(
        restore_verify_postgres.PostgresOperatorError,
        match="five isolated NOLOGIN application and migrator roles",
    ):
        restore_verify_postgres.restore_coupled_and_verify(
            manifest,
            "litblog_restore_verify_20260822_roles",
            upload_target=restore_root,
            confirmation="litblog_restore_verify_20260822_roles",
            database_url=DATABASE_URL,
            runner=runner,
            drift_checker=lambda _connection, _target: None,
            tls_custody_validator=lambda _connection: None,
        )

    assert not any(Path(call[0][0]).name == "createdb" for call in runner.calls)

    preflight = restore_verify_postgres.SYNTHETIC_TARGET_STATE_SQL
    assert "pg_catalog.pg_auth_members" in preflight
    assert "granted_role.oid = membership.roleid" in preflight
    assert "member_role.oid = membership.member" in preflight
    assert "pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]" in preflight


def test_restore_acl_probe_is_catalog_wide_and_checks_fixed_security_boundary():
    probe = restore_verify_postgres.IDENTITY_DATA_INTEGRITY_SQL

    for fragment in (
        "aclexplode",
        "pg_auth_members",
        "litblogs_runtime",
        "litblogs_migrator",
        "litblog_identity_owner",
        "litblog_account_operator",
        "litblog_invitation_operator",
        "operator_set_account_status",
        "operator_create_teacher_invitation",
        "operator_revoke_teacher_invitation",
        "prosecdef",
        "search_path=pg_catalog, pg_temp",
        "expected_default_function_acl",
        "actual_default_function_acl",
        "default_function_acl_scope_valid",
        "expected_user_schemas",
        "actual_user_schemas",
        "database_acl_valid",
    ):
        assert fragment in probe

    assert "SELECT * FROM actual_default_function_acl" in probe
    assert "EXCEPT\n        SELECT * FROM expected_default_function_acl" in probe
    assert "SELECT * FROM expected_default_function_acl" in probe
    assert "EXCEPT\n        SELECT * FROM actual_default_function_acl" in probe
    assert "default_acl.defaclnamespace = 0" in probe
    assert "default_acl.defaclnamespace <> 0" in probe
    assert "pg_catalog.pg_get_userbyid(default_acl.defaclrole)" not in probe

    recovery_docs = (
        (ROOT_DIR / "docs/operations/production-runbook.md").read_text(encoding="utf-8")
        + (ROOT_DIR / "deploy/README.md").read_text(encoding="utf-8")
    ).casefold()
    assert "exact global default-function acl" in recovery_docs
    assert "schema-scoped default-function acl" in recovery_docs
    assert "only non-system schema" in recovery_docs
    assert "pg_read_all_data" in recovery_docs
    assert (
        "neither the backup role nor any role in its recursive membership closure "
        "may own"
    ) in recovery_docs
    assert "has_database_privilege('litblogs_backup', datname, 'connect')" in recovery_docs


def test_restore_pins_exact_reviewed_operator_routine_bodies_and_metadata():
    contract = restore_verify_postgres._load_expected_operator_routine_contract(
        ROOT_DIR / "litblogs"
    )

    assert set(contract) == {
        (
            "operator_set_account_status(character varying, boolean, "
            "character varying, character varying)"
        ),
        (
            "operator_create_teacher_invitation(character varying, character "
            "varying, timestamp with time zone, character varying, character varying)"
        ),
        (
            "operator_revoke_teacher_invitation(character varying, character "
            "varying, character varying)"
        ),
    }
    migration_source = (
        ROOT_DIR
        / "litblogs/migrations/versions/c5136f36e302_identity_controls.py"
    ).read_text(encoding="utf-8")
    for expected in contract.values():
        assert expected["source"] in migration_source
        assert expected == {
            **expected,
            "language": "plpgsql",
            "return_type": "character varying",
            "volatility": "v",
            "parallel_safety": "u",
            "strict": False,
            "leakproof": False,
            "kind": "f",
            "security_definer": True,
            "configuration": ["search_path=pg_catalog, pg_temp"],
            "argument_defaults": 0,
            "owner": "litblog_identity_owner",
        }

    catalog_probe = restore_verify_postgres.OPERATOR_ROUTINE_CATALOG_SQL
    for fragment in (
        "routine.prosrc",
        "language.lanname",
        "pg_catalog.format_type(routine.prorettype, NULL)",
        "routine.provolatile",
        "routine.proparallel",
        "routine.proisstrict",
        "routine.proleakproof",
        "routine.prokind",
        "routine.prosecdef",
        "routine.proconfig",
        "routine.pronargdefaults",
        "owner.rolname",
    ):
        assert fragment in catalog_probe


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_restore_rejects_ambiguous_migration_routine_sources(tmp_path, mutation):
    source_path = (
        ROOT_DIR
        / "litblogs/migrations/versions/c5136f36e302_identity_controls.py"
    )
    migration_source = source_path.read_text(encoding="utf-8")
    marker = "CREATE OR REPLACE FUNCTION public.operator_set_account_status("
    if mutation == "missing":
        migration_source = migration_source.replace(marker, "REMOVED FUNCTION(", 1)
    else:
        start = migration_source.index(marker)
        end = migration_source.index("$operator_set_account_status$;", start)
        end += len("$operator_set_account_status$;")
        migration_source += "\n" + migration_source[start:end]

    backend_root = tmp_path / "litblogs"
    candidate = (
        backend_root / "migrations/versions/c5136f36e302_identity_controls.py"
    )
    candidate.parent.mkdir(parents=True)
    candidate.write_text(migration_source, encoding="utf-8")

    with pytest.raises(
        restore_verify_postgres.PostgresOperatorError,
        match="operator routine source contract",
    ):
        restore_verify_postgres._load_expected_operator_routine_contract(backend_root)


def test_restore_rejects_decoy_routines_outside_the_reviewed_migration_constant(
    tmp_path,
):
    source_path = (
        ROOT_DIR
        / "litblogs/migrations/versions/c5136f36e302_identity_controls.py"
    )
    migration_source = source_path.read_text(encoding="utf-8").replace(
        'OPERATOR_FUNCTIONS_SQL = r"""',
        'OPERATOR_FUNCTIONS_SQL = ""\nDECOY_OPERATOR_SQL = r"""',
        1,
    )
    backend_root = tmp_path / "litblogs"
    candidate = (
        backend_root / "migrations/versions/c5136f36e302_identity_controls.py"
    )
    candidate.parent.mkdir(parents=True)
    candidate.write_text(migration_source, encoding="utf-8")

    with pytest.raises(
        restore_verify_postgres.PostgresOperatorError,
        match="operator routine source contract",
    ):
        restore_verify_postgres._load_expected_operator_routine_contract(backend_root)


def test_backup_precheck_denies_transitive_membership_and_effective_write_access():
    probe = backup_postgres.BACKUP_ROLE_PRECHECK_SQL

    for fragment in (
        "WITH RECURSIVE",
        "membership_closure",
        "effective_roles",
        "SELECT role.oid AS role_oid",
        "SELECT closure.granted_role_oid",
        "membership.inherit_option",
        "membership.set_option",
        "pg_catalog.has_table_privilege",
        "pg_catalog.has_any_column_privilege",
        "('INSERT')",
        "('UPDATE')",
        "('DELETE')",
        "('TRUNCATE')",
        "('REFERENCES')",
        "('TRIGGER')",
        "pg_catalog.has_sequence_privilege",
        "VALUES ('USAGE'), ('UPDATE')",
        "pg_catalog.has_schema_privilege",
        "'CREATE'",
        "pg_catalog.has_function_privilege",
        "'EXECUTE'",
        "database.datdba = role.role_oid",
        "namespace.nspowner = role.role_oid",
        "relation.relowner = role.role_oid",
        "routine.proowner = role.role_oid",
        "type_record.typowner = role.role_oid",
    ):
        assert fragment in probe

    for workflow_path in (
        ROOT_DIR / ".github/workflows/ci.yml",
        ROOT_DIR / ".github/workflows/release.yml",
    ):
        workflow = workflow_path.read_text(encoding="utf-8")
        assert "GRANT pg_write_all_data TO pg_read_all_data" in workflow
        assert "REVOKE pg_write_all_data FROM pg_read_all_data" in workflow


def test_restore_runbook_transitions_to_runtime_only_after_final_exact_verifier():
    runbook = (ROOT_DIR / "docs/operations/production-runbook.md").read_text(
        encoding="utf-8"
    )

    final_verifier = runbook.index("--verify-existing")
    runtime_transition = runbook.index(
        "ALTER ROLE litblogs_runtime LOGIN", final_verifier
    )
    readiness = runbook.index("database.check_database_readiness", runtime_transition)
    journeys = runbook.index("legacy OAuth recovery", readiness)
    destruction = runbook.index("destroy the disposable cluster", journeys)
    assert final_verifier < runtime_transition < readiness < journeys < destruction
    for fragment in (
        "before either exact verifier",
        "only documented one-way synthetic runtime transition",
        "GRANT CONNECT ON DATABASE litblog_restore_verify_",
        "SCRAM",
        "wrong password",
        "all other application roles remain `NOLOGIN`",
        "must not rerun or claim the exact restore verifier",
        "Never use the restore DBA for application checks",
        "never carry the synthetic credential to production",
    ):
        assert fragment in runbook


def test_registry_and_restore_data_probes_pin_the_public_schema():
    assert "FROM public.upload_assets" in backup_postgres.REGISTRY_INVENTORY_SQL
    assert (
        "FROM public.upload_assets"
        in restore_verify_postgres.UPLOAD_REGISTRY_INVENTORY_SQL
    )
    core_probe = restore_verify_postgres.CORE_DATA_INTEGRITY_SQL
    for relation in (
        "users",
        "password_resets",
        "push_subscriptions",
        "teachers",
        "user_settings",
        "classes",
        "assignments",
        "blogs",
        "class_enrollments",
        "assignment_drafts",
        "assignment_reminder_notifications",
        "assignment_submissions",
        "comments",
        "post_likes",
        "saved_posts",
        "assignment_submission_replies",
        "comment_likes",
        "upload_assets",
    ):
        assert f"FROM public.{relation}" in core_probe

    identity_probe = restore_verify_postgres.IDENTITY_DATA_INTEGRITY_SQL
    assert "FROM federated_identities" not in identity_probe
    assert "FROM public.federated_identities AS identity" in identity_probe
    assert "LEFT JOIN public.users AS identity_user" in identity_probe


@pytest.mark.skipif(os.name != "posix", reason="POSIX custody metadata only")
def test_coupled_restore_rejects_mutable_staging_before_loading_manifest(
    tmp_path, monkeypatch
):
    mutable_parent = tmp_path / "mutable-staging-parent"
    staging = mutable_parent / "staging"
    staging.mkdir(parents=True, mode=0o700)
    mutable_parent.chmod(0o770)
    loader_called = False

    def forbidden_loader(_manifest):
        nonlocal loader_called
        loader_called = True
        pytest.fail("manifest loader must not run before staging custody")

    monkeypatch.setattr(
        restore_verify_postgres,
        "load_coupled_recovery_set",
        forbidden_loader,
    )
    try:
        with pytest.raises(
            restore_verify_postgres.PostgresOperatorError,
            match="unsafe permissions",
        ):
            restore_verify_postgres._load_coupled_with_custody(
                staging / "litblogs-20260822T120000Z-a1b2c3d4.manifest.json"
            )
    finally:
        mutable_parent.chmod(0o700)

    assert loader_called is False


def test_restore_rejects_restored_registry_drift_and_retains_database_and_files(tmp_path):
    database, uploads, assets, manifest, inventory, _payloads = _recovery_fixture(tmp_path)
    upload_snapshot_common.write_coupled_manifest(
        manifest,
        database_path=database,
        upload_archive_path=uploads,
        asset_inventory_path=assets,
        inventory=inventory,
        created_at="2026-08-22T12:00:00Z",
    )
    restore_root = tmp_path / "litblog_restore_uploads_20260822_a4"
    restore_root.mkdir(mode=0o700)
    if os.name == "posix":
        restore_root.chmod(0o700)
    changed = list(inventory)
    changed[0] = upload_snapshot_common.AssetRecord(
        asset_id=changed[0].asset_id,
        storage_key=changed[0].storage_key,
        state="DELETE_PENDING",
        size_bytes=changed[0].size_bytes,
        sha256_digest=changed[0].sha256_digest,
    )
    runner = _RestoreRunner(tuple(changed))

    with pytest.raises(
        restore_verify_postgres.PostgresOperatorError,
        match="registry does not match",
    ):
        restore_verify_postgres.restore_coupled_and_verify(
            manifest,
            "litblog_restore_verify_20260822_a4",
            upload_target=restore_root,
            confirmation="litblog_restore_verify_20260822_a4",
            database_url=DATABASE_URL,
            runner=runner,
            drift_checker=lambda _connection, _target: None,
            tls_custody_validator=lambda _connection: None,
        )

    assert list(restore_root.glob("objects/*/*"))
    assert not any(
        Path(call[0][0]).name == "dropdb"
        for call in runner.calls
    )


def test_initial_legacy_rollout_is_not_told_to_run_the_current_head_backup_tool():
    runbook = (ROOT_DIR / "docs/operations/production-runbook.md").read_text(
        encoding="utf-8"
    ).casefold()
    deployment = (ROOT_DIR / "deploy/README.md").read_text(encoding="utf-8").casefold()
    combined = f"{deployment}\n{runbook}"

    for phrase in (
        "initial legacy rollout is blocked",
        "storage-native pre-migration checkpoint",
        "upload_assets does not exist",
        "do not run backup_postgres.py",
        "offline legacy upload inventory and import",
        "current-head coupled recovery set",
    ):
        assert phrase in combined

#!/usr/bin/env python3
"""Create a guarded, manifest-last database/upload recovery set."""

from __future__ import annotations

import argparse
import csv
import io
import os
import secrets
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from postgres_common import (
    PostgresConnection,
    PostgresOperatorError,
    build_pg_environment,
    parse_postgres_url,
    postgres_executable,
    validate_postgres_client_installation,
    validate_postgres_tls_custody,
    validate_private_operator_directory,
)
from upload_snapshot_common import (
    PRODUCTION_UPLOAD_ROOT,
    AssetRecord,
    UploadRootCustody,
    UploadSnapshotError,
    create_upload_archive,
    production_upload_custody,
    registry_inventory,
    require_stable_registry,
    verify_upload_tree,
    write_asset_inventory,
    write_coupled_manifest,
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
InventoryReader = Callable[
    [PostgresConnection, CommandRunner],
    tuple[AssetRecord, ...],
]
REGISTRY_INVENTORY_SQL = """
COPY (
    SELECT
        id AS asset_id,
        storage_key,
        state,
        size_bytes,
        pg_catalog.rtrim(sha256_digest) AS sha256_digest
    FROM public.upload_assets
    ORDER BY storage_key
) TO STDOUT WITH (FORMAT CSV, HEADER TRUE);
""".strip()
BACKUP_ROLE_PRECHECK_SQL = """
WITH RECURSIVE backup_role AS (
    SELECT
        role.oid,
        role.rolcanlogin,
        role.rolinherit,
        role.rolsuper,
        role.rolcreatedb,
        role.rolcreaterole,
        role.rolreplication,
        role.rolbypassrls
    FROM pg_catalog.pg_roles AS role
    WHERE role.rolname = 'litblogs_backup'
),
direct_memberships AS (
    SELECT
        membership.roleid AS granted_role_oid,
        granted_role.rolname AS granted_role_name,
        membership.admin_option,
        membership.inherit_option,
        membership.set_option
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted_role
      ON granted_role.oid = membership.roleid
    JOIN pg_catalog.pg_roles AS member_role
      ON member_role.oid = membership.member
    WHERE member_role.rolname = 'litblogs_backup'
),
membership_closure(
    granted_role_oid,
    granted_role_name,
    admin_option,
    inherit_option,
    set_option,
    membership_depth,
    role_path
) AS (
    SELECT
        membership.granted_role_oid,
        membership.granted_role_name,
        membership.admin_option,
        membership.inherit_option,
        membership.set_option,
        1,
        ARRAY[role.oid, membership.granted_role_oid]
    FROM direct_memberships AS membership
    CROSS JOIN backup_role AS role
    UNION ALL
    SELECT
        membership.roleid,
        granted_role.rolname,
        membership.admin_option,
        membership.inherit_option,
        membership.set_option,
        closure.membership_depth + 1,
        closure.role_path || membership.roleid
    FROM membership_closure AS closure
    JOIN pg_catalog.pg_auth_members AS membership
      ON membership.member = closure.granted_role_oid
    JOIN pg_catalog.pg_roles AS granted_role
      ON granted_role.oid = membership.roleid
    WHERE NOT membership.roleid = ANY(closure.role_path)
),
effective_roles(role_oid) AS (
    SELECT role.oid AS role_oid
    FROM backup_role AS role
    UNION
    SELECT closure.granted_role_oid
    FROM membership_closure AS closure
),
reverse_memberships AS (
    SELECT 1 AS present
    FROM pg_catalog.pg_auth_members AS membership
    JOIN pg_catalog.pg_roles AS granted_role
      ON granted_role.oid = membership.roleid
    WHERE granted_role.rolname = 'litblogs_backup'
),
target_database AS (
    SELECT
        database.oid,
        database.datdba,
        role.oid AS backup_role_oid,
        pg_catalog.has_database_privilege(
            role.oid, database.oid, 'CONNECT'
        ) AS can_connect,
        pg_catalog.has_database_privilege(
            role.oid, database.oid, 'CREATE'
        ) AS can_create,
        pg_catalog.has_database_privilege(
            role.oid, database.oid, 'TEMPORARY'
        ) AS can_create_temporary,
        pg_catalog.has_schema_privilege(
            role.oid, 'public', 'CREATE'
        ) AS can_create_in_public
    FROM pg_catalog.pg_database AS database
    CROSS JOIN backup_role AS role
    WHERE database.datname = pg_catalog.current_database()
),
unexpected_database_privilege AS (
    SELECT 1 AS present
    FROM pg_catalog.pg_database AS database
    CROSS JOIN backup_role AS role
    WHERE (
        database.datname <> pg_catalog.current_database()
        AND pg_catalog.has_database_privilege(
            role.oid, database.oid, 'CONNECT'
        )
    ) OR pg_catalog.has_database_privilege(
        role.oid, database.oid, 'CREATE'
    ) OR pg_catalog.has_database_privilege(
        role.oid, database.oid, 'TEMPORARY'
    )
),
expected_database_acl(role_name, privilege_type, is_grantable) AS (
    VALUES ('litblogs_backup', 'CONNECT', FALSE)
),
actual_database_acl(role_name, privilege_type, is_grantable) AS (
    SELECT
        COALESCE(grantee.rolname, 'PUBLIC'),
        acl.privilege_type,
        acl.is_grantable
    FROM target_database AS database
    CROSS JOIN LATERAL pg_catalog.aclexplode(
        COALESCE(
            (SELECT datacl FROM pg_catalog.pg_database WHERE oid = database.oid),
            pg_catalog.acldefault('d', database.datdba)
        )
    ) AS acl
    LEFT JOIN pg_catalog.pg_roles AS grantee ON grantee.oid = acl.grantee
    WHERE acl.grantee = 0 OR acl.grantee = database.backup_role_oid
),
direct_application_acl AS (
    SELECT 1 AS present
    FROM backup_role AS role
    JOIN pg_catalog.pg_namespace AS namespace ON TRUE
    CROSS JOIN LATERAL pg_catalog.aclexplode(namespace.nspacl) AS acl
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND acl.grantee = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_class AS relation ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(relation.relacl) AS acl
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND acl.grantee = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_attribute AS attribute ON TRUE
    JOIN pg_catalog.pg_class AS relation ON relation.oid = attribute.attrelid
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(attribute.attacl) AS acl
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND acl.grantee = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_proc AS routine ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(routine.proacl) AS acl
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND acl.grantee = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_type AS type_record ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = type_record.typnamespace
    CROSS JOIN LATERAL pg_catalog.aclexplode(type_record.typacl) AS acl
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND acl.grantee = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_default_acl AS default_acl
      ON default_acl.defaclrole = role.oid
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_default_acl AS default_acl ON TRUE
    CROSS JOIN LATERAL pg_catalog.aclexplode(default_acl.defaclacl) AS acl
    WHERE acl.grantee = role.oid
),
effective_write_or_execute_privilege AS (
    SELECT 1 AS present
    FROM backup_role AS role
    JOIN pg_catalog.pg_namespace AS namespace ON TRUE
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND pg_catalog.has_schema_privilege(role.oid, namespace.oid, 'CREATE')
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_class AS relation ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    CROSS JOIN (
        VALUES
            ('INSERT'),
            ('UPDATE'),
            ('DELETE'),
            ('TRUNCATE'),
            ('REFERENCES'),
            ('TRIGGER')
    ) AS privilege(privilege_name)
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
      AND (
          pg_catalog.has_table_privilege(
              role.oid, relation.oid, privilege.privilege_name
          )
          OR (
              privilege.privilege_name IN ('INSERT', 'UPDATE', 'REFERENCES')
              AND pg_catalog.has_any_column_privilege(
                  role.oid, relation.oid, privilege.privilege_name
              )
          )
      )
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_class AS sequence ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = sequence.relnamespace
    CROSS JOIN (
        VALUES ('USAGE'), ('UPDATE')
    ) AS privilege(privilege_name)
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND sequence.relkind = 'S'
      AND pg_catalog.has_sequence_privilege(
          role.oid, sequence.oid, privilege.privilege_name
      )
    UNION ALL
    SELECT 1
    FROM backup_role AS role
    JOIN pg_catalog.pg_proc AS routine ON TRUE
    JOIN pg_catalog.pg_namespace AS namespace
      ON namespace.oid = routine.pronamespace
    WHERE namespace.nspname <> 'information_schema'
      AND namespace.nspname !~ '^pg_'
      AND pg_catalog.has_function_privilege(role.oid, routine.oid, 'EXECUTE')
),
owned_application_objects AS (
    SELECT 1 AS present
    FROM effective_roles AS role
    JOIN pg_catalog.pg_database AS database ON database.datdba = role.role_oid
    UNION ALL
    SELECT 1
    FROM effective_roles AS role
    JOIN pg_catalog.pg_namespace AS namespace ON namespace.nspowner = role.role_oid
    UNION ALL
    SELECT 1
    FROM effective_roles AS role
    JOIN pg_catalog.pg_class AS relation ON relation.relowner = role.role_oid
    UNION ALL
    SELECT 1
    FROM effective_roles AS role
    JOIN pg_catalog.pg_proc AS routine ON routine.proowner = role.role_oid
    UNION ALL
    SELECT 1
    FROM effective_roles AS role
    JOIN pg_catalog.pg_type AS type_record ON type_record.typowner = role.role_oid
)
SELECT CASE WHEN
    SESSION_USER = CURRENT_USER
    AND CURRENT_USER = 'litblogs_backup'
    AND pg_catalog.current_schemas(FALSE) = ARRAY['public'::name]
    AND COALESCE((
        SELECT
            role.rolcanlogin
            AND role.rolinherit
            AND NOT role.rolsuper
            AND NOT role.rolcreatedb
            AND NOT role.rolcreaterole
            AND NOT role.rolreplication
            AND NOT role.rolbypassrls
        FROM backup_role AS role
    ), FALSE)
    AND (SELECT COUNT(*) FROM membership_closure) = 1
    AND NOT EXISTS (
        SELECT 1
        FROM membership_closure AS membership
        WHERE membership.granted_role_name <> 'pg_read_all_data'
           OR membership.admin_option
           OR NOT membership.inherit_option
           OR NOT membership.set_option
           OR membership.membership_depth <> 1
    )
    AND NOT EXISTS (SELECT 1 FROM reverse_memberships)
    AND NOT EXISTS (SELECT 1 FROM unexpected_database_privilege)
    AND COALESCE((
        SELECT
            database.datdba <> database.backup_role_oid
            AND database.can_connect
            AND NOT database.can_create
            AND NOT database.can_create_temporary
            AND NOT database.can_create_in_public
        FROM target_database AS database
    ), FALSE)
    AND NOT EXISTS (
        SELECT * FROM actual_database_acl
        EXCEPT
        SELECT * FROM expected_database_acl
    )
    AND NOT EXISTS (
        SELECT * FROM expected_database_acl
        EXCEPT
        SELECT * FROM actual_database_acl
    )
    AND NOT EXISTS (SELECT 1 FROM direct_application_acl)
    AND NOT EXISTS (SELECT 1 FROM effective_write_or_execute_privilege)
    AND NOT EXISTS (SELECT 1 FROM owned_application_objects)
THEN 'ok' ELSE 'failed' END;
""".strip()


@dataclass(frozen=True)
class BackupResult:
    database_archive: Path
    upload_archive: Path
    asset_inventory: Path
    manifest: Path
    created_at: str

    @property
    def archive(self) -> Path:
        """Compatibility alias for callers that label the DB member archive."""

        return self.database_archive


def is_private_directory_mode(mode: int) -> bool:
    """Return whether the directory has exact owner-only POSIX custody."""

    return mode & 0o777 == 0o700


def validate_backup_principal(
    connection: PostgresConnection,
    runner: CommandRunner = subprocess.run,
) -> None:
    """Require the fixed non-admin backup principal before reading application data."""

    if connection.user != "litblogs_backup":
        raise PostgresOperatorError(
            "The database backup principal failed least-privilege validation"
        )
    command = [
        postgres_executable("psql"),
        "--no-psqlrc",
        "--no-password",
        "--tuples-only",
        "--no-align",
        "--set=ON_ERROR_STOP=1",
        "--command",
        BACKUP_ROLE_PRECHECK_SQL,
    ]
    try:
        result = runner(
            command,
            env=build_pg_environment(connection),
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise PostgresOperatorError(
            "The database backup principal failed least-privilege validation"
        ) from exc
    if result.returncode != 0 or (result.stdout or "").strip() != "ok":
        raise PostgresOperatorError(
            "The database backup principal failed least-privilege validation"
        )


def _fsync_file(path: Path) -> None:
    """Flush a completed regular file before publishing its name."""

    # A writable descriptor is required by fsync on Windows; production POSIX
    # behavior is identical and the work files are operator-owned mode 0600.
    with path.open("r+b") as source:
        os.fsync(source.fileno())


def _fsync_directory(path: Path) -> None:
    """Persist same-directory link/unlink operations on production POSIX hosts."""

    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def read_registry_inventory(
    connection: PostgresConnection,
    runner: CommandRunner = subprocess.run,
) -> tuple[AssetRecord, ...]:
    """Read every upload registry row without exposing its contents in logs."""

    command = [
        postgres_executable("psql"),
        "--no-psqlrc",
        "--no-password",
        "--set=ON_ERROR_STOP=1",
        "--command",
        REGISTRY_INVENTORY_SQL,
    ]
    try:
        result = runner(
            command,
            env=build_pg_environment(connection),
            check=False,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise PostgresOperatorError(
            "The upload asset registry inventory could not be read"
        ) from exc
    if result.returncode != 0:
        raise PostgresOperatorError(
            "The upload asset registry inventory could not be read"
        )
    try:
        source = io.StringIO(result.stdout or "")
        reader = csv.DictReader(source)
        if reader.fieldnames != [
            "asset_id",
            "storage_key",
            "state",
            "size_bytes",
            "sha256_digest",
        ]:
            raise ValueError
        rows = [
            {
                "asset_id": int(row["asset_id"]),
                "storage_key": row["storage_key"],
                "state": row["state"],
                "size_bytes": int(row["size_bytes"]),
                "sha256_digest": row["sha256_digest"],
            }
            for row in reader
        ]
        return registry_inventory(rows)
    except (KeyError, TypeError, ValueError, csv.Error, UploadSnapshotError) as exc:
        raise PostgresOperatorError(
            "The upload asset registry inventory was invalid"
        ) from exc


def _create_database_archive(
    destination: Path,
    connection: PostgresConnection,
    *,
    runner: CommandRunner,
) -> None:
    descriptor: int | None = None
    try:
        descriptor = os.open(
            destination,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        os.close(descriptor)
        descriptor = None
        destination.chmod(0o600)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise PostgresOperatorError(
            "A private database backup work file could not be created"
        ) from exc
    command = [
        postgres_executable("pg_dump"),
        "--format=custom",
        "--compress=6",
        "--no-password",
        "--file",
        str(destination),
    ]
    try:
        result = runner(
            command,
            env=build_pg_environment(connection),
            check=False,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        raise PostgresOperatorError("The database backup command could not start") from exc
    if result.returncode != 0:
        raise PostgresOperatorError("The database backup failed")
    try:
        _fsync_file(destination)
        with destination.open("rb") as backup_file:
            if backup_file.read(5) != b"PGDMP":
                raise OSError
    except OSError as exc:
        raise PostgresOperatorError(
            "The database backup was not a custom-format archive"
        ) from exc


def create_backup(
    output_directory: str | Path,
    database_url: str,
    *,
    upload_root: str | Path,
    writes_quiesced: bool,
    runner: CommandRunner = subprocess.run,
    inventory_reader: InventoryReader = read_registry_inventory,
    tls_custody_validator=None,
    upload_custody: UploadRootCustody | None = None,
) -> BackupResult:
    """Create and publish a coupled recovery set with its manifest last."""

    if writes_quiesced is not True:
        raise PostgresOperatorError(
            "All database and upload writes must be quiesced and explicitly confirmed"
        )
    if upload_custody is None and Path(upload_root) != PRODUCTION_UPLOAD_ROOT:
        raise PostgresOperatorError(
            "The production upload root must be /var/lib/litblogs/uploads"
        )
    output_path = Path(output_directory)
    if not output_path.is_absolute():
        raise PostgresOperatorError(
            "The backup output directory must be an absolute path"
        )
    if output_path.is_symlink() or not output_path.is_dir():
        raise PostgresOperatorError("The backup output directory must already exist")
    validate_private_operator_directory(
        output_path, purpose="backup output directory"
    )
    connection = parse_postgres_url(database_url)
    (tls_custody_validator or validate_postgres_tls_custody)(connection)
    validate_backup_principal(connection, runner)
    required_upload_custody = upload_custody or production_upload_custody()

    now = datetime.now(UTC)
    created_at = now.isoformat().replace("+00:00", "Z")
    base_name = f"litblogs-{now:%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}"
    database_archive = output_path / f"{base_name}.dump"
    upload_archive = output_path / f"{base_name}.uploads.tar"
    asset_inventory = output_path / f"{base_name}.assets.jsonl"
    manifest = output_path / f"{base_name}.manifest.json"
    database_partial = output_path / f".{base_name}.dump.partial"
    uploads_partial = output_path / f".{base_name}.uploads.tar.partial"
    assets_partial = output_path / f".{base_name}.assets.jsonl.partial"
    manifest_partial = output_path / f".{base_name}.manifest.json.partial"

    try:
        inventory_a = inventory_reader(connection, runner)
        verify_upload_tree(
            upload_root,
            inventory_a,
            custody=required_upload_custody,
        )
        write_asset_inventory(assets_partial, inventory_a)
        create_upload_archive(
            uploads_partial,
            upload_root,
            inventory_a,
            custody=required_upload_custody,
        )
        _create_database_archive(database_partial, connection, runner=runner)
        inventory_b = inventory_reader(connection, runner)
        require_stable_registry(inventory_a, inventory_b)
        verify_upload_tree(
            upload_root,
            inventory_b,
            custody=required_upload_custody,
        )

        for partial, published in (
            (database_partial, database_archive),
            (uploads_partial, upload_archive),
            (assets_partial, asset_inventory),
        ):
            _fsync_file(partial)
            os.link(partial, published)
        _fsync_directory(output_path)

        write_coupled_manifest(
            manifest_partial,
            published_manifest_path=manifest,
            database_path=database_archive,
            upload_archive_path=upload_archive,
            asset_inventory_path=asset_inventory,
            inventory=inventory_b,
            created_at=created_at,
        )
        _fsync_file(manifest_partial)
        os.link(manifest_partial, manifest)
        _fsync_directory(output_path)
        for partial in (
            database_partial,
            uploads_partial,
            assets_partial,
            manifest_partial,
        ):
            partial.unlink()
        _fsync_directory(output_path)
    except UploadSnapshotError as exc:
        raise PostgresOperatorError(str(exc)) from exc
    except OSError as exc:
        try:
            _fsync_directory(output_path)
        except OSError:
            pass
        raise PostgresOperatorError(
            "The coupled recovery set could not be published safely"
        ) from exc

    return BackupResult(
        database_archive=database_archive,
        upload_archive=upload_archive,
        asset_inventory=asset_inventory,
        manifest=manifest,
        created_at=created_at,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create a manifest-last coupled database/upload recovery set."
    )
    parser.add_argument(
        "--output-dir",
        required=True,
        help="Existing private directory on encrypted backup storage.",
    )
    parser.add_argument(
        "--upload-root",
        required=True,
        help="Canonical private upload root whose writers are stopped.",
    )
    parser.add_argument(
        "--confirm-writes-quiesced",
        action="store_true",
        help="Confirm web and maintenance writers are stopped for this checkpoint.",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: CommandRunner = subprocess.run,
    client_validator=None,
    inventory_reader: InventoryReader = read_registry_inventory,
    tls_custody_validator=None,
    upload_custody: UploadRootCustody | None = None,
) -> int:
    args = _parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "ERROR: DATABASE_URL is required in the operator environment",
            file=sys.stderr,
        )
        return 2
    try:
        (client_validator or validate_postgres_client_installation)()
        result = create_backup(
            args.output_dir,
            database_url,
            upload_root=args.upload_root,
            writes_quiesced=args.confirm_writes_quiesced,
            runner=runner,
            inventory_reader=inventory_reader,
            tls_custody_validator=tls_custody_validator,
            upload_custody=upload_custody,
        )
    except PostgresOperatorError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Database archive: {result.database_archive}")
    print(f"Upload archive: {result.upload_archive}")
    print(f"Asset inventory: {result.asset_inventory}")
    print(f"Coupled manifest: {result.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

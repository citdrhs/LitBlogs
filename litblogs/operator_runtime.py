"""Minimal, least-privilege runtime for trusted identity operator commands."""

import json
import os
import re
import stat
from dataclasses import dataclass
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, SecretStr, field_validator, model_validator
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.orm import Session, sessionmaker

MAX_OPERATOR_CONFIG_BYTES = 64 * 1024
OPERATOR_CONFIG_FD_ENV = "LITBLOG_OPERATOR_CONFIG_FD"
OPERATOR_RUNTIME_PLATFORM = os.name
OPERATOR_DATABASE_HOST = "127.0.0.1"
OPERATOR_ROOT_CERTIFICATE_PATH = "/etc/litblogs/postgres-root-ca.pem"
_OPERATOR_DATABASE_ROLES = {
    "invitation": "litblog_invitation_operator",
    "account": "litblog_account_operator",
}
_DOMAIN_PATTERN = re.compile(
    r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$"
)
_PLACEHOLDER_FRAGMENTS = (
    "changeme",
    "change-me",
    "placeholder",
    "replace-me",
    "replace-with",
    "test-only",
)


class OperatorSettings(BaseModel):
    """Only the secrets and policy needed by the two identity operator roles."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    purpose: Literal["invitation", "account"]
    database_url: SecretStr
    teacher_invite_hmac_key: SecretStr
    allowed_email_domains: tuple[str, ...] = ()

    @field_validator("teacher_invite_hmac_key")
    @classmethod
    def validate_invitation_hmac_key(cls, value: SecretStr) -> SecretStr:
        raw_value = value.get_secret_value()
        normalized = raw_value.casefold()
        if len(raw_value.encode("utf-8")) < 32:
            raise ValueError("operator invitation HMAC key is too short")
        if len(set(raw_value)) < 8 or any(
            fragment in normalized for fragment in _PLACEHOLDER_FRAGMENTS
        ):
            raise ValueError("operator invitation HMAC key is not random")
        return value

    @field_validator("allowed_email_domains", mode="before")
    @classmethod
    def normalize_email_domains(cls, value):
        if value is None:
            return ()
        if not isinstance(value, (list, tuple)):
            raise ValueError("allowed email domains must be a list")
        normalized = tuple(dict.fromkeys(str(item).strip().lower() for item in value))
        if any(not _DOMAIN_PATTERN.fullmatch(domain) for domain in normalized):
            raise ValueError("allowed email domain is invalid")
        return normalized

    @model_validator(mode="after")
    def validate_database_url(self):
        database_url = make_url(self.database_url.get_secret_value())
        if database_url.drivername != "postgresql+psycopg2":
            raise ValueError("operator database driver is invalid")
        if database_url.username != expected_database_role(self.purpose):
            raise ValueError("operator database credential must match expected role")
        password = database_url.password or ""
        if len(password.encode("utf-8")) < 32 or len(set(password)) < 8:
            raise ValueError("operator database password is not strong")
        lowered_password = password.casefold()
        if any(fragment in lowered_password for fragment in _PLACEHOLDER_FRAGMENTS):
            raise ValueError("operator database password is not strong")
        host = database_url.host or ""
        if host != OPERATOR_DATABASE_HOST:
            raise ValueError("operator database host is invalid")
        if database_url.port != 5_432:
            raise ValueError("operator database port is invalid")
        if database_url.database != "litblogs":
            raise ValueError("operator database name is invalid")
        if set(database_url.query) != {"sslmode", "sslrootcert"}:
            raise ValueError("operator database TLS parameters are invalid")
        if database_url.query["sslmode"] != "verify-full":
            raise ValueError("operator database TLS verification is required")
        root_certificate = database_url.query["sslrootcert"]
        if root_certificate != OPERATOR_ROOT_CERTIFICATE_PATH:
            raise ValueError("operator database root certificate path is invalid")
        return self


def expected_database_role(
    purpose: Literal["invitation", "account"],
) -> str:
    """Return the reviewed role name; operator-controlled config cannot override it."""

    try:
        return _OPERATOR_DATABASE_ROLES[purpose]
    except KeyError as exc:
        raise ValueError("operator purpose is invalid") from exc


def _operator_config_fd(config_fd: int | None) -> int:
    if config_fd is not None:
        candidate = config_fd
    else:
        raw_value = os.environ.get(OPERATOR_CONFIG_FD_ENV, "3")
        if not raw_value.isascii() or not raw_value.isdecimal():
            raise RuntimeError("operator config file descriptor is invalid")
        candidate = int(raw_value)
    if isinstance(candidate, bool) or not isinstance(candidate, int):
        raise RuntimeError("operator config file descriptor is invalid")
    if candidate < 3 or candidate > 1_024:
        raise RuntimeError("operator config file descriptor is invalid")
    return candidate


def load_operator_settings(
    *,
    expected_purpose: Literal["invitation", "account"],
    config_fd: int | None = None,
) -> OperatorSettings:
    """Read a bounded JSON config from an already-open protected descriptor."""

    file_descriptor = _operator_config_fd(config_fd)
    descriptor_stat = os.fstat(file_descriptor)
    if not (stat.S_ISREG(descriptor_stat.st_mode) or stat.S_ISFIFO(descriptor_stat.st_mode)):
        raise RuntimeError("operator config descriptor type is invalid")
    effective_user_id = getattr(os, "geteuid", lambda: descriptor_stat.st_uid)()
    if descriptor_stat.st_uid not in {0, effective_user_id}:
        raise RuntimeError("operator config descriptor owner is invalid")
    if stat.S_IMODE(descriptor_stat.st_mode) & 0o077:
        raise RuntimeError("operator config descriptor permissions are invalid")
    with os.fdopen(os.dup(file_descriptor), "rb") as config_stream:
        payload = config_stream.read(MAX_OPERATOR_CONFIG_BYTES + 1)
    if not payload or len(payload) > MAX_OPERATOR_CONFIG_BYTES:
        raise RuntimeError("operator config is unavailable")
    try:
        decoded = json.loads(payload.decode("utf-8"))
        settings = OperatorSettings.model_validate(decoded)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError("operator config is invalid") from exc
    if settings.purpose != expected_purpose:
        raise RuntimeError("operator config purpose is invalid")
    return settings


def require_expected_database_role(
    session: Session,
    *,
    expected_purpose: Literal["invitation", "account"],
) -> Session:
    """Fail closed unless PostgreSQL exposes the exact unprivileged operator role."""

    expected_role = expected_database_role(expected_purpose)
    try:
        role_record = session.execute(
            text(
                """
                SELECT
                    session_user,
                    current_user,
                    roles.rolsuper,
                    roles.rolinherit,
                    roles.rolcreaterole,
                    roles.rolcreatedb,
                    roles.rolcanlogin,
                    roles.rolreplication,
                    roles.rolbypassrls,
                    EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_auth_members AS memberships
                        WHERE memberships.member = roles.oid
                           OR memberships.roleid = roles.oid
                    ) AS has_role_membership
                FROM pg_catalog.pg_roles AS roles
                WHERE roles.rolname = current_user
                """
            )
        ).one()
    except Exception:
        session.close()
        raise
    (
        authenticated_role,
        actual_role,
        is_superuser,
        inherits_roles,
        can_create_roles,
        can_create_databases,
        can_login,
        can_replicate,
        bypasses_row_security,
        has_role_membership,
    ) = role_record
    if (
        authenticated_role != expected_role
        or actual_role != expected_role
        or is_superuser
        or inherits_roles
        or can_create_roles
        or can_create_databases
        or not can_login
        or can_replicate
        or bypasses_row_security
        or has_role_membership
    ):
        session.close()
        raise RuntimeError("operator database privilege boundary mismatch")
    try:
        privilege_record = session.execute(
            text(
                """
                WITH required_relations(relation_oid) AS (
                    SELECT pg_catalog.to_regclass(relation_name)
                    FROM pg_catalog.unnest(ARRAY[
                        'public.users',
                        'public.browser_sessions',
                        'public.password_resets',
                        'public.teacher_invitations',
                        'public.operator_audit_events'
                    ]) AS relation_names(relation_name)
                ),
                expected_operator_functions(function_oid, allowed_role_name) AS (
                    VALUES
                        (
                            pg_catalog.to_regprocedure(
                                'public.operator_set_account_status(character varying,boolean,character varying,character varying)'
                            ),
                            'litblog_account_operator'::TEXT
                        ),
                        (
                            pg_catalog.to_regprocedure(
                                'public.operator_create_teacher_invitation(character varying,character varying,timestamp with time zone,character varying,character varying)'
                            ),
                            'litblog_invitation_operator'::TEXT
                        ),
                        (
                            pg_catalog.to_regprocedure(
                                'public.operator_revoke_teacher_invitation(character varying,character varying,character varying)'
                            ),
                            'litblog_invitation_operator'::TEXT
                        )
                )
                SELECT
                    (SELECT pg_catalog.bool_and(relation_oid IS NOT NULL)
                     FROM required_relations) AS all_relations_present,
                    EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_class AS relations
                        JOIN pg_catalog.pg_namespace AS namespaces
                          ON namespaces.oid = relations.relnamespace
                        WHERE namespaces.nspname = 'public'
                          AND relations.relkind IN ('r', 'p', 'v', 'm', 'f')
                          AND (
                            COALESCE(pg_catalog.has_table_privilege(
                            current_user,
                            relations.oid,
                            'SELECT,INSERT,UPDATE,DELETE,TRUNCATE,REFERENCES,TRIGGER'
                            ), FALSE)
                            OR COALESCE(pg_catalog.has_any_column_privilege(
                            current_user,
                            relations.oid,
                            'SELECT,INSERT,UPDATE,REFERENCES'
                            ), FALSE)
                          )
                    ) AS has_direct_table_privilege,
                    EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_class AS sequences
                        JOIN pg_catalog.pg_namespace AS namespaces
                          ON namespaces.oid = sequences.relnamespace
                        WHERE namespaces.nspname = 'public'
                          AND sequences.relkind = 'S'
                          AND COALESCE(pg_catalog.has_sequence_privilege(
                              current_user,
                              sequences.oid,
                              'USAGE,SELECT,UPDATE'
                          ), FALSE)
                    ) AS has_direct_sequence_privilege,
                    pg_catalog.has_schema_privilege(current_user, 'public', 'CREATE'),
                    COALESCE(pg_catalog.has_function_privilege(
                        current_user,
                        pg_catalog.to_regprocedure(
                            'public.operator_set_account_status(character varying,boolean,character varying,character varying)'
                        ),
                        'EXECUTE'
                    ), FALSE),
                    COALESCE(pg_catalog.has_function_privilege(
                        current_user,
                        pg_catalog.to_regprocedure(
                            'public.operator_create_teacher_invitation(character varying,character varying,timestamp with time zone,character varying,character varying)'
                        ),
                        'EXECUTE'
                    ), FALSE),
                    COALESCE(pg_catalog.has_function_privilege(
                        current_user,
                        pg_catalog.to_regprocedure(
                            'public.operator_revoke_teacher_invitation(character varying,character varying,character varying)'
                        ),
                        'EXECUTE'
                    ), FALSE),
                    (SELECT count(*)
                     FROM pg_catalog.pg_proc AS procedures
                     JOIN pg_catalog.pg_namespace AS namespaces
                       ON namespaces.oid = procedures.pronamespace
                     WHERE namespaces.nspname = 'public'
                       AND procedures.proname IN (
                           'operator_set_account_status',
                           'operator_create_teacher_invitation',
                           'operator_revoke_teacher_invitation'
                       )) AS operator_function_count,
                    (SELECT count(*)
                     FROM pg_catalog.pg_proc AS procedures
                     JOIN pg_catalog.pg_namespace AS namespaces
                       ON namespaces.oid = procedures.pronamespace
                     WHERE namespaces.nspname = 'public'
                       AND pg_catalog.has_function_privilege(
                           current_user,
                           procedures.oid,
                           'EXECUTE'
                       )) AS executable_public_routine_count,
                    EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_proc AS procedures
                        JOIN pg_catalog.pg_namespace AS namespaces
                          ON namespaces.oid = procedures.pronamespace
                        JOIN pg_catalog.pg_roles AS owners
                          ON owners.oid = procedures.proowner
                        WHERE namespaces.nspname = 'public'
                          AND procedures.proname IN (
                              'operator_set_account_status',
                              'operator_create_teacher_invitation',
                              'operator_revoke_teacher_invitation'
                          )
                          AND owners.rolname = current_user
                    ) AS owns_operator_function,
                    EXISTS (
                        SELECT 1
                        FROM pg_catalog.pg_proc AS procedures
                        JOIN pg_catalog.pg_namespace AS namespaces
                          ON namespaces.oid = procedures.pronamespace
                        CROSS JOIN LATERAL pg_catalog.aclexplode(
                            COALESCE(
                                procedures.proacl,
                                pg_catalog.acldefault('f', procedures.proowner)
                            )
                        ) AS privileges
                        WHERE namespaces.nspname = 'public'
                          AND privileges.grantee = 0
                          AND privileges.privilege_type = 'EXECUTE'
                    ) AS public_can_execute,
                    COALESCE((
                        SELECT pg_catalog.bool_and(
                            procedures.prosecdef
                            AND owners.rolname = 'litblog_identity_owner'
                            AND procedures.proconfig = ARRAY[
                                'search_path=pg_catalog, pg_temp'
                            ]::TEXT[]
                        )
                        FROM pg_catalog.pg_proc AS procedures
                        JOIN pg_catalog.pg_namespace AS namespaces
                          ON namespaces.oid = procedures.pronamespace
                        JOIN pg_catalog.pg_roles AS owners
                          ON owners.oid = procedures.proowner
                        WHERE namespaces.nspname = 'public'
                          AND procedures.proname IN (
                              'operator_set_account_status',
                              'operator_create_teacher_invitation',
                              'operator_revoke_teacher_invitation'
                          )
                    ), FALSE) AS all_operator_functions_secured,
                    COALESCE((
                        SELECT
                            NOT owners.rolcanlogin
                            AND NOT owners.rolsuper
                            AND NOT owners.rolinherit
                            AND NOT owners.rolcreaterole
                            AND NOT owners.rolcreatedb
                            AND NOT owners.rolreplication
                            AND NOT owners.rolbypassrls
                            AND NOT EXISTS (
                                SELECT 1
                                FROM pg_catalog.pg_auth_members AS memberships
                                WHERE memberships.member = owners.oid
                                   OR memberships.roleid = owners.oid
                            )
                        FROM pg_catalog.pg_roles AS owners
                        WHERE owners.rolname = 'litblog_identity_owner'
                    ), FALSE) AS identity_owner_is_secured,
                    COALESCE(pg_catalog.has_schema_privilege(
                        'litblog_identity_owner',
                        'public',
                        'CREATE'
                    ), FALSE) AS identity_owner_can_create,
                    COALESCE((
                        SELECT pg_catalog.bool_and(
                            expected.function_oid IS NOT NULL
                            AND EXISTS (
                                SELECT 1
                                FROM pg_catalog.aclexplode(
                                    COALESCE(
                                        procedures.proacl,
                                        pg_catalog.acldefault(
                                            'f',
                                            procedures.proowner
                                        )
                                    )
                                ) AS owner_privileges
                                WHERE owner_privileges.privilege_type = 'EXECUTE'
                                  AND owner_privileges.grantee = procedures.proowner
                            )
                            AND EXISTS (
                                SELECT 1
                                FROM pg_catalog.aclexplode(
                                    COALESCE(
                                        procedures.proacl,
                                        pg_catalog.acldefault(
                                            'f',
                                            procedures.proowner
                                        )
                                    )
                                ) AS purpose_privileges
                                JOIN pg_catalog.pg_roles AS purpose_roles
                                  ON purpose_roles.oid = purpose_privileges.grantee
                                WHERE purpose_privileges.privilege_type = 'EXECUTE'
                                  AND purpose_roles.rolname = expected.allowed_role_name
                                  AND NOT purpose_privileges.is_grantable
                            )
                            AND NOT EXISTS (
                                SELECT 1
                                FROM pg_catalog.aclexplode(
                                    COALESCE(
                                        procedures.proacl,
                                        pg_catalog.acldefault(
                                            'f',
                                            procedures.proowner
                                        )
                                    )
                                ) AS unexpected_privileges
                                LEFT JOIN pg_catalog.pg_roles AS unexpected_roles
                                  ON unexpected_roles.oid = unexpected_privileges.grantee
                                WHERE unexpected_privileges.privilege_type = 'EXECUTE'
                                  AND unexpected_privileges.grantee
                                      <> procedures.proowner
                                  AND (
                                      unexpected_roles.rolname
                                          IS DISTINCT FROM expected.allowed_role_name
                                      OR unexpected_privileges.is_grantable
                                  )
                            )
                        )
                        FROM expected_operator_functions AS expected
                        LEFT JOIN pg_catalog.pg_proc AS procedures
                          ON procedures.oid = expected.function_oid
                    ), FALSE) AS operator_function_acl_is_exact
                """
            )
        ).one()
    except Exception:
        session.close()
        raise
    (
        all_relations_present,
        has_direct_table_privilege,
        has_direct_sequence_privilege,
        can_create_in_public,
        can_execute_account_status,
        can_execute_invitation_create,
        can_execute_invitation_revoke,
        operator_function_count,
        executable_public_routine_count,
        owns_operator_function,
        public_can_execute,
        all_operator_functions_secured,
        identity_owner_is_secured,
        identity_owner_can_create,
        operator_function_acl_is_exact,
    ) = privilege_record
    expected_execute_boundary = {
        "account": (True, False, False),
        "invitation": (False, True, True),
    }[expected_purpose]
    expected_routine_count = 1 if expected_purpose == "account" else 2
    if (
        not all_relations_present
        or has_direct_table_privilege
        or has_direct_sequence_privilege
        or can_create_in_public
        or (
            can_execute_account_status,
            can_execute_invitation_create,
            can_execute_invitation_revoke,
        )
        != expected_execute_boundary
        or operator_function_count != 3
        or executable_public_routine_count != expected_routine_count
        or owns_operator_function
        or public_can_execute
        or not all_operator_functions_secured
        or not identity_owner_is_secured
        or identity_owner_can_create
        or not operator_function_acl_is_exact
    ):
        session.close()
        raise RuntimeError("operator database privilege boundary mismatch")
    return session


def _validate_root_certificate_custody() -> None:
    if OPERATOR_RUNTIME_PLATFORM != "posix":
        raise RuntimeError("operator runtime requires the reviewed POSIX host")
    if os.path.realpath(OPERATOR_ROOT_CERTIFICATE_PATH) != OPERATOR_ROOT_CERTIFICATE_PATH:
        raise RuntimeError("operator database root certificate path is not canonical")
    current_path = OPERATOR_ROOT_CERTIFICATE_PATH
    is_certificate = True
    while True:
        path_stat = os.lstat(current_path)
        expected_type = stat.S_ISREG if is_certificate else stat.S_ISDIR
        if (
            not expected_type(path_stat.st_mode)
            or path_stat.st_uid != 0
            or stat.S_IMODE(path_stat.st_mode) & 0o022
        ):
            raise RuntimeError("operator database root certificate custody is invalid")
        if current_path == "/":
            break
        current_path = os.path.dirname(current_path)
        is_certificate = False


@dataclass
class OperatorRuntime:
    settings: OperatorSettings
    session_factory: Callable[[], Session]
    engine: Engine

    def close(self) -> None:
        self.engine.dispose()


def build_operator_runtime(
    *,
    expected_purpose: Literal["invitation", "account"],
    config_fd: int | None = None,
    engine_factory: Callable[..., Engine] = create_engine,
    sessionmaker_factory: Callable[..., Callable[[], Session]] = sessionmaker,
) -> OperatorRuntime:
    settings = load_operator_settings(
        expected_purpose=expected_purpose,
        config_fd=config_fd,
    )
    _validate_root_certificate_custody()
    engine = engine_factory(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 5,
            "options": (
                "-c search_path=pg_catalog "
                "-c statement_timeout=30000 "
                "-c lock_timeout=5000 "
                "-c idle_in_transaction_session_timeout=30000"
            ),
        },
    )
    unchecked_session_factory = sessionmaker_factory(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def checked_session_factory() -> Session:
        session = unchecked_session_factory()
        return require_expected_database_role(
            session,
            expected_purpose=expected_purpose,
        )

    return OperatorRuntime(
        settings=settings,
        session_factory=checked_session_factory,
        engine=engine,
    )


__all__ = [
    "OperatorRuntime",
    "OperatorSettings",
    "build_operator_runtime",
    "expected_database_role",
    "load_operator_settings",
    "require_expected_database_role",
]

# database.py
import re

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from base import Base
from config import get_settings

settings = get_settings()
DATABASE_URL = settings.database_url
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is required")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

UPLOAD_ASSET_COLUMN_SHAPE = {
    "id": ("BIGINT", False),
    "storage_key": ("VARCHAR(255)", False),
    "owner_user_id": ("INTEGER", True),
    "blog_id": ("INTEGER", True),
    "purpose": ("VARCHAR(20)", False),
    "state": ("VARCHAR(20)", False),
    "original_filename": ("VARCHAR(255)", True),
    "media_type": ("VARCHAR(127)", False),
    "size_bytes": ("BIGINT", False),
    "sha256_digest": ("CHAR(64)", False),
    "created_at": ("TIMESTAMP WITH TIME ZONE", False),
    "expires_at": ("TIMESTAMP WITH TIME ZONE", True),
    "bound_at": ("TIMESTAMP WITH TIME ZONE", True),
    "delete_after": ("TIMESTAMP WITH TIME ZONE", True),
    "deleted_at": ("TIMESTAMP WITH TIME ZONE", True),
    "scan_completed_at": ("TIMESTAMP WITH TIME ZONE", True),
}
UPLOAD_ASSET_INDEX_SHAPE = {
    "ix_upload_assets_owner_state_created": (
        ("owner_user_id", "state", "created_at"),
        False,
    ),
    "ix_upload_assets_blog_id": (("blog_id",), False),
    "ix_upload_assets_expires_at": (("expires_at",), False),
    "ix_upload_assets_state_delete_after": (("state", "delete_after"), False),
    "uq_upload_assets_active_profile_purpose": (
        ("owner_user_id", "purpose"),
        True,
    ),
}
UPLOAD_ASSET_CHECK_NAMES = frozenset(
    {
        "ck_upload_assets_purpose",
        "ck_upload_assets_state",
        "ck_upload_assets_positive_size",
        "ck_upload_assets_sha256_length",
        "ck_upload_assets_sha256_lower_hex",
        "ck_upload_assets_storage_key_prefix",
        "ck_upload_assets_storage_key_format",
        "ck_upload_assets_state_shape",
    }
)


def _schema_not_ready() -> None:
    raise RuntimeError("Database schema is not ready")


def _normalized_sql(sqltext) -> str:
    value = str(sqltext or "").lower().replace('"', "")
    value = re.sub(
        r"::\s*(?:character varying|timestamp with time zone|text|bigint|integer)"
        r"(?:\[\])?",
        "",
        value,
    )
    value = value.replace("upload_assets.", "")
    return " ".join(value.split())


def _flat_sql(sqltext) -> str:
    return re.sub(r"[\s()\[\]]+", "", _normalized_sql(sqltext))


def _strip_enclosing_parentheses(value: str) -> str:
    value = value.strip()
    while value.startswith("(") and value.endswith(")"):
        depth = 0
        in_quote = False
        encloses_all = True
        index = 0
        while index < len(value):
            character = value[index]
            if character == "'":
                if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                in_quote = not in_quote
            elif not in_quote:
                if character == "(":
                    depth += 1
                elif character == ")":
                    depth -= 1
                    if depth == 0 and index != len(value) - 1:
                        encloses_all = False
                        break
            index += 1
        if not encloses_all or depth != 0 or in_quote:
            break
        value = value[1:-1].strip()
    return value


def _split_top_level_boolean(value: str, operator: str) -> list[str]:
    parts = []
    start = 0
    depth = 0
    in_quote = False
    index = 0
    while index < len(value):
        character = value[index]
        if character == "'":
            if in_quote and index + 1 < len(value) and value[index + 1] == "'":
                index += 2
                continue
            in_quote = not in_quote
            index += 1
            continue
        if not in_quote:
            if character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
            elif depth == 0 and value.startswith(operator, index):
                before = value[index - 1] if index else " "
                after_index = index + len(operator)
                after = value[after_index] if after_index < len(value) else " "
                if not (before.isalnum() or before == "_") and not (
                    after.isalnum() or after == "_"
                ):
                    parts.append(value[start:index].strip())
                    start = after_index
                    index = after_index
                    continue
        index += 1
    if not parts:
        return [value]
    parts.append(value[start:].strip())
    return parts


def _boolean_sql_ast(sqltext):
    def parse(value: str):
        value = _strip_enclosing_parentheses(value)
        for operator in ("or", "and"):
            parts = _split_top_level_boolean(value, operator)
            if len(parts) > 1:
                children = []
                for part in parts:
                    child = parse(part)
                    if child[0] == operator:
                        children.extend(child[1])
                    else:
                        children.append(child)
                return operator, tuple(children)
        atom = _flat_sql(value).replace("=anyarray", "in")
        return "atom", atom

    return parse(_normalized_sql(sqltext))


_APPROVED_CHECK_SQL = {
    "ck_upload_assets_purpose": (
        "purpose IN ('POST', 'PROFILE_IMAGE', 'COVER_IMAGE')"
    ),
    "ck_upload_assets_state": (
        "state IN ('PENDING', 'ACTIVE', 'DELETE_PENDING', 'DELETED')"
    ),
    "ck_upload_assets_positive_size": "size_bytes > 0",
    "ck_upload_assets_sha256_length": "length(sha256_digest) = 64",
    "ck_upload_assets_sha256_lower_hex": (
        "sha256_digest ~ '^[0-9a-f]{64}$'"
    ),
    "ck_upload_assets_storage_key_prefix": (
        "substr(storage_key, 1, 8) = 'objects/' "
        "AND substr(storage_key, 9, 2) = substr(storage_key, 12, 2)"
    ),
    "ck_upload_assets_storage_key_format": (
        "storage_key ~ '^objects/[0-9a-f]{2}/[0-9a-f]{32}\\.[a-z0-9]{1,10}$'"
    ),
    "ck_upload_assets_state_shape": (
        "(state = 'PENDING' AND purpose = 'POST' "
        "AND owner_user_id IS NOT NULL AND blog_id IS NULL "
        "AND expires_at IS NOT NULL AND bound_at IS NULL "
        "AND delete_after IS NULL AND deleted_at IS NULL "
        "AND scan_completed_at IS NOT NULL) OR "
        "(state = 'ACTIVE' AND owner_user_id IS NOT NULL "
        "AND expires_at IS NULL AND bound_at IS NOT NULL "
        "AND delete_after IS NULL AND deleted_at IS NULL "
        "AND scan_completed_at IS NOT NULL AND "
        "((purpose = 'POST' AND blog_id IS NOT NULL) OR "
        "(purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE') AND blog_id IS NULL))) OR "
        "(state = 'DELETE_PENDING' AND delete_after IS NOT NULL "
        "AND blog_id IS NULL AND expires_at IS NULL "
        "AND deleted_at IS NULL AND scan_completed_at IS NOT NULL) OR "
        "(state = 'DELETED' AND blog_id IS NULL AND expires_at IS NULL "
        "AND delete_after IS NULL AND deleted_at IS NOT NULL "
        "AND original_filename IS NULL AND scan_completed_at IS NOT NULL)"
    ),
}


def _approved_check_variants(name: str) -> set[str]:
    flat = _flat_sql(_APPROVED_CHECK_SQL[name])
    variants = {flat}
    variants.add(
        flat.replace(
            "purposein'profile_image','cover_image'",
            "purpose=anyarray'profile_image','cover_image'",
        ).replace(
            "purposein'post','profile_image','cover_image'",
            "purpose=anyarray'post','profile_image','cover_image'",
        ).replace(
            "statein'pending','active','delete_pending','deleted'",
            "state=anyarray'pending','active','delete_pending','deleted'",
        )
    )
    if name == "ck_upload_assets_storage_key_prefix":
        variants.add(
            _flat_sql(
                "substring(storage_key FROM 1 FOR 8) = 'objects/' "
                "AND substring(storage_key FROM 9 FOR 2) "
                "= substring(storage_key FROM 12 FOR 2)"
            )
        )
    return variants


def _check_has_expected_semantics(name: str, sqltext) -> bool:
    if _flat_sql(sqltext) not in _approved_check_variants(name):
        return False
    if name == "ck_upload_assets_state_shape":
        return _boolean_sql_ast(sqltext) == _boolean_sql_ast(
            _APPROVED_CHECK_SQL[name]
        )
    return True


def _profile_index_predicate_is_exact(sqltext) -> bool:
    flat = _flat_sql(sqltext)
    return flat in {
        _flat_sql(
            "state = 'ACTIVE' AND purpose IN ('PROFILE_IMAGE', 'COVER_IMAGE')"
        ),
        _flat_sql(
            "state = 'ACTIVE' "
            "AND purpose = ANY (ARRAY['PROFILE_IMAGE', 'COVER_IMAGE'])"
        ),
    }


def verify_database_schema():
    """Fail closed when the externally migrated production schema is absent."""

    if engine.dialect.name != "postgresql":
        _schema_not_ready()
    schema = inspect(engine)
    if not schema.has_table("upload_assets"):
        _schema_not_ready()
    columns = {
        column.get("name"): column for column in schema.get_columns("upload_assets")
    }
    if set(columns) != set(UPLOAD_ASSET_COLUMN_SHAPE):
        _schema_not_ready()
    for name, (expected_type, expected_nullable) in UPLOAD_ASSET_COLUMN_SHAPE.items():
        column = columns[name]
        try:
            reflected_type = column["type"].compile(dialect=engine.dialect).upper()
        except (AttributeError, KeyError):
            _schema_not_ready()
        if reflected_type != expected_type or column.get("nullable") is not expected_nullable:
            _schema_not_ready()
    id_column = columns["id"]
    id_default = _normalized_sql(id_column.get("default"))
    if not (
        id_column.get("identity")
        or ("nextval" in id_default and "upload_assets_id_seq" in id_default)
    ):
        _schema_not_ready()
    if _flat_sql(columns["created_at"].get("default")) not in {
        "current_timestamp",
        "now",
    }:
        _schema_not_ready()
    primary_key = schema.get_pk_constraint("upload_assets")
    if tuple(primary_key.get("constrained_columns") or ()) != ("id",):
        _schema_not_ready()
    checks = {
        constraint.get("name"): constraint
        for constraint in schema.get_check_constraints("upload_assets")
    }
    if not UPLOAD_ASSET_CHECK_NAMES.issubset(checks):
        _schema_not_ready()
    if any(
        not _check_has_expected_semantics(name, checks[name].get("sqltext"))
        for name in UPLOAD_ASSET_CHECK_NAMES
    ):
        _schema_not_ready()
    indexes = {
        index.get("name"): index for index in schema.get_indexes("upload_assets")
    }
    if not set(UPLOAD_ASSET_INDEX_SHAPE).issubset(indexes):
        _schema_not_ready()
    for name, (expected_columns, expected_unique) in UPLOAD_ASSET_INDEX_SHAPE.items():
        index = indexes[name]
        if (
            tuple(index.get("column_names") or ()) != expected_columns
            or bool(index.get("unique")) is not expected_unique
        ):
            _schema_not_ready()
    profile_index = indexes["uq_upload_assets_active_profile_purpose"]
    predicate = (profile_index.get("dialect_options") or {}).get(
        "postgresql_where",
        "",
    )
    if not _profile_index_predicate_is_exact(predicate):
        _schema_not_ready()
    unique_columns = {
        tuple(constraint.get("column_names") or ())
        for constraint in schema.get_unique_constraints("upload_assets")
    }
    if unique_columns != {("storage_key",)}:
        _schema_not_ready()
    foreign_keys = {
        tuple(key.get("constrained_columns") or ()): key
        for key in schema.get_foreign_keys("upload_assets")
    }
    expected_foreign_keys = {
        ("owner_user_id",): ("fk_upload_assets_owner_user", "users"),
        ("blog_id",): ("fk_upload_assets_blog", "blogs"),
    }
    if set(foreign_keys) != set(expected_foreign_keys):
        _schema_not_ready()
    for columns, (expected_name, expected_table) in expected_foreign_keys.items():
        key = foreign_keys[columns]
        if (
            key.get("name") != expected_name
            or key.get("referred_schema") not in (None, "public")
            or key.get("referred_table") != expected_table
            or tuple(key.get("referred_columns") or ()) != ("id",)
            or str((key.get("options") or {}).get("ondelete", "")).upper()
            != "SET NULL"
        ):
            _schema_not_ready()


def initialize_database(*, allow_schema_create: bool):
    if allow_schema_create:
        Base.metadata.create_all(bind=engine)
        return
    verify_database_schema()

def reset_database():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

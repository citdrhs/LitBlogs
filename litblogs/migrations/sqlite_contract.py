"""Immutable SQLite reflection helpers for fail-closed migration adoption."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from sqlalchemy.engine.reflection import Inspector

ColumnContract = tuple[str, bool, str | None, bool]
IndexContract = tuple[tuple[str, ...], bool, str | None]
ForeignKeyContract = tuple[str | None, tuple[str, ...], str, tuple[str, ...], str | None]


def _normalize_expression(value: object) -> str | None:
    if value is None:
        return None
    return " ".join(str(value).strip().lower().split())


def _normalize_default(value: object) -> str | None:
    normalized = _normalize_expression(value)
    if normalized is None:
        return None
    while normalized.startswith("(") and normalized.endswith(")"):
        normalized = normalized[1:-1].strip()
    if (
        len(normalized) >= 2
        and normalized[0] in {"'", '"'}
        and normalized[-1] == normalized[0]
    ):
        normalized = normalized[1:-1]
    return normalized


def table_contract_matches(
    inspector: Inspector,
    table_name: str,
    *,
    columns: Mapping[str, ColumnContract],
    indexes: Mapping[str, IndexContract] | None = None,
    unique_constraints: Sequence[tuple[str | None, tuple[str, ...]]] | None = None,
    check_constraints: Mapping[str, str] | None = None,
    foreign_keys: Sequence[ForeignKeyContract] | None = None,
    exact_columns: bool = False,
    exact_indexes: bool = False,
    exact_unique_constraints: bool = False,
    exact_check_constraints: bool = False,
    exact_foreign_keys: bool = False,
) -> bool:
    if table_name not in inspector.get_table_names():
        return False

    reflected_columns = inspector.get_columns(table_name)
    reflected_by_name = {column["name"]: column for column in reflected_columns}
    if exact_columns and set(reflected_by_name) != set(columns):
        return False
    for name, (type_name, nullable, default, primary_key) in columns.items():
        column = reflected_by_name.get(name)
        if column is None:
            return False
        if (
            str(column["type"]).upper() != type_name.upper()
            or bool(column["nullable"]) is not nullable
            or _normalize_default(column.get("default")) != _normalize_default(default)
            or bool(column.get("primary_key")) is not primary_key
        ):
            return False

    if indexes is not None:
        reflected_indexes = {
            index["name"]: (
                tuple(index["column_names"]),
                bool(index["unique"]),
                _normalize_expression(
                    index.get("dialect_options", {}).get("sqlite_where")
                ),
            )
            for index in inspector.get_indexes(table_name)
        }
        expected_indexes = {
            name: (column_names, unique, _normalize_expression(where))
            for name, (column_names, unique, where) in indexes.items()
        }
        if exact_indexes:
            if reflected_indexes != expected_indexes:
                return False
        elif any(
            reflected_indexes.get(name) != contract
            for name, contract in expected_indexes.items()
        ):
            return False

    if unique_constraints is not None:
        reflected_uniques = {
            (constraint["name"], tuple(constraint["column_names"]))
            for constraint in inspector.get_unique_constraints(table_name)
        }
        expected_uniques = set(unique_constraints)
        if exact_unique_constraints:
            if reflected_uniques != expected_uniques:
                return False
        elif not expected_uniques <= reflected_uniques:
            return False

    if check_constraints is not None:
        reflected_checks = {
            constraint["name"]: _normalize_expression(constraint["sqltext"])
            for constraint in inspector.get_check_constraints(table_name)
        }
        expected_checks = {
            name: _normalize_expression(expression)
            for name, expression in check_constraints.items()
        }
        if exact_check_constraints:
            if reflected_checks != expected_checks:
                return False
        elif any(
            reflected_checks.get(name) != expression
            for name, expression in expected_checks.items()
        ):
            return False

    if foreign_keys is not None:
        reflected_foreign_keys = {
            (
                foreign_key["name"],
                tuple(foreign_key["constrained_columns"]),
                foreign_key["referred_table"],
                tuple(foreign_key["referred_columns"]),
                foreign_key.get("options", {}).get("ondelete"),
            )
            for foreign_key in inspector.get_foreign_keys(table_name)
        }
        expected_foreign_keys = set(foreign_keys)
        if exact_foreign_keys:
            if reflected_foreign_keys != expected_foreign_keys:
                return False
        elif not expected_foreign_keys <= reflected_foreign_keys:
            return False

    return True


def has_any_named_schema_object(
    inspector: Inspector,
    table_name: str,
    *,
    columns: Sequence[str] = (),
    indexes: Sequence[str] = (),
    unique_constraints: Sequence[str] = (),
    check_constraints: Sequence[str] = (),
) -> bool:
    if table_name not in inspector.get_table_names():
        return False
    return bool(
        set(columns) & {column["name"] for column in inspector.get_columns(table_name)}
        or set(indexes) & {index["name"] for index in inspector.get_indexes(table_name)}
        or set(unique_constraints)
        & {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(table_name)
        }
        or set(check_constraints)
        & {
            constraint["name"]
            for constraint in inspector.get_check_constraints(table_name)
        }
    )

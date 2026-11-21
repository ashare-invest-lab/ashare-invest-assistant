"""T-T106 I2 隔离契约的离线元数据与迁移源码检查。"""

from __future__ import annotations

import ast
import re
import socket
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from app.db.tables.market import (
    minute5_bars,
    minute_bars,
    quotes_snapshot,
    realtime_quotes,
)
from sqlalchemy import CheckConstraint, Table

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "src/backend/migrations/versions"
TABLES = (quotes_snapshot, realtime_quotes, minute_bars, minute5_bars)
HYPERTABLES = {realtime_quotes.name, minute_bars.name, minute5_bars.name}
MINUTE_TABLES = {minute_bars.name, minute5_bars.name}
OFFLINE_SOURCES = {
    "tdx_local",
    "pro_latest",
    "pro_history",
    "ssjy_more",
    "ssjy_all",
    "real_all",
}
LICENSED_SOURCES = {"mairui"}
EXPECTED_SOURCE_CHECKS = {
    "quotes_snapshot": LICENSED_SOURCES,
    "realtime_quotes": {"ssjy_more", "ssjy_all", "real_all"},
    "minute_bars": {"pro_latest", "pro_history", "mairui", "tdx_local"},
    "minute5_bars": {"pro_latest", "pro_history", "mairui", "tdx_local"},
}
I2_SENTINEL = "T-B196-I2-ISOLATION"
ZERO_DEFAULT = re.compile(r"(?:^|[^0-9.])0(?:\.0+)?(?:$|[^0-9.])")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        pytest.fail("I2 离线检查不得访问网络")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _unique_objects(table: Table) -> list[Any]:
    objects: list[Any] = [table.primary_key, *table.constraints, *table.indexes]
    return [
        obj
        for obj in objects
        if getattr(obj, "columns", None) is not None
        and (getattr(obj, "primary_key", False) or getattr(obj, "unique", False))
    ]


def _columns(obj: Any) -> tuple[str, ...]:
    return tuple(column.name for column in obj.columns)


def _predicate(obj: Any) -> str:
    dialect_options = getattr(obj, "dialect_options", {})
    postgres = dialect_options.get("postgresql", {})
    where = postgres.get("where")
    if where is None:
        where = getattr(obj, "dialect_kwargs", {}).get("postgresql_where")
    if where is None:
        return ""
    return re.sub(r"\s+", " ", str(where).replace('"', "").lower()).strip()


def _is_unpredicated_code_ts(obj: Any) -> bool:
    return frozenset(_columns(obj)) == frozenset({"code", "ts"}) and not _predicate(obj)


def _source_values(predicate: str) -> set[str]:
    match = re.search(r"\bsource\b\s+in\s*\(([^)]*)\)", predicate)
    if match is None:
        return set()
    return set(re.findall(r"'([^']+)'", match.group(1)))


def _has_predicate(obj: Any, required: Iterable[str], source_values: set[str] | None = None) -> bool:
    predicate = _predicate(obj)
    if not predicate or any(fragment not in predicate for fragment in required):
        return False
    return source_values is None or _source_values(predicate) == source_values


def _find_unique(
    table: Table,
    columns: Iterable[str],
    required_predicate: Iterable[str],
    source_values: set[str] | None = None,
) -> Any | None:
    expected = frozenset(columns)
    for obj in _unique_objects(table):
        if frozenset(_columns(obj)) != expected:
            continue
        if _has_predicate(obj, required_predicate, source_values):
            return obj
    return None


def _has_unpredicated_code_ts(table: Table) -> bool:
    return any(_is_unpredicated_code_ts(obj) for obj in _unique_objects(table))



def _source_check(table: Table) -> CheckConstraint | None:
    expected = f"ck_{table.name}_source"
    named = [
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint) and constraint.name == expected
    ]
    return named[0] if named else None


def _check_source_in_values(table: Table) -> set[str] | None:
    constraint = _source_check(table)
    if constraint is None:
        return None
    predicate = re.sub(r"\s+", " ", str(constraint.sqltext).replace('"', "").lower()).strip()
    values = _source_values(predicate)
    return values or None


def _primary_key_shape(table: Table) -> tuple[str, ...]:
    return _columns(table.primary_key)


def i2_schema_ready(table: Table) -> bool:
    """按 I2 §1.1、§2.1、§2.2 逐表检查目标 schema。"""
    required = {"code", "ts", "source", "source_licence_id", "row_id", "revision", "content_fingerprint"}
    if table.name in MINUTE_TABLES:
        required.add("is_final")
    if not required <= set(table.c.keys()):
        return False
    if (
        not table.c.source.nullable
        or not table.c.source_licence_id.nullable
        or not table.c.content_fingerprint.nullable
    ):
        return False
    if table.name in MINUTE_TABLES and not table.c.is_final.nullable:
        return False

    expected_primary_key = ("ts", "row_id") if table.name in HYPERTABLES else ("row_id",)
    if _primary_key_shape(table) != expected_primary_key or _has_unpredicated_code_ts(table):
        return False

    licence_key = ("code", "ts", "source", "source_licence_id", "revision")
    offline_key = ("code", "ts", "source", "revision")
    legacy_key = ("code", "ts")
    fingerprint_key = ("code", "ts", "source", "source_licence_id", "content_fingerprint")
    if _find_unique(table, licence_key, ("source_licence_id is not null",), LICENSED_SOURCES) is None:
        return False
    if _find_unique(
        table,
        offline_key,
        ("source_licence_id is null",),
        OFFLINE_SOURCES,
    ) is None:
        return False
    if _find_unique(
        table,
        legacy_key,
        ("source is null", "source_licence_id is null"),
    ) is None:
        return False
    if _find_unique(
        table,
        fingerprint_key,
        ("source_licence_id is not null",),
        LICENSED_SOURCES,
    ) is None:
        return False
    if _find_unique(
        table,
        fingerprint_key,
        ("source_licence_id is null",),
        OFFLINE_SOURCES,
    ) is None:
        return False
    return _check_source_in_values(table) == EXPECTED_SOURCE_CHECKS[table.name]


READY = {table.name: i2_schema_ready(table) for table in TABLES}


def _schema_param(table: Table) -> Any:
    return pytest.param(
        table,
        id=table.name,
        marks=pytest.mark.xfail(
            not READY[table.name],
            reason=f"{table.name} 尚未实现 T-B196 I2 归属键 schema",
            strict=True,
        ),
    )


def _licence_nullable(table: Table) -> bool:
    column = table.c.get("source_licence_id")
    return column is not None and column.nullable is True


def _migration_is_i2(path: Path) -> bool:
    return I2_SENTINEL in path.read_text(encoding="utf-8")


def i2_migration_found() -> Path | None:
    matches = [path for path in sorted(MIGRATIONS.glob("*.py")) if _migration_is_i2(path)]
    if len(matches) > 1:
        raise AssertionError(f"I2 sentinel appears in multiple migrations: {matches}")
    return matches[0] if matches else None


I2_MIGRATION = i2_migration_found()


def _migration_schema_param(table: Table) -> Any:
    return pytest.param(
        table,
        id=table.name,
        marks=pytest.mark.xfail(
            not READY[table.name] or I2_MIGRATION is None,
            reason=f"{table.name} 尚未具备 I2 schema 或 T-B196 sentinel 迁移",
            strict=True,
        ),
    )


def _revision_values(source: str) -> list[str]:
    tree = ast.parse(source)
    values: list[str] = []
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == "revision" for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.append(value.value)
    return values


def test_migration_directory_and_revisions_are_readable() -> None:
    assert MIGRATIONS.is_dir(), f"迁移目录不存在或不可读：{MIGRATIONS}"
    paths = sorted(MIGRATIONS.glob("*.py"))
    assert paths, f"迁移目录没有 Python 文件：{MIGRATIONS}"

    revisions: list[str] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        found = _revision_values(source)
        assert len(found) == 1, f"{path} 必须包含唯一可读的 revision = \"...\""
        assert found[0], f"{path} 的 revision 不得为空"
        revisions.append(found[0])
    assert len(revisions) == len(set(revisions)), "迁移 revision 必须全局唯一"


@pytest.mark.parametrize("table", [_schema_param(table) for table in TABLES])
def test_two_licences_same_minute_have_distinct_unique_keys(table: Table) -> None:
    licence_key = ("code", "ts", "source", "source_licence_id", "revision")
    index = _find_unique(table, licence_key, ("source_licence_id is not null",), LICENSED_SOURCES)
    assert index is not None
    assert "source_licence_id" in _columns(index)
    assert "source" in _columns(index)

    first_row = {
        "code": "SYN001.SH",
        "ts": "2026-11-02T10:31:00+08:00",
        "source": "mairui",
        "source_licence_id": "00000000-0000-4000-8000-000000000001",
        "revision": 0,
    }
    second_row = {**first_row, "source_licence_id": "00000000-0000-4000-8000-000000000002"}
    first_key = tuple(first_row[column] for column in _columns(index))
    second_key = tuple(second_row[column] for column in _columns(index))
    assert first_key != second_key
    assert first_row["source_licence_id"] != first_row["source"]


@pytest.mark.parametrize("table", [_schema_param(table) for table in TABLES])
def test_legacy_and_tdx_local_use_separate_partial_keys(table: Table) -> None:
    assert _licence_nullable(table)
    legacy = _find_unique(
        table,
        ("code", "ts"),
        ("source is null", "source_licence_id is null"),
    )
    offline = _find_unique(
        table,
        ("code", "ts", "source", "revision"),
        ("source_licence_id is null",),
        OFFLINE_SOURCES,
    )
    assert legacy is not None
    assert offline is not None
    assert legacy is not offline
    assert not _has_unpredicated_code_ts(table)
    assert "source_licence_id" not in _columns(offline)


@pytest.mark.parametrize("table", [_schema_param(table) for table in TABLES])
def test_i2_primary_key_shape_and_no_unpredicated_code_ts(table: Table) -> None:
    expected = ("ts", "row_id") if table.name in HYPERTABLES else ("row_id",)
    assert _primary_key_shape(table) == expected
    assert not _has_unpredicated_code_ts(table)


@pytest.mark.parametrize("table", [_schema_param(table) for table in TABLES])
def test_i2_content_fingerprint_partial_keys(table: Table) -> None:
    assert table.c.content_fingerprint is not None
    fingerprint_key = ("code", "ts", "source", "source_licence_id", "content_fingerprint")
    licence_fingerprint = _find_unique(
        table,
        fingerprint_key,
        ("source_licence_id is not null",),
        LICENSED_SOURCES,
    )
    offline_fingerprint = _find_unique(
        table,
        fingerprint_key,
        ("source_licence_id is null",),
        OFFLINE_SOURCES,
    )
    assert licence_fingerprint is not None
    assert offline_fingerprint is not None
    assert "content_fingerprint" in _columns(licence_fingerprint)
    assert "content_fingerprint" in _columns(offline_fingerprint)


@pytest.mark.parametrize("table", [_migration_schema_param(table) for table in TABLES])
def test_legacy_rows_are_not_backfilled_with_licence(table: Table) -> None:
    assert I2_MIGRATION is not None
    assert _licence_nullable(table)
    source = I2_MIGRATION.read_text(encoding="utf-8")
    assert not re.search(
        r"(?:source_licence_id|source)\b.{0,120}[0-9a-f]{8}-[0-9a-f-]{27,}|"
        r"[0-9a-f]{8}-[0-9a-f-]{27,}.{0,120}(?:source_licence_id|source)\b",
        source,
        re.IGNORECASE | re.DOTALL,
    )
    assert "null" in source.lower() or "nullable=true" in source.lower()


@pytest.mark.xfail(
    I2_MIGRATION is None,
    reason="T-B196 未实现：尚无带 T-B196-I2-ISOLATION sentinel 的迁移，无法验证回滚保护",
    strict=True,
)
def test_i2_downgrade_refuses_new_ownership_rows() -> None:
    assert I2_MIGRATION is not None
    tree = ast.parse(I2_MIGRATION.read_text(encoding="utf-8"))
    downgrade = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "downgrade"
    )
    function_source = ast.unparse(downgrade).lower()
    assert all(table.name in function_source for table in TABLES)
    assert "revision" in function_source
    assert "is_final" in function_source
    query_terms = ("select", "exists", "count")
    refusal_words = ("refus", "reject", "拒绝", "丢", "data loss")
    guard_pattern = re.compile(
        r"(?:revision\s*(?:>|>=|<>|is\s+not)|is_final\s+(?:is\s+not|is\s+distinct)|"
        r"is_final\s*[=<>])"
    )

    def is_conditional_refusal(node: ast.If) -> bool:
        source = ast.unparse(node).lower()
        if not any(term in source for term in query_terms) or not guard_pattern.search(source):
            return False
        for child in ast.walk(node):
            if not isinstance(child, ast.Raise) or not isinstance(child.exc, ast.Call):
                continue
            if not isinstance(child.exc.func, ast.Name) or child.exc.func.id not in {"RuntimeError", "ValueError"}:
                continue
            if any(word in ast.unparse(child).lower() for word in refusal_words):
                return True
        return False

    def is_refusal_raise(node: ast.AST) -> bool:
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            return False
        if not isinstance(node.exc.func, ast.Name) or node.exc.func.id not in {"RuntimeError", "ValueError"}:
            return False
        return any(word in ast.unparse(node).lower() for word in refusal_words)

    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(downgrade):
        parents.update({child: parent for child in ast.iter_child_nodes(parent)})

    def is_under_if(node: ast.AST) -> bool:
        parent = parents.get(node)
        while parent is not None:
            if isinstance(parent, ast.If):
                return True
            parent = parents.get(parent)
        return False

    assert not any(is_refusal_raise(node) and not is_under_if(node) for node in ast.walk(downgrade)), (
        "downgrade 的拒绝必须位于数据检查条件内"
    )
    assert any(is_conditional_refusal(node) for node in ast.walk(downgrade) if isinstance(node, ast.If)), (
        "downgrade 必须按四表检查 revision>0 或新的 is_final 后条件性拒绝降级"
    )


def _server_default_text(column: Any) -> str:
    default = column.server_default
    if default is None:
        return ""
    argument = getattr(default, "arg", default)
    return str(argument)


def test_nullable_market_values_do_not_default_to_zero() -> None:
    expected = {
        quotes_snapshot: ("price", "pct_change"),
        realtime_quotes: ("price", "open", "high", "low", "pre_close", "volume", "amount", "pct_change"),
        minute_bars: ("open", "high", "low", "close", "volume", "amount"),
        minute5_bars: ("open", "high", "low", "close", "volume", "amount"),
    }
    for table, names in expected.items():
        for name in names:
            column = table.c[name]
            assert column.nullable is True
            assert not ZERO_DEFAULT.search(_server_default_text(column))


def test_0034_nullable_licence_does_not_close_i2() -> None:
    for table in (minute_bars, minute5_bars):
        assert _licence_nullable(table)
    # 无谓词 (code, ts) 一旦仍在，不得把 0034 的可空证书列判成 I2 已关闭。
    for table in TABLES:
        if _has_unpredicated_code_ts(table):
            assert not i2_schema_ready(table)


def test_existing_source_checks_keep_i2_allowed_values() -> None:
    for table in (realtime_quotes, minute_bars, minute5_bars):
        assert table.c.source.nullable is True
        constraint = _source_check(table)
        assert constraint is not None
        assert constraint.name == f"ck_{table.name}_source"
        assert _check_source_in_values(table) == EXPECTED_SOURCE_CHECKS[table.name]


@pytest.mark.xfail(
    "source" not in quotes_snapshot.c
    or _check_source_in_values(quotes_snapshot) != LICENSED_SOURCES,
    reason="quotes_snapshot 尚未增加 I2 source 列与 ck_quotes_snapshot_source",
    strict=True,
)
def test_quotes_snapshot_source_check_allows_mairui() -> None:
    assert quotes_snapshot.c.source.nullable is True
    constraint = _source_check(quotes_snapshot)
    assert constraint is not None
    assert constraint.name == "ck_quotes_snapshot_source"
    assert _check_source_in_values(quotes_snapshot) == LICENSED_SOURCES

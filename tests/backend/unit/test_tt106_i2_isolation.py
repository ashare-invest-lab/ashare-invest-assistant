"""T-T106 I2 隔离契约的离线元数据与迁移源码检查。"""

from __future__ import annotations

import ast
import re
import socket
from pathlib import Path
from typing import Any

import pytest
from app.db.tables.market import minute_bars, quotes_snapshot
from sqlalchemy import Table
from sqlalchemy.dialects.postgresql import dialect as postgresql_dialect
from sqlalchemy.schema import CreateTable

ROOT = Path(__file__).resolve().parents[3]
MIGRATIONS = ROOT / "src/backend/migrations/versions"
OWNERSHIP_COLUMNS = {"source", "source_licence_id"}
ZERO_DEFAULT = re.compile(r"(?:^|[^0-9.])0(?:\.0+)?(?:$|[^0-9.])")
I2_SENTINEL = "T-B196-I2-ISOLATION"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        pytest.fail("I2 离线检查不得访问网络")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _unique_constraints(table: Table) -> list[frozenset[str]]:
    constraints = [table.primary_key, *table.constraints]
    keys = [
        frozenset(column.name for column in constraint.columns)
        for constraint in constraints
        if getattr(constraint, "columns", None) is not None
        and (getattr(constraint, "primary_key", False) or getattr(constraint, "unique", False))
    ]
    keys.extend(
        frozenset(column.name for column in index.columns)
        for index in table.indexes
        if index.unique
    )
    return keys


def i2_isolation_ready(table: Table) -> bool:
    """表必须按 code、ts 与至少一个归属列联合唯一。"""
    columns = set(table.c.keys())
    ownership = columns & OWNERSHIP_COLUMNS
    if not ownership or not {"code", "ts"} <= columns:
        return False
    keys = _unique_constraints(table)
    if frozenset(("code", "ts")) in keys:
        return False
    return any({"code", "ts"} | {owner} <= key for owner in ownership for key in keys)


def _licence_nullable(table: Table) -> bool:
    column = table.c.get("source_licence_id")
    if column is None:
        column = table.c.get("source")
    return column is not None and column.nullable is True


def _migration_is_i2(path: Path) -> bool:
    return I2_SENTINEL in path.read_text(encoding="utf-8")


def i2_migration_found() -> Path | None:
    matches = [path for path in sorted(MIGRATIONS.glob("*.py")) if _migration_is_i2(path)]
    if len(matches) > 1:
        raise AssertionError(f"I2 sentinel appears in multiple migrations: {matches}")
    return matches[0] if matches else None


READY = {table.name: i2_isolation_ready(table) for table in (quotes_snapshot, minute_bars)}
I2_MIGRATION = i2_migration_found()


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


@pytest.mark.parametrize("table", [quotes_snapshot, minute_bars], ids=lambda table: table.name)
@pytest.mark.xfail(
    not all(READY.values()), reason="T-B196 未实现：行情表仍按 (code, ts) 唯一", strict=True
)
def test_two_licences_same_minute_have_distinct_unique_keys(table: Table) -> None:
    assert i2_isolation_ready(table)
    keys = _unique_constraints(table)
    ownership = set(table.c.keys()) & OWNERSHIP_COLUMNS
    assert any({"code", "ts"} | {owner} <= key for owner in ownership for key in keys)
    assert frozenset(("code", "ts")) not in keys

    # 只编译 DDL，确保联合约束在 PostgreSQL 方言下可生成，不连接数据库。
    ddl = str(CreateTable(table).compile(dialect=postgresql_dialect()))
    assert "PRIMARY KEY" in ddl or "UNIQUE" in ddl

    # 两个虚构证书的联合键不同，因此不应互相覆盖。
    owner = next(iter(ownership))
    key = next(key for key in keys if {"code", "ts", owner} <= key)
    first = tuple("00000000-0000-4000-8000-000000000001" if item == owner else "600000.SH" if item == "code" else "2026-11-02T10:31:00+08:00" for item in key)
    second = tuple("00000000-0000-4000-8000-000000000002" if item == owner else value for item, value in zip(key, first))
    assert first != second


@pytest.mark.xfail(
    not all(READY.values()), reason="T-B196 未实现：旧无归属行隔离语义尚未落地", strict=True
)
def test_old_rows_without_licence_are_not_claimed_by_a_licence() -> None:
    assert all(READY.values())
    for table in (quotes_snapshot, minute_bars):
        ownership = set(table.c.keys()) & OWNERSHIP_COLUMNS
        assert ownership
        assert _licence_nullable(table)

    assert I2_MIGRATION is not None
    source = I2_MIGRATION.read_text(encoding="utf-8")
    assert not re.search(
        r"(?:source_licence_id|source)\s*=\s*['\"]?[0-9a-f]{8}-[0-9a-f-]{27,}['\"]?",
        source,
        re.IGNORECASE,
    )
    # 迁移源码须显式保留 NULL，而不能以 licence=X 的条件冒领旧行。
    assert "null" in source.lower() or "nullable=true" in source.lower()


@pytest.mark.xfail(
    I2_MIGRATION is None, reason="T-B196 未实现：尚无带 T-B196-I2-ISOLATION sentinel 的迁移，无法验证回滚保护", strict=True
)
def test_i2_downgrade_refuses_data_loss() -> None:
    assert I2_MIGRATION is not None
    tree = ast.parse(I2_MIGRATION.read_text(encoding="utf-8"))
    downgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    function_source = ast.unparse(downgrade).lower()
    data_checks = ("select", "exists", "count", "row", "rows", "sourced", "nonempty")
    tables = ("quotes_snapshot", "minute_bars")
    refusal_words = ("refus", "reject", "拒绝", "丢", "data loss")

    def is_refusal(node: ast.AST) -> bool:
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            return False
        if not isinstance(node.exc.func, ast.Name) or node.exc.func.id not in {"RuntimeError", "ValueError"}:
            return False
        return any(word in ast.unparse(node).lower() for word in refusal_words)

    conditional_refusal = any(
        isinstance(node, ast.If)
        and any(is_refusal(child) for child in ast.walk(node))
        and any(term in ast.unparse(node).lower() for term in data_checks)
        and any(table in function_source for table in tables)
        and any(term in function_source for term in ("select", "exists", "count"))
        for node in ast.walk(downgrade)
    )
    assert conditional_refusal, "downgrade 必须在检查隔离表已有数据后条件性拒绝降级"


def _server_default_text(column: Any) -> str:
    default = column.server_default
    if default is None:
        return ""
    argument = getattr(default, "arg", default)
    return str(argument)


def test_nullable_market_values_do_not_default_to_zero() -> None:
    expected = {
        quotes_snapshot: ("price", "pct_change"),
        minute_bars: ("open", "high", "low", "close", "volume", "amount"),
    }
    for table, names in expected.items():
        for name in names:
            column = table.c[name]
            assert column.nullable is True
            assert not ZERO_DEFAULT.search(_server_default_text(column))

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
    if path.name.startswith("0034_"):
        return False
    text = path.read_text(encoding="utf-8")
    lower = text.lower()
    if "source_licence_id" not in lower and "source" not in lower:
        return False
    # 基线只创建旧表，不能被误认作后续 I2 迁移。
    if "source_licence_id" not in lower and not any(
        token in lower
        for token in ("add_column", "drop_constraint", "create_unique_constraint", "create_primary_key", "alter_column")
    ):
        return False
    if "quotes_snapshot" in lower:
        return any(token in lower for token in ("unique", "primary key", "constraint"))
    if "minute_bars" in lower:
        return any(token in lower for token in ("unique", "primary key", "drop_constraint"))
    return False


def i2_migration_found() -> Path | None:
    for path in sorted(MIGRATIONS.glob("*.py")):
        if _migration_is_i2(path):
            return path
    return None


READY = {table.name: i2_isolation_ready(table) for table in (quotes_snapshot, minute_bars)}
I2_MIGRATION = i2_migration_found()


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
    I2_MIGRATION is None, reason="T-B196 未实现：尚无 I2 迁移，无法验证回滚保护", strict=True
)
def test_i2_downgrade_refuses_data_loss() -> None:
    assert I2_MIGRATION is not None
    tree = ast.parse(I2_MIGRATION.read_text(encoding="utf-8"))
    downgrade = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "downgrade"
    )
    raises_runtime_error = any(
        isinstance(node, ast.Raise)
        and isinstance(node.exc, ast.Call)
        and isinstance(node.exc.func, ast.Name)
        and node.exc.func.id in {"RuntimeError", "ValueError"}
        for node in ast.walk(downgrade)
    )
    assert raises_runtime_error
    source = I2_MIGRATION.read_text(encoding="utf-8").lower()
    assert any(word in source for word in ("refus", "reject", "丢", "data loss"))


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

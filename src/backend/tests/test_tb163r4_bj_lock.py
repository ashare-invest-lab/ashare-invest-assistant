"""T-B163r4: self-reported pairs cannot authorize production BJ writes."""

# ruff: noqa: S101
from __future__ import annotations

import ast
import re
import socket
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from app import bj_offline_volume as gate
from app.cli.tb143_day_load import load_day
from app.marketdata import daily_bars as writer
from probes import tb140_history_load as history

BACKEND = Path(__file__).resolve().parents[1]
DAY = date(2031, 1, 2)
BJ, OUTSIDE, UNMATCHED = "920000.BJ", "920001.BJ", "920999.BJ"


@pytest.fixture(autouse=True)
def offline_confirmation(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    denied = Mock(side_effect=AssertionError("Synthetic test must not connect"))
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(gate, "_bj_offline_volume_codes", frozenset())
    monkeypatch.setattr(gate, "_bj_confirmation_pid", None)
    yield
    # Clear any synthetic process state before monkeypatch restores the prior state.
    with pytest.raises(gate.RowReject, match="requires_20"):
        gate.confirm_bj_offline_volume_units([])


def pairs() -> list[dict[str, dict[str, object]]]:
    return [
        {
            "mairui": {"code": f"920{i:03}.BJ", "t": DAY.isoformat(), "v": "1"},
            "tdx_local": {"code": f"920{i:03}.BJ", "trade_date": DAY.isoformat(),
                          "volume": 100, "source": "tdx_local"},
        }
        for i in range(20)
    ]


def connection() -> MagicMock:
    conn = MagicMock()
    conn.info.transaction_status = 0

    def execute(statement: object) -> SimpleNamespace:
        assert getattr(statement, "is_insert", False)
        params = statement.compile().params  # type: ignore[attr-defined]
        codes = [value for key, value in params.items() if key.startswith("code_m")]
        return SimpleNamespace(all=lambda: [
            SimpleNamespace(code=code, trade_date=DAY, adj_type="none") for code in codes
        ])

    conn.execute.side_effect = execute
    conn.cursor.return_value.__enter__.return_value.fetchone.return_value = (0,)
    return conn


def upsert(conn: MagicMock, codes: Iterable[str]) -> writer.UpsertStats:
    bars = [writer.DailyBar(code, DAY, "none", *([None] * 8)) for code in codes]
    return writer.upsert_daily_bars(
        conn, writer.FetchResult(bars), source="tdx_local", licence_id=None,
        fetched_at=datetime(2031, 1, 2, tzinfo=UTC),
    )


def test_bj_selfreported_pairs_do_not_unlock_upsert() -> None:
    assert len(gate.confirm_bj_offline_volume_units(pairs())) == 20
    conn = connection()
    stats = upsert(conn, [BJ])
    assert stats.inserted == 0
    assert stats.blocked_bj_unconfirmed == 1
    conn.execute.assert_not_called()


def test_bj_selfreported_pairs_do_not_unlock_tb143_load_day(tmp_path: Path) -> None:
    assert len(gate.confirm_bj_offline_volume_units(pairs())) == 20
    csv = tmp_path / "synthetic.csv"
    csv.write_text("code,trade_date,adj_type,open,high,low,close,volume,amount\n", encoding="utf-8")
    conn = MagicMock()
    conn.info.transaction_status = 0
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (0, 0)
    cursor.fetchmany.side_effect = [[(BJ, DAY, "none", 1, 1, 1, 1, 100, 100)], []]
    cursor.description = [SimpleNamespace(name=name) for name in ("code", "trade_date", "adj_type")]
    cursor.fetchall.return_value = [(BJ, DAY, "none")]
    stats = load_day(conn, csv, date(2032, 1, 1))
    assert stats == {"candidates": 1, "inserted": 0, "skipped": 1, "blocked_bj_unconfirmed": 1}
    assert not any("INSERT INTO market.daily_bars" in str(call.args[0])
                   for call in cursor.execute.call_args_list)


def test_bj_confirmation_only_effective_with_injected_isolated_list(
    bj_isolated_list: Callable[[Iterable[str]], None],
) -> None:
    bj_isolated_list([BJ, UNMATCHED])
    # Injection alone cannot confirm even a listed code.
    assert upsert(connection(), [BJ]).blocked_bj_unconfirmed == 1
    assert len(gate.confirm_bj_offline_volume_units(pairs())) == 20
    conn = connection()
    stats = upsert(conn, [BJ, OUTSIDE, UNMATCHED])
    assert stats.inserted == 1
    assert stats.blocked_bj_unconfirmed == 2
    assert conn.execute.call_args.args[0].compile().params["code_m0"] == BJ
    # Removing the list also invalidates existing process confirmation.
    bj_isolated_list([])
    assert upsert(connection(), [BJ]).blocked_bj_unconfirmed == 1


def test_shsz_rows_unaffected_by_bj_lock() -> None:
    assert len(gate.confirm_bj_offline_volume_units(pairs())) == 20
    stats = upsert(connection(), ["600000.SH", "000001.SZ", BJ])
    assert stats.inserted == 2
    assert stats.blocked_bj_unconfirmed == 1


@pytest.mark.parametrize("isolated", [False, True])
def test_tb140_render_and_apply_share_bj_lock(
    tmp_path: Path, bj_isolated_list: Callable[[Iterable[str]], None], isolated: bool,
) -> None:
    if isolated:
        bj_isolated_list([BJ])
    assert len(gate.confirm_bj_offline_volume_units(pairs())) == 20
    codes = [BJ, OUTSIDE, "600000.SH", "000001.SZ"]
    rows = [{"code": code, "trade_date": DAY.isoformat(), "adj_type": "none", "source": "mairui",
             "open": "1", "high": "1", "low": "1", "close": "1", "pre_close": "1", "volume": 100,
             "amount": "100", "is_suspended": False} for code in codes]
    sql = history.render_insert_sql(rows, None, bind_note="synthetic")
    executable = re.sub(r"--[^\n]*", "", sql)
    assert (BJ in executable) is isolated
    assert OUTSIDE not in executable
    assert all(code in executable for code in codes[2:])
    assert "§10.12 第 1 条" in sql
    assert "call confirm_bj_offline_volume_units first" not in sql
    artifact = tmp_path / "synthetic.sql"
    artifact.write_text(sql, encoding="utf-8")
    stats = history.apply_insert_artifact(connection(), artifact)
    assert stats["inserted"] == 2 + int(isolated)
    assert stats["blocked_bj_unconfirmed"] == 2 - int(isolated)
    if isolated:
        bj_isolated_list([])
        stats = history.apply_insert_artifact(connection(), artifact)
        assert stats["inserted"] == 2
        assert stats["blocked_bj_unconfirmed"] == 2


def test_bj_isolated_list_defaults_empty_and_has_no_production_assignment() -> None:
    assert frozenset() == gate._BJ_ISOLATED_CONFIRMATIONS
    name = "_BJ_ISOLATED_CONFIRMATIONS"
    definitions = []
    for directory in ("app", "probes"):
        for path in (BACKEND / directory).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
                        and node.target.id == name
                        and path == BACKEND / "app/bj_offline_volume.py"):
                    assert node in tree.body
                    assert ast.unparse(node.annotation) == "frozenset[str]"
                    assert ast.unparse(node.value) == "frozenset()"
                    definitions.append((path, node.lineno))
                    continue
                if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign, ast.NamedExpr)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    assert all(name not in ast.unparse(target) for target in targets), (
                        path, node.lineno, "isolated list assignment",
                    )
                if isinstance(node, ast.Call):
                    func = ast.unparse(node.func)
                    if func.endswith(("setattr", "__setattr__", "__setitem__", ".update")):
                        assert name not in ast.unparse(node), (path, node.lineno)
    assert len(definitions) == 1


def test_tb143_load_day_sql_has_no_target_dml_commit_or_rollback() -> None:
    sql = (BACKEND / "probes/tb143_load_day.sql").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/|--[^\n]*", "", sql, flags=re.S)
    code = re.sub(r"\bON\s+COMMIT\s+DROP\b", "", code, flags=re.I)
    assert not re.search(r"\b(?:COMMIT|ROLLBACK)\b", code, re.I)
    temps = set(re.findall(r"\bCREATE\s+TEMP(?:ORARY)?\s+TABLE\s+(\w+)", code, re.I))
    targets = re.findall(
        r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|'
        r'TRUNCATE(?:\s+TABLE)?|COPY)\s+([\w.\"]+)', code, re.I,
    )
    assert temps
    assert set(targets) <= temps

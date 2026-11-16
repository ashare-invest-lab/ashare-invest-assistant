"""T-T83 第二份：公共 writer 的来源优先级、错后缀保护与旧窗口。

仅用合成行情、内存数据库替身和 monkeypatch，不连接 PG/Redis/docker。
BJ 的 0/1/19/20、精度、撤销矩阵及 §10.12 原始字节＋隔离清单验收归属 #197；
本文件仅保留未确认 BJ 的短引用例，不据此声称原始证据契约已实现。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import BindParameter, BooleanClauseList, ColumnClause, Tuple

from tests.backend.unit.test_ta157_bj_routing import (  # noqa: F401
    TOKEN, Wire, api, assert_invalid_fields, bar, counter, offline_only,
)

pytestmark = pytest.mark.unit


@pytest.fixture
def writer():
    from app.marketdata import daily_bars

    return daily_bars


def evaluate(expression, row):
    """只解释本替身支持的 SQL 表达式；不含来源优先级或对账策略。"""
    if isinstance(expression, BindParameter):
        return expression.value
    if isinstance(expression, ColumnClause):
        return row[expression.name]
    if isinstance(expression, Tuple):
        return tuple(evaluate(part, row) for part in expression.clauses)
    if isinstance(expression, BooleanClauseList):
        assert expression.operator is operators.and_
        return all(evaluate(part, row) for part in expression.clauses)
    left, right = evaluate(expression.left, row), evaluate(expression.right, row)
    if expression.operator is operators.eq:
        return left == right
    assert expression.operator is operators.in_op
    return left in right


class StatementDB:
    """执行生产入口的 INSERT/SELECT/条件 UPDATE；仅模拟存储和事务。

    UPDATE 的值和 WHERE 均取自实际 SQLAlchemy 对象，不直接写回预设 incoming。
    """

    def __init__(self, rows=(), *, race=False):
        self.rows = {self.key(row): deepcopy(row) for row in rows}
        self.events = []
        self.race_key = self.key(rows[0]) if race else None

    @staticmethod
    def key(row):
        return row["code"], row["trade_date"], row["adj_type"]

    @contextmanager
    def transaction(self):
        before = deepcopy(self.rows)
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.rows = before
            self.events.append("rollback")
            raise
        else:
            self.events.append("commit")

    def execute(self, statement):
        params = statement.compile().params
        if statement.is_insert:
            self.events.append("insert")
            inserted = []
            index = 0
            while True:
                suffix = f"_m{index}"
                values = {key[:-len(suffix)]: value for key, value in params.items()
                          if key.endswith(suffix)}
                if not values:
                    break
                key = self.key(values)
                if key not in self.rows:
                    self.rows[key] = values
                    inserted.append(SimpleNamespace(**values))
                index += 1
            return SimpleNamespace(all=lambda: inserted)
        if statement.is_select:
            self.events.append("select")
            rows = [deepcopy(row) for row in self.rows.values()
                    if all(evaluate(expr, row) for expr in statement._where_criteria)]
            return SimpleNamespace(mappings=lambda: rows)
        assert statement.is_update, "只允许 INSERT、SELECT 和条件 UPDATE"
        self.events.append("update")
        if self.race_key is not None:
            # SELECT 后另一事务已将同键目标来源改为 mairui。
            self.rows[self.race_key]["source"] = "mairui"
        changed = []
        for row in self.rows.values():
            if all(evaluate(expr, row) for expr in statement._where_criteria):
                row.update({getattr(column, "key", column): value.value
                            for column, value in statement._values.items()})
                changed.append({"code": row["code"]})
        return SimpleNamespace(mappings=lambda: changed)


def make_bar(writer, code="600997.SH"):
    return writer.DailyBar(
        code, date(2001, 1, 4), "none", *([Decimal("10")] * 5),
        Decimal(200), Decimal(2000), False,
    )


def write(writer, db, bars, sink=None):
    return writer.upsert_daily_bars(
        db, writer.FetchResult(bars), source="mairui", licence_id=None,
        fetched_at=datetime(2026, 11, 13, tzinfo=timezone.utc), reconcile_sink=sink,
    )


@pytest.mark.parametrize("label,source,same,fail_audit,race", [
    ("replace", "tdx_local", False, False, False),
    ("same", "tdx_local", True, False, False),
    ("audit-failed", "tdx_local", False, True, False),
    ("race", "tdx_local", False, False, True),
    ("mairui", "mairui", False, False, False),
    ("fake", "fake", False, False, False),
])
def test_ta157_tdx_priority(writer, api, tmp_path, label, source, same, fail_audit, race):
    incoming = make_bar(writer)
    existing = dict(vars(incoming), source=source, source_licence_id=None)
    if not same:
        existing.update(open=Decimal("9.99"), high=Decimal("9.99"),
                        low=Decimal("9.99"), close=Decimal("9.99"))
    # 不同代码/日期/复权的旁观行证明 UPDATE 不得越过同键条件。
    sentinels = [dict(existing, code="000997.SZ"),
                 dict(existing, trade_date=date(2001, 1, 5)),
                 dict(existing, adj_type="qfq")]
    db = StatementDB([existing, *sentinels], race=race)
    audit = tmp_path / f"{label}.jsonl"
    persist = api.load.jsonl_reconcile_sink(audit)

    def sink(record):
        db.events.append("audit")
        if fail_audit:
            raise OSError("synthetic audit failure")
        persist(record)

    if fail_audit:
        before = deepcopy(db.rows)
        with pytest.raises(OSError, match="synthetic audit failure"):
            with db.transaction():
                write(writer, db, [incoming], sink)
        assert db.rows == before
        assert db.events[-1] == "rollback" and "audit" in db.events
        assert "update" not in db.events and not audit.exists()
        return

    with db.transaction():
        stats = write(writer, db, [incoming], sink)
        if audit.exists():
            assert not any(json.loads(line).get("value") == "committed"
                           for line in audit.read_text().splitlines())
    stats.reconcile_after_transaction(committed=True)
    should_replace = source == "tdx_local" and not race
    assert stats.inserted == 0 and stats.replaced == int(should_replace)
    assert stats.conflicts == int(source != "tdx_local")
    for row in sentinels:
        assert db.rows[db.key(row)] == row
    stored = db.rows[db.key(existing)]
    records = [json.loads(line) for line in audit.read_text().splitlines()] if audit.exists() else []
    if source != "tdx_local":
        assert stored == existing and records == [] and "update" not in db.events
        return
    assert db.events.index("audit") < db.events.index("update") < db.events.index("commit")
    kind = "replaced_tdx_local_same" if same else "replaced_tdx_local"
    diffs = [record for record in records if record.get("kind") == kind]
    assert diffs and all(record["existing_source"] == "tdx_local"
                         and record["incoming_source"] == "mairui" for record in diffs)
    if same:
        assert [record["field"] for record in diffs] == ["*"]
    else:
        close = next(record for record in diffs if record["field"] == "close")
        assert Decimal(close["existing_value"]) == Decimal("9.99")
        assert Decimal(close["incoming_value"]) == Decimal("10")
    result = records[-1]
    assert result["kind"] == "replace_result"
    assert result["value"] == ("skipped" if race else "committed")
    assert {record["replacement_id"] for record in records} == {result["replacement_id"]}
    if race:
        assert stored == dict(existing, source="mairui")
    else:
        assert all(stored[field] == value for field, value in vars(incoming).items())
        assert stored["source"] == "mairui" and stored["source_licence_id"] is None


def test_ta157_wrong_suffix_read_only(writer, api):
    # 生产统计入口只读查询、结果透传；不在替身中重写分组/比较算法。
    groups = [("920997.SH", "tdx_local", "none", 3, "2001-01-04", "2001-01-08")]
    comparison = [
        ("920997.SH", "tdx_local", target_source, "none", category, 1, day, day)
        for target_source, category, day in (
            (None, "target_missing", "2001-01-04"),
            ("mairui", "same_key_same_values", "2001-01-05"),
            ("mairui", "same_key_different_values", "2001-01-08"),
        )
    ]
    conn, cursor = Mock(), Mock()
    conn.cursor.return_value.__enter__ = Mock(return_value=cursor)
    conn.cursor.return_value.__exit__ = Mock(return_value=False)
    cursor.fetchall.side_effect = [groups, comparison]
    result = api.load.wrong_suffix_stats(conn)
    assert result == {"groups": groups, "comparison": comparison}
    queries = [call.args[0] for call in cursor.execute.call_args_list]
    assert queries == [api.load.WRONG_SUFFIX_GROUP_SQL, api.load.WRONG_SUFFIX_COMPARE_SQL]
    assert all(query.lstrip().upper().startswith("SELECT") for query in queries)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()
    cursor.executemany.assert_not_called()
    # 公共 writer 拒绝错后缀，不自动修库或覆盖已有错误库存。
    wrong = dict(vars(make_bar(writer, "920997.SH")), source="tdx_local")
    db = StatementDB([wrong])
    before = deepcopy(db.rows)
    with pytest.raises(ValueError, match="qualified_code_invalid"):
        write(writer, db, [make_bar(writer, "920997.SH")])
    assert db.rows == before and db.events == []


def test_ta157_bj_volume_lots_to_shares(api, writer, tmp_path):
    raw = bar(code="920801.BJ", v="2", a="2000")
    accepted = api.load.validate_bar(raw, "920801.BJ")
    assert accepted is not None and api.load.VOL_MULT == 100 and accepted["volume"] == 200
    assert accepted["close"] == "10" and accepted["amount"] == "2000"
    rows, rejects = api.load.normalize_history("920801", [raw])
    assert rows == [accepted] and rejects == []
    assert_invalid_fields(api.load, "920801.BJ")
    path = tmp_path / "normalized.json"
    api.load.write_normalized(path, "920801", rows, rejects)
    assert api.load.load_normalized(path) == rows
    db = StatementDB()
    bj = writer.DailyBar(**{**vars(make_bar(writer, "920801.BJ")),
                           "trade_date": date(2026, 11, 13)})
    stats = write(writer, db, [bj])
    assert stats.inserted == 0 and stats.blocked_bj_unconfirmed == 1
    assert db.rows == {} and db.events == []


def test_ta158_bj_write_requires_offline_volume_check(writer):
    """引用 #197：只观察公共 writer 默认阻断；完整证据/撤销矩阵由该单维护。"""
    db = StatementDB()
    bj, sh, sz = [make_bar(writer, code) for code in ("920997.BJ", "600997.SH", "000997.SZ")]
    stats = write(writer, db, [bj, sh, sz])
    assert stats.blocked_bj_unconfirmed == 1 and stats.inserted == 2
    assert stats.issues == ("blocked_bj_unconfirmed",)
    assert set(db.rows) == {db.key(vars(sh)), db.key(vars(sz))}


def test_ta157_old_window_not_complete(api, tmp_path, capsys):
    # 通过真实 run_batch 观察旧账本：不重置计数、不自动重拉、显示待补范围。
    state = counter()
    state["done_history"] = ["600997"]
    original = deepcopy(state)
    ledger = tmp_path / "counter.json"
    ledger.write_text(json.dumps(state))
    ledger.chmod(0o600)
    before = ledger.read_bytes()
    codes = tmp_path / "codes.txt"
    codes.write_text("600997\n")
    old = tmp_path / "old/history"
    old.mkdir(parents=True)
    row = api.load.validate_bar(bar(), "600997.SH")
    api.load.write_normalized(old / "600997.SH.json", "600997", [row], [])
    wire = Wire()
    summary = api.backfill.run_batch(
        codes_file=codes,
        licence_file=None,
        counter_path=ledger,
        stop_path=tmp_path / "STOP",
        run_dir=tmp_path / "old",
        secret=TOKEN,
        st=None,
        et=None,
        connection_factory=lambda: wire,
        sleeper=lambda _seconds: None,
    )
    assert wire.paths == [] and summary["calls"] == 0, "不得自动重拉旧 done_history"
    assert ledger.read_bytes() == before and json.loads(before) == original, (
        "不得重置计数或完成记录"
    )
    # 独立检查 HALT 保留；不依赖未知的新规划入口。
    halted = dict(original, halted=True, halt_reason="synthetic HALT")
    ledger.write_text(json.dumps(halted))
    halted_before = ledger.read_bytes()
    with pytest.raises(api.backfill.Halt, match="halted"):
        api.backfill.run_batch(
            codes_file=codes,
            licence_file=None,
            counter_path=ledger,
            stop_path=tmp_path / "STOP",
            run_dir=tmp_path / "halted",
            secret=TOKEN,
            st=None,
            et=None,
            connection_factory=lambda: wire,
            sleeper=lambda _seconds: None,
        )
    assert ledger.read_bytes() == halted_before and wire.paths == []
    display = capsys.readouterr().out + json.dumps(summary, ensure_ascii=False)
    assert "待补" in display and "600997" in display, (
        "§10.5/10.9：旧三年完成记录不能冒充无界全历史完成；必须显示关联原账本的待补范围；"
        "此处观察生产 run_batch 输出与账本不变性"
    )

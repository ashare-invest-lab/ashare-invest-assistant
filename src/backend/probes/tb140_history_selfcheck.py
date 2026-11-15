#!/usr/bin/env python3
"""T-B140c 离线自检：全部虚构数据，不连麦蕊、不读凭据、不连真实库、不改正式 STOP/账本。"""
from __future__ import annotations

import http.client
import io
import json
import os
import stat
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import patch

PROBES = Path(__file__).resolve().parent
if str(PROBES) not in sys.path:
    sys.path.insert(0, str(PROBES))

import tb140_history_backfill as bf  # noqa: E402
import tb140_history_load as ld  # noqa: E402
import tb140_history_supervisor as sv  # noqa: E402

MOCK_SECRET = "MOCK-LICENCE-TOKEN-XXXX-NOT-A-REAL-KEY"
RESULTS: list[tuple[str, str]] = []


class Fail(AssertionError):
    pass


def check(name: str, fn: Any) -> None:
    try:
        fn()
        RESULTS.append((name, "PASS"))
    except Exception as exc:  # noqa: BLE001
        RESULTS.append((name, f"FAIL:{type(exc).__name__}:{exc}"))


def old_buggy_mkt(code: str) -> str:
    """既有 tb140_daily_bars.mkt 的宽泛规则，仅作对照，不调用原脚本。"""
    if code.startswith(("6", "9")):
        return "SH"
    if code.startswith(("4", "8")) or code.startswith("92"):
        return "BJ"
    return "SZ"


def test_market_prefixes() -> None:
    cases = {
        "000001": "SZ",
        "001234": "SZ",
        "002535": "SZ",
        "003000": "SZ",
        "300364": "SZ",
        "301218": "SZ",
        "302001": "SZ",
        "600519": "SH",
        "601611": "SH",
        "603000": "SH",
        "605000": "SH",
        "688018": "SH",
        "689009": "SH",
        "920982": "BJ",
        "430001": "BJ",
        "831000": "BJ",
        "873000": "BJ",
    }
    for code, mkt in cases.items():
        assert ld.market_of(code) == mkt, (code, ld.market_of(code), mkt)
        assert ld.qualified_code(code) == f"{code}.{mkt}"
    # 既有缺陷：920 被判成 SH；未知前缀被回落成 SZ。
    assert old_buggy_mkt("920982") == "SH"
    assert ld.market_of("920982") == "BJ"
    try:
        ld.market_of("900001")  # 沪 B，不在 A 股允许名单
        raise Fail("900001 should be rejected")
    except ld.CodeReject:
        pass
    try:
        ld.market_of("123456")
        raise Fail("unknown prefix should be rejected")
    except ld.CodeReject:
        pass
    try:
        ld.market_of("1")
        raise Fail("short code should be rejected")
    except ld.CodeReject:
        pass


def _bar(**over: Any) -> dict[str, Any]:
    base = {"t": "2024-01-02", "o": 10, "h": 11, "l": 9.5, "c": 10.5, "v": 12, "a": 12500.5, "pc": 10, "sf": 0}
    base.update(over)
    return base


def test_normalize_and_units() -> None:
    rows, rejects = ld.normalize_history("000001", [_bar(), _bar(t="20231113", v=1, a=100)])
    assert rejects == []
    assert rows[0]["trade_date"] == "2023-11-13"
    assert rows[1]["trade_date"] == "2024-01-02"
    assert rows[1]["code"] == "000001.SZ"
    assert rows[1]["adj_type"] == "none"
    assert rows[1]["source"] == "mairui"
    assert rows[1]["volume"] == 1200  # 12 手 × 100 股
    assert rows[1]["amount"] == "12500.5"
    assert rows[1]["is_suspended"] is False
    sus, _ = ld.normalize_history("000001", [_bar(sf=1, v=0, a=0, o=10, h=10, l=10, c=10)])
    assert sus[0]["is_suspended"] is True
    assert sus[0]["volume"] == 0


def test_validation_rejects() -> None:
    # 窗口外跳过，不入库、不伪造
    rows, rejects = ld.normalize_history("000001", [_bar(t="2020-01-01"), _bar(t="2026-11-14")], st=ld.HIST_ST, et=ld.HIST_ET)
    assert rows == []
    assert {r["reason"] for r in rejects} == {"date_out_of_window"}
    # OHLC 矛盾
    _, bad = ld.normalize_history("000001", [_bar(h=9, l=10)])
    assert bad[0]["reason"] == "ohlc_inconsistent"
    _, neg = ld.normalize_history("000001", [_bar(o=-1, h=11, l=-2, c=10)])
    assert neg[0]["reason"] == "ohlc_not_positive"
    # 身份不一致
    _, ident = ld.normalize_history("000001", [_bar(code="600519.SH")])
    assert ident[0]["reason"] == "identity_mismatch"
    # 非 list
    try:
        ld.normalize_history("000001", {"t": "2024-01-02"})
        raise Fail("dict body should fail")
    except ld.RowReject as exc:
        assert "not_list" in str(exc)
    # 窗口边界内
    rows, rej = ld.normalize_history("600519", [_bar(t="2026-11-13"), _bar(t="2023-11-13")])
    assert rej == []
    assert [r["code"] for r in rows] == ["600519.SH", "600519.SH"]


def test_sql_and_conflict() -> None:
    rows, _ = ld.normalize_history("688018", [_bar()])
    sql = ld.render_insert_sql(rows, None, bind_note="pending_bind")
    assert "ON CONFLICT (code, trade_date, adj_type) DO NOTHING" in sql
    assert "source_licence_id" in sql
    assert "NULL" in sql
    assert "'none'" in sql
    assert "'688018.SH'" in sql
    assert ",1200," in sql or ",1200)" in sql.split("VALUES", 1)[1]
    assert "DELETE FROM" not in sql.upper() and "TRUNCATE" not in sql.upper()
    assert "pending_bind" in sql
    uid = "12345678-1234-4234-8234-123456789abc"
    sql2 = ld.render_insert_sql(rows, uid, bind_note="bound")
    assert f"'{uid}'::uuid" in sql2
    stats = ld.apply_insert_offline(set(), rows)
    assert stats == {"inserted": 1, "skipped_existing": 0, "total": 1}
    stats2 = ld.apply_insert_offline({("688018.SH", "2024-01-02", "none")}, rows)
    assert stats2["inserted"] == 0 and stats2["skipped_existing"] == 1
    lid, note = ld.resolve_active_licence([])
    assert lid is None and note == "pending_bind"
    lid, note = ld.resolve_active_licence([uid])
    assert lid == uid and note == "bound"
    lid, note = ld.resolve_active_licence([uid, "12345678-1234-4234-8234-123456789abd"])
    assert lid is None and note == "pending_bind_ambiguous"


def test_offline_insert_blocks_unconfirmed_bj() -> None:
    # 主动撤销旧确认，使本用例不依赖其他自检的运行顺序。
    try:
        ld.confirm_bj_offline_volume_units([])
        raise Fail("empty comparison must revoke confirmation and fail")
    except ld.RowReject:
        pass
    bj_rows, rejects = ld.normalize_history("920801", [_bar()])
    assert rejects == []
    existing: set[tuple[str, str, str]] = set()
    stats = ld.apply_insert_offline(existing, bj_rows)
    assert stats == {"inserted": 0, "skipped_existing": 0, "total": 0,
                     "blocked_bj_unconfirmed": 1}
    assert ("920801.BJ", "2024-01-02", "none") not in existing
    sh_rows, _ = ld.normalize_history("689801", [_bar()])
    sz_rows, _ = ld.normalize_history("302801", [_bar()])
    mixed = ld.apply_insert_offline(
        {("689801.SH", "2024-01-02", "none")}, bj_rows + sh_rows + sz_rows + sz_rows,
    )
    assert mixed == {"inserted": 1, "skipped_existing": 2, "total": 2,
                     "blocked_bj_unconfirmed": 1}


class FakeResp:
    def __init__(self, status: int, body: Any) -> None:
        self.status = status
        if isinstance(body, bytes):
            self._body = body
        elif isinstance(body, str):
            self._body = body.encode("utf-8")
        else:
            self._body = json.dumps(body, ensure_ascii=False).encode("utf-8")

    def read(self, n: int = -1) -> bytes:
        data, self._body = self._body, b""
        if n is not None and n >= 0:
            return data[:n]
        return data


class ScriptedConn:
    def __init__(self, script: list[Any], *, shared: bool = False) -> None:
        self.script = script if shared else list(script)
        self.requests: list[tuple[str, str]] = []
        self.closed = False

    def request(self, method: str, url: str, headers: dict[str, str] | None = None) -> None:
        self.requests.append((method, url))
        self._pending = True

    def getresponse(self) -> Any:
        if not self.script:
            raise ConnectionError("script exhausted")
        item = self.script.pop(0)
        if item == "drop":
            raise ConnectionResetError("dropped secret=" + MOCK_SECRET)
        if item == "timeout":
            raise TimeoutError("timeout url=https://api.mairuiapi.com/" + MOCK_SECRET)
        if item == "remote":
            raise http.client.RemoteDisconnected("Remote end closed " + MOCK_SECRET)
        status, body = item
        return FakeResp(status, body)

    def close(self) -> None:
        self.closed = True


class FakePg:
    """内存假库：模拟 psycopg 3 的 cursor/transaction，不连真实 PG。"""

    def __init__(self) -> None:
        self.table: dict[tuple[str, str, str], tuple[Any, ...]] = {}
        self.statements: list[str] = []
        self.committed = 0
        self.rolled_back = 0
        self.closed = False
        self.fail_insert = False
        self.dsns: list[str] = []

    def execute(self, statement: Any) -> Any:
        # 公共 writer 的 SQLAlchemy 假连接；沿用原有表、事务与故障注入。
        from types import SimpleNamespace
        from sqlalchemy.dialects.postgresql import dialect

        sql = str(statement.compile(dialect=dialect()))
        params = statement.compile(dialect=dialect()).params
        self.statements.append(sql)
        columns = ("code", "trade_date", "adj_type", "open", "high", "low", "close",
                   "pre_close", "volume", "amount", "is_suspended", "source", "source_licence_id")
        result = []
        if getattr(statement, "is_insert", False):
            if self.fail_insert:
                raise RuntimeError("insert failed dsn=postgresql://mock-should-not-log")
            for name in params:
                if not name.startswith("code_m"):
                    continue
                suffix = name[len("code"):]
                row = {column: params[column + suffix] for column in columns}
                key = tuple(str(row[column]) for column in columns[:3])
                if key not in self.table:
                    self.table[key] = tuple(str(row[c]) if c in ("trade_date", "source_licence_id")
                                            and row[c] is not None else row[c] for c in columns)
                    result.append(row)
        else:
            for values in self.table.values():
                row = dict(zip(columns, values))
                row["trade_date"] = date.fromisoformat(row["trade_date"])
                result.append(row)
        return SimpleNamespace(all=lambda: [SimpleNamespace(**row) for row in result],
                               mappings=lambda: result)

    def transaction(self) -> Any:
        return _FakeTx(self)

    def cursor(self) -> Any:
        return _FakeCursor(self)

    def close(self) -> None:
        self.closed = True


class _FakeTx:
    def __init__(self, conn: FakePg) -> None:
        self.conn = conn

    def __enter__(self) -> FakePg:
        return self.conn

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        if exc_type:
            self.conn.rolled_back += 1
        else:
            self.conn.committed += 1
        return False


class _FakeCursor:
    def __init__(self, conn: FakePg) -> None:
        self.conn = conn
        self._result: Any = None

    def __enter__(self) -> "_FakeCursor":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.conn.statements.append(sql)
        stripped = " ".join(sql.split()).lower()
        if stripped.startswith("select count"):
            self._result = (len(self.conn.table),)
            return
        raise AssertionError("unexpected sql")

    def executemany(self, sql: str, seq: list[Any]) -> None:
        self.conn.statements.append(sql)
        upper = sql.upper()
        assert "ON CONFLICT" in upper and "DO NOTHING" in upper
        assert "%s" in sql
        assert "DELETE" not in upper and "TRUNCATE" not in upper and "UPDATE " not in upper
        assert "ALTER" not in upper and "DROP" not in upper
        if self.conn.fail_insert:
            raise RuntimeError("insert failed dsn=postgresql://mock-should-not-log")
        for params in seq:
            key = (str(params[0]), str(params[1]), str(params[2]))
            if key not in self.conn.table:
                self.conn.table[key] = tuple(params)
        self._result = None

    def fetchone(self) -> Any:
        return self._result


def _workspace(tmp: Path) -> dict[str, Path]:
    counter = tmp / "mairui-batch-T-B140.count"
    stop = tmp / "mairui-T-B140.STOP"
    run = tmp / "run"
    lic = tmp / "licence.tmp"
    codes = tmp / "codes.txt"
    run.mkdir()
    fd = os.open(counter, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(bf.default_counter(), fh)
    os.chmod(counter, 0o600)
    fd = os.open(lic, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(MOCK_SECRET)
    os.chmod(lic, 0o600)
    codes.write_text("000001\n600519\n920982\n", encoding="utf-8")
    return {"counter": counter, "stop": stop, "run": run, "lic": lic, "codes": codes}


def _clock(steps: list[float]) -> tuple[Any, list[float]]:
    sleeps: list[float] = []
    t = {"v": 0.0}

    def now() -> float:
        return t["v"]

    def sleep(sec: float) -> None:
        sleeps.append(sec)
        t["v"] += float(sec)

    steps.append(0)  # holder unused
    return now, sleep, sleeps, t


def test_success_and_redaction() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        bars = [_bar(t="2024-06-03"), _bar(t="2024-06-04")]
        conn = ScriptedConn([(200, bars)])
        now, sleep, sleeps, box = _clock([])
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary = bf.run_batch(st="20231113", et="20261113",
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                max_calls=1,
                interval=1.0,
                connection_factory=lambda: conn,
                sleeper=sleep,
                clock=now,
            )
        assert summary["calls"] == 1 and summary["done"] == 1 and summary["halt"] is None
        assert sleeps and sleeps[0] >= 1.0
        assert conn.closed is True
        assert len(conn.requests) == 1
        method, url = conn.requests[0]
        assert method == "GET"
        assert MOCK_SECRET in url  # 请求路径依法含证书
        assert "/hsstock/history/000001.SZ/d/n/" in url
        assert "st=20231113" in url and "et=20261113" in url
        out = buf.getvalue()
        assert MOCK_SECRET not in out
        dumped = (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
        assert MOCK_SECRET not in dumped
        assert "***" in dumped or "licence_deleted" in dumped
        saved = json.loads((ws["run"] / "history" / "000001.SZ.json").read_text(encoding="utf-8"))
        assert saved["n"] == 2 and saved["code"] == "000001.SZ"
        blob = json.dumps(saved)
        assert MOCK_SECRET not in blob
        sql = (ws["run"] / "sql" / "000001.SZ.sql").read_text(encoding="utf-8")
        assert MOCK_SECRET not in sql
        assert "ON CONFLICT" in sql
        assert not ws["lic"].exists()
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["total"] == 1 and state["done_history"] == ["000001"]
        assert state["halted"] is False
        # 920 不会被写成 .SH
        assert "920982.SH" not in sql


def test_429_is_counted_and_halts() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        conn = ScriptedConn([(429, "103:同一Licence证书在60秒内最多允许2个不同IP访问")])
        now, sleep, sleeps, _ = _clock([])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                bf.run_batch(
                    codes_file=ws["codes"],
                    licence_file=ws["lic"],
                    counter_path=ws["counter"],
                    stop_path=ws["stop"],
                    run_dir=ws["run"],
                    max_calls=3,
                    interval=1.0,
                    connection_factory=lambda: conn,
                    sleeper=sleep,
                    clock=now,
                )
            raise Fail("429 should halt")
        except bf.Halt as exc:
            assert "429" in str(exc) or "rate" in str(exc)
        out = buf.getvalue()
        assert MOCK_SECRET not in out
        summary = json.loads((ws["run"] / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert summary["calls"] == 1, summary  # 既有脚本漏记此项
        assert summary["halted"] is True
        assert summary["licence_deleted"] is True
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["total"] == 1
        assert state["halted"] is True
        assert state["done_history"] == []  # 失败代码不记完成，可续接
        assert ws["stop"].exists()
        assert not ws["lic"].exists()
        # 不会发第 2 次请求
        assert len(conn.requests) == 1
        joined = out + ws["stop"].read_text(encoding="utf-8") + json.dumps(summary)
        assert MOCK_SECRET not in joined


def test_existing_stop_not_cleared_and_no_request() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        ws["stop"].write_text("OLD_STOP_LINE_KEEP_ME\n", encoding="utf-8")
        called = {"n": 0}

        def factory() -> Any:
            called["n"] += 1
            raise Fail("factory should not run")

        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                bf.run_batch(
                    codes_file=ws["codes"],
                    licence_file=ws["lic"],
                    counter_path=ws["counter"],
                    stop_path=ws["stop"],
                    run_dir=ws["run"],
                    connection_factory=factory,
                    sleeper=lambda _s: None,
                    clock=lambda: 0.0,
                )
            raise Fail("STOP should refuse")
        except bf.Halt as exc:
            assert str(exc) == "STOP"
        assert called["n"] == 0
        assert ws["stop"].read_text(encoding="utf-8").startswith("OLD_STOP_LINE_KEEP_ME")
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["total"] == 0 and state["halted"] is True
        assert state["halt_reason"] == "STOP"
        assert ws["stop"].read_text(encoding="utf-8").splitlines()[-1].endswith(" STOP")
        assert not ws["lic"].exists()


def test_redirect_and_drop_halt_no_retry() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        conn = ScriptedConn([(302, "moved"), (200, [_bar()])])
        try:
            bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                connection_factory=lambda: conn,
                sleeper=lambda _s: None,
                clock=lambda: 0.0,
            )
            raise Fail("redirect should halt")
        except bf.Halt:
            pass
        assert len(conn.requests) == 1  # 不跟随、不重试
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is True and state["total"] == 1

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        conn = ScriptedConn(["drop", (200, [_bar()])])
        sleeps: list[float] = []
        bf.run_batch(
            codes_file=ws["codes"],
            licence_file=ws["lic"],
            counter_path=ws["counter"],
            stop_path=ws["stop"],
            run_dir=ws["run"],
            max_calls=1,
            connection_factory=lambda: conn,
            sleeper=lambda s: sleeps.append(float(s)),
            clock=lambda: 0.0,
        )
        # 传输失败改为等 60 秒后续接同一只，不再立即熔断
        assert len(conn.requests) == 2
        assert 60.0 in sleeps
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is False and state["done_history"] == ["000001"]
        assert state["total"] == 2  # 首次与重试都先记账
        dumped = (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
        assert "ConnectionResetError" in dumped
        assert "dropped secret=" not in dumped
        assert MOCK_SECRET not in dumped


def test_business_limit_on_200() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        conn = ScriptedConn([(200, {"code": "103", "msg": "限流"})])
        try:
            bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                connection_factory=lambda: conn,
                sleeper=lambda _s: None,
                clock=lambda: 0.0,
            )
            raise Fail("business limit should halt")
        except bf.Halt as exc:
            assert "rate" in str(exc) or "103" in str(exc)
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is True and state["total"] == 1 and state["done_history"] == []


def test_single_connection_reused() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        made: list[ScriptedConn] = []

        def factory() -> ScriptedConn:
            conn = ScriptedConn([(200, [_bar()]), (200, [_bar(t="2024-02-01")])])
            made.append(conn)
            return conn

        now, sleep, sleeps, t = _clock([])
        # 让两次请求都能看到间隔
        bf.run_batch(
            codes_file=ws["codes"],
            licence_file=ws["lic"],
            counter_path=ws["counter"],
            stop_path=ws["stop"],
            run_dir=ws["run"],
            max_calls=2,
            interval=1.0,
            connection_factory=factory,
            sleeper=sleep,
            clock=now,
        )
        assert len(made) == 1
        assert len(made[0].requests) == 2
        assert len(sleeps) >= 2 and all(s >= 1.0 for s in sleeps[:2])
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["done_history"] == ["000001", "600519"]
        # 第二只应标 SH
        assert (ws["run"] / "history" / "600519.SH.json").exists()


def test_fail_closed_counter_and_mode() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        ws["counter"].unlink()
        try:
            bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                connection_factory=lambda: ScriptedConn([]),
                sleeper=lambda _s: None,
                clock=lambda: 0.0,
            )
            raise Fail("missing counter should fail closed")
        except bf.Halt as exc:
            assert "counter_missing" in str(exc)
        assert not ws["lic"].exists()
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        os.chmod(ws["lic"], 0o644)
        try:
            bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                connection_factory=lambda: ScriptedConn([(200, [_bar()])]),
                sleeper=lambda _s: None,
                clock=lambda: 0.0,
            )
            raise Fail("0644 licence should be refused")
        except bf.Halt as exc:
            assert "permissions" in str(exc)
        # 即使拒绝读取，finally 仍删除临时证书
        assert not ws["lic"].exists()


def test_stdlib_only_and_no_live_host() -> None:
    import re
    for mod in ("tb140_history_backfill", "tb140_history_load"):
        src = (PROBES / f"{mod}.py").read_text(encoding="utf-8")
        assert not re.search(r"^\s*(import|from)\s+(requests|httpx)\b", src, re.M)
        assert "os.environ" not in src and "MAIRUI_LICENCE" not in src
    assert bf.HOST == "api.mairuiapi.com"
    assert "http.client" in (PROBES / "tb140_history_backfill.py").read_text(encoding="utf-8")
    assert "set_tunnel" not in (PROBES / "tb140_history_backfill.py").read_text(encoding="utf-8")
    svsrc = (PROBES / "tb140_history_supervisor.py").read_text(encoding="utf-8")
    assert not re.search(r"^\s*(import|from)\s+(requests|httpx)\b", svsrc, re.M)
    assert "MAIRUI_LICENCE" not in svsrc
    assert "clear-stop" not in svsrc and "reset-halted" not in svsrc and "init-counter" not in svsrc


def test_checkpoint_resume() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        state = bf.default_counter()
        state["done_history"] = ["000001"]
        state["total"] = 5
        bf.atomic_save(ws["counter"], state)
        conn = ScriptedConn([(200, [_bar(t="2024-03-01")])])
        bf.run_batch(
            codes_file=ws["codes"],
            licence_file=ws["lic"],
            counter_path=ws["counter"],
            stop_path=ws["stop"],
            run_dir=ws["run"],
            max_calls=1,
            interval=1.0,
            connection_factory=lambda: conn,
            sleeper=lambda _s: None,
            clock=lambda: 0.0,
        )
        method, url = conn.requests[0]
        assert "600519.SH" in url
        assert "000001" not in url
        new_state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert new_state["total"] == 6
        assert new_state["done_history"] == ["000001", "600519"]



MOCK_DSN = "postgresql+psycopg://mock:mock@127.0.0.1:1/mockdb"
MOCK_ENV = {"DATABASE_URL": MOCK_DSN}


def _request_count(conns: list[ScriptedConn]) -> int:
    return sum(len(c.requests) for c in conns)


def test_transport_resume_three_then_success() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        queue: list[Any] = ["remote", "timeout", "drop", (200, [_bar()])]
        made: list[ScriptedConn] = []

        def factory() -> ScriptedConn:
            conn = ScriptedConn(queue, shared=True)
            made.append(conn)
            return conn

        now, sleep, sleeps, _ = _clock([])
        buf = io.StringIO()
        with redirect_stdout(buf):
            summary = bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                max_calls=1,
                interval=1.0,
                connection_factory=factory,
                sleeper=sleep,
                clock=now,
            )
        assert summary["halt"] is None
        assert len(made) == 4  # 初始 + 三次重建
        assert _request_count(made) == 4
        assert sleeps.count(60.0) == 3
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is False
        assert state["done_history"] == ["000001"]
        assert state["total"] == 4
        dumped = buf.getvalue() + (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
        for name in ("RemoteDisconnected", "TimeoutError", "ConnectionResetError"):
            assert name in dumped
        assert "dropped secret=" not in dumped
        assert "timeout url=" not in dumped
        assert "Remote end closed" not in dumped
        assert MOCK_SECRET not in dumped
        assert not ws["lic"].exists()


def test_transport_fourth_halts() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        queue: list[Any] = ["drop", "drop", "drop", "drop", (200, [_bar()])]
        made: list[ScriptedConn] = []

        def factory() -> ScriptedConn:
            conn = ScriptedConn(queue, shared=True)
            made.append(conn)
            return conn

        now, sleep, sleeps, _ = _clock([])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                bf.run_batch(
                    codes_file=ws["codes"],
                    licence_file=ws["lic"],
                    counter_path=ws["counter"],
                    stop_path=ws["stop"],
                    run_dir=ws["run"],
                    max_calls=1,
                    interval=1.0,
                    connection_factory=factory,
                    sleeper=sleep,
                    clock=now,
                )
            raise Fail("fourth transport failure should halt")
        except bf.Halt as exc:
            assert "transport" in str(exc)
            assert "ConnectionResetError" in str(exc)
        assert len(made) == 4
        assert _request_count(made) == 4
        assert sleeps.count(60.0) == 3  # 第 4 次不再等 60 秒续接
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is True and state["done_history"] == []
        assert state["total"] == 4
        assert ws["stop"].exists()
        assert not (ws["run"] / "history" / "000001.SZ.json").exists()
        dumped = buf.getvalue() + (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
        assert "ConnectionResetError" in dumped
        assert "dropped secret=" not in dumped
        assert MOCK_SECRET not in dumped
        assert not ws["lic"].exists()


def test_fuse_codes_do_not_retry() -> None:
    """非 200 / JSON 或纯文本业务停止码 / 已有 STOP：不重试、不等 60 秒。"""
    cases = [
        ("http503", (503, "unavailable body " + MOCK_SECRET + ("Z" * 400)), "503"),
        ("http429", (429, "103:同一Licence证书"), "429"),
        ("http302", (302, "redirect"), "302"),
        ("http500", (500, "server error"), "500"),
        ("http503_non_utf8", (503, b"\xff"), "503"),
        ("biz101", (200, {"code": 101}), "rate"),
        ("biz103_code_only", (200, {"code": "103"}), "rate"),
        ("biz429", (200, {"code": 429}), "rate"),
        ("biz103", (200, {"code": "103", "msg": "限流"}), "rate"),
        ("text101", (200, "101:quota"), "rate"),
        ("text103", (200, "103:quota"), "rate"),
        ("text429", (200, "429:quota"), "rate"),
    ]
    for label, script_item, needle in cases:
        with tempfile.TemporaryDirectory() as raw:
            tmp = Path(raw)
            ws = _workspace(tmp)
            made: list[ScriptedConn] = []

            def factory(item: Any = script_item, bucket: list[ScriptedConn] = made) -> ScriptedConn:
                conn = ScriptedConn([item, (200, [_bar()])])
                bucket.append(conn)
                return conn

            now, sleep, sleeps, _ = _clock([])
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    bf.run_batch(
                        codes_file=ws["codes"],
                        licence_file=ws["lic"],
                        counter_path=ws["counter"],
                        stop_path=ws["stop"],
                        run_dir=ws["run"],
                        max_calls=2,
                        interval=1.0,
                        connection_factory=factory,
                        sleeper=sleep,
                        clock=now,
                    )
                raise Fail(f"{label} should halt")
            except bf.Halt as exc:
                text = str(exc)
                assert needle in text, (label, text)
            assert len(made) == 1
            assert _request_count(made) == 1
            assert 60.0 not in sleeps
            state = json.loads(ws["counter"].read_text(encoding="utf-8"))
            assert state["halted"] is True and state["done_history"] == []
            assert state["total"] == 1
            assert ws["stop"].read_text(encoding="utf-8").splitlines()[-1].endswith(state["halt_reason"])
            assert made[0].closed is True
            dumped = buf.getvalue() + (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
            assert MOCK_SECRET not in dumped
            if label == "http503":
                line = json.loads((ws["run"] / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
                preview = line.get("http_body_preview") or ""
                assert preview.startswith("unavailable body ")
                assert "***" in preview
                assert MOCK_SECRET not in preview
                assert len(preview.encode("utf-8")) <= 300 or preview.count("Z") <= 300
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        ws["stop"].write_text("OLD_STOP_LINE_KEEP_ME\n", encoding="utf-8")
        called = {"n": 0}

        def factory() -> Any:
            called["n"] += 1
            raise Fail("STOP should not open connection")

        try:
            bf.run_batch(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                connection_factory=factory,
                sleeper=lambda _s: None,
                clock=lambda: 0.0,
            )
            raise Fail("STOP should refuse")
        except bf.Halt as exc:
            assert str(exc) == "STOP"
        assert called["n"] == 0
        assert ws["stop"].read_text(encoding="utf-8").startswith("OLD_STOP_LINE_KEEP_ME")


def test_non_200_body_failure_does_not_retry() -> None:
    class BrokenBodyResp(FakeResp):
        def read(self, n: int = -1) -> bytes:
            raise TimeoutError("mock response body timeout")

    class BrokenBodyConn(ScriptedConn):
        def getresponse(self) -> Any:
            status, body = self.script.pop(0)
            return BrokenBodyResp(status, body)

    for status in (429, 503, 500):
        with tempfile.TemporaryDirectory() as raw:
            ws = _workspace(Path(raw))
            conn = BrokenBodyConn([(status, None)])
            now, sleep, sleeps, _ = _clock([])
            try:
                with redirect_stdout(io.StringIO()):
                    bf.run_batch(
                        codes_file=ws["codes"], licence_file=ws["lic"],
                        counter_path=ws["counter"], stop_path=ws["stop"],
                        run_dir=ws["run"], connection_factory=lambda: conn,
                        sleeper=sleep, clock=now,
                    )
                raise Fail("non-200 must halt even if body read fails")
            except bf.Halt as exc:
                assert str(exc).startswith(f"HTTP_{status}")
            state = bf.load_counter(ws["counter"])
            assert state["halted"] is True and state["total"] == 1
            assert ws["stop"].read_text(encoding="utf-8").splitlines()[-1].endswith(state["halt_reason"])
            assert len(conn.requests) == 1 and conn.closed is True
            assert 60.0 not in sleeps


def test_cross_batch_db_and_checkpoint() -> None:
    # 20 只人工合成 BJ 对照，只确认量单位，不读取真实行情或证券样本。
    ld.confirm_bj_offline_volume_units([
        {
            "mairui": {"code": f"{920801 + offset}.BJ", "t": "2024-01-04", "v": 2 + offset},
            "tdx_local": {"code": f"{920801 + offset}.BJ", "trade_date": "2024-01-04",
                          "source": "tdx_local", "volume": 200 + offset * 100},
        }
        for offset in range(20)
    ])
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        script: list[Any] = [
            (200, [_bar(t="2024-01-02")]),
            (200, [_bar(t="2024-01-03")]),
            (200, [_bar(t="2024-01-04")]),
        ]
        made: list[ScriptedConn] = []

        def factory() -> ScriptedConn:
            conn = ScriptedConn(script, shared=True)
            made.append(conn)
            return conn

        db = FakePg()
        seen_dsn: list[str] = []

        def connect(dsn: str) -> FakePg:
            seen_dsn.append(dsn)
            return db

        now, sleep, sleeps, _ = _clock([])
        buf = io.StringIO()
        with redirect_stdout(buf):
            overall = sv.run_supervised(
                codes_file=ws["codes"],
                licence_file=ws["lic"],
                counter_path=ws["counter"],
                stop_path=ws["stop"],
                run_dir=ws["run"],
                max_calls=2,
                interval=2.0,
                connection_factory=factory,
                sleeper=sleep,
                clock=now,
                environ=MOCK_ENV,
                db_connect=connect,
            )
        assert overall["halt"] is None
        assert overall["batches"] == 2
        assert overall["done"] == 3
        assert len(made) == 1  # 跨批复用同一条连接，传输未失败则不重建
        assert _request_count(made) == 3
        assert 60.0 not in sleeps
        assert all(s >= 2.0 or s == 0 for s in sleeps) or all(s >= 2.0 for s in sleeps if s != 60.0)
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["done_history"] == ["000001", "600519", "920982"]
        assert state["halted"] is False
        assert db.committed == 2
        assert db.closed is True
        assert len(db.table) == 3
        keys = set(db.table)
        assert ("000001.SZ", "2024-01-02", "none") in keys
        assert ("600519.SH", "2024-01-03", "none") in keys
        assert ("920982.BJ", "2024-01-04", "none") in keys
        assert seen_dsn == ["postgresql://mock:mock@127.0.0.1:1/mockdb"]
        assert ld.to_psycopg_dsn(MOCK_DSN) == "postgresql://mock:mock@127.0.0.1:1/mockdb"
        lines = (ws["run"] / "runs.jsonl").read_text(encoding="utf-8").splitlines()
        batch_lines = [json.loads(x) for x in lines if json.loads(x).get("mode") == "history"]
        assert len(batch_lines) == 2
        assert batch_lines[0]["db_count_before"] == 0
        assert batch_lines[0]["db_count_after"] == 2
        assert batch_lines[0]["db_inserted"] == 2
        assert batch_lines[1]["db_count_before"] == 2
        assert batch_lines[1]["db_count_after"] == 3
        assert batch_lines[1]["db_inserted"] == 1
        out = buf.getvalue() + "\n".join(lines)
        assert MOCK_SECRET not in out
        assert MOCK_DSN not in out
        assert "postgresql://mock:mock@" not in out
        assert not ws["lic"].exists()
        assert (ws["run"] / "sql" / "000001.SZ.sql").exists()
        assert (ws["run"] / "sql" / "920982.BJ.sql").exists()


def test_supervisor_interval_and_db_failure() -> None:
    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                sv.run_supervised(
                    codes_file=ws["codes"],
                    licence_file=ws["lic"],
                    counter_path=ws["counter"],
                    stop_path=ws["stop"],
                    run_dir=ws["run"],
                    interval=0.19,
                    connection_factory=lambda: ScriptedConn([]),
                    sleeper=lambda _s: None,
                    clock=lambda: 0.0,
                    environ=MOCK_ENV,
                    db_connect=lambda _d: FakePg(),
                )
            raise Fail("interval 0.19 should be rejected by supervisor")
        except bf.Halt as exc:
            assert "interval" in str(exc)
        assert not ws["lic"].exists()
        assert json.loads(ws["counter"].read_text(encoding="utf-8"))["halted"] is False

    with tempfile.TemporaryDirectory() as raw:
        tmp = Path(raw)
        ws = _workspace(tmp)
        db = FakePg()
        db.fail_insert = True
        now, sleep, sleeps, _ = _clock([])
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                sv.run_supervised(
                    codes_file=ws["codes"],
                    licence_file=ws["lic"],
                    counter_path=ws["counter"],
                    stop_path=ws["stop"],
                    run_dir=ws["run"],
                    max_calls=1,
                    interval=2.0,
                    connection_factory=lambda: ScriptedConn([(200, [_bar()])]),
                    sleeper=sleep,
                    clock=now,
                    environ=MOCK_ENV,
                    db_connect=lambda _d: db,
                )
            raise Fail("db write failure should halt")
        except bf.Halt as exc:
            assert str(exc) == "db_write_failed"
        state = json.loads(ws["counter"].read_text(encoding="utf-8"))
        assert state["halted"] is True
        assert ws["stop"].exists()
        dumped = buf.getvalue() + (ws["run"] / "runs.jsonl").read_text(encoding="utf-8")
        assert "mock-should-not-log" not in dumped
        assert MOCK_SECRET not in dumped
        assert MOCK_DSN not in dumped
        assert not ws["lic"].exists()


def _check_interval(*, supervised: bool, interval: float, accepted: bool) -> None:
    with tempfile.TemporaryDirectory() as raw:
        ws = _workspace(Path(raw))
        conn = ScriptedConn([(200, [_bar()])] * 3)
        now, sleep, sleeps, _ = _clock([])
        kwargs: dict[str, Any] = {
            "codes_file": ws["codes"],
            "licence_file": ws["lic"],
            "counter_path": ws["counter"],
            "stop_path": ws["stop"],
            "run_dir": ws["run"],
            "max_calls": 2,
            "interval": interval,
            "connection_factory": lambda: conn,
            "sleeper": sleep,
            "clock": now,
        }
        runner = sv.run_supervised if supervised else bf.run_batch
        if supervised:
            kwargs.update(environ=MOCK_ENV, db_connect=lambda _d: FakePg())
        try:
            with redirect_stdout(io.StringIO()):
                summary = runner(**kwargs)
        except bf.Halt as exc:
            assert not accepted, str(exc)
            assert str(exc) == "interval_below_minimum"
        else:
            assert accepted, "interval below floor should be rejected"
            expected = 3 if supervised else 2
            assert summary["done"] == expected and summary["halt"] is None
            assert len(conn.requests) == expected
            assert len(sleeps) == expected and all(s >= 0.2 for s in sleeps)
        state = bf.load_counter(ws["counter"])
        assert state["halted"] is False
        if not accepted:
            assert conn.requests == [] and sleeps == [] and state["total"] == 0
        assert not ws["lic"].exists()


def test_backfill_interval_floor_accepted() -> None:
    _check_interval(supervised=False, interval=0.2, accepted=True)


def test_backfill_interval_below_floor_rejected() -> None:
    _check_interval(supervised=False, interval=0.19, accepted=False)


def test_supervisor_interval_floor_accepted() -> None:
    assert sv.build_parser().get_default("interval") == 2.0
    assert "小于 0.2 拒绝" in sv.build_parser().format_help()
    _check_interval(supervised=True, interval=0.2, accepted=True)


def test_supervisor_interval_below_floor_rejected() -> None:
    _check_interval(supervised=True, interval=0.19, accepted=False)


def test_direct_http_client_connection() -> None:
    # 同时替换 TLS 上下文及连接构造器，既不读证书也不打开网络。
    with patch.object(bf.ssl, "create_default_context") as context_factory:
        with patch.object(bf.http.client, "HTTPSConnection") as connection_factory:
            conn = bf.open_connection(timeout=12.0)
            connection_factory.assert_called_once_with(
                bf.HOST, timeout=12.0, context=context_factory.return_value,
            )
            assert conn is connection_factory.return_value
            conn.set_tunnel.assert_not_called()


def test_proxy_env_presence_only() -> None:
    class PresenceOnlyEnv(dict):
        def __getitem__(self, key: str) -> str:
            assert key not in sv.PROXY_ENV_NAMES, "proxy value must not be read"
            return super().__getitem__(key)

        def get(self, key: str, default: Any = None) -> Any:
            assert key not in sv.PROXY_ENV_NAMES, "proxy value must not be read"
            return super().get(key, default)

    # 空值也算变量存在；同时覆盖大小写，且日志只含布尔值。
    for name in (None, *sv.PROXY_ENV_NAMES):
        with tempfile.TemporaryDirectory() as raw:
            ws = _workspace(Path(raw))
            env = PresenceOnlyEnv(MOCK_ENV)
            if name is not None:
                env[name] = ""
            conn = ScriptedConn([(200, [_bar()])] * 3)
            now, sleep, _, _ = _clock([])
            with redirect_stdout(io.StringIO()):
                overall = sv.run_supervised(
                    codes_file=ws["codes"], licence_file=ws["lic"],
                    counter_path=ws["counter"], stop_path=ws["stop"],
                    run_dir=ws["run"], connection_factory=lambda: conn,
                    sleeper=sleep, clock=now, environ=env,
                    db_connect=lambda _d: FakePg(),
                )
            logged = json.loads((ws["run"] / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
            for record in (overall, logged):
                assert type(record["proxy_env_present"]) is bool
                assert record["proxy_env_present"] is (name is not None)


def test_supervisor_existing_stop_halts_and_appends() -> None:
    with tempfile.TemporaryDirectory() as raw:
        ws = _workspace(Path(raw))
        old = "OLD_STOP_LINE_KEEP_ME\n"
        ws["stop"].write_text(old, encoding="utf-8")

        def forbidden(*_args: Any) -> Any:
            raise Fail("STOP must refuse before connecting")

        try:
            with redirect_stdout(io.StringIO()):
                sv.run_supervised(
                    codes_file=ws["codes"], licence_file=ws["lic"],
                    counter_path=ws["counter"], stop_path=ws["stop"],
                    run_dir=ws["run"], connection_factory=forbidden,
                    sleeper=forbidden, environ=MOCK_ENV, db_connect=forbidden,
                )
            raise Fail("STOP should refuse")
        except bf.Halt as exc:
            assert str(exc) == "STOP"
        state = bf.load_counter(ws["counter"])
        assert state["halted"] is True and state["halt_reason"] == "STOP"
        assert state["total"] == 0
        text = ws["stop"].read_text(encoding="utf-8")
        assert text.startswith(old) and text.splitlines()[-1].endswith(" STOP")
        overall = json.loads((ws["run"] / "runs.jsonl").read_text(encoding="utf-8").splitlines()[-1])
        assert type(overall["proxy_env_present"]) is bool


def test_parameterized_insert_and_conflict() -> None:
    rows, _ = ld.normalize_history("000001", [_bar()])
    db = FakePg()
    first = ld.apply_daily_bars(db, rows, None)
    assert first == {"count_before": 0, "count_after": 1, "inserted": 1}
    again = ld.apply_daily_bars(db, rows, None)
    assert again == {"count_before": 1, "count_after": 1, "inserted": 0}
    sql = " ".join(db.statements)
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql
    assert "DELETE" not in sql.upper() and "TRUNCATE" not in sql.upper()
    uid = "12345678-1234-4234-8234-123456789abc"
    db2 = FakePg()
    ld.apply_daily_bars(db2, rows, uid)
    params = next(iter(db2.table.values()))
    assert params[-1] == uid and params[0] == "000001.SZ" and params[8] == 1200


def main() -> int:
    tests = [
        ("market_prefixes_vs_old_bug", test_market_prefixes),
        ("normalize_units_adj_identity", test_normalize_and_units),
        ("validation_rejects", test_validation_rejects),
        ("sql_conflict_and_licence_bind", test_sql_and_conflict),
        ("offline_insert_blocks_unconfirmed_bj", test_offline_insert_blocks_unconfirmed_bj),
        ("success_redaction_interval", test_success_and_redaction),
        ("calls_counted_on_429", test_429_is_counted_and_halts),
        ("existing_stop_preserved", test_existing_stop_not_cleared_and_no_request),
        ("redirect_and_drop_no_retry", test_redirect_and_drop_halt_no_retry),
        ("business_limit_on_200", test_business_limit_on_200),
        ("single_connection_reused", test_single_connection_reused),
        ("fail_closed_counter_and_mode", test_fail_closed_counter_and_mode),
        ("stdlib_only_no_env_licence", test_stdlib_only_and_no_live_host),
        ("checkpoint_resume", test_checkpoint_resume),
        ("transport_resume_three_then_success", test_transport_resume_three_then_success),
        ("transport_fourth_halts", test_transport_fourth_halts),
        ("fuse_codes_do_not_retry", test_fuse_codes_do_not_retry),
        ("non_200_body_failure_does_not_retry", test_non_200_body_failure_does_not_retry),
        ("cross_batch_db_and_checkpoint", test_cross_batch_db_and_checkpoint),
        ("supervisor_interval_and_db_failure", test_supervisor_interval_and_db_failure),
        ("backfill_interval_0.2_accepted", test_backfill_interval_floor_accepted),
        ("backfill_interval_0.19_rejected", test_backfill_interval_below_floor_rejected),
        ("supervisor_interval_0.2_accepted", test_supervisor_interval_floor_accepted),
        ("supervisor_interval_0.19_rejected", test_supervisor_interval_below_floor_rejected),
        ("direct_http_client_connection", test_direct_http_client_connection),
        ("proxy_env_presence_only", test_proxy_env_presence_only),
        ("supervisor_existing_stop_halts_and_appends", test_supervisor_existing_stop_halts_and_appends),
        ("parameterized_insert_and_conflict", test_parameterized_insert_and_conflict),
    ]
    for name, fn in tests:
        check(name, fn)
    passed = sum(1 for _, s in RESULTS if s == "PASS")
    failed = [f"{n}: {s}" for n, s in RESULTS if s != "PASS"]
    print(json.dumps({"passed": passed, "failed": len(failed), "total": len(RESULTS), "detail": RESULTS}, ensure_ascii=False, indent=2))
    if failed:
        for line in failed:
            print(line, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

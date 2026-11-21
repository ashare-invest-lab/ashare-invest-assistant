"""T-T83 / #161：daily-bars-source §10.6 的离线路由与窗口契约。

全部证券、行情与凭据占位均为合成数据；禁网、假 transport 与假连接。
写入/来源优先级用例拆至 test_ta157_bj_writers.py，两个文件可独立运行。
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import socket
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlencode, urlsplit

import pytest

pytestmark = pytest.mark.unit

TOKEN = "SYNTHETIC licence/+?占位"
BJ_CODES = ("920997", "439997", "839997", "879997")
ROUTE_CODES = (*BJ_CODES, "600997", "000997")
BAR_COLUMNS = (
    "code",
    "trade_date",
    "adj_type",
    "open",
    "high",
    "low",
    "close",
    "pre_close",
    "volume",
    "amount",
    "is_suspended",
    "source",
    "source_licence_id",
)


@pytest.fixture(autouse=True)
def offline_only(monkeypatch):
    """生产模块导入前禁网；拦截环境文件和凭据文件的一切打开操作。"""
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "src/backend")
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    attempts = []

    def no_network(*_args, **_kwargs):
        attempts.append("network")
        pytest.fail("T-T83：禁止网络，只允许假 transport / 假连接")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, no_network)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, no_network)

    def guard_open(original):
        def guarded(file, *args, **kwargs):
            if isinstance(file, (str, bytes, os.PathLike)):
                path = Path(os.fsdecode(file))
                if (
                    path.name == ".env"
                    or path.name.startswith(".env.")
                    or path.suffix in {".pem", ".key"}
                    or any(p in {".aws", ".ssh", "secrets"} for p in path.parts)
                ):
                    pytest.fail("T-T83：禁止访问 .env 或密钥文件")
            return original(file, *args, **kwargs)

        return guarded

    for owner in (builtins, io, os):
        monkeypatch.setattr(owner, "open", guard_open(owner.open))
    gate = importlib.import_module("app.bj_offline_volume")
    monkeypatch.setattr(gate, "_bj_offline_volume_codes", frozenset())
    yield
    assert attempts == [], "真实网络调用次数必须为零"


@pytest.fixture
def api(monkeypatch):
    """脚本内部的裸导入指向同一个包模块，不复制代码、不替换被测函数。"""
    load = importlib.import_module("probes.tb140_history_load")
    monkeypatch.setitem(sys.modules, "tb140_history_load", load)
    backfill = importlib.import_module("probes.tb140_history_backfill")
    monkeypatch.setitem(sys.modules, "tb140_history_backfill", backfill)
    return SimpleNamespace(
        load=load,
        backfill=backfill,
        supervisor=importlib.import_module("probes.tb140_history_supervisor"),
        daily=importlib.import_module("probes.tb140_daily_bars"),
    )


def check(problems, condition, reason):
    if not condition:
        problems.append(reason)


def bar(day="2026-11-13", **changes):
    row = {
        "t": day,
        "o": "10",
        "h": "10",
        "l": "10",
        "c": "10",
        "v": "2",
        "a": "2000",
        "pc": "10",
        "sf": 0,
    }
    row.update(changes)
    return row


def counter():
    return {
        "schema": "T-B140/v1",
        "total": 7,
        "halted": False,
        "halt_reason": None,
        "by_kind": {"history": 7},
        "done_history": [],
    }


class Wire:
    """http.client 与 requests 两种假 transport 均保留最终请求 path。"""

    def __init__(self, body=None, status=200):
        self.body = [] if body is None else body
        self.status = status
        self.paths = []

    def request(self, method, path, headers=None):
        assert method == "GET"
        self.paths.append(path)

    def getresponse(self):
        raw = json.dumps(self.body, ensure_ascii=False).encode()
        return SimpleNamespace(status=self.status, read=lambda limit: raw[:limit])

    def get(self, url, params=None, **_kwargs):
        parsed = urlsplit(url)
        path = parsed.path + ("?" + parsed.query if parsed.query else "")
        if params:
            path += ("&" if parsed.query else "?") + urlencode(params)
        self.paths.append(path)
        return SimpleNamespace(
            status_code=self.status, content=b"fixture", json=lambda: self.body
        )

    def close(self):
        pass


class MemoryDB:
    """仅模拟 SQL 存储层；来源优先级、对账和事务选择必须由生产代码发起。"""

    def __init__(self, rows=()):
        self.rows = {self.key(row): deepcopy(row) for row in rows}
        self.statements = []
        self.events = []

    @staticmethod
    def key(row):
        return tuple(row[c] for c in BAR_COLUMNS[:3])

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

    def cursor(self):
        return MemoryCursor(self)

    def close(self):
        pass


class MemoryCursor:
    """Minimal DB-API adapter for the public SQLAlchemy writer path.

    The fixture stays synthetic and in-memory, but accepts the compiled SELECT/
    INSERT statements emitted by ``upsert_daily_bars`` so routing tests exercise
    the same production entry point as a psycopg connection.
    """

    def __init__(self, db):
        self.db = db
        self.rowcount = 0
        self.description = None
        self._result_rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, params=None):
        text = str(sql)
        self.db.statements.append((text, params))
        upper = text.lstrip().upper()
        values = params or {}
        self.rowcount = 0
        if upper.startswith("SELECT"):
            if "COUNT(" in upper:
                self.description = [SimpleNamespace(name="count")]
                self._result_rows = [(len(self.db.rows),)]
            else:
                self.description = [
                    SimpleNamespace(name=column) for column in BAR_COLUMNS
                ]
                self._result_rows = [
                    tuple(row.get(column) for column in BAR_COLUMNS)
                    for row in self.db.rows.values()
                ]
            return self
        if upper.startswith("INSERT"):
            suffixes = sorted(
                {key[len("code_") :] for key in values if key.startswith("code_")}
            )
            inserted = []
            for suffix in suffixes:
                row = {
                    column: values.get(f"{column}_{suffix}") for column in BAR_COLUMNS
                }
                key = self.db.key(row)
                if key not in self.db.rows:
                    self.db.rows[key] = row
                    inserted.append((row["code"], row["trade_date"], row["adj_type"]))
            self.rowcount = len(inserted)
            self.description = [
                SimpleNamespace(name=column)
                for column in ("code", "trade_date", "adj_type")
            ]
            self._result_rows = inserted
            return self
        raise AssertionError(text)

    def executemany(self, sql, rows):
        assert str(sql).lstrip().upper().startswith("INSERT")
        self.db.statements.append((str(sql), None))
        for values in rows:
            row = dict(zip(BAR_COLUMNS, values, strict=True))
            key = self.db.key(row)
            if key not in self.db.rows:
                self.db.rows[key] = row
                self.rowcount += 1

    def fetchone(self):
        if self._result_rows:
            return self._result_rows[0]
        return (len(self.db.rows),)

    def fetchall(self):
        return list(self._result_rows)


class NoCredentialFile:
    """旧 main 的 finally 可以调用清理接口，但没有任何证书文件操作。"""

    def unlink(self, **_kwargs):
        pass

    def exists(self):
        return False


def run_cli(
    api,
    monkeypatch,
    root,
    kind,
    *,
    codes=("600997",),
    body=None,
    options=(),
    state=None,
    status=200,
):
    """执行真实 CLI main；只有证书、HTTP、数据库和等待被替换。"""
    root.mkdir(parents=True)
    codes_file = root / "codes.txt"
    codes_file.write_text("\n".join(codes), encoding="utf-8")
    ledger = root / "counter.json"
    ledger.write_text(
        json.dumps(counter() if state is None else state), encoding="utf-8"
    )
    ledger.chmod(0o600)
    wire = Wire([bar()] if body is None else body, status)
    reads = []

    def read_placeholder(*_args):
        reads.append("placeholder")
        return TOKEN

    if kind == "daily":
        module = api.daily
        monkeypatch.setattr(module, "DATA", root)
        monkeypatch.setattr(module, "COUNTER", ledger)
        monkeypatch.setattr(module, "STOP", root / "STOP")
        monkeypatch.setattr(module, "TEMP_SECRET", NoCredentialFile())
        monkeypatch.setattr(module, "write_secret", read_placeholder)
        monkeypatch.setattr(module, "session", lambda: wire)
        argv = ["history", "--codes-file", str(codes_file), *options]
        monkeypatch.setattr(sys, "argv", ["tb140_daily_bars", *argv])
        call = module.main
    else:
        module = getattr(api, kind)
        for target in (api.backfill, api.supervisor):
            monkeypatch.setattr(target, "read_licence_file", read_placeholder)
            monkeypatch.setattr(target, "delete_licence_file", lambda _path: True)
        monkeypatch.setattr(api.backfill, "open_connection", lambda: wire)
        monkeypatch.setattr(api.backfill.time, "sleep", lambda _seconds: None)
        monkeypatch.setattr(
            api.supervisor, "read_named_dsn", lambda *_args: "fixture-dsn"
        )
        monkeypatch.setattr(
            api.supervisor, "default_psycopg_connect", lambda _dsn: MemoryDB()
        )
        monkeypatch.setattr(api.supervisor, "PROXY_ENV_NAMES", ())
        argv = [
            "--codes-file",
            str(codes_file),
            "--licence-file",
            str(root / "unused"),
            "--counter",
            str(ledger),
            "--stop-file",
            str(root / "STOP"),
            "--run-dir",
            str(root),
            "--interval",
            "0.2",
            *options,
        ]

        def call():
            return module.main(argv)

    try:
        rc = call()
    except SystemExit as exc:
        rc = exc.code
    except api.load.CodeReject:
        rc = 1
    summaries = []
    if (root / "runs.jsonl").exists():
        summaries = [
            json.loads(line) for line in (root / "runs.jsonl").read_text().splitlines()
        ]
    return SimpleNamespace(
        rc=rc, wire=wire, reads=reads, root=root, ledger=ledger, summaries=summaries
    )


def test_ta157_market_single_source(api):
    problems = []
    for code in BJ_CODES:
        markets = (api.daily.mkt(code), api.load.market_of(code))
        qualified = api.load.qualified_code(code)
        check(problems, markets == ("BJ", "BJ"), f"{code}: mkt/market_of 必须一致为 BJ")
        check(
            problems,
            qualified == code + ".BJ" and qualified.count(".BJ") == 1,
            f"{code}: 只加一次 .BJ，保留原裸码",
        )
    assert not problems, problems


def test_ta157_sh_sz_and_reject(api, monkeypatch, tmp_path):
    problems = []
    for code, market in (
        ("600997", "SH"),
        ("688997", "SH"),
        ("000997", "SZ"),
        ("300997", "SZ"),
    ):
        check(
            problems,
            api.daily.mkt(code) == api.load.market_of(code) == market,
            f"{code}: 白名单市场错误",
        )
        check(
            problems,
            api.load.qualified_code(code) == code + "." + market,
            f"{code}: 后缀错误",
        )
    for code in ("999997", "123997", "920997.BJ"):
        for function in (api.daily.mkt, api.load.market_of, api.load.qualified_code):
            try:
                function(code)
            except ValueError:
                pass
            else:
                problems.append(f"{function.__name__} 必须拒绝 {code}")
        for kind in ("backfill", "supervisor", "daily"):
            # 捕获输入拒绝，不将契约允许的拒绝异常误算作测试运行错误。
            result = run_cli(
                api, monkeypatch, tmp_path / f"{kind}-{code}", kind, codes=(code,)
            )
            check(
                problems,
                result.rc != 0 and result.wire.paths == [],
                f"{kind}: {code} 必须在请求前拒绝",
            )
    assert not problems, problems


def test_ta157_history_routes(api, monkeypatch, tmp_path, capsys):
    problems = []
    for code in BJ_CODES[1:]:
        assert api.load.market_of(code) == "BJ"
    expected = {
        "/bj/history/920997.BJ/d/n/" + quote(TOKEN, safe=""),
        "/hsstock/history/600997.SH/d/n/" + quote(TOKEN, safe=""),
        "/hsstock/history/000997.SZ/d/n/" + quote(TOKEN, safe=""),
    }
    for kind in ("backfill", "supervisor", "daily"):
        result = run_cli(api, monkeypatch, tmp_path / kind, kind, codes=ROUTE_CODES)
        output = capsys.readouterr().out
        paths = [urlsplit(path).path for path in result.wire.paths]
        safe_paths = [api.backfill.redact(path, TOKEN) for path in paths]
        check(
            problems,
            len(paths) == 3 and set(paths) == expected,
            f"{kind}: 仅请求 920 京市及沪深，43/83/87 请求数须为零；实际 {safe_paths}",
        )
        assert not any(code in path for code in BJ_CODES[1:] for path in paths)
        state = json.loads(result.ledger.read_text())
        assert set(state["done_history"]) == {"600997", "000997"}, kind
        assert not set(BJ_CODES) & set(state["done_history"]), kind
        assert set(state["history_windows"]) == {"600997", "000997"}, kind
        summary = result.summaries[-1]
        assert summary["blocked_bj_unconfirmed"] == ["920997"], kind
        assert summary["remaining"] == 1, kind
        assert summary["calls"] == 3 and summary["halt"] is None, kind
        if kind != "daily":
            sql_dir = result.root / "sql"
            assert "INSERT INTO" not in (sql_dir / "920997.BJ.sql").read_text()
            for code in ("600997.SH", "000997.SZ"):
                assert "INSERT INTO" in (sql_dir / f"{code}.sql").read_text()
        if kind == "supervisor":
            batch = next(item for item in result.summaries if item["mode"] == "history")
            assert batch["db_blocked_bj_unconfirmed"] == 1
            assert batch["db_inserted"] == 2
        artifacts = "\n".join(p.read_text() for p in result.root.rglob("*.json*"))
        check(
            problems,
            "旧码不请求" in output + artifacts,
            f"{kind}: 必须记录「旧码不请求」",
        )
    assert not problems, problems


@pytest.mark.parametrize(
    "kind",
    ["backfill", "supervisor", "daily"],
)
def test_ta157_history_blocked_exit_code(api, monkeypatch, tmp_path, kind):
    # 退出码单独验收，避免未实现项掩盖已实现的路由、阻断和沪深完成断言。
    result = run_cli(api, monkeypatch, tmp_path / kind, kind, codes=ROUTE_CODES)
    assert result.summaries[-1]["blocked_bj_unconfirmed"] == ["920997"]
    assert result.rc != 0, f"{kind}: 未确认 BJ 不得以成功退出标为全量完成"


def test_ta157_log_redaction(api, monkeypatch, tmp_path, capsys):
    problems = []
    encoded = quote(TOKEN, safe="")
    for code, route in (("920997", "bj"), ("600997", "hsstock")):
        actual = api.backfill.history_path(code, TOKEN, "20100104", "20201231")
        logged = api.backfill.history_path_log(code, "20100104", "20201231")
        check(
            problems,
            logged == actual.replace(encoded, "***"),
            f"{code}: 请求与日志的路由、查询参数必须相同",
        )
        check(
            problems,
            urlsplit(logged).path.startswith(f"/{route}/history/"),
            f"{code}: 日志必须显示正确路由 /{route}/history",
        )
        check(
            problems,
            TOKEN not in logged and encoded not in logged and "***" in logged,
            f"{code}: 日志只能保留 ***",
        )
        # 503 正文模拟上游将原占位/编码值放进错误消息；真实 run_batch 摘要必须脱敏。
        result = run_cli(
            api,
            monkeypatch,
            tmp_path / code,
            "backfill",
            codes=(code,),
            body={"error": f"{TOKEN} {encoded} {actual}"},
            status=503,
        )
        output = capsys.readouterr().out + (result.root / "runs.jsonl").read_text()
        check(
            problems,
            result.rc == 1 and len(result.wire.paths) == 1,
            f"{code}: 假 503 必须停止且不重试",
        )
        check(
            problems,
            TOKEN not in output and encoded not in output and "***" in output,
            f"{code}: 异常摘要泄露占位证书",
        )
        engine = api.backfill.Backfill(
            counter_path=result.ledger,
            stop_path=result.root / "exception-STOP",
            run_dir=result.root,
            connection_factory=lambda result=result: result.wire,
            sleeper=lambda _seconds: None,
        )
        with pytest.raises(api.backfill.Halt, match="HTTP_503") as caught:
            engine.call_history(counter(), TOKEN, code, "20100104", "20201231")
        check(
            problems,
            TOKEN not in str(caught.value) and encoded not in str(caught.value),
            f"{code}: 异常字符串泄露占位证书",
        )
    assert not problems, problems


def test_ta157_optional_window_url(api, monkeypatch, tmp_path):
    problems = []
    for kind in ("backfill", "supervisor", "daily"):
        for label, options, expected in (
            ("none", (), {}),
            ("et", ("--et", "20201231"), {"et": ["20201231"]}),
        ):
            result = run_cli(
                api, monkeypatch, tmp_path / f"{kind}-{label}", kind, options=options
            )
            check(
                problems,
                result.rc == 0 and len(result.wire.paths) == 1,
                f"{kind}/{label}: CLI 必须支持可空边界并构造一个请求",
            )
            for path in result.wire.paths:
                parsed = urlsplit(path)
                check(
                    problems,
                    parse_qs(parsed.query, keep_blank_values=True) == expected,
                    f"{kind}/{label}: 只发送显式日期，无 lt；实际 {parsed.query}",
                )
                check(
                    problems,
                    expected or "?" not in path,
                    f"{kind}/{label}: 不得留下空查询串",
                )
    # 直接按契约以 None 调用现有四参数签名，防止只改 CLI 而仍序列化 None。
    for st, et, expected in (
        (None, None, {}),
        (None, "20201231", {"et": ["20201231"]}),
    ):
        path = api.backfill.history_path("600997", TOKEN, st, et)
        log = api.backfill.history_path_log("600997", st, et)
        check(
            problems,
            parse_qs(urlsplit(path).query, keep_blank_values=True) == expected,
            "history_path: None 边界必须省略",
        )
        check(
            problems,
            parse_qs(urlsplit(log).query, keep_blank_values=True) == expected,
            "history_path_log: None 边界必须省略",
        )
    assert not problems, problems


def test_ta157_explicit_window(api, monkeypatch, tmp_path):
    problems = []
    body = [
        bar(day) for day in ("2009-12-31", "2010-01-04", "2020-12-31", "2021-01-04")
    ]
    for kind in ("backfill", "supervisor", "daily"):
        for label, options, query in (
            (
                "both",
                ("--st", "20100104", "--et", "20201231"),
                {"st": ["20100104"], "et": ["20201231"]},
            ),
            ("st", ("--st", "20100104"), {"st": ["20100104"]}),
        ):
            result = run_cli(
                api,
                monkeypatch,
                tmp_path / f"{kind}-{label}",
                kind,
                body=body,
                options=options,
            )
            check(
                problems,
                result.rc == 0 and len(result.wire.paths) == 1,
                f"{kind}/{label}: 显式日期 CLI 必须成功",
            )
            for path in result.wire.paths:
                check(
                    problems,
                    parse_qs(urlsplit(path).query) == query,
                    f"{kind}/{label}: 请求边界不一致",
                )
            if kind != "daily":
                path = result.root / "history/600997.SH.json"
                if not path.exists():
                    problems.append(f"{kind}/{label}: 没有规范化产物")
                    continue
                payload = json.loads(path.read_text())
                expected_window = {
                    "st": "2010-01-04",
                    "et": "2020-12-31" if label == "both" else None,
                }
                check(
                    problems,
                    payload["window"] == expected_window,
                    f"{kind}/{label}: 写入窗口元数据必须沿用 CLI",
                )
                dates = [row["trade_date"] for row in api.load.load_normalized(path)]
                expected_dates = ["2010-01-04", "2020-12-31"]
                if label == "st":
                    expected_dates.append("2021-01-04")
                check(
                    problems,
                    dates == expected_dates,
                    f"{kind}/{label}: 请求→规范化→重读丢失边界内历史行：{dates}",
                )
        for label, options in (
            ("bad-day", ("--st", "20100230")),
            ("bad-end", ("--et", "20200230")),
            ("reverse", ("--st", "20201231", "--et", "20100104")),
        ):
            result = run_cli(
                api, monkeypatch, tmp_path / f"{kind}-{label}", kind, options=options
            )
            check(
                problems,
                result.rc != 0 and not result.reads and not result.wire.paths,
                f"{kind}/{label}: 非法/逆序窗口须在取证书和请求前拒绝",
            )
    # 旧文件的显式窗口必须继续有意义，不能重读时悄悄恢复三年窗口。
    early, rejects = api.load.normalize_history(
        "600997", body, st=date(2010, 1, 4), et=date(2020, 12, 31)
    )
    assert len(early) == 2 and len(rejects) == 2
    legacy = tmp_path / "explicit-old-file.json"
    api.load.write_normalized(legacy, "600997", early, rejects)
    payload = json.loads(legacy.read_text())
    payload["window"] = {"st": "2010-01-04", "et": "2020-12-31"}
    legacy.write_text(json.dumps(payload))
    check(
        problems,
        api.load.load_normalized(legacy) == early,
        "load_normalized 必须采用旧文件中已有的显式窗口",
    )
    assert not problems, problems


def assert_invalid_fields(load, code):
    for field, value in (
        ("o", "NaN"),
        ("h", "9"),
        ("v", "-1"),
        ("a", "-1"),
        ("pc", "0"),
        ("code", "000997.SZ"),
        ("t", "2001-02-30"),
    ):
        row = bar()
        row[field] = value
        with pytest.raises(load.RowReject):
            load.validate_bar(row, code, st=date(2000, 1, 1), et=date(2026, 11, 13))


def test_ta157_validate_early_bar(api):
    early = bar("2001-01-04", code="600997.SH")
    accepted = api.load.validate_bar(early, "600997.SH")
    outside = api.load.validate_bar(early, "600997.SH", st=date(2010, 1, 4))
    assert outside is None, "显式 st 必须拒绝窗口外日期"
    assert_invalid_fields(api.load, "600997.SH")
    assert accepted is not None and accepted["volume"] == 200, (
        "§10.4：无边界必须接纳 2001-01-04 合法沪深行，并按既有规则换为 200 股"
    )

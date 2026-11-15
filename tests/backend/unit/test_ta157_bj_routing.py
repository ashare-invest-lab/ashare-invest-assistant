"""T-T83：daily-bars-source §10.6 的离线契约测试（全部证券与行情均为虚构）。

未验证：契约没有命名错后缀统计入口；对应测试只验证 §10.3 的只读 SQL 方案，
不声称覆盖生产统计工具。扩窗规划/账本的新入口也未命名；只观察已命名 run_batch
对旧完成记录的输出，不猜新的函数或账本字段。
T-A158 第 5 项/plan-next §7.8：BJ 写库前须至少 20 只 tdx_local 离线量单位对算通过。
未验证：契约未命名生产对算入口及证据传递接口；测试内对算仅为夹具判据，
不冒充生产门闩，只观察现有 render_insert_sql / apply_daily_bars 的写入行为。
未验证：apply_daily_bars 的对账配置接口未命名；沿用现有签名，观察实际 SQL、
jsonl 落盘和事务，不给它臆造 reconcile_sink 等参数。
"""

from __future__ import annotations

import builtins
import importlib
import io
import json
import os
import re
import socket
import sys
from contextlib import contextmanager
from copy import deepcopy
from datetime import date
from decimal import Decimal
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
VALUE_COLUMNS = BAR_COLUMNS[3:11]


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

    def __init__(self, rows=(), *, incoming=None, race=False):
        self.rows = {self.key(row): deepcopy(row) for row in rows}
        self.incoming = incoming
        self.race = race
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
    def __init__(self, db):
        self.db = db
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql, params=None):
        text = str(sql)
        self.db.statements.append((text, params))
        if text.lstrip().upper().startswith("UPDATE"):
            # 模拟数据库条件 UPDATE 的原子性；不会自行发起替换或生成对账记录。
            assert (
                "WHERE" in text.upper()
                and re.search(r"\bsource\s*=", text, re.IGNORECASE)
                and "tdx_local" in text + str(params)
            ), "替换 SQL 必须有 source=tdx_local 的条件（允许参数绑定）"
            assert self.db.incoming is not None
            key = self.db.key(self.db.incoming)
            if self.db.race:
                self.db.rows[key]["source"] = "mairui"
            if self.db.rows[key]["source"] == "tdx_local":
                self.db.rows[key] = deepcopy(self.db.incoming)
                self.rowcount = 1
            self.db.events.append("update")
        else:
            assert text.lstrip().upper().startswith("SELECT"), text
        return self

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
        return (len(self.db.rows),)

    def fetchall(self):
        return list(self.db.rows.values())


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
            result.rc == 0 and len(paths) == 3 and set(paths) == expected,
            f"{kind}: 仅请求 920 京市及沪深，43/83/87 请求数须为零；实际 {safe_paths}",
        )
        artifacts = "\n".join(p.read_text() for p in result.root.rglob("*.json*"))
        check(
            problems,
            "旧码不请求" in output + artifacts,
            f"{kind}: 必须记录「旧码不请求」",
        )
    assert not problems, problems


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


def test_ta157_tdx_priority(api, monkeypatch, tmp_path):
    problems = []
    incoming = api.load.validate_bar(
        bar("2001-01-04"), "600997.SH", st=date(2001, 1, 4), et=date(2001, 1, 4)
    )
    assert incoming is not None
    for label, source, same, fail_audit, race in (
        ("replace", "tdx_local", False, False, False),
        ("same", "tdx_local", True, False, False),
        ("audit-failed", "tdx_local", False, True, False),
        ("race", "tdx_local", False, False, True),
        ("mairui", "mairui", False, False, False),
        ("fake", "fake", False, False, False),
    ):
        existing = dict(incoming, source=source)
        if not same:
            existing.update(open="9.99", high="9.99", low="9.99", close="9.99")
        db = MemoryDB([existing], incoming=incoming, race=race)
        audit_writes = []

        def audit_open(
            original, audit_writes=audit_writes, db=db, fail_audit=fail_audit
        ):
            def opened(file, mode="r", *args, **kwargs):
                if (
                    isinstance(file, (str, os.PathLike))
                    and str(file).endswith(".jsonl")
                    and any(flag in mode for flag in ("w", "a"))
                ):
                    audit_writes.append(str(Path(file).resolve()))
                    db.events.append("audit")
                    if fail_audit:
                        raise OSError("synthetic audit failure")
                return original(file, mode, *args, **kwargs)

            return opened

        audit_dir = tmp_path / label
        audit_dir.mkdir()
        with monkeypatch.context() as patch:
            patch.chdir(audit_dir)
            patch.setattr(builtins, "open", audit_open(builtins.open))
            patch.setattr(io, "open", audit_open(io.open))
            try:
                stats = api.load.apply_daily_bars(db, [incoming])
            except OSError as exc:
                assert fail_audit and str(exc) == "synthetic audit failure"
                stats = {}
        updates = [
            sql for sql, _ in db.statements if sql.lstrip().upper().startswith("UPDATE")
        ]
        should_replace = source == "tdx_local" and not fail_audit and not race
        check(
            problems,
            stats.get("replaced", 0) == int(should_replace),
            f"{label}: replaced 计数应为 {int(should_replace)}，实际 {stats}",
        )
        if should_replace:
            check(
                problems,
                db.rows[db.key(incoming)] == incoming and bool(updates),
                f"{label}: 应用 mairui 整行条件替换 tdx_local",
            )
            check(
                problems,
                audit_writes and db.events.index("audit") < db.events.index("update"),
                f"{label}: 必须先对账落盘再 UPDATE",
            )
            records = [
                json.loads(line)
                for filename in set(audit_writes)
                for line in Path(filename).read_text().splitlines()
            ]
            kind = "replaced_tdx_local_same" if same else "replaced_tdx_local"
            check(
                problems,
                any(r.get("kind") == kind for r in records),
                f"{label}: 缺少 {kind} 对账记录",
            )
            check(
                problems,
                any(
                    r.get("kind") == kind
                    and r.get("field") == ("*" if same else "close")
                    and r.get("existing_source") == "tdx_local"
                    and r.get("incoming_source") == "mairui"
                    and (
                        same
                        or (
                            Decimal(str(r.get("existing_value", "NaN")))
                            == Decimal("9.99")
                            and Decimal(str(r.get("incoming_value", "NaN")))
                            == Decimal(10)
                        )
                    )
                    for r in records
                ),
                f"{label}: 对账必须包含来源、差异旧新值；同值时 field=*",
            )
            check(
                problems,
                any(r.get("replace_result") == "committed" for r in records),
                f"{label}: 事务后缺少 committed 结果",
            )
        else:
            check(problems, not updates or race, f"{label}: 不得替换")
            check(
                problems,
                db.rows[db.key(existing)]["close"] == existing["close"],
                f"{label}: 禁止覆盖旧值",
            )
        if race:
            check(
                problems,
                bool(updates) and audit_writes,
                "race: 必须实际经过对账及条件更新的并发冲突路径",
            )
            records = [
                json.loads(line)
                for filename in set(audit_writes)
                for line in Path(filename).read_text().splitlines()
            ]
            check(
                problems,
                any(r.get("replace_result") == "skipped" for r in records),
                "race: 条件更新零行必须记录 skipped",
            )
            check(
                problems,
                db.rows[db.key(existing)]["source"] == "mairui",
                "race: 保留并发写入后的来源",
            )
        if fail_audit:
            check(
                problems, bool(audit_writes), "audit-failed: 必须尝试对账，失败后不替换"
            )
    sql = api.load.render_insert_sql([incoming], None, bind_note="pending_bind")
    check(
        problems,
        bool(re.search(r"\bUPDATE\b", sql, re.IGNORECASE)) and "tdx_local" in sql,
        "render_insert_sql 产物仍仅 DO NOTHING，未接入 §4 受控替换",
    )
    assert not problems, problems


# 未验证：无命名生产统计入口；此 SQL 为 §10.3 方案的测试内表达，不是修库脚本。
WRONG_SUFFIX_SQL = """
SELECT s.code, s.source, s.adj_type,
       CASE WHEN b.code IS NULL THEN 'missing'
            WHEN ROW(s.open,s.high,s.low,s.close,s.pre_close,s.volume,s.amount,s.is_suspended)
                 IS NOT DISTINCT FROM
                 ROW(b.open,b.high,b.low,b.close,b.pre_close,b.volume,b.amount,b.is_suspended)
            THEN 'same' ELSE 'different' END AS category,
       count(*) AS row_count, min(s.trade_date) AS first_date, max(s.trade_date) AS last_date
FROM market.daily_bars s
LEFT JOIN market.daily_bars b ON b.code = left(s.code,6) || '.BJ'
 AND b.trade_date = s.trade_date AND b.adj_type = s.adj_type
WHERE s.code ~ '^920[0-9]{3}[.]SH$'
GROUP BY s.code, s.source, s.adj_type, category
ORDER BY s.code, s.source, s.adj_type, category
"""


class ReadOnlyStats:
    """内存关系替身只解释上面的有限 SELECT 形状，不连接任何数据库。"""

    def __init__(self, rows):
        self.rows = deepcopy(rows)
        self.statements = []

    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def execute(self, sql):
        assert sql.lstrip().upper().startswith("SELECT")
        assert not re.search(
            r"\b(INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|TRUNCATE)\b", sql, re.IGNORECASE
        )
        self.statements.append(sql)
        assert "LEFT JOIN" in sql and "b.trade_date = s.trade_date" in sql
        assert "b.adj_type = s.adj_type" in sql and "left(s.code,6) || '.BJ'" in sql
        assert "GROUP BY s.code, s.source, s.adj_type, category" in sql
        assert "IS NOT DISTINCT FROM" in sql
        self.pattern = re.search(r"WHERE s.code ~ '([^']+)'", sql).group(1)
        self.fields = re.findall(r"s\.(\w+)", re.search(r"ROW\((.*?)\)", sql).group(1))

    def fetchall(self):
        groups = {}
        for row in self.rows:
            if not re.fullmatch(self.pattern, row["code"]):
                continue
            target = next(
                (
                    b
                    for b in self.rows
                    if b["code"] == row["code"][:6] + ".BJ"
                    and b["trade_date"] == row["trade_date"]
                    and b["adj_type"] == row["adj_type"]
                ),
                None,
            )
            category = (
                "missing"
                if target is None
                else (
                    "same"
                    if all(row[c] == target[c] for c in self.fields)
                    else "different"
                )
            )
            key = (row["code"], row["source"], row["adj_type"], category)
            groups.setdefault(key, []).append(row["trade_date"])
        return [
            (*key, len(days), min(days), max(days))
            for key, days in sorted(groups.items())
        ]


def test_ta157_wrong_suffix_read_only(api):
    template = api.load.validate_bar(bar(), "920997.BJ")
    assert template is not None
    rows = []
    # 同一虚构代码在不同日构造缺失、同值、八个字段各自异值；空值也比较。
    scenarios = [("2026-10-01", "missing", None), ("2026-10-02", "same", None)]
    scenarios.extend(
        (f"2026-10-{i:02d}", "different", field)
        for i, field in enumerate(VALUE_COLUMNS, 3)
    )
    for day, category, field in scenarios:
        wrong = dict(template, code="920997.SH", trade_date=day, pre_close=None)
        rows.append(wrong)
        if category != "missing":
            target = dict(wrong, code="920997.BJ")
            if field:
                target[field] = not target[field] if field == "is_suspended" else "11"
            rows.append(target)
    rows.extend([dict(template, code="600997.SH"), dict(template, code="9209977.SH")])
    # 同日而复权不同不是同键目标；来源、复权分组不能混合。
    rows.extend(
        [
            dict(template, code="920997.SH", adj_type="qfq", source="tdx_local"),
            dict(template, adj_type="hfq"),
        ]
    )
    db = ReadOnlyStats(rows)
    before = deepcopy(db.rows)
    with db.cursor() as cur:
        cur.execute(WRONG_SUFFIX_SQL)
        result = cur.fetchall()
    assert result == [
        ("920997.SH", "mairui", "none", "different", 8, "2026-10-03", "2026-10-10"),
        ("920997.SH", "mairui", "none", "missing", 1, "2026-10-01", "2026-10-01"),
        ("920997.SH", "mairui", "none", "same", 1, "2026-10-02", "2026-10-02"),
        ("920997.SH", "tdx_local", "qfq", "missing", 1, "2026-11-13", "2026-11-13"),
    ]
    assert db.rows == before and db.statements == [WRONG_SUFFIX_SQL]
    assert tuple(db.fields) == VALUE_COLUMNS


@pytest.fixture
def bj_volume_pairs():
    """20 只虚构 BJ 股票；mairui 为手，独立合成的 tdx_local 为股，价额为元。"""
    pairs = []
    for offset in range(20):
        code = f"{920801 + offset}.BJ"
        lots = 2 + offset
        shares = 200 + offset * 100
        pairs.append(
            {
                "mairui": bar(code=code, v=str(lots), a=str(shares * 10)),
                "tdx_local": {
                    "code": code,
                    "trade_date": "2026-11-13",
                    "adj_type": "none",
                    "open": "10",
                    "high": "10",
                    "low": "10",
                    "close": "10",
                    "pre_close": "10",
                    "volume": shares,
                    "amount": str(shares * 10),
                    "is_suspended": False,
                    "source": "tdx_local",
                },
            }
        )
    return pairs


def offline_bj_volume_matches(pairs):
    """测试内离线判据，非生产入口；只累计同码同日且 v×100 一致的不同股票。"""
    matched = set()
    for pair in pairs:
        mairui, tdx = pair["mairui"], pair["tdx_local"]
        assert mairui["code"] == tdx["code"]
        assert mairui["t"] == tdx["trade_date"]
        assert tdx["source"] == "tdx_local"
        assert tdx["code"].endswith(".BJ")
        if Decimal(mairui["v"]) * 100 == Decimal(tdx["volume"]):
            matched.add(tdx["code"])
    return matched


def observe_unverified_bj_writes(load, rows, label):
    """不在假库内实现门闩，不过滤输入；两个真实写入入口都必须自行拒绝。"""
    problems = []
    try:
        sql = load.render_insert_sql(rows, None, bind_note="pending_bind")
    except load.RowReject:
        pass
    else:
        check(
            problems,
            not (
                re.search(r"(?im)^INSERT\s+INTO\s+market\.daily_bars\b", sql)
                and any(row["code"] in sql for row in rows)
            ),
            f"{label}: render_insert_sql 未满足 20 只一致对算仍生成 BJ INSERT",
        )
    db = MemoryDB()
    try:
        stats = load.apply_daily_bars(db, rows)
    except load.RowReject:
        stats = {"inserted": 0}
    check(
        problems,
        not db.rows
        and stats["inserted"] == 0
        and not any(
            sql.lstrip().upper().startswith("INSERT") for sql, _ in db.statements
        ),
        f"{label}: apply_daily_bars 未满足 20 只一致对算仍向假库插入 BJ 行",
    )
    return problems


def test_ta157_bj_volume_lots_to_shares(api, tmp_path, bj_volume_pairs):
    row = bj_volume_pairs[0]["mairui"]
    accepted = api.load.validate_bar(row, "920801.BJ")
    assert (
        accepted is not None and api.load.VOL_MULT == 100 and accepted["volume"] == 200
    )
    assert accepted["close"] == "10" and accepted["amount"] == "2000"
    rows, rejects = api.load.normalize_history("920801", [row])
    assert rows == [accepted] and rejects == []
    assert_invalid_fields(api.load, "920801.BJ")

    matched = offline_bj_volume_matches(bj_volume_pairs)
    assert len(matched) == len(bj_volume_pairs) == 20
    assert accepted["code"] in matched
    assert accepted["volume"] == bj_volume_pairs[0]["tdx_local"]["volume"]
    # 测试内对算仅验证夹具；生产对算/证据接口未命名，不据此断言写库放行。
    path = tmp_path / "normalized.json"
    api.load.write_normalized(path, "920801", rows, rejects)
    assert api.load.load_normalized(path) == rows


@pytest.mark.parametrize(
    ("sample_count", "inconsistent"),
    [(0, False), (1, False), (19, False), (20, True)],
    ids=["unchecked", "only-1", "only-19", "unit-mismatch"],
)
def test_ta158_bj_write_requires_offline_volume_check(
    api, bj_volume_pairs, sample_count, inconsistent
):
    comparisons = deepcopy(bj_volume_pairs[:sample_count])
    if inconsistent:
        # 20 只中仅一只本地量仍为 2；其余 19 只均一致也不得放行。
        comparisons[0]["tdx_local"]["volume"] = 2
    matched = offline_bj_volume_matches(comparisons)
    assert len(matched) == (sample_count - int(inconsistent))
    assert not (len(comparisons) >= 20 and len(matched) == len(comparisons))
    rows = []
    for pair in bj_volume_pairs:
        raw = pair["mairui"]
        normalized, rejects = api.load.normalize_history(raw["code"][:6], [raw])
        assert rejects == [] and len(normalized) == 1
        assert normalized[0]["volume"] == pair["tdx_local"]["volume"]
        rows.extend(normalized)
    # 对算失败后仍调用现有入口，以暴露生产缺失的门闩；不能由测试跳过写入造绿。
    problems = observe_unverified_bj_writes(
        api.load, rows, f"离线对算 {sample_count} 只，单位不一致={inconsistent}"
    )
    assert not problems, problems


def test_ta157_old_window_not_complete(api, tmp_path, capsys):
    # 未验证：扩窗规划没有命名入口/字段；只观察 §10.5 点名的 run_batch。
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
        "新规划入口未验证，此处仅观察已有 run_batch 输出"
    )

"""T-T81 多源导入红测；依据派单附带的 T-T81-contract.md 定稿。

只用合成字节、行情和权息事件，不读取实际行情、环境文件或凭据。
§4、§5 C1/C2 优先：日线麦蕊可替换通达信，离线分钟按日期分段。
不把三种来源拼成契约没有规定的全局优先级队列。

未验证：契约只给出 tb140_history_load 脚本名，未给包路径或 validate_bar 签名；
probes.tb140_history_load.validate_bar(row, code, st=..., et=...) 及字典返回值
参照本地 T-B140i 工作树的只读源码；不从其他工作树加载被测代码。
未验证：app.ingest.gbbq、app.ingest.minute_catalog 的包路径与公开函数签名
未在契约指定；ref_price、CatalogEntry、effective_range、check_overlap、
hf_entries_from_manifest 参照本地 origin/be/T-B143 的只读源码线索。
未验证：compute_adjust_factors 名称、参数、返回结构是待后端确认的测试接缝，
契约 §2.5 只规定算法，尚未指定生产入口；不得以测试实现替代此入口。
未验证：parse_*、scan、run_import 的参数和 ParseResult 返回结构沿用 main；
run_import 在契约中没有给出函数名。写库入口沿用源契 §1 的 upsert_daily_bars。
"""

from __future__ import annotations

import builtins
import datetime as dt
import importlib
import io
import json
import os
import socket
import struct
import sys
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from pathlib import Path
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

pytestmark = pytest.mark.unit

DAY = dt.date(2026, 8, 7)
CODE = "600999.SH"
SHANGHAI = ZoneInfo("Asia/Shanghai")
TDX = "app.ingest.tdx_local"
GBBQ = "app.ingest.gbbq"
CATALOG = "app.ingest.minute_catalog"
# 以下只是 §2.3 的输入标签和期望标签，不执行任何标签修复。
MINUTES = tuple(range(571, 691)) + tuple(range(781, 901))


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """在用例内导入生产模块之前禁止出网及读取环境文件、凭据。"""
    monkeypatch.syspath_prepend(
        str(Path(__file__).resolve().parents[3] / "src/backend")
    )
    monkeypatch.setattr(sys, "dont_write_bytecode", True)

    def no_network(*_args, **_kwargs):
        pytest.fail("T-T81：仅允许合成夹具，禁止网络访问或麦蕊调用")

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
                    or any(part in {".aws", ".ssh", "secrets"} for part in path.parts)
                ):
                    pytest.fail("T-T81：禁止访问 .env 或密钥文件")
            return original(file, *args, **kwargs)

        return guarded

    monkeypatch.setattr(builtins, "open", guard_open(builtins.open))
    monkeypatch.setattr(io, "open", guard_open(io.open))
    monkeypatch.setattr(os, "open", guard_open(os.open))


def entry(module: str, name: str, section: str):
    """由用例调用，缺入口逐例报红，不在收集阶段导入生产代码。"""
    try:
        loaded = importlib.import_module(module)
    except ImportError as exc:
        pytest.fail(
            f"契约 {section}：生产入口 {module}.{name} 无法导入：{exc}", pytrace=False
        )
    function = getattr(loaded, name, None)
    assert callable(function), f"契约 {section}：缺少生产入口 {module}.{name}"
    return function


def day_bytes() -> bytes:
    """合成 §7 指定的日线样例：价 12.34 元、量 700 股、额 8638 元。"""
    return struct.pack("<IIIIIfII", 20260807, 1234, 1234, 1234, 1234, 8638.0, 700, 0)


def lc_bytes(minutes=MINUTES, *, price: float = 10.0) -> bytes:
    """按 §2.2 的磁盘格式构造假字节，不借用生产编码或舍入函数。"""
    packed_day = (2026 - 2004) * 2048 + 807
    return b"".join(
        struct.pack(
            "<HHfffffII",
            packed_day,
            minute,
            price,
            price,
            price,
            price,
            price * 700,
            700,
            0,
        )
        for minute in minutes
    )


def test_day_volume_is_shares() -> None:
    parse = entry(TDX, "parse_day_bytes", "§2.4、§3.1、§7")
    result = parse(CODE, day_bytes())
    assert not result.rejected, "契约 §3.1：合法合成日线不得拒绝"
    assert len(result.bars) == 1, "契约 §7：应解析一条日线"
    bar = result.bars[0]
    assert bar.volume == Decimal(700), "契约 §2.4、§3.1：.day 量本来是股，不乘 100"
    assert bar.close == Decimal("12.34"), "契约 §2.4：.day 价格除以 100"


@pytest.mark.parametrize("kind", ["lc1", "lc5"])
def test_lc_volume_is_shares(kind: str) -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.4、§3.2")
    result = parse(CODE, lc_bytes((575,)), kind)
    assert not result.rejected, "契约 §3.2：合法合成分钟记录不得拒绝"
    assert len(result.bars) == 1, "契约 §3.2：不得丢失合法分钟记录"
    assert result.bars[0].volume == Decimal(700), (
        "契约 §2.4：通达信分钟量为股，不乘 100"
    )


@pytest.mark.parametrize("hands,shares", [("7.5", "750"), ("0.01", "1")])
def test_mairui_daily_hands_to_shares(hands: str, shares: str) -> None:
    validate = entry("probes.tb140_history_load", "validate_bar", "§2.4、§3.1")
    # 未验证：模块路径、参数顺序和返回结构来自 T-B140i 源码，契约未定义。
    row = {
        "t": "2026-08-07",
        "o": "10",
        "h": "10",
        "l": "10",
        "c": "10",
        "pc": "10",
        "v": hands,
        "a": str(Decimal(shares) * 10),
        "sf": 0,
    }
    bar = validate(row, CODE, st=DAY, et=DAY)
    assert bar is not None, "契约 §3.1：窗口内合法麦蕊日线不得丢弃"
    assert bar["volume"] == Decimal(shares), (
        "契约 §2.4、§3.1：麦蕊日线手数必须乘 100 为股"
    )


def test_lc1_day_has_240_end_labels() -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.2、§2.3")
    result = parse(CODE, lc_bytes(), "lc1")
    expected = [
        dt.datetime(2026, 8, 7, tzinfo=SHANGHAI) + dt.timedelta(minutes=m)
        for m in MINUTES
    ]
    assert not result.rejected, "契约 §2.3：标准完整交易日不得拒绝"
    assert len(result.bars) == 240, "契约 §2.3：完整交易日应有 240 根"
    assert [bar.ts for bar in result.bars] == expected, (
        "契约 §2.2、§2.3：北京时间结束标签须为 09:31–11:30、13:01–15:00"
    )


def test_lc1_relabels_complete_1300_day() -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.3、§5 C11、§7")
    minutes = tuple(m for m in MINUTES if m != 690) + (780,)
    result = parse(CODE, lc_bytes(minutes), "lc1")
    assert not result.rejected, "契约 §2.3：239 个标准标签加 13:00 可修复"
    assert len(result.bars) == 240, "契约 §2.3：修复不能增删完整交易日记录"
    assert {bar.ts.strftime("%H:%M") for bar in result.bars} == {
        f"{m // 60:02d}:{m % 60:02d}" for m in MINUTES
    }, "契约 §2.3、§5 C11：只将异常 13:00 改记为缺失的 11:30"


def test_lc1_drops_unconfirmed_1300() -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.3、§5 C11")
    result = parse(CODE, lc_bytes((571, 780)), "lc1")
    assert [bar.ts.strftime("%H:%M") for bar in result.bars] == ["09:31"], (
        "契约 §2.3：不足 240 根时丢弃未经确认的 13:00，不能伪造 11:30"
    )


@pytest.mark.parametrize(
    "minutes", [(690, 780), (571, 571), (570,), (720,), (901,), (1440,)]
)
def test_lc1_refuses_invalid_file_labels(minutes: tuple[int, ...]) -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.3、§3.2")
    result = parse(CODE, lc_bytes(minutes), "lc1")
    assert not result.bars and result.rejected, (
        "契约 §2.3、§3.2：11:30/13:00 并存、重复、非法标签或分钟数 ≥1440 应拒绝文件"
    )


@pytest.mark.parametrize("kind", ["lc1", "lc5"])
def test_minute_price_uses_decimal_half_up(kind: str) -> None:
    parse = entry(TDX, "parse_lc_bytes", "§2.4、§3.2、§5 C6、§7")
    # 10.125 可用 float32 精确表示，排除二进制近似引入的伪边界。
    with localcontext() as context:
        context.rounding = ROUND_HALF_EVEN
        result = parse(CODE, lc_bytes((575,), price=10.125), kind)
    assert len(result.bars) == 1, "契约 §3.2：合法半分价格记录不得丢失"
    bar = result.bars[0]
    for field in ("open", "high", "low", "close"):
        actual = getattr(bar, field)
        assert isinstance(actual, Decimal), f"契约 §2.4、§5 C6：{field} 用 Decimal 舍入"
        assert actual == Decimal("10.13"), (
            f"契约 §2.4、§5 C6：{field} 的 10.125 应为 10.13，银行家舍入会错误地得 10.12"
        )


@pytest.mark.parametrize(
    "kind,folder,suffix",
    [
        ("lc1", "minline", ".lc1"),
        ("lc5", "fzline", ".lc5"),
    ],
)
def test_bj_minutes_are_not_scanned(
    tmp_path: Path, kind: str, folder: str, suffix: str
) -> None:
    scan = entry(TDX, "scan", "§2.1、§3.2、§5 C7、§7")
    names = {"sh600999": CODE, "sz000999": "000999.SZ", "bj920999": "920999.BJ"}
    for filename in names:
        directory = tmp_path / filename[:2] / folder
        directory.mkdir(parents=True)
        (directory / (filename + suffix)).write_bytes(lc_bytes((575,)))
    result = scan(
        tmp_path,
        kind,
        normalize=lambda name: names[name.lower()],
        security_of=lambda _code: ("stock", "listed"),
        scope_codes=None,
    )
    assert {item.code for item in result.files} == {CODE, "000999.SZ"}, (
        "契约 §3.2、§5 C7：默认只扫描沪深分钟文件，.BJ 不导入，无需手工 exclude"
    )


def test_hf_bj_minutes_are_not_registered() -> None:
    register = entry(CATALOG, "hf_entries_from_manifest", "§3.2、§5 C7")
    # 未验证：清单输入的字段拼写沿用 origin/be/T-B143，契约未定义清单函数签名。
    base = {
        "rows": "240",
        "first_ts": "2026-08-06T09:31:00+08:00",
        "last_ts": "2026-08-06T15:00:00+08:00",
        "sha256": "a" * 64,
    }
    rows = [
        dict(base, exchange="SH", symbol="600999", is_bj="false"),
        dict(base, exchange="BJ", symbol="920999", is_bj="true"),
        dict(base, exchange="BJ", symbol="830999", is_bj="false"),
    ]
    entries, _counts = register(rows, generator="合成夹具")
    assert [item.code for item in entries] == [CODE], (
        "契约 §3.2、§5 C7：HF 的 is_bj=true 或 exchange=BJ 均不得登记"
    )


def test_existing_mairui_is_append_only(tmp_path: Path) -> None:
    run = entry(TDX, "run_import", "§4、§7")
    existing_type = entry(TDX, "ExistingBar", "§4")
    root, audit = tmp_path / "合成行情", tmp_path / "合成对账"
    audit.mkdir()
    for market in ("sh", "sz", "bj"):
        (root / market / "lday").mkdir(parents=True)
    (root / "sh/lday/sh600999.day").write_bytes(day_bytes())
    existing = existing_type(
        "mairui", *(Decimal("12.00"),) * 4, Decimal(700), Decimal(8400)
    )
    writer = Mock(return_value=1)
    # 未验证：这些注入参数取自 main 的 run_import，不是契约新增的 API 要求。
    options = dict(
        root=root,
        audit_dir=audit,
        kind="day",
        start=None,
        until_for=lambda _code: DAY,
        normalize=lambda _name: CODE,
        security_of=lambda _code: ("stock", "listed"),
        scope_codes=None,
        existing_for=lambda _code, _bars: {DAY: existing},
        writer=writer,
        now=dt.datetime(2026, 8, 8, tzinfo=dt.UTC),
        compare_amount=True,
    )
    first = run(**options, run_id="首次")
    second = run(**options, run_id="复跑")
    assert writer.call_count == 0, "契约 §4：任何通达信冲突行均不得送入写入器"
    assert first.inserted == second.inserted == 0, (
        "契约 §4、§7：已有麦蕊键不可追加或覆盖"
    )
    records = [
        json.loads(line)
        for line in (audit / first.reconcile_name).read_text().splitlines()
    ]
    assert any(
        row.get("kind") == "mismatch" and row.get("existing_source") == "mairui"
        for row in records
    ), "契约 §4：通达信冲突必须留下对账差异"


def test_mairui_late_arrival_requires_replacement() -> None:
    module = "app.marketdata.daily_bars"
    upsert = entry(module, "upsert_daily_bars", "§4、§5 C1、§7")
    make_bar = entry(module, "DailyBar", "§3.1、§4")
    make_result = entry(module, "DailyBarsResult", "§4")
    incoming = make_bar(
        CODE,
        DAY,
        "none",
        *(Decimal("12.01"),) * 4,
        None,
        Decimal(700),
        Decimal(8407),
        False,
    )
    existing = dict(vars(incoming), source="tdx_local", close=Decimal("12.00"))
    # 仅回放数据库响应，不解释 SQL，不在替身内实现冲突合并或来源优先级。
    response = Mock()
    response.all.return_value = []
    response.mappings.return_value = [existing]
    connection = Mock()
    connection.execute.return_value = response
    stats = upsert(
        connection,
        make_result(bars=(incoming,)),
        source="mairui",
        licence_id=None,
        fetched_at=dt.datetime(2026, 8, 8, tzinfo=dt.UTC),
    )
    assert getattr(stats, "replaced", None) == 1, (
        "契约 §4、§5 C1：麦蕊后到应替换 tdx_local；UpsertStats.replaced 应计 1"
    )
    assert stats.conflicts == 0, "契约 §4：合法替换不计 conflict"


def test_minute_sources_use_disjoint_date_segments() -> None:
    make_entry = entry(CATALOG, "CatalogEntry", "§3.3、§4、§5 C2")
    effective = entry(CATALOG, "effective_range", "§3.3、§4")
    overlap = entry(CATALOG, "check_overlap", "§3.3、§4")
    # 未验证：目录函数名与构造签名取自 origin/be/T-B143；目录列与规则见 §3.3。
    common = dict(
        code=CODE,
        kind="1m",
        date_from=dt.date(2026, 8, 6),
        date_to=DAY,
        sha256="a" * 64,
        row_count=480,
        generator="合成夹具",
    )
    hf = make_entry(
        **common, source="hf_1min", splice_segment="hf_1m", rel_path="hf/a.parquet"
    )
    tdx = make_entry(
        **common,
        source="tdx_local",
        splice_segment="vipdoc_1m",
        rel_path="tdx/a.parquet",
    )
    assert effective(hf) == (dt.date(2026, 8, 6), dt.date(2026, 8, 6)), (
        "契约 §3.2、§3.3、§4：HF 有效区间截止 2026-08-06"
    )
    assert effective(tdx) == (DAY, DAY), "契约 §3.3、§4：08-07 同日只取 tdx_local"
    overlap([hf], tdx)
    duplicate = make_entry(
        **common,
        source="tdx_local",
        splice_segment="vipdoc_1m",
        rel_path="tdx/重复.parquet",
    )
    with pytest.raises(ValueError, match="重叠"):
        overlap([hf, tdx], duplicate)


def test_gbbq_reference_price() -> None:
    reference = entry(GBBQ, "ref_price", "§2.5、§3.4、§5 C5、§7")
    # 假权息表已按 §3.4 映射为每股值；期望为 §7 的手算常量。
    event = dict(
        cash=Decimal("0.2"),
        rights_price=Decimal("8"),
        bonus=Decimal("0.1"),
        rights=Decimal("0.1"),
    )
    actual = reference(pc_raw=Decimal("12"), **event)
    assert actual == Decimal("10.50"), "契约 §2.5、§7：按 gbbq 计算除权参考价 10.50"


@pytest.mark.parametrize("scenario", ["单一快照且不偷看未来", "缺少前收", "参考价非正"])
def test_gbbq_adjustment_factors(scenario: str) -> None:
    calculate = entry(GBBQ, "compute_adjust_factors", "§2.5、§5 C5、§7（入口未验证）")
    # 未验证：此函数名、参数名、事件字典及结果结构尚待契约补齐；不假装为既定 API。
    # 每股红利 2 元，12 元前收对应 10 元参考价，后复权因子应为常量 1.2。
    snapshot = "a" * 64
    event = dict(
        code=CODE,
        ex_date=DAY,
        snapshot_sha256=snapshot,
        cash_per_share=Decimal(2),
        rights_price=Decimal(0),
        bonus_ratio=Decimal(0),
        rights_ratio=Decimal(0),
    )
    events = [
        event,
        dict(event, snapshot_sha256="b" * 64),
        dict(event, ex_date=dt.date(2026, 8, 10)),
    ]
    previous = {dt.date(2026, 8, 6): Decimal(12)}
    if scenario == "缺少前收":
        previous = {}
    elif scenario == "参考价非正":
        events[0] = dict(event, cash_per_share=Decimal(12))
    result = calculate(
        code=CODE,
        trade_dates=[dt.date(2026, 8, 6), DAY],
        raw_closes=previous,
        events=events,
        snapshot_sha256=snapshot,
    )
    assert result.snapshot_sha256 == snapshot, "契约 §2.5：结果必须记下唯一 gbbq 快照"
    if scenario == "单一快照且不偷看未来":
        assert result.factors == {
            dt.date(2026, 8, 6): Decimal(1),
            DAY: Decimal("1.2"),
        }, "契约 §2.5：最早因子为 1；仅一次计入选定快照的当日事件，未来事件不得参与"
    else:
        assert result.factors.get(DAY) is None, (
            "契约 §2.5：前收缺失或参考价非正不得补因子 1"
        )
        assert "adjust_factor_missing:2026-08-07" in result.issues, (
            "契约 §2.5：无效事件必须记除权日缺口"
        )

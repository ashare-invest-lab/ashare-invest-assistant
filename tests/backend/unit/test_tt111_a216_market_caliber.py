"""T-A216 offline contract checks for realtime market caliber.

All values in this module are synthetic.  The tests do not load captures, call a
provider, or construct a database client.  They cover the public MarketBasis and
Bar contracts plus the conservative paths already present on main.
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import inspect
import socket
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        pytest.fail("T-A216 离线契约测试禁止网络访问")

    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)


def _module(name: str, reason: str) -> Any:
    if importlib.util.find_spec(name) is None:
        pytest.xfail(reason)
    return importlib.import_module(name)


def _bar_row(fetched_at: dt.datetime) -> SimpleNamespace:
    return SimpleNamespace(
        trade_date=dt.date(2031, 2, 3),
        open="12.10",
        high="12.80",
        low="11.90",
        close="12.50",
        pre_close="12.00",
        volume="1200",
        amount="15000.00",
        fetched_at=fetched_at,
    )


def _find_rows_entrypoint(
    modules: tuple[str, ...],
    names: tuple[str, ...],
    predicate: Any,
) -> Any | None:
    """Find an implemented production entrypoint without treating models as one."""
    for module_name in modules:
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        for name in names:
            candidate = getattr(module, name, None)
            if callable(candidate):
                return candidate
        for name, candidate in vars(module).items():
            if callable(candidate) and predicate(name.lower()):
                return candidate
    return None


def _call_rows_entrypoint(entrypoint: Any, rows: list[dict[str, str]]) -> Any:
    """Call a rows-based entrypoint while supplying a synthetic ssjy/all source."""
    parameters = inspect.signature(entrypoint).parameters
    row_name = next(
        (
            name
            for name in ("rows", "batch_rows", "snapshot_rows", "records", "items", "batch")
            if name in parameters
        ),
        None,
    )
    source_name = next(
        (name for name in ("source", "batch_source", "source_name") if name in parameters),
        None,
    )
    kwargs: dict[str, Any] = {}
    if row_name is not None:
        kwargs[row_name] = rows
    if source_name is not None:
        kwargs[source_name] = "ssjy/all"
    if row_name is not None or source_name is not None:
        return entrypoint(**kwargs)
    return entrypoint(rows)


def _basis_or_rows(result: Any) -> tuple[str, Any]:
    """Normalize a mapper result to either its basis object or filtered rows."""
    if isinstance(result, dict):
        for key in ("basis", "market_basis"):
            if key in result:
                return _basis_or_rows(result[key])
        if "eligible" in result or "scope" in result:
            return "basis", result
    for attribute in ("basis", "market_basis"):
        nested = getattr(result, attribute, None)
        if nested is not None:
            return _basis_or_rows(nested)
    if any(hasattr(result, field) for field in ("eligible", "scope")):
        return "basis", result
    if isinstance(result, (list, tuple, set, frozenset)):
        for item in result:
            if isinstance(item, dict) and ("eligible" in item or "scope" in item):
                return "basis", item
            if any(hasattr(item, field) for field in ("eligible", "scope")):
                return "basis", item
        return "rows", result
    return "unknown", result


def _field(value: Any, name: str) -> Any:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def test_u1_market_basis_uses_stock_scope_and_uniform_batch() -> None:
    """A synthetic ssjy/all batch may contain an index, but basis stays stock-scoped."""
    rows = [
        {"dm": "SYN001.SH", "kind": "stock", "t": "2031-02-03T10:00:00+08:00"},
        {"dm": "SYNIDX.SH", "kind": "index", "t": "2031-02-03T10:00:00+08:00"},
    ]
    assert {row["t"] for row in rows} == {"2031-02-03T10:00:00+08:00"}
    mapper = _find_rows_entrypoint(
        (
            "app.aggregates.service",
            "app.aggregates.market",
            "app.marketdata.market",
            "app.marketdata.snapshot",
        ),
        (
            "market_basis_from_rows",
            "build_market_basis",
            "market_basis_from_batch",
            "market_eligibility_from_rows",
            "eligible_market_rows",
        ),
        lambda name: ("market" in name or "snapshot" in name)
        and ("basis" in name or "eligib" in name),
    )
    if mapper is None:
        pytest.xfail("资格池过滤未落地，待实现；不得把全市场行数当沪深股票分母")

    kind, mapped = _basis_or_rows(_call_rows_entrypoint(mapper, rows))
    if kind == "basis":
        assert _field(mapped, "scope") == "沪深股票口径"
        assert _field(mapped, "eligible") == 1
        for field in ("observed", "trading", "suspended", "missing"):
            count = _field(mapped, field)
            if count is not None:
                assert count <= 1
    elif kind == "rows":
        assert len(mapped) == 1
        assert next(iter(mapped))["kind"] == "stock"
    else:
        pytest.fail("资格池入口未返回可核验的 MarketBasis 或过滤后行")


def test_u1_missing_index_fields_are_null_with_gap() -> None:
    service = _module("app.aggregates.service", "U1 market service 未实现")
    from app.aggregates.models import MarketClock
    from app.schemas.enums import GapReason, MarketSession

    overview = service.market(
        MarketClock(trade_date=dt.date(2031, 2, 3), session=MarketSession.MORNING)
    )
    assert overview.indices == []
    assert all(
        field is None
        for item in overview.indices
        for field in (item.price, item.change_pct, item.amount, item.t)
    )
    assert overview.gaps
    assert any(gap.reason is GapReason.NO_SOURCE for gap in overview.gaps)


def test_u1_snapshot_units_wait_for_a_normalizer() -> None:
    service = _module("app.aggregates.service", "U1/U8 实时快照单位归一化未实现，待 T-B203 真调")
    normalizer = getattr(service, "normalize_realtime_quote", None)
    if not callable(normalizer):
        pytest.xfail("U1/U8 real/time 与 ssjy 单位归一化未实现，待 T-B203 真调")
    ssjy = normalizer(
        {"dm": "SYN001.SH", "p": "12.50", "v": "3", "cje": "700", "pv": "300"},
        source="ssjy",
    )
    real_time = normalizer(
        {"dm": "SYN001.SH", "p": "12.50", "v": "3", "cje": "700", "pv": "300"},
        source="real/time",
    )
    # 同一原始 v 不得跨套「手」与「万手」。手→股乘数未验证，不断言具体股数。
    if "volume_unit" in ssjy or "volume_unit" in real_time:
        assert ssjy.get("volume_unit") != real_time.get("volume_unit")
    else:
        assert ssjy["volume"] != real_time["volume"]
    assert ssjy["amount"] == real_time["amount"] == "700"


@pytest.mark.parametrize(
    ("fetched", "expected"),
    [
        (dt.datetime(2031, 2, 3, 17, 9, tzinfo=dt.timezone(dt.timedelta(hours=8))), False),
        (dt.datetime(2031, 2, 3, 17, 10, tzinfo=dt.timezone(dt.timedelta(hours=8))), True),
    ],
)
def test_close_batch_final_after_is_applied(fetched: dt.datetime, expected: bool) -> None:
    mod = _module("app.marketdata.daily_snapshot", "U1 日快照 final 规则未实现")
    item = mod._bar_item(_bar_row(fetched))
    assert item["is_final"] is expected
    assert item["first_seen_at"].endswith("+08:00")


@pytest.mark.parametrize(
    "clock",
    [
        dt.datetime(2031, 2, 3, 15, 0, tzinfo=dt.timezone(dt.timedelta(hours=8))),
        dt.datetime(2031, 2, 3, 15, 5, tzinfo=dt.timezone(dt.timedelta(hours=8))),
    ],
)
def test_close_batch_1500_and_1505_are_not_formal_daily_close(clock: dt.datetime) -> None:
    mod = _module("app.marketdata.daily_snapshot", "U1 日快照 final 规则未实现")
    assert mod._bar_item(_bar_row(clock))["is_final"] is False


def test_u1_source_completion_at_1505_is_unverified() -> None:
    mod = _module("app.marketdata.daily_snapshot", "U1 来源完成事实未实现，待 T-B203 真调")
    if not callable(getattr(mod, "source_completion_at", None)):
        pytest.xfail("U1 15:05 来源完成标记与终值仍未验证，待 T-B203 真调")
    assert mod.source_completion_at(dt.date(2031, 2, 3), dt.time(15, 5)) is False


def test_u4_market_without_limit_source_is_null_with_no_source_gap() -> None:
    service = _module("app.aggregates.service", "U4 market service 未实现")
    from app.aggregates.models import MarketClock
    from app.schemas.enums import GapReason, MarketSession

    result = service.market(
        MarketClock(trade_date=dt.date(2031, 2, 3), session=MarketSession.AFTERNOON)
    )
    assert result.breadth is None
    assert result.gaps
    assert result.gaps[0].reason is GapReason.NO_SOURCE


def test_u4_percentages_do_not_infer_limit_pool_counts() -> None:
    synthetic_rows = [
        {"dm": "SYN001.SH", "pc": "10.00"},
        {"dm": "SYN002.SH", "pc": "-10.00"},
        {"dm": "SYN003.SH", "pc": "20.00"},
        {"dm": "SYN004.SH", "pc": "-20.00"},
    ]
    breadth_fn = _find_rows_entrypoint(
        (
            "app.aggregates.service",
            "app.aggregates.breadth",
            "app.aggregates.market",
            "app.marketdata.market",
            "app.marketdata.snapshot",
        ),
        (
            "breadth_from_rows",
            "calculate_breadth",
            "aggregate_breadth",
            "market_breadth_from_rows",
            "build_breadth",
        ),
        lambda name: "breadth" in name
        and any(term in name for term in ("row", "snapshot", "market", "calc", "aggregate")),
    )
    if breadth_fn is None:
        pytest.xfail("无快照宽度入口；接入后不得用 pc 推算涨跌停")

    result = _call_rows_entrypoint(breadth_fn, synthetic_rows)
    breadth = (
        result.get("breadth")
        if isinstance(result, dict) and "breadth" in result
        else getattr(result, "breadth", result)
    )
    if isinstance(breadth, dict):
        assert {"limit_up", "limit_down"} <= breadth.keys()
        assert breadth["limit_up"] is None
        assert breadth["limit_down"] is None
    elif breadth is not None:
        assert hasattr(breadth, "limit_up") and hasattr(breadth, "limit_down")
        assert getattr(breadth, "limit_up", None) is None
        assert getattr(breadth, "limit_down", None) is None


def test_u4_limit_pool_source_and_special_rule_fields_are_unverified() -> None:
    service = _module("app.aggregates.service", "U4 涨跌停池未实现，待 T-B203 真调")
    if not callable(getattr(service, "read_limit_pool", None)):
        pytest.xfail("U4 封板字段、发布时间、dm 覆盖及停牌/零量/ST规则未验证，待 T-B203 真调")
    assert service.read_limit_pool([]) is None


def test_u8_complete_minute_bar_keeps_end_time_and_decimal_zero() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现")
    bar = bars.Bar(
        t="2031-02-03T09:31:00+08:00",
        open="12.10",
        high="12.80",
        low="11.90",
        close="12.50",
        pre_close="12.00",
        volume="0",
        amount="0",
        avg_price=None,
        is_final=False,
    )
    assert bar.t.endswith("09:31:00+08:00")
    assert bar.volume == bar.amount == "0"
    assert bar.close == "12.50"


def test_u8_missing_close_cannot_become_a_public_minute_bar() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现")
    with pytest.raises(ValidationError):
        bars.Bar(
            t="2031-02-03T09:31:00+08:00",
            open="12.10",
            high="12.80",
            low="11.90",
            close=None,
            pre_close="12.00",
            volume="100",
            amount="1250",
            avg_price=None,
            is_final=False,
        )


def test_u8_late_minute_revision_dedup_is_unimplemented() -> None:
    candidates = ("app.marketdata.intraday_bars", "app.marketdata.bars_write", "app.intraday.engine")
    names = ("deduplicate_bars", "upsert_minute_bars", "merge_minute_revision")
    for module_name in candidates:
        if importlib.util.find_spec(module_name) is None:
            continue
        module = importlib.import_module(module_name)
        if any(callable(getattr(module, name, None)) for name in names):
            pytest.fail("发现未定义测试契约的分钟去重入口，需要按 T-A216 重新核对")
    pytest.xfail("U8 1m 按(code,ts)保留较新 fetched_at 且不回写冻结信号未实现，待 T-B203 真调")


def test_u8_minute_supplier_units_end_labels_and_etf_coverage_unverified() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现")
    if not hasattr(bars, "minute_source_evidence"):
        pytest.xfail("U8 1m供应商字段、单位、结束标签及ETF覆盖未验证，待 T-B203 真调")
    assert bars.minute_source_evidence("synthetic") is None

"""T-A216 offline contract checks for realtime market caliber.

All values in this module are synthetic.  The tests do not load captures, call a
provider, or construct a database client.  They cover the public MarketBasis and
Bar contracts plus the conservative paths already present on main.
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
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


OVERVIEW_FIELDS = {
    "basis",
    "trade_date",
    "session",
    "indices",
    "breadth",
    "regime",
    "regime_position_range",
    "turnover_total",
    "data_status",
    "data_as_of",
    "gaps",
}
BASIS_FIELDS = {
    "snapshot_id",
    "observed_date",
    "mode",
    "scope",
    "eligible",
    "observed",
    "trading",
    "suspended",
    "missing",
    "source",
}
BREADTH_FIELDS = {"up", "down", "flat", "limit_up", "limit_down"}


def _public_market_overview() -> dict[str, Any]:
    service = _module("app.aggregates.service", "U1/U4 市场概览未实现，待 T-B203 真调")
    from app.aggregates.models import MarketClock
    from app.schemas.enums import MarketSession

    return service.market(
        MarketClock(trade_date=dt.date(2031, 2, 3), session=MarketSession.MORNING)
    ).model_dump(mode="json")


def test_u1_market_basis_uses_stock_scope_and_uniform_batch() -> None:
    # 出处: docs/api-contract.md v0.2.11 §5.1 MarketBasis、§7.3 /market/overview。
    overview = _public_market_overview()
    assert OVERVIEW_FIELDS <= overview.keys()
    basis = overview["basis"]
    if basis is None:
        pytest.xfail("资格池过滤未落地，待 T-B203 真调；不得把全市场行数当沪深股票分母")
    assert BASIS_FIELDS <= basis.keys()
    assert basis["scope"] == "沪深股票口径"
    eligible = basis["eligible"]
    if eligible is None:
        assert all(
            basis[field] is None for field in ("observed", "trading", "suspended", "missing")
        )
        pytest.xfail("资格池计数未落地，待 T-B203 真调；不得把全市场行数当沪深股票分母")
    for field in ("observed", "trading", "suspended", "missing"):
        count = basis[field]
        if count is not None:
            assert count <= eligible
    if basis["observed"] is not None and basis["missing"] is not None:
        assert basis["missing"] == eligible - basis["observed"]
    pytest.xfail("公开入口尚不能注入含指数的合成批次以核验股票口径过滤，待 T-B203 真调")


def test_u1_missing_index_fields_are_null_with_gap() -> None:
    service = _module("app.aggregates.service", "U1 market service 未实现，待 T-B203 真调")
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
    quotes = _module("app.marketdata.quotes_read", "U1/U8 单位未验证，待 T-B203 真调")
    from app.marketdata.subresource_read import Gap
    from app.schemas.enums import DataStatus, GapReason

    unknown = quotes.QuoteItem(
        security_code="SYN001.SH",
        name="合成证券",
        data_status=DataStatus.UNAVAILABLE,
        gaps=[Gap(key="quotes.amount", reason=GapReason.NO_SOURCE, message="合成缺口")],
    )
    assert unknown.volume is None
    assert unknown.amount is None
    assert unknown.gaps[0].reason is GapReason.NO_SOURCE
    zero = quotes.QuoteItem(
        security_code="SYN002.SH",
        name="合成零量证券",
        volume="0",
        amount="0",
        data_status=DataStatus.STALE,
        gaps=[],
    )
    assert zero.volume == zero.amount == "0"
    pytest.xfail("U1/U8 单位未验证，待 T-B203 真调")


@pytest.mark.parametrize(
    ("fetched", "expected"),
    [
        (dt.datetime(2031, 2, 3, 17, 9, tzinfo=dt.timezone(dt.timedelta(hours=8))), False),
        (dt.datetime(2031, 2, 3, 17, 10, tzinfo=dt.timezone(dt.timedelta(hours=8))), True),
    ],
)
def test_close_batch_final_after_is_applied(fetched: dt.datetime, expected: bool) -> None:
    mod = _module("app.marketdata.daily_snapshot", "U1 日快照 final 规则未实现，待 T-B203 真调")
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
    mod = _module("app.marketdata.daily_snapshot", "U1 日快照 final 规则未实现，待 T-B203 真调")
    assert mod._bar_item(_bar_row(clock))["is_final"] is False


def test_u1_1505_completion_is_unverified() -> None:
    overview = _public_market_overview()
    assert overview["data_status"] == "unavailable"
    assert any(gap["reason"] == "no_source" for gap in overview["gaps"])
    pytest.xfail("U1 15:05 来源完成标记与终值未验证，待 T-B203 真调")


def test_u4_market_without_limit_source_is_null_with_no_source_gap() -> None:
    service = _module("app.aggregates.service", "U4 market service 未实现，待 T-B203 真调")
    from app.aggregates.models import MarketClock
    from app.schemas.enums import GapReason, MarketSession

    result = service.market(
        MarketClock(trade_date=dt.date(2031, 2, 3), session=MarketSession.AFTERNOON)
    )
    assert result.breadth is None
    assert result.gaps
    assert result.gaps[0].reason is GapReason.NO_SOURCE


def test_u4_percentages_do_not_infer_limit_pool_counts() -> None:
    # 出处: docs/api-contract.md v0.2.11 §7.3 breadth 形状；无来源时整体为 null。
    overview = _public_market_overview()
    assert OVERVIEW_FIELDS <= overview.keys()
    breadth = overview["breadth"]
    if breadth is None:
        assert any(gap["reason"] == "no_source" for gap in overview["gaps"])
        pytest.xfail("公开入口尚不能注入仅含 pc 的批次以核验不得用 ±10% 推算涨跌停，待 T-B203 真调")
    assert BREADTH_FIELDS <= breadth.keys()
    pytest.xfail("公开入口尚不能注入仅含 pc 的批次以核验不得用 ±10% 推算涨跌停，待 T-B203 真调")


def test_u4_limit_pool_source_and_special_rule_fields_are_unverified() -> None:
    overview = _public_market_overview()
    breadth = overview["breadth"]
    if breadth is not None:
        assert BREADTH_FIELDS <= breadth.keys()
    pytest.xfail("U4 涨跌停池字段、发布时间、覆盖及特殊规则未验证，待 T-B203 真调")


def test_u8_complete_minute_bar_keeps_end_time_and_decimal_zero() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现，待 T-B203 真调")
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
    end = dt.datetime.fromisoformat(bar.t)
    assert end.utcoffset() == dt.timedelta(hours=8)
    assert end.time() == dt.time(9, 31)
    assert bar.volume == bar.amount == "0"
    assert bar.close == "12.50"


def test_u8_missing_close_cannot_become_a_public_minute_bar() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现，待 T-B203 真调")
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


def test_u8_late_minute_revision_is_unverified() -> None:
    bars = _module("app.marketdata.bars_read", "U8 1m 读取入口未实现，待 T-B203 真调")
    bar = bars.Bar(
        t="2031-02-03T09:31:00+08:00",
        open="12.10",
        high="12.80",
        low="11.90",
        close="12.50",
        pre_close="12.00",
        volume="100",
        amount="1250",
        avg_price=None,
        is_final=True,
    )
    assert bar.close == "12.50"
    pytest.xfail("U8 1m 晚到修订、fetched_at 选择及冻结信号未验证，待 T-B203 真调")


def test_u8_minute_supplier_units_end_labels_and_etf_coverage_unverified() -> None:
    bars = _module("app.marketdata.bars_read", "U8 Bar 模型未实现，待 T-B203 真调")
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
        is_final=True,
    )
    assert bar.volume == bar.amount == "0"
    pytest.xfail("U8 1m 供应商字段、单位、结束标签及 ETF 覆盖未验证，待 T-B203 真调")

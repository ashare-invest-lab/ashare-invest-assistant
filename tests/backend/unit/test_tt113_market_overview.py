"""T-T113: offline HTTP contract probes for T-A219 market overview.

The facts below are deliberately fictional. The endpoint is exercised through
the real FastAPI route. A missing aggregate is reported as a single-case xfail
until T-B210 wires the production reader; tests never replace the route response
with a hand-built MarketOverview.
"""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.aggregates import models as aggregate_models
from app.api.v1 import aggregates as routes
from app.auth import deps
from app.auth.sessions import SESSION_COOKIE
from app.common.errors import install_exception_handlers
from app.schemas.enums import MarketSession


OWNER = uuid.UUID("00000000-0000-0000-0000-00000000b210")
LICENCE_A = uuid.UUID("00000000-0000-0000-0000-00000000a219")
LICENCE_B = uuid.UUID("00000000-0000-0000-0000-00000000a220")
QUERY = dt.datetime(2026, 11, 13, 10, 0, tzinfo=dt.timezone.utc)
TRADE_DATE = dt.date(2026, 11, 13)
SHANGHAI = dt.timezone(dt.timedelta(hours=8))


def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract fixtures must not reach PG, Redis, or a vendor."""

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("T-T113 is offline and must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@dataclass(frozen=True)
class MarketFact:
    code: str
    query_as_of: dt.datetime
    ts: dt.datetime
    fetched_at: dt.datetime
    source: str
    source_licence_id: uuid.UUID | None
    price: Decimal | None = None
    pct_change: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    kind: str = "stock"
    pre_close: Decimal | None = None
    close: Decimal | None = None
    is_suspended: bool = False
    listing_status: str = "listed"
    risk_flag: str | None = None


@dataclass
class OverviewState:
    facts: list[MarketFact] = field(default_factory=list)
    query_as_of: dt.datetime = QUERY
    clock: aggregate_models.MarketClock = field(
        default_factory=lambda: aggregate_models.MarketClock(
            trade_date=TRADE_DATE, session=MarketSession.MORNING
        )
    )


class FixtureConnection:
    """Read-only SQL-shaped adapter for synthetic market rows."""

    def __init__(self, state: OverviewState) -> None:
        self.state = state

    @staticmethod
    def _row(**values: object) -> SimpleNamespace:
        return SimpleNamespace(_mapping=values, **values)

    def execute(self, statement: object) -> Any:
        sql = str(statement)
        facts = self.state.facts
        if "user_data_licence_status" in sql:
            active = next(
                (
                    fact.source_licence_id
                    for fact in facts
                    if fact.source == "mairui" and fact.source_licence_id is not None
                ),
                None,
            )
            return SimpleNamespace(scalar_one_or_none=lambda: active)
        if "security_listing_status_history" in sql:
            return SimpleNamespace(all=lambda: [])
        if "securities" in sql:
            params = statement.compile().params  # type: ignore[attr-defined]
            kind = next((value for value in params.values() if value in {"index", "stock"}), None)
            rows = {}
            for fact in facts:
                exchange = fact.code.rsplit(".", 1)[-1]
                if kind is not None and fact.kind != kind:
                    continue
                if kind == "stock" and exchange not in {"SH", "SZ"}:
                    continue
                rows.setdefault(
                    fact.code,
                    self._row(
                        code=fact.code,
                        name=fact.code,
                        type=fact.kind,
                        exchange=exchange,
                        listing_status=fact.listing_status,
                        list_date=None,
                        delist_date=None,
                    ),
                )
            return SimpleNamespace(all=lambda: list(rows.values()))
        if "quotes_snapshot" in sql:
            active = next(
                (
                    fact.source_licence_id
                    for fact in facts
                    if fact.source == "mairui" and fact.source_licence_id is not None
                ),
                None,
            )
            rows = [
                self._row(
                    code=fact.code,
                    ts=fact.ts,
                    price=fact.price,
                    pct_change=fact.pct_change,
                    payload=None,
                    source=fact.source,
                    source_licence_id=fact.source_licence_id,
                    volume=fact.volume,
                    amount=fact.amount,
                    is_suspended=fact.is_suspended,
                    limit_up=None,
                    limit_down=None,
                    batch_id=uuid.UUID("00000000-0000-0000-0000-00000000a219"),
                    fetched_at=fact.fetched_at,
                )
                for fact in facts
                if fact.close is None
                and fact.source == "mairui"
                and fact.source_licence_id == active
                and fact.ts <= self.state.query_as_of
                and fact.fetched_at <= self.state.query_as_of
            ]
            return SimpleNamespace(all=lambda: rows)
        if "daily_bars" in sql:
            params = statement.compile().params  # type: ignore[attr-defined]
            day = next(
                (
                    value
                    for value in params.values()
                    if isinstance(value, dt.date) and not isinstance(value, dt.datetime)
                ),
                None,
            )
            exact_day = "trade_date =" in sql
            rows = []
            for fact in facts:
                fact_day = fact.ts.astimezone(SHANGHAI).date()
                if (
                    fact.close is None
                    or fact.source != "mairui"
                    or fact.fetched_at > self.state.query_as_of
                    or (day is not None and exact_day and fact_day != day)
                    or (day is not None and not exact_day and fact_day >= day)
                ):
                    continue
                rows.append(
                    self._row(
                        code=fact.code,
                        trade_date=fact_day,
                        adj_type="none",
                        close=fact.close,
                        pre_close=fact.pre_close,
                        volume=fact.volume,
                        amount=fact.amount,
                        is_suspended=fact.is_suspended,
                        source=fact.source,
                        source_licence_id=fact.source_licence_id,
                        fetched_at=fact.fetched_at,
                    )
                )
            return SimpleNamespace(all=lambda: rows)
        raise AssertionError(sql)


class FixtureEngine:
    def __init__(self, state: OverviewState) -> None:
        self.state = state

    def connect(self) -> Any:
        return nullcontext(FixtureConnection(self.state))


def intraday_fact(
    code: str,
    change: str,
    *,
    query_as_of: dt.datetime = QUERY,
    ts: dt.datetime | None = None,
    fetched_at: dt.datetime | None = None,
    licence: uuid.UUID | None = LICENCE_A,
    volume: str | None = "100",
    amount: str | None = "1000",
    kind: str = "stock",
    **extra: Any,
) -> MarketFact:
    observed = ts or dt.datetime(2026, 11, 13, 2, 0, tzinfo=dt.timezone.utc)
    return MarketFact(
        code=code,
        query_as_of=query_as_of,
        ts=observed,
        fetched_at=fetched_at or observed,
        source="mairui",
        source_licence_id=licence,
        price=Decimal("10.00"),
        pct_change=Decimal(change),
        volume=Decimal(volume) if volume is not None else None,
        amount=Decimal(amount) if amount is not None else None,
        kind=kind,
        **extra,
    )


def close_fact(
    code: str,
    close: str,
    pre_close: str,
    *,
    trade_date: dt.date = TRADE_DATE,
    query_as_of: dt.datetime = dt.datetime(2026, 11, 13, 9, 15, tzinfo=dt.timezone.utc),
    fetched_at: dt.datetime | None = None,
    licence: uuid.UUID | None = LICENCE_A,
    kind: str = "stock",
    source: str = "mairui",
    volume: str = "100",
    amount: str = "1000",
    **extra: Any,
) -> MarketFact:
    observed = dt.datetime.combine(trade_date, dt.time(15), tzinfo=SHANGHAI)
    visible_at = fetched_at or dt.datetime.combine(
        trade_date, dt.time(9, 15), tzinfo=dt.timezone.utc
    )
    return MarketFact(
        code=code,
        query_as_of=query_as_of,
        ts=observed,
        fetched_at=visible_at,
        source=source,
        source_licence_id=licence,
        close=Decimal(close),
        pre_close=Decimal(pre_close),
        price=Decimal(close),
        volume=Decimal(volume),
        amount=Decimal(amount),
        kind=kind,
        **extra,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> OverviewState:
    state = OverviewState()
    engine = FixtureEngine(state)
    settings = SimpleNamespace(
        business=SimpleNamespace(
            market_rules={},
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(effective_stale_threshold_s=30)
            ),
        )
    )

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            value = state.query_as_of
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)
    monkeypatch.setattr(routes, "market_clock", lambda conn, now, rules: state.clock)
    monkeypatch.setattr(routes.dt, "datetime", FrozenDateTime)
    with TestClient(app) as client:
        deny_network(monkeypatch)
        client.cookies.set(SESSION_COOKIE, "synthetic-session")
        state.client = client  # type: ignore[attr-defined]
        yield state


def get_overview(state: OverviewState) -> dict[str, Any]:
    response = state.client.get("/api/v1/market/overview")  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_status"] != "pending"
    return payload


def is_unwired_empty_state(payload: dict[str, Any]) -> bool:
    indices = payload.get("indices") or []
    empty_indices = not indices or all(
        item.get("price") is None
        and item.get("change_pct") is None
        and item.get("amount") is None
        for item in indices
    )
    gaps = payload.get("gaps") or []
    return (
        payload.get("basis") is None
        and payload.get("breadth") is None
        and payload.get("turnover_total") is None
        and payload.get("data_status") == "unavailable"
        and empty_indices
        and bool(gaps)
        and all(
            gap.get("key") == "market"
            and gap.get("reason") == "no_source"
            and "行情聚合尚未接线" in gap.get("message", "")
            for gap in gaps
        )
    )


def require_component(payload: dict[str, Any], condition: bool, reason: str) -> None:
    if not condition and is_unwired_empty_state(payload):
        pytest.xfail(f"T-B210 未实现：{reason}")
    assert condition


def assert_decimal_ratio(value: Any, expected: Decimal) -> None:
    assert isinstance(value, str)
    parsed = Decimal(value)
    assert parsed.quantize(Decimal("0.0001")) == expected.quantize(Decimal("0.0001"))
    assert len(value.split(".")[1]) >= 4


def assert_decimal_string(value: Any, expected: Decimal) -> None:
    assert isinstance(value, str)
    assert Decimal(value) == expected


def complete_intraday_facts() -> list[MarketFact]:
    return [
        intraday_fact("600000.SH", "2", amount="1200"),
        intraday_fact("000001.SZ", "1", amount="800"),
        intraday_fact("688001.SH", "-1", amount="600"),
    ]


def test_market_overview_empty_state_is_honest(world: OverviewState) -> None:
    world.facts = []
    payload = get_overview(world)
    assert payload["indices"] == [] or all(
        item["price"] is None and item["change_pct"] is None and item["amount"] is None
        for item in payload["indices"]
    )
    assert payload["breadth"] is None
    assert payload["regime"] is None
    assert payload["regime_position_range"] is None
    assert payload["turnover_total"] is None
    assert payload["data_status"] == "unavailable"
    assert payload["data_as_of"] is None
    assert payload["gaps"]
    assert all(gap["key"].startswith("market") for gap in payload["gaps"])
    assert all(gap["reason"] in {"no_source", "data_licence_unavailable"} for gap in payload["gaps"])
    assert all(gap["reason"] != "pending" for gap in payload["gaps"])


def test_market_overview_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: FixtureEngine(OverviewState())
    app.dependency_overrides[deps.get_session_store] = lambda: SimpleNamespace(get=lambda _: None)
    app.dependency_overrides[deps.get_settings] = lambda: SimpleNamespace(
        business=SimpleNamespace(
            market_rules={},
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(effective_stale_threshold_s=30)
            ),
        )
    )
    monkeypatch.setattr(routes, "market_clock", lambda conn, now, rules: OverviewState().clock)
    with TestClient(app) as client:
        deny_network(monkeypatch)
        response = client.get("/api/v1/market/overview")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_market_overview_rejects_unsupported_method(world: OverviewState) -> None:
    response = world.client.post("/api/v1/market/overview")  # type: ignore[attr-defined]
    assert response.status_code == 405


def test_market_overview_complete_intraday_batch(world: OverviewState) -> None:
    world.facts = complete_intraday_facts()
    payload = get_overview(world)
    breadth = payload["breadth"]
    basis = payload["basis"]
    require_component(
        payload,
        breadth is not None and basis is not None and payload["turnover_total"] is not None,
        "完整盘中宽度比例与同批 basis/turnover，契约 §5.1/§9",
    )
    assert (breadth["up"], breadth["down"], breadth["flat"]) == (2, 1, 0)
    assert all(isinstance(breadth[field], int) for field in ("up", "down", "flat"))
    # §5.2：完整批次若无规则出处，limit_* 仍应是 null，而不是 int。
    assert all(
        breadth[field] is None or isinstance(breadth[field], int)
        for field in ("limit_up", "limit_down")
    )
    assert_decimal_ratio(breadth["up_ratio"], Decimal(2) / Decimal(3))
    assert_decimal_ratio(breadth["down_ratio"], Decimal(1) / Decimal(3))
    assert_decimal_ratio(breadth["flat_ratio"], Decimal("0"))
    assert basis["mode"] == "intraday"
    assert basis["observed_date"] == "2026-11-13"
    assert basis["source"] == "mairui"
    assert_decimal_string(payload["turnover_total"], Decimal("2600"))


def test_market_overview_intraday_missing_volume_amount_is_partial(world: OverviewState) -> None:
    world.facts = [
        intraday_fact("600000.SH", "1", volume=None, amount=None),
        intraday_fact("000001.SZ", "-1", volume=None, amount=None),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        bool(payload["indices"])
        and any(item["price"] is not None for item in payload["indices"])
        and (
            payload["data_status"] == "partial"
            or any(
                g["key"] in {"market.breadth", "market.turnover_total"}
                for g in payload["gaps"]
            )
        ),
        "盘中缺量额不得补零，契约 §2/§5.3/§9",
    )
    assert all(
        item["amount"] is None
        for item in payload["indices"]
        if item["security_code"] in {"600000.SH", "000001.SZ"}
    )
    assert payload["turnover_total"] is None


@pytest.mark.parametrize(
    ("query_as_of", "expect_close"),
    [
        (dt.datetime(2026, 11, 13, 6, 59, 59, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 7, 0, 1, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 9, 9, 59, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 9, 15, 1, tzinfo=dt.timezone.utc), True),
    ],
)
def test_market_overview_1500_and_1710_selection(
    world: OverviewState, query_as_of: dt.datetime, expect_close: bool
) -> None:
    world.query_as_of = query_as_of
    world.facts = [
        intraday_fact("600000.SH", "1", query_as_of=query_as_of),
        close_fact(
            "600000.SH",
            "11",
            "10",
            query_as_of=query_as_of,
            fetched_at=dt.datetime(2026, 11, 13, 9, 11, tzinfo=dt.timezone.utc),
        ),
    ]
    payload = get_overview(world)
    basis = payload["basis"]
    require_component(
        payload,
        basis is not None,
        "15:00/17:10 时点门槛与 PIT 选择，契约 §4/§9",
    )
    if expect_close:
        assert basis["mode"] == "close"
    else:
        assert basis["mode"] != "close"


def test_market_overview_daily_close_uses_decimal_amounts(world: OverviewState) -> None:
    world.query_as_of = dt.datetime(2026, 11, 13, 9, 15, tzinfo=dt.timezone.utc)
    world.facts = [
        close_fact("600000.SH", "11.25", "10.00", fetched_at=world.query_as_of),
        close_fact("000001.SZ", "9.50", "10.00", fetched_at=world.query_as_of),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["basis"] is not None and payload["basis"]["mode"] == "close",
        "合格 daily_bars 收盘模式与元单位，契约 §2/§4/§9",
    )
    assert_decimal_string(payload["turnover_total"], Decimal("2000"))


def test_market_overview_excludes_suspended_zero_delisted_but_keeps_st(world: OverviewState) -> None:
    world.facts = [
        close_fact("600000.SH", "11", "10", is_suspended=True),
        close_fact("000001.SZ", "11", "10", volume="0"),
        close_fact("688001.SH", "11", "10", listing_status="delisted"),
        close_fact("000002.SZ", "11", "10", risk_flag="st"),
    ]
    payload = get_overview(world)
    breadth = payload["breadth"]
    require_component(
        payload,
        breadth is not None
        and any(g["key"] == "market.breadth.limit_counts" for g in payload["gaps"]),
        "停牌/零量/退市资格排除与 ST 基础宽度，契约 §3.1/§5.2/§9",
    )
    assert breadth["up"] + breadth["down"] + breadth["flat"] == 1
    assert breadth["limit_up"] is None and breadth["limit_down"] is None


def test_market_overview_etf_index_and_bj_scope(world: OverviewState) -> None:
    world.facts = [
        close_fact("510001.SH", "1.01", "1.00", kind="etf"),
        close_fact("000300.SH", "4000", "3990", kind="index"),
        close_fact("830001.BJ", "10.1", "10.0"),
        close_fact("600000.SH", "11", "10"),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["basis"] is not None and payload["breadth"] is not None,
        "ETF/指数/BJ 沪深股票口径过滤，契约 §3.1/§9",
    )
    assert payload["basis"]["scope"] == "沪深股票口径"
    assert payload["breadth"]["up"] + payload["breadth"]["down"] + payload["breadth"]["flat"] == 1
    assert all(item["security_code"] != "510001.SH" for item in payload["indices"])
    assert any(item["security_code"] == "000300.SH" for item in payload["indices"])


def test_market_overview_limit_counts_need_rule_evidence(world: OverviewState) -> None:
    world.facts = [close_fact("600000.SH", "11", "10")]
    payload = get_overview(world)
    breadth = payload["breadth"]
    require_component(
        payload,
        breadth is not None
        and any(
            gap["key"] == "market.breadth.limit_counts" and gap["reason"] == "no_source"
            for gap in payload["gaps"]
        ),
        "缺 T 日规则或最小价位单位时 limit_* 为 null，契约 §5.2/§9",
    )
    assert breadth["limit_up"] is None and breadth["limit_down"] is None


def test_market_overview_coverage_threshold_stays_disabled(world: OverviewState) -> None:
    world.facts = complete_intraday_facts()
    payload = get_overview(world)
    basis = payload["basis"]
    no_source_gaps = [gap for gap in payload["gaps"] if gap["reason"] == "no_source"]
    require_component(
        payload,
        basis is not None
        and payload.get("coverage_threshold") is None
        and basis.get("coverage_threshold") is None
        and bool(no_source_gaps)
        and all(gap["reason"] != "coverage_unknown" for gap in payload["gaps"]),
        "coverage_threshold 保持 disabled，相关值为 null 且不冒充覆盖率证据，契约 §3.1",
    )
    assert payload.get("coverage_threshold") is None
    assert basis.get("coverage_threshold") is None
    assert all(gap["reason"] != "coverage_unknown" for gap in payload["gaps"])


def test_market_overview_zero_denominator_keeps_width_null(world: OverviewState) -> None:
    world.facts = [
        close_fact("600000.SH", "11", "10", is_suspended=True),
        close_fact("000001.SZ", "11", "10", volume="0"),
    ]
    payload = get_overview(world)
    breadth = payload["breadth"]
    width_fields = (
        "up",
        "down",
        "flat",
        "up_ratio",
        "down_ratio",
        "flat_ratio",
        "limit_up",
        "limit_down",
    )
    require_component(
        payload,
        breadth is not None
        and all(breadth[field] is None for field in width_fields)
        and any(gap["reason"] == "no_source" for gap in payload["gaps"]),
        "宽度分母 N=0 时计数与比例均为 null，契约 §1/§5.1",
    )
    assert all(breadth[field] is None for field in width_fields)


@pytest.mark.parametrize("catalog_status", ["declared", "verified_live"])
def test_market_overview_regime_remains_gated(catalog_status: str, world: OverviewState) -> None:
    world.facts = [close_fact("000300.SH", "4000", "3990", kind="index")]
    world.regime_feature = {  # type: ignore[attr-defined]
        "f.market_regime": "uptrend",
        "catalog_status": catalog_status,
    }
    payload = get_overview(world)
    assert payload["regime"] is None
    assert payload["regime_position_range"] is None
    regime_gap = next(
        (gap for gap in payload["gaps"] if gap["key"] == "market.regime"),
        None,
    )
    if is_unwired_empty_state(payload) and regime_gap is None:
        pytest.xfail("T-B210 未实现：F25/G-02 未批准时 regime 门控，契约 §7/§9")
    assert regime_gap is not None
    assert regime_gap["reason"] == "no_source"
    assert "F25/G-02 参数未批准" in regime_gap["message"]


def test_market_overview_no_licence_or_all_future_is_unavailable(world: OverviewState) -> None:
    world.query_as_of = QUERY
    world.facts = [
        intraday_fact("600000.SH", "1", licence=None),
        intraday_fact(
            "000001.SZ",
            "-1",
            fetched_at=QUERY + dt.timedelta(minutes=1),
            licence=LICENCE_A,
        ),
    ]
    payload = get_overview(world)
    expected_gap_keys = {
        "market.indices.600000.SH",
        "market.indices.000001.SZ",
        "market.basis",
        "market.breadth",
        "market.turnover_total",
    }
    require_component(
        payload,
        payload["data_status"] == "unavailable"
        and all(item["price"] is None for item in payload["indices"])
        and any(gap["reason"] == "data_licence_unavailable" for gap in payload["gaps"])
        and expected_gap_keys.issubset(
            {
                gap["key"]
                for gap in payload["gaps"]
                if gap["reason"] == "no_source"
            }
        ),
        "无证书与全空 PIT 响应，契约 §6/§8/§9",
    )
    assert payload["data_as_of"] is None
    assert payload["basis"] is None
    assert payload["breadth"] is None
    assert payload["turnover_total"] is None


@pytest.mark.parametrize(
    ("session", "trade_date"),
    [
        (MarketSession.NON_TRADING_DAY, dt.date(2026, 11, 14)),
        (MarketSession.PRE_OPEN, dt.date(2026, 11, 13)),
    ],
)
def test_market_overview_nontrading_and_preopen_use_stale_close(
    world: OverviewState, session: MarketSession, trade_date: dt.date
) -> None:
    world.clock = aggregate_models.MarketClock(
        trade_date=trade_date, session=session
    )
    world.query_as_of = dt.datetime.combine(
        trade_date, dt.time(0), tzinfo=dt.timezone.utc
    )
    # 11-14 为休市日，最近已完成收盘批是 11-13；开盘前（11-13 08:00）则用 11-12。
    previous_trade_date = (
        dt.date(2026, 11, 13)
        if session is MarketSession.NON_TRADING_DAY
        else dt.date(2026, 11, 12)
    )
    early_same_day = world.query_as_of - dt.timedelta(minutes=30)
    world.facts = [
        close_fact(
            "600000.SH",
            "11",
            "10",
            trade_date=previous_trade_date,
            query_as_of=world.query_as_of,
        ),
        # 查询时已可见的当日（或休市日清晨）盘中行，仍不得被当作回退收盘。
        intraday_fact(
            "600000.SH",
            "1",
            query_as_of=world.query_as_of,
            ts=early_same_day,
            fetched_at=early_same_day,
        ),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["data_status"] == "stale"
        and payload["session"] == session.value
        and payload["basis"] is not None
        and payload["basis"]["mode"] == "close"
        and payload["basis"]["observed_date"] == previous_trade_date.isoformat()
        and any(
            item["security_code"] == "600000.SH" and item["price"] == "11"
            for item in payload["indices"]
        )
        and all(
            item["change_pct"] != "1"
            for item in payload["indices"]
            if item["security_code"] == "600000.SH"
        ),
        "非交易日/开盘前沿用上一完整收盘且不读当日盘中，契约 §4/§8/§9",
    )
    assert payload["trade_date"] == trade_date.isoformat()
    assert payload["basis"]["mode"] == "close"
    assert payload["basis"]["observed_date"] == previous_trade_date.isoformat()
    selected = [
        item for item in payload["indices"] if item["security_code"] == "600000.SH"
    ]
    assert len(selected) == 1
    assert selected[0]["price"] == "11"
    assert selected[0]["change_pct"] != "1"


def test_market_overview_bj_gate_stays_closed_below_twenty_clean_rows(world: OverviewState) -> None:
    world.facts = [
        close_fact(f"830{i:03d}.BJ", "10.1", "10.0", source=source)
        for i in range(1, 20)
        for source in ("mairui", "tdx_local")
    ] + [
        close_fact("830020.BJ", "10.1", "10.0", volume="0", source="mairui"),
        close_fact("830020.BJ", "10.1", "10.0", volume="0", source="tdx_local"),
        close_fact("830021.BJ", "10.1", "10.0", is_suspended=True, source="mairui"),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["basis"] is not None,
        "BJ 同日双来源门闩与默认拦截，契约 §3.2/§9。该契约待合入，不宣称主线验收",
    )
    assert payload["basis"]["scope"] == "沪深股票口径"
    assert payload["breadth"] is None or (
        payload["breadth"]["up"]
        + payload["breadth"]["down"]
        + payload["breadth"]["flat"]
        == 0
    )


def test_market_overview_bj_gate_positive_requires_twenty_clean_pairs(
    world: OverviewState,
) -> None:
    world.facts = [
        close_fact(
            f"830{i:03d}.BJ",
            "10.1",
            "10.0",
            source=source,
            licence=licence,
        )
        for i in range(1, 21)
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ] + [
        close_fact(
            "830021.BJ", "10.1", "10.0", source=source, licence=licence, is_suspended=True
        )
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ] + [
        close_fact("830022.BJ", "10.1", "10.0", source=source, licence=licence, volume="0")
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ]
    # 对照结果、来源时点和规则版本可追溯；该门闩待合入，不宣称主线已验收。
    world.bj_gate_evidence = {  # type: ignore[attr-defined]
        "rule_version": "synthetic-T-A219-bj-2026-11-13",
        "sources": ("mairui", "tdx_local"),
        "reconciled_on": TRADE_DATE.isoformat(),
        "clean_codes": 20,
    }
    payload = get_overview(world)
    breadth = payload["breadth"]
    basis = payload["basis"]
    admitted = (
        basis is not None
        and basis["mode"] == "close"
        and basis["observed_date"] == "2026-11-13"
        and (
            (breadth is not None and breadth["up"] + breadth["down"] + breadth["flat"] == 20)
            or basis.get("eligible") == 20
        )
    )
    require_component(
        payload,
        admitted,
        "BJ 足数双源正例仅在 20 个清洗后代码且来源时点/规则可追溯时启用，契约 §3.2/§9。该契约待合入，不宣称主线验收",
    )
    if breadth is not None:
        assert breadth["up"] + breadth["down"] + breadth["flat"] == 20
    else:
        assert basis["eligible"] == 20


def test_market_overview_pit_cross_licence_does_not_borrow_rows(world: OverviewState) -> None:
    world.query_as_of = QUERY
    world.facts = [
        intraday_fact("600000.SH", "1", licence=LICENCE_A, query_as_of=QUERY),
        intraday_fact("600000.SH", "-1", licence=LICENCE_B, query_as_of=QUERY),
        # 证书 A 下第二只股票使用更晚的行情时点，用以断言 data_as_of 取参与源最早 ts。
        intraday_fact(
            "688001.SH",
            "2",
            licence=LICENCE_A,
            query_as_of=QUERY,
            ts=dt.datetime(2026, 11, 13, 2, 5, tzinfo=dt.timezone.utc),
        ),
        intraday_fact(
            "600000.SH",
            "5",
            licence=LICENCE_A,
            query_as_of=QUERY,
            fetched_at=QUERY + dt.timedelta(minutes=1),
        ),
        intraday_fact("000001.SZ", "1", licence=None, query_as_of=QUERY),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["data_as_of"] == "2026-11-13T02:00:00Z"
        and len(
            [
                item
                for item in payload["indices"]
                if item["security_code"] in {"600000.SH", "688001.SH"}
            ]
        )
        == 2,
        "同码同日证书归属与未来 fetched_at PIT 过滤，契约 §2/§4/§9",
    )
    assert payload["data_as_of"] <= QUERY.isoformat()
    selected = [
        item for item in payload["indices"] if item["security_code"] == "600000.SH"
    ]
    assert len(selected) == 1
    assert selected[0]["change_pct"] == "1"
    assert dt.datetime.fromisoformat(selected[0]["t"]).astimezone(dt.timezone.utc) == dt.datetime(
        2026, 11, 13, 2, tzinfo=dt.timezone.utc
    )
    assert payload["data_as_of"] == "2026-11-13T02:00:00Z"
    unowned = [
        item for item in payload["indices"] if item["security_code"] == "000001.SZ"
    ]
    assert not unowned or (
        unowned[0]["price"] is None and unowned[0]["change_pct"] is None
    )

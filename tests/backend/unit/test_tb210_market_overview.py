# ruff: noqa: S101, ANN201, PT018
from __future__ import annotations

import datetime as dt
from contextlib import nullcontext
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.aggregates import models as m
from app.aggregates.calendar import market_clock
from app.aggregates.market_overview import build_market_overview
from app.api.v1 import aggregates as aggregate_routes
from app.auth import deps
from app.common.errors import AppError, ErrorCode, install_exception_handlers
from app.schemas.enums import DataStatus, GapReason, MarketSession

pytestmark = pytest.mark.unit
DAY = dt.date(2031, 2, 3)
BEIJING = dt.timezone(dt.timedelta(hours=8))
BATCH_ID = UUID("00000000-0000-0000-0000-000000000210")
OWNER = UUID("00000000-0000-0000-0000-000000000211")
LICENCE_A = UUID("00000000-0000-0000-0000-000000000212")
LICENCE_B = UUID("00000000-0000-0000-0000-000000000213")


class Result:
    def __init__(self, rows: list[object] | None = None, scalar: object = None) -> None:
        self.rows, self.scalar = rows or [], scalar

    def all(self) -> list[object]:
        return self.rows

    def first(self) -> object | None:
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self) -> object:
        return self.scalar


def row(**values: object) -> SimpleNamespace:
    return SimpleNamespace(_mapping=values)


def quote(
    code: str,
    licence: UUID | None = LICENCE_A,
    *,
    pct: str | None = "1",
    volume: str | None = "100",
    amount: str | None = "100.00",
    ts: dt.datetime | None = None,
    fetched_at: dt.datetime | None = None,
    suspended: bool | None = False,
    limit_up: bool | None = False,
    limit_down: bool | None = False,
    batch_id: UUID | None = BATCH_ID,
    source: str | None = "mairui",
) -> SimpleNamespace:
    stamp = ts or dt.datetime(2031, 2, 3, 10, tzinfo=BEIJING)
    return row(
        code=code,
        ts=stamp,
        price="10.00",
        pct_change=pct,
        payload=None,
        source=source,
        source_licence_id=licence,
        row_id=uuid4(),
        revision=0,
        content_fingerprint="synthetic",
        volume=volume,
        amount=amount,
        is_suspended=suspended,
        limit_up=limit_up,
        limit_down=limit_down,
        batch_id=batch_id,
        fetched_at=fetched_at or stamp,
    )


def daily(
    code: str,
    *,
    trade_date: dt.date = DAY,
    fetched_at: dt.datetime | None = None,
    close: str = "10",
    pre_close: str = "9",
    volume: str | None = "100",
    amount: str | None = "100.00",
    suspended: bool = False,
    licence: UUID = LICENCE_A,
    source: str = "mairui",
) -> SimpleNamespace:
    return row(
        code=code,
        trade_date=trade_date,
        adj_type="none",
        close=close,
        pre_close=pre_close,
        volume=volume,
        amount=amount,
        is_suspended=suspended,
        source=source,
        source_licence_id=licence,
        fetched_at=fetched_at or dt.datetime.combine(trade_date, dt.time(17, 15), BEIJING),
    )


def security(
    code: str,
    exchange: str,
    *,
    kind: str = "stock",
    status: str = "listed",
    risk_flag: str | None = None,
) -> SimpleNamespace:
    return row(
        code=code,
        exchange=exchange,
        type=kind,
        listing_status=status,
        list_date=None,
        delist_date=None,
        name=code,
        risk_flag=risk_flag,
    )


class Connection:
    def __init__(
        self,
        licence: UUID | None = LICENCE_A,
        *,
        stocks: list[object] | None = None,
        indices: list[object] | None = None,
        quotes: list[object] | None = None,
        daily_rows: list[object] | None = None,
        history: list[object] | None = None,
    ) -> None:
        self.licence = licence
        self.stocks = stocks or [
            security("600000.SH", "SH"),
            security("000001.SZ", "SZ"),
        ]
        self.indices = indices or [row(code="000300.SH", name="示例指数")]
        self.quotes, self.daily_rows, self.history = (
            quotes or [],
            daily_rows or [],
            history or [],
        )
        self.as_of: dt.datetime | None = None

    def execute(self, statement: object) -> Result:
        sql = str(statement)
        if "user_data_licence_status" in sql:
            return Result(scalar=self.licence)
        if "security_listing_status_history" in sql:
            return Result(self.history)
        if "quotes_snapshot" in sql:
            rows = [
                item
                for item in self.quotes
                if self.as_of is None
                or (
                    item._mapping["ts"] <= self.as_of
                    and item._mapping["fetched_at"] <= self.as_of
                    and item._mapping["source"] == "mairui"
                    and item._mapping["source_licence_id"] == self.licence
                )
            ]
            return Result(rows)
        if "daily_bars" in sql:
            params = statement.compile().params  # type: ignore[attr-defined]
            trade_day = next(
                (
                    value
                    for value in params.values()
                    if isinstance(value, dt.date) and not isinstance(value, dt.datetime)
                ),
                None,
            )
            exact_day = "trade_date =" in sql
            fetched_after = next(
                (
                    value
                    for value in params.values()
                    if isinstance(value, dt.datetime)
                    and value.astimezone(BEIJING).time() == dt.time(17, 10)
                ),
                None,
            )
            return Result(
                [
                    item
                    for item in self.daily_rows
                    if (
                        self.as_of is None
                        or item._mapping["fetched_at"] <= self.as_of
                    )
                    and (
                        trade_day is None
                        or (
                            exact_day
                            and item._mapping["trade_date"] == trade_day
                        )
                        or (
                            not exact_day
                            and item._mapping["trade_date"] < trade_day
                        )
                    )
                    and (
                        fetched_after is None
                        or item._mapping["fetched_at"] >= fetched_after
                    )
                ]
            )
        if "securities" in sql:
            params = statement.compile().params  # type: ignore[attr-defined]
            if "index" in params.values():
                return Result(self.indices)
            return Result(
                [
                    item
                    for item in self.stocks
                    if item._mapping.get("type", "stock") == "stock"
                    and item._mapping["exchange"] in {"SH", "SZ"}
                    and item._mapping["listing_status"] == "listed"
                ]
            )
        raise AssertionError(sql)


def clock(session: MarketSession = MarketSession.MORNING, day: dt.date = DAY) -> m.MarketClock:
    return m.MarketClock(trade_date=day, session=session)


def overview(conn: Connection, at: dt.datetime, session: MarketSession = MarketSession.MORNING):
    conn.as_of = at
    return build_market_overview(conn, OWNER, clock(session), at)


def gap_reasons(result: object) -> set[GapReason]:
    return {gap.reason for gap in result.gaps}  # type: ignore[attr-defined]


def test_complete_intraday_fixture_uses_owner_same_batch_and_decimal_ratios() -> None:
    conn = Connection(
        stocks=[
            security("600000.SH", "SH"),
            security("000001.SZ", "SZ"),
            security("688001.SH", "SH"),
        ],
        quotes=[
            quote("600000.SH", pct="2"),
            quote("000001.SZ", pct="-1"),
            quote("688001.SH", pct="0"),
        ],
    )
    result = overview(conn, dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING))
    assert result.basis is not None and (
        result.basis.mode,
        result.basis.eligible,
        result.basis.observed,
    ) == ("intraday", 3, 3)
    assert result.basis.observed_date == DAY
    assert result.breadth is not None
    assert (result.breadth.up, result.breadth.down, result.breadth.flat) == (1, 1, 1)
    assert (
        result.breadth.up_ratio,
        result.breadth.down_ratio,
        result.breadth.flat_ratio,
    ) == (
        "0.3333",
        "0.3333",
        "0.3333",
    )
    assert result.turnover_total == "300.00"


def test_stock_facts_are_kept_without_index_cards() -> None:
    conn = Connection(
        quotes=[
            quote("600000.SH", pct="2", amount="120.00"),
            quote("000001.SZ", pct="-1", amount="80.00"),
        ]
    )
    conn.indices = []

    result = overview(conn, dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING))

    assert result.indices == []
    assert result.basis is not None and result.basis.observed == 2
    assert result.breadth is not None and (result.breadth.up, result.breadth.down) == (1, 1)
    assert result.data_status is DataStatus.PARTIAL
    assert result.turnover_total == "200.00"
    assert any(
        gap.key == "market.indices"
        and gap.reason is GapReason.NO_SOURCE
        and gap.message == "没有配置可展示的指数卡片。"
        for gap in result.gaps
    )


def test_unbatched_intraday_rows_are_excluded_from_aggregate() -> None:
    conn = Connection(
        quotes=[
            quote("600000.SH", batch_id=None),
            quote("000001.SZ", batch_id=None),
        ]
    )

    result = overview(conn, dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING))

    assert result.data_status is DataStatus.UNAVAILABLE
    assert result.breadth is None
    assert result.turnover_total is None
    assert result.indices[0].price is None


def test_intraday_missing_volume_amount_is_partial_and_not_zero() -> None:
    conn = Connection(
        quotes=[
            quote("600000.SH", volume=None, amount=None),
            quote("000001.SZ", volume=None, amount=None),
        ]
    )
    result = overview(conn, dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING))
    assert result.data_status is DataStatus.PARTIAL
    assert (
        result.breadth is not None and result.breadth.up is None and result.breadth.up_ratio is None
    )
    assert result.turnover_total is None and GapReason.NO_SOURCE in gap_reasons(result)


@pytest.mark.parametrize(
    ("at", "mode"),
    [
        (dt.datetime(2031, 2, 3, 14, 59, 59, tzinfo=BEIJING), "intraday"),
        (dt.datetime(2031, 2, 3, 15, 0, 1, tzinfo=BEIJING), "intraday"),
        (dt.datetime(2031, 2, 3, 17, 9, 59, tzinfo=BEIJING), "intraday"),
        (dt.datetime(2031, 2, 3, 17, 10, 1, tzinfo=BEIJING), "close"),
    ],
)
def test_four_market_close_boundaries(at: dt.datetime, mode: str) -> None:
    final_at = dt.datetime(2031, 2, 3, 17, 10, tzinfo=BEIJING)
    result = overview(
        Connection(
            quotes=[quote("600000.SH"), quote("000001.SZ"), quote("000300.SH")],
            daily_rows=[
                daily("600000.SH", fetched_at=final_at),
                daily("000001.SZ", fetched_at=final_at),
                daily("000300.SH", fetched_at=final_at),
            ],
        ),
        at,
    )
    assert result.basis is not None and result.basis.mode == mode
    assert result.indices[0].t == dt.datetime(
        2031, 2, 3, 15 if mode == "close" else 10, tzinfo=BEIJING
    )


def test_close_fixture_uses_final_mairui_bar_and_amount_in_yuan() -> None:
    result = overview(
        Connection(
            daily_rows=[
                daily("600000.SH", amount="12.50"),
                daily("000001.SZ", amount="7.50"),
                daily("000300.SH"),
            ]
        ),
        dt.datetime(2031, 2, 3, 17, 15, tzinfo=BEIJING),
    )
    assert result.basis is not None and result.basis.mode == "close"
    assert result.turnover_total == "20.00"
    assert result.indices[0].change_pct == "11.1111"


def test_intraday_index_change_pct_is_quantized() -> None:
    result = overview(
        Connection(quotes=[quote("000300.SH", pct="11.11111111111111111111111111")]),
        dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING),
    )
    assert result.indices[0].change_pct == "11.1111"


def test_suspended_zero_volume_delisted_excluded_and_st_keeps_width() -> None:
    stocks = [
        security("600000.SH", "SH"),
        security("000001.SZ", "SZ"),
        security("688001.SH", "SH", risk_flag="st"),
        security("300001.SZ", "SZ", status="delisted"),
    ]
    quotes = [
        quote("600000.SH", suspended=True),
        quote("000001.SZ", volume="0"),
        quote("688001.SH", pct="2", limit_up=None, limit_down=None),
    ]
    result = overview(
        Connection(stocks=stocks, quotes=quotes),
        dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING),
    )
    assert result.basis is not None and result.basis.eligible == 3 and result.basis.suspended == 1
    assert result.breadth is not None and (
        result.breadth.up,
        result.breadth.down,
        result.breadth.flat,
    ) == (1, 0, 0)
    assert result.breadth.limit_up is None and result.breadth.limit_down is None
    assert any(g.key == "market.breadth.limit_counts" for g in result.gaps)


def test_etf_index_and_bj_are_out_of_scope() -> None:
    stocks = [
        security("510001.SH", "SH", kind="etf"),
        security("830001.BJ", "BJ"),
        security("600000.SH", "SH"),
    ]
    result = overview(
        Connection(stocks=stocks, quotes=[quote("600000.SH")]),
        dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING),
    )
    assert result.basis is not None and result.basis.eligible == 1
    assert result.breadth is not None and result.breadth.up == 1
    assert [item.security_code for item in result.indices] == ["000300.SH"]


def test_missing_limit_certificate_does_not_infer_ten_percent() -> None:
    result = overview(
        Connection(
            quotes=[
                quote("600000.SH", limit_up=None, limit_down=None),
                quote("000001.SZ"),
            ]
        ),
        dt.datetime(2031, 2, 3, 10, 0, 10, tzinfo=BEIJING),
    )
    assert (
        result.breadth is not None
        and result.breadth.limit_up is None
        and result.breadth.limit_down is None
    )
    assert any(
        g.key == "market.breadth.limit_counts" and g.reason is GapReason.NO_SOURCE
        for g in result.gaps
    )


@pytest.mark.parametrize("catalog_status", ["declared", "verified_live"])
def test_regime_catalog_states_remain_null_without_approved_parameters(
    catalog_status: str,
) -> None:
    result = overview(
        Connection(quotes=[quote("600000.SH"), quote("000001.SZ")]),
        dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING),
    )
    assert catalog_status in {"declared", "verified_live"}
    assert result.regime is None and result.regime_position_range is None
    assert any(g.key == "market.regime" and g.reason is GapReason.NO_SOURCE for g in result.gaps)


def test_no_licence_and_future_rows_are_unavailable_with_public_cards() -> None:
    no_licence = overview(Connection(None), dt.datetime(2031, 2, 3, 10, tzinfo=BEIJING))
    assert no_licence.data_status is DataStatus.UNAVAILABLE and no_licence.indices[0].price is None
    assert GapReason.DATA_LICENCE_UNAVAILABLE in gap_reasons(no_licence)
    future = overview(
        Connection(
            quotes=[quote("600000.SH", fetched_at=dt.datetime(2031, 2, 3, 11, tzinfo=BEIJING))]
        ),
        dt.datetime(2031, 2, 3, 10, tzinfo=BEIJING),
    )
    assert future.data_status is DataStatus.UNAVAILABLE and future.breadth is None


@pytest.mark.parametrize("session", [MarketSession.PRE_OPEN, MarketSession.NON_TRADING_DAY])
def test_pre_open_and_non_trading_use_previous_final_bar_as_stale(
    session: MarketSession,
) -> None:
    previous = DAY - dt.timedelta(days=1)
    result = build_market_overview(
        Connection(
            quotes=[quote("600000.SH", ts=dt.datetime.combine(DAY, dt.time(8), BEIJING))],
            daily_rows=[
                daily("600000.SH", trade_date=previous),
                daily("000001.SZ", trade_date=previous),
                daily("000300.SH", trade_date=previous),
            ],
        ),
        OWNER,
        clock(session, previous if session is MarketSession.NON_TRADING_DAY else DAY),
        dt.datetime.combine(DAY, dt.time(8 if session is MarketSession.PRE_OPEN else 12), BEIJING),
    )
    assert (
        result.data_status is DataStatus.STALE
        and result.basis is not None
        and result.basis.mode == "close"
    )
    assert result.basis.observed_date == previous


def test_after_final_deadline_uses_previous_final_bar_as_stale() -> None:
    previous = DAY - dt.timedelta(days=1)
    result = overview(
        Connection(
            daily_rows=[
                daily("600000.SH", trade_date=previous),
                daily("000001.SZ", trade_date=previous),
                daily("000300.SH", trade_date=previous),
            ]
        ),
        dt.datetime(2031, 2, 3, 17, 30, tzinfo=BEIJING),
    )
    assert result.basis is not None
    assert result.basis.mode == "close"
    assert result.basis.observed_date == previous
    assert result.data_status is DataStatus.STALE


def test_previous_close_fallback_does_not_mix_trade_dates() -> None:
    previous = DAY - dt.timedelta(days=1)
    older = DAY - dt.timedelta(days=2)
    result = overview(
        Connection(
            daily_rows=[
                daily("600000.SH", trade_date=previous, amount="100.00"),
                daily("000001.SZ", trade_date=older, amount="999.00"),
                daily("000300.SH", trade_date=previous),
            ]
        ),
        dt.datetime(2031, 2, 3, 8, tzinfo=BEIJING),
        MarketSession.PRE_OPEN,
    )
    assert result.basis is not None
    assert (result.basis.observed_date, result.basis.observed, result.basis.missing) == (
        previous,
        1,
        1,
    )
    assert result.breadth is not None and (result.breadth.up, result.breadth.down) == (1, 0)
    assert result.turnover_total is None
    assert result.data_status is DataStatus.PARTIAL


def test_bj_gate_stays_closed_below_twenty_confirmed_codes() -> None:
    stocks = [security(f"830{i:03d}.BJ", "BJ") for i in range(1, 21)]
    result = overview(
        Connection(stocks=stocks, quotes=[quote(f"830{i:03d}.BJ") for i in range(1, 21)]),
        dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING),
    )
    assert result.basis is None and result.breadth is None


def test_bj_gate_needs_twenty_clean_codes_and_both_sources() -> None:
    class BJConnection(Connection):
        def execute(self, statement: object) -> Result:
            sql = str(statement)
            if "securities" in sql:
                params = statement.compile().params  # type: ignore[attr-defined]
                if "index" not in params.values():
                    return Result(
                        [
                            item
                            for item in self.stocks
                            if item._mapping.get("type", "stock") == "stock"
                            and item._mapping["exchange"] in {"SH", "SZ", "BJ"}
                            and item._mapping["listing_status"] == "listed"
                        ]
                    )
            return super().execute(statement)

    bj_codes = [f"830{i:03d}.BJ" for i in range(1, 21)]
    stocks = [security(code, "BJ") for code in bj_codes]
    daily_rows = [
        daily(code, source=source, volume="100")
        for code in bj_codes
        for source in ("mairui", "tdx_local")
    ]
    result = overview(
        BJConnection(stocks=stocks, daily_rows=daily_rows),
        dt.datetime(2031, 2, 3, 17, 30, tzinfo=BEIJING),
    )
    assert result.breadth is None
    assert result.basis is not None and result.basis.eligible == 0
    assert any(
        gap.key == "market.breadth"
        and gap.reason is GapReason.NO_SOURCE
        and gap.message == "BJ 门闩待 T-A172 §10 可信证据"
        for gap in result.gaps
    )


def test_close_bj_gate_does_not_make_sh_sz_incomplete() -> None:
    class BJConnection(Connection):
        def execute(self, statement: object) -> Result:
            sql = str(statement)
            if "securities" in sql:
                params = statement.compile().params  # type: ignore[attr-defined]
                if "index" not in params.values():
                    return Result(
                        [
                            item
                            for item in self.stocks
                            if item._mapping.get("type", "stock") == "stock"
                            and item._mapping["exchange"] in {"SH", "SZ", "BJ"}
                            and item._mapping["listing_status"] == "listed"
                        ]
                    )
            return super().execute(statement)

    stocks = [
        security("600000.SH", "SH"),
        security("000001.SZ", "SZ"),
        security("830001.BJ", "BJ"),
        security("830002.BJ", "BJ"),
    ]
    daily_rows = [
        daily("600000.SH", amount="120.00"),
        daily("000001.SZ", amount="80.00"),
        daily("000300.SH"),
    ]
    for code in ("830001.BJ", "830002.BJ"):
        daily_rows.extend(
            [
                daily(code, source="mairui"),
                daily(code, source="tdx_local"),
            ]
        )

    result = overview(
        BJConnection(stocks=stocks, daily_rows=daily_rows),
        dt.datetime(2031, 2, 3, 17, 30, tzinfo=BEIJING),
    )

    assert result.basis is not None
    assert (result.basis.eligible, result.basis.observed, result.basis.missing) == (2, 2, 0)
    assert result.breadth is not None and (result.breadth.up, result.breadth.down) == (2, 0)
    assert result.turnover_total == "200.00"


def test_previous_close_bj_gate_uses_observed_trade_date() -> None:
    class BJConnection(Connection):
        def execute(self, statement: object) -> Result:
            sql = str(statement)
            if "securities" in sql:
                params = statement.compile().params  # type: ignore[attr-defined]
                if "index" not in params.values():
                    return Result(
                        [
                            item
                            for item in self.stocks
                            if item._mapping.get("type", "stock") == "stock"
                            and item._mapping["exchange"] in {"SH", "SZ", "BJ"}
                            and item._mapping["listing_status"] == "listed"
                        ]
                    )
            return super().execute(statement)

    previous = DAY - dt.timedelta(days=1)
    bj_codes = [f"830{i:03d}.BJ" for i in range(1, 21)]
    stocks = [security("600000.SH", "SH"), security("000001.SZ", "SZ")]
    stocks.extend(security(code, "BJ") for code in bj_codes)
    daily_rows = [
        daily("600000.SH", trade_date=previous),
        daily("000001.SZ", trade_date=previous),
        daily("000300.SH", trade_date=previous),
    ]
    for code in bj_codes:
        daily_rows.extend(
            [
                daily(code, trade_date=previous, source="mairui"),
                daily(code, trade_date=previous, source="tdx_local"),
            ]
        )

    result = overview(
        BJConnection(stocks=stocks, daily_rows=daily_rows),
        dt.datetime(2031, 2, 3, 17, 30, tzinfo=BEIJING),
    )

    assert result.basis is not None
    assert result.basis.observed_date == previous
    assert (result.basis.eligible, result.basis.observed, result.basis.missing) == (2, 2, 0)
    assert result.turnover_total is not None


def test_pit_reads_only_current_licence_and_excludes_future_and_unbound_rows() -> None:
    same_ts = dt.datetime(2031, 2, 3, 10, tzinfo=BEIJING)
    quotes = [
        quote("000300.SH", LICENCE_A, ts=same_ts, fetched_at=same_ts),
        quote("600000.SH", LICENCE_A, ts=same_ts, fetched_at=same_ts),
        quote("600000.SH", LICENCE_B, ts=same_ts, fetched_at=same_ts, amount="999"),
        quote("600000.SH", None, ts=same_ts, fetched_at=same_ts, source=None, amount="888"),
        quote(
            "600000.SH",
            LICENCE_A,
            ts=same_ts,
            fetched_at=same_ts.replace(hour=11),
            amount="777",
        ),
        quote("000001.SZ", LICENCE_A, ts=same_ts, fetched_at=same_ts),
    ]
    result = overview(Connection(quotes=quotes), dt.datetime(2031, 2, 3, 10, 1, tzinfo=BEIJING))
    assert (
        result.indices[0].amount == "100.00"
        and result.basis is not None
        and result.basis.observed == 2
    )


class ClockConnection:
    def __init__(self, covered: bool = True) -> None:
        self.covered = covered

    def execute(self, statement: object) -> object:
        sql = str(statement)
        if "min(" in sql:
            return SimpleNamespace(one=lambda: (DAY, DAY) if self.covered else (None, None))
        if "is_open" in sql and "max(" not in sql:
            return SimpleNamespace(first=lambda: SimpleNamespace(is_open=True))
        if "max(" in sql:
            return SimpleNamespace(scalar_one=lambda: DAY)
        raise AssertionError(sql)


def test_contract_errors_and_http_empty_method_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(AppError) as covered:
        market_clock(
            ClockConnection(False),
            dt.datetime.combine(DAY, dt.time(10), BEIJING),
            SimpleNamespace(segment_for=lambda _day: None),
        )
    assert covered.value.code is ErrorCode.CALENDAR_NOT_COVERED
    with pytest.raises(AppError) as rules:
        market_clock(
            ClockConnection(),
            dt.datetime.combine(DAY, dt.time(10), BEIJING),
            SimpleNamespace(segment_for=lambda _day: None),
        )
    assert rules.value.code is ErrorCode.MAINTENANCE

    app = FastAPI()
    install_exception_handlers(app)
    from app.api.v1.aggregates import router

    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.current_auth] = lambda: (_ for _ in ()).throw(
        AppError(ErrorCode.AUTH_REQUIRED)
    )
    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 401 and response.json()["error"]["code"] == "AUTH_REQUIRED"
    app.dependency_overrides[deps.current_auth] = lambda: (_ for _ in ()).throw(
        AppError(ErrorCode.ACCOUNT_NOT_APPROVED)
    )
    response = client.get("/api/v1/market/overview")
    assert (
        response.status_code == 403 and response.json()["error"]["code"] == "ACCOUNT_NOT_APPROVED"
    )
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)
    app.dependency_overrides[deps.get_engine] = lambda: SimpleNamespace(
        connect=lambda: nullcontext(Connection())
    )
    app.dependency_overrides[deps.get_settings] = lambda: SimpleNamespace(
        business=SimpleNamespace(market_rules=SimpleNamespace(segment_for=lambda _day: None))
    )
    monkeypatch.setattr(
        aggregate_routes,
        "market_clock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AppError(ErrorCode.CALENDAR_NOT_COVERED)
        ),
    )
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 503 and response.json()["error"]["code"] == "CALENDAR_NOT_COVERED"
    monkeypatch.setattr(
        aggregate_routes,
        "market_clock",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AppError(ErrorCode.MAINTENANCE)),
    )
    response = client.get("/api/v1/market/overview")
    assert response.status_code == 503 and response.json()["error"]["code"] == "MAINTENANCE"
    assert client.post("/api/v1/market/overview").status_code == 405
    assert client.get("/api/v1/market/missing").status_code == 404

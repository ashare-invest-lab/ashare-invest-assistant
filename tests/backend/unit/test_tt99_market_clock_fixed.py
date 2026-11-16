"""Fixed instants and fictional calendar rows; SQLite stays entirely in memory."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from app.aggregates.calendar import BEIJING, market_clock
from app.common.errors import AppError, ErrorCode
from app.config_files import MarketRulesConfig
from app.db.tables.market import trading_calendar
from app.schemas.enums import MarketSession
from sqlalchemy import Connection, create_engine, insert

pytestmark = pytest.mark.unit
DAY = dt.date(2030, 6, 11)
PREVIOUS = DAY - dt.timedelta(days=1)
FOLLOWING = DAY + dt.timedelta(days=1)


@pytest.fixture
def rules() -> MarketRulesConfig:
    path = Path(__file__).resolve().parents[3] / "config/market_rules.yaml"
    return MarketRulesConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


@pytest.fixture
def conn() -> Iterator[Connection]:
    engine = create_engine("sqlite://", execution_options={"schema_translate_map": {"market": None}})
    try:
        with engine.connect() as connection:
            trading_calendar.create(connection)
            yield connection
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("time", "session"),
    [
        ("00:30", MarketSession.PRE_OPEN),
        ("09:00", MarketSession.PRE_OPEN),
        ("09:15", MarketSession.CALL_AUCTION),
        ("09:20", MarketSession.CALL_AUCTION),
        ("09:25", MarketSession.PRE_OPEN),
        ("09:29:59", MarketSession.PRE_OPEN),
        ("09:30", MarketSession.MORNING),
        ("10:00", MarketSession.MORNING),
        ("11:29:59", MarketSession.MORNING),
        ("11:30", MarketSession.LUNCH_BREAK),
        ("12:00", MarketSession.LUNCH_BREAK),
        ("13:00", MarketSession.AFTERNOON),
        ("14:00", MarketSession.AFTERNOON),
        ("14:56:59", MarketSession.AFTERNOON),
        ("14:57", MarketSession.CLOSING_AUCTION),
        ("14:59:59", MarketSession.CLOSING_AUCTION),
        ("15:00", MarketSession.CLOSED),
        ("16:00", MarketSession.CLOSED),
    ],
)
def test_open_day_sessions(
    conn: Connection, rules: MarketRulesConfig, time: str, session: MarketSession
) -> None:
    conn.execute(insert(trading_calendar), [{"date": DAY, "is_open": True}])
    local = dt.datetime.fromisoformat(f"{DAY}T{time}").replace(tzinfo=BEIJING)
    clock = market_clock(conn, local.astimezone(dt.UTC), rules)
    assert clock.trade_date == DAY
    assert clock.session == session


def test_non_trading_day_uses_last_open_day(conn: Connection, rules: MarketRulesConfig) -> None:
    conn.execute(
        insert(trading_calendar),
        [
            {"date": PREVIOUS, "is_open": True},
            {"date": DAY, "is_open": False},
            {"date": FOLLOWING, "is_open": False},
        ],
    )
    clock = market_clock(conn, dt.datetime.combine(FOLLOWING, dt.time(10), BEIJING), rules)
    assert clock.trade_date == PREVIOUS
    assert clock.session == MarketSession.NON_TRADING_DAY


@pytest.mark.parametrize(
    ("rows", "day"),
    [
        ([], DAY),
        ([(DAY, True)], PREVIOUS),
        ([(DAY, True)], FOLLOWING),
        ([(PREVIOUS, True), (FOLLOWING, True)], DAY),
        ([(DAY, False), (FOLLOWING, True)], DAY),
    ],
    ids=["empty", "before-coverage", "after-coverage", "hole", "no-previous-open"],
)
def test_calendar_not_covered(
    conn: Connection, rules: MarketRulesConfig, rows: list[tuple[dt.date, bool]], day: dt.date
) -> None:
    if rows:
        conn.execute(
            insert(trading_calendar), [{"date": date, "is_open": is_open} for date, is_open in rows]
        )
    with pytest.raises(AppError) as exc:
        market_clock(conn, dt.datetime.combine(day, dt.time(10), BEIJING), rules)
    assert exc.value.code == ErrorCode.CALENDAR_NOT_COVERED
    assert exc.value.details == {
        "date": day.isoformat(),
        "coverage_start": min(date for date, _ in rows).isoformat() if rows else None,
        "coverage_end": max(date for date, _ in rows).isoformat() if rows else None,
    }


def test_missing_rule_segment(conn: Connection, rules: MarketRulesConfig) -> None:
    day = rules.modeled_from - dt.timedelta(days=1)
    conn.execute(insert(trading_calendar), [{"date": day, "is_open": True}])
    with pytest.raises(AppError) as exc:
        market_clock(conn, dt.datetime.combine(day, dt.time(10), BEIJING), rules)
    assert exc.value.code == ErrorCode.MAINTENANCE
    assert exc.value.details == {"issue": "market_rule_segment_missing"}


def test_naive_datetime_rejected(conn: Connection, rules: MarketRulesConfig) -> None:
    with pytest.raises(ValueError, match="market clock requires an aware instant"):
        market_clock(conn, dt.datetime(2030, 6, 11, 10), rules)


def test_api_clock_freeze_is_local(
    conn: Connection, rules: MarketRulesConfig, fixed_aggregate_clock: dt.datetime
) -> None:
    from app.api.v1 import aggregates

    assert aggregates.dt is not dt
    assert aggregates.dt.datetime is not dt.datetime
    instant = aggregates.dt.datetime.now(dt.UTC)
    assert instant == fixed_aggregate_clock
    assert instant.tzinfo is dt.UTC
    day = instant.astimezone(BEIJING).date()
    conn.execute(insert(trading_calendar), [{"date": day, "is_open": True}])
    clock = market_clock(conn, instant, rules)
    assert clock.trade_date == day
    assert clock.session == MarketSession.MORNING

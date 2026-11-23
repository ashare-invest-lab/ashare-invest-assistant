"""T-T99b：隔离 PG、合成行情与固定北京时间；rc1.load 不访问外网。"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.config import Settings, load_yaml_dir
from app.db.tables.market import (
    daily_bars,
    quotes_snapshot,
    realtime_quotes,
    trading_calendar,
)
from app.risk import rc1
from app.risk.rc1 import SH, load
from sqlalchemy import Connection, create_engine, insert, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url

STDLIB_DATETIME = dt.datetime
DAY = dt.date(2030, 6, 11)
AT = dt.datetime(2030, 6, 11, 14, 59, tzinfo=SH)
CLOSING = AT.replace(hour=15, minute=0)
CODE = "TT99B.SYNTHETIC"
OWNER = uuid.UUID(int=99)
PRICE = Decimal("10.25")
QUOTE_AT = AT - dt.timedelta(seconds=10)
FETCHED_AT = AT - dt.timedelta(seconds=5)
LICENCE = uuid.UUID("00000000-0000-0000-0000-000000000099")


@pytest.fixture
def settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    # 只接受显式测试配置，禁用环境、dotenv 和证书来源。
    monkeypatch.setattr(
        Settings,
        "settings_customise_sources",
        classmethod(lambda cls, settings_cls, init_settings, **kwargs: (init_settings,)),
    )
    config_dir = Path(__file__).resolve().parents[3] / "config"
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://tt99b_test:tt99b_test@invalid/tt99b_test",
        redis_url="redis://invalid/0",
        config_dir=config_dir,
        business=load_yaml_dir(config_dir),
    )


@pytest.fixture
def rc1_conn(pg_url: str) -> Iterator[Connection]:
    engine = create_engine(make_url(pg_url).set(drivername="postgresql+psycopg"))
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS market"))
                for table in (trading_calendar, realtime_quotes, quotes_snapshot, daily_bars):
                    table.create(conn, checkfirst=True)
                conn.execute(
                    pg_insert(trading_calendar)
                    .values(date=DAY, is_open=True)
                    .on_conflict_do_update(
                        index_elements=[trading_calendar.c.date],
                        set_={"is_open": True},
                    )
                )
                conn.execute(
                    insert(quotes_snapshot).values(
                        code=CODE,
                        ts=QUOTE_AT,
                        price=PRICE,
                        source="mairui",
                        source_licence_id=LICENCE,
                        fetched_at=FETCHED_AT,
                    )
                )
                conn.execute(
                    insert(daily_bars).values(
                        code=CODE,
                        trade_date=DAY,
                        adj_type="none",
                        open=Decimal(10),
                        low=Decimal(9),
                        high=Decimal(12),
                        close=Decimal(11),
                        fetched_at=CLOSING,
                    )
                )
                yield conn
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_intraday_uses_fixed_at_quote(
    settings: Settings, rc1_conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.marketdata.daily_snapshot.active_licence_id",
        lambda conn, owner, at: LICENCE,
    )
    facts = load(
        rc1_conn, OWNER, None, CODE, settings, at=AT, stops_at=AT, position_known=False
    )
    assert facts.mode == "intraday"
    assert facts.endpoint == "market.quotes_snapshot:raw"
    assert facts.last == PRICE
    assert facts.observed_at == QUOTE_AT
    assert facts.fetched_at == FETCHED_AT


@pytest.mark.parametrize("hour", [15, 16], ids=["at-close", "after-close"])
def test_close_uses_fixed_at_daily_bar(
    settings: Settings, rc1_conn: Connection, hour: int
) -> None:
    at = CLOSING.replace(hour=hour)
    facts = load(
        rc1_conn, OWNER, None, CODE, settings, at=at, stops_at=at, position_known=False
    )
    assert facts.mode == "close"
    assert facts.endpoint == "market.daily_bars:adj_type=none"
    assert facts.low == Decimal(9)
    assert facts.high == Decimal(12)
    assert facts.observed_at == CLOSING
    assert facts.fetched_at == CLOSING
    assert facts.last is None


@pytest.fixture
def rc1_without_wall_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    def unexpected_now(*args: object, **kwargs: object) -> dt.datetime:
        raise AssertionError("rc1.load must not read the wall clock")

    # 只替换 rc1 自己的绑定，保留标准库 datetime 供延迟导入的模型使用。
    monkeypatch.setattr(
        rc1,
        "dt",
        SimpleNamespace(
            datetime=SimpleNamespace(now=unexpected_now, combine=dt.datetime.combine),
            date=dt.date,
            time=dt.time,
            timedelta=dt.timedelta,
            timezone=dt.timezone,
            UTC=dt.UTC,
        ),
    )


def test_fixed_at_is_independent_of_wall_clock(
    settings: Settings,
    rc1_conn: Connection,
    rc1_without_wall_clock: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.marketdata.daily_snapshot.active_licence_id",
        lambda conn, owner, at: LICENCE,
    )
    facts = load(
        rc1_conn, OWNER, None, CODE, settings, at=AT, stops_at=AT, position_known=False
    )
    assert facts.mode == "intraday"
    assert facts.endpoint == "market.quotes_snapshot:raw"
    assert facts.last == PRICE
    assert facts.observed_at == QUOTE_AT
    assert facts.fetched_at == FETCHED_AT


def test_intraday_ignores_legacy_and_foreign_quotes(
    settings: Settings, rc1_conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.marketdata.daily_snapshot.active_licence_id",
        lambda conn, owner, at: LICENCE,
    )
    rc1_conn.execute(
        insert(realtime_quotes).values(
            code=CODE,
            ts=AT - dt.timedelta(seconds=2),
            price=Decimal(99),
            source="ssjy_more",
            fetched_at=AT,
        )
    )
    rc1_conn.execute(
        insert(quotes_snapshot).values(
            code=CODE,
            ts=AT - dt.timedelta(seconds=1),
            price=Decimal(88),
            source="mairui",
            source_licence_id=uuid.UUID("00000000-0000-0000-0000-000000000098"),
            fetched_at=AT,
        )
    )
    facts = load(
        rc1_conn, OWNER, None, CODE, settings, at=AT, stops_at=AT, position_known=False
    )
    assert facts.last == PRICE
    assert facts.observed_at == QUOTE_AT


def test_fixed_at_patch_is_independent_of_stdlib_datetime(
    rc1_without_wall_clock: None,
) -> None:
    from pydantic import BaseModel

    assert rc1.dt is not dt
    assert dt.datetime is STDLIB_DATETIME
    with pytest.raises(AssertionError, match="must not read the wall clock"):
        rc1.dt.datetime.now(SH)

    class TimestampModel(BaseModel):
        timestamp: dt.datetime

    assert TimestampModel(timestamp=AT).timestamp == AT
    assert dt.datetime is STDLIB_DATETIME

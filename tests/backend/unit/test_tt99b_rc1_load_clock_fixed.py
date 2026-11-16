"""T-T99b：隔离 PG、合成行情与固定北京时间；rc1.load 不访问外网。"""

# ruff: noqa: S101
from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import Connection, create_engine, insert, text
from sqlalchemy.engine import make_url

from app.config import Settings, load_yaml_dir
from app.db.tables.market import daily_bars, realtime_quotes, trading_calendar
from app.risk import rc1
from app.risk.rc1 import SH, load

DAY = dt.date(2030, 6, 11)
AT = dt.datetime(2030, 6, 11, 14, 59, tzinfo=SH)
CLOSING = AT.replace(hour=15, minute=0)
CODE = "TT99B.SYNTHETIC"
OWNER = uuid.UUID(int=99)
PRICE = Decimal("10.25")
QUOTE_AT = AT - dt.timedelta(seconds=10)
FETCHED_AT = AT - dt.timedelta(seconds=5)


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
                for table in (trading_calendar, realtime_quotes, daily_bars):
                    table.create(conn, checkfirst=True)
                conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
                conn.execute(
                    insert(realtime_quotes).values(
                        code=CODE,
                        ts=QUOTE_AT,
                        price=PRICE,
                        source="ssjy_more",
                        fetched_at=FETCHED_AT,
                    )
                )
                conn.execute(
                    insert(daily_bars).values(
                        code=CODE,
                        trade_date=DAY,
                        adj_type="none",
                        open=Decimal("10"),
                        low=Decimal("9"),
                        high=Decimal("12"),
                        close=Decimal("11"),
                        fetched_at=CLOSING,
                    )
                )
                yield conn
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def test_intraday_uses_fixed_at_quote(settings: Settings, rc1_conn: Connection) -> None:
    facts = load(
        rc1_conn, OWNER, None, CODE, settings, at=AT, stops_at=AT, position_known=False
    )
    assert facts.mode == "intraday"
    assert facts.endpoint == "market.realtime_quotes:raw"
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
    assert facts.low == Decimal("9")
    assert facts.high == Decimal("12")
    assert facts.observed_at == CLOSING
    assert facts.fetched_at == CLOSING
    assert facts.last is None


def test_fixed_at_is_independent_of_wall_clock(
    settings: Settings, rc1_conn: Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FrozenDatetime(dt.datetime):
        frozen = AT

        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return cls.frozen.astimezone(tz) if tz is not None else cls.frozen.replace(tzinfo=None)

    monkeypatch.setattr(rc1.dt, "datetime", FrozenDatetime)
    results = []
    for wall_clock in (AT, CLOSING.replace(hour=16)):
        monkeypatch.setattr(FrozenDatetime, "frozen", wall_clock)
        assert rc1.dt.datetime.now(SH) == wall_clock
        results.append(
            load(rc1_conn, OWNER, None, CODE, settings, at=AT, stops_at=AT, position_known=False)
        )
    assert results[0] == results[1]
    assert results[0].endpoint == "market.realtime_quotes:raw"
    assert results[0].last == PRICE
    assert results[0].observed_at == QUOTE_AT
    assert results[0].fetched_at == FETCHED_AT

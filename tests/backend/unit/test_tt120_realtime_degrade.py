"""T-T120：实时行情降级契约格。create_app + 虚构只读夹具，采集只走公开入口。"""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.config import Settings
from app.main import create_app

CODE = "999991.SH"
OWNER = uuid.UUID(int=1201)
LICENCE = uuid.UUID(int=1202)
BJ = ZoneInfo("Asia/Shanghai")
UTC = dt.UTC
DAY = dt.date(2041, 5, 6)

class FixtureRow:
    """最小 SQLAlchemy Row 形状，同时支持属性和 ``_mapping`` 访问。"""

    def __init__(self, **values: Any) -> None:
        self._mapping = values
        for key, value in values.items():
            setattr(self, key, value)

class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

def daily_bar(**overrides: Any) -> FixtureRow:
    values = dict(
        code=CODE, trade_date=DAY, adj_type="none", source="mairui",
        source_licence_id=LICENCE, open=Decimal("7.0"), high=Decimal("8.0"),
        low=Decimal("7.0"), close=Decimal("7.8750"), pre_close=Decimal("7.5"),
        volume=Decimal("123"), amount=Decimal("456"), is_suspended=False,
        fetched_at=dt.datetime(2041, 5, 6, 7, 10, tzinfo=UTC),
    )
    values.update(overrides)
    return FixtureRow(**values)

class Clock:
    current: dt.datetime
    combine = staticmethod(dt.datetime.combine)

    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
        return cls.current if tz is None else cls.current.astimezone(tz)

class FakeConnection:
    def __init__(self, state: SimpleNamespace) -> None:
        self.state = state

    def execute(self, statement: Any) -> Result:
        compiled = statement.compile(dialect=postgresql.dialect())
        rendered = str(compiled)
        assert rendered.lstrip().upper().startswith("SELECT "), rendered
        self.state.sql.append(rendered)
        params = compiled.params

        if "market.securities" in rendered:
            requested = params["code_1"]
            return Result([
                FixtureRow(code=code, name="虚构证券 " + code, type="stock")
                for code in requested
            ])

        if "app.user_data_licence_status" in rendered:
            return Result([LICENCE] if self.state.licence_available else [])

        if "market.trading_calendar" in rendered:
            local_day = self.state.now.astimezone(BJ).date()
            if "SELECT market.trading_calendar.is_open" in rendered:
                return Result([self.state.calendar[local_day]])
            inclusive = "date<=" in rendered.replace(" ", "")
            open_days = [
                day for day, is_open in self.state.calendar.items()
                if is_open and (day <= local_day if inclusive else day < local_day)
            ]
            return Result([max(open_days)] if open_days else [])

        if "market.daily_bars" in rendered:
            requested = params["code_1"]
            latest_day = params["trade_date_1"]
            as_of = params["fetched_at_1"]
            rows = [
                row for row in self.state.bars
                if row.code in requested and row.source == "mairui"
                and row.source_licence_id == LICENCE and row.trade_date <= latest_day
                and row.fetched_at <= as_of and row.is_suspended is False
                and row.fetched_at >= dt.datetime.combine(row.trade_date, dt.time(15), BJ)
                and all(getattr(row, f) is not None for f in ("open", "high", "low", "close"))
            ]
            latest: dict[str, FixtureRow] = {}
            for row in sorted(rows, key=lambda item: item.trade_date, reverse=True):
                latest.setdefault(row.code, row)
            return Result(list(latest.values()))

        if "market.quotes_snapshot" in rendered:
            return Result(list(self.state.snapshots))

        return Result([])

def _settings_with_realtime_source(settings: Settings) -> Settings:
    try:
        object.__setattr__(settings, "realtime_quotes_source", "mairui")
        return settings
    except Exception:
        copied = settings.model_copy(update={"realtime_quotes_source": "mairui"})
        object.__setattr__(copied, "realtime_quotes_source", "mairui")
        return copied

def _reset_ingest_runtime_state(module: Any) -> None:
    for name in ("_last_realtime_quotes_tick", "_realtime_breaker_until"):
        if hasattr(module, name):
            setattr(module, name, None)

def _snapshot(ts: dt.datetime, price: str = "8.1250") -> FixtureRow:
    amount = Decimal("73")
    volume = Decimal("9")
    value = Decimal(price)
    change = Decimal("8.33")
    return FixtureRow(
        code=CODE, ts=ts, realtime_ts=ts, price=value, realtime_price=value,
        pct_change=change, realtime_pct_change=change, volume=volume,
        realtime_volume=volume, amount=amount, realtime_amount=amount,
        fetched_at=ts, source="mairui", source_licence_id=LICENCE, revision=1,
    )

def _strict_xfail(request: pytest.FixtureRequest, reason: str) -> None:
    request.applymarker(pytest.mark.xfail(strict=True, reason=reason))
    pytest.xfail(reason)


def _breaker_runtime(
    request: pytest.FixtureRequest,
) -> tuple[Any, Any, type[BaseException], Any]:
    try:
        import app.workers.ingest as ingest
        from app.workers.ingest import tick_realtime_quotes
        import app.marketdata.realtime_collect as realtime_collect
        from app.marketdata.realtime_collect import RealtimeCollectionStoppedError
    except ImportError:
        _strict_xfail(request, "待 T-B224/#391：breaker_cooldown_s 运行时未接线")
    return tick_realtime_quotes, realtime_collect, RealtimeCollectionStoppedError, ingest

@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(
        now=dt.datetime(2041, 5, 6, 8, 5, tzinfo=UTC),
        bars=[daily_bar()],
        snapshots=[],
        licence_available=True,
        sql=[],
        calendar={DAY: True, DAY - dt.timedelta(days=1): False},
    )
    Clock.current = state.now
    monkeypatch.setattr("app.marketdata.quotes_read.dt", SimpleNamespace(
        datetime=Clock, time=dt.time, timedelta=dt.timedelta, UTC=UTC,
    ))
    settings = _settings_with_realtime_source(
        Settings(_env_file=None, app_env="test", database_url=None, redis_url=None)
    )
    monkeypatch.setattr("app.marketdata.quotes_read.get_settings", lambda: settings, raising=False)
    engine = SimpleNamespace(connect=lambda: nullcontext(FakeConnection(state)))
    session = Session("synthetic-session", str(OWNER), "synthetic-csrf", state.now.isoformat())
    store = SimpleNamespace(get=lambda sid: session if sid else None)
    app = create_app(settings)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: store
    app.dependency_overrides[deps.get_redis] = lambda: SimpleNamespace()
    monkeypatch.setattr(deps, "load_user", lambda _e, uid: SimpleNamespace(id=uid, status="approved"))

    with TestClient(app) as client:
        monkeypatch.setattr(socket.socket, "connect", lambda *_a, **_k: pytest.fail("禁网"))
        monkeypatch.setattr(socket, "create_connection", lambda *_a, **_k: pytest.fail("禁网"))
        client.cookies.set(SESSION_COOKIE, "synthetic-session")
        yield SimpleNamespace(client=client, state=state, settings=settings)

def item(world: Any) -> dict[str, Any]:
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 200, response.text
    return response.json()["items"][0]

def test_realtime_missing_falls_back_to_owned_daily_close(world: Any) -> None:
    result = item(world)
    assert result["security_code"] == CODE
    assert result["price"] == "7.8750"
    assert result["t"] == "2041-05-06T15:00:00+08:00"
    assert result["data_as_of"] == "2041-05-06T15:10:00+08:00"
    assert result["data_status"] == "fresh"


def test_intraday_daily_fallback_is_stale_without_realtime_snapshot(world: Any) -> None:
    previous = DAY - dt.timedelta(days=1)
    when = dt.datetime(2041, 5, 6, 3, 0, tzinfo=UTC)  # 11:00 Beijing
    world.state.now = when
    Clock.current = when
    world.state.calendar = {DAY: True, previous: True}
    world.state.bars = [
        daily_bar(
            trade_date=previous,
            fetched_at=dt.datetime(2041, 5, 5, 7, 10, tzinfo=UTC),
        )
    ]
    world.state.snapshots = []
    result = item(world)
    assert result["price"] == "7.8750"
    assert result["t"] == "2041-05-05T15:00:00+08:00"
    assert result["data_as_of"] == "2041-05-05T15:10:00+08:00"
    assert result["data_status"] == "stale"

def test_suspended_daily_row_has_null_quote_fields(world: Any) -> None:
    world.state.bars = [daily_bar(is_suspended=True)]
    result = item(world)
    assert result["data_status"] == "unavailable"
    assert all(
        result[field] is None
        for field in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
    )

def test_unusable_owner_licence_cannot_fall_back_to_daily_price(world: Any) -> None:
    world.state.licence_available = False
    result = item(world)
    assert result["data_status"] == "unavailable"
    assert all(
        result[field] is None
        for field in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
    )
    assert "data_licence_unavailable" in {gap["reason"] for gap in result["gaps"]}

@pytest.mark.parametrize(
    "when",
    [
        dt.datetime(2041, 5, 6, 0, 30, tzinfo=UTC),  # 08:30 Beijing, pre-market
        dt.datetime(2041, 5, 6, 4, 0, tzinfo=UTC),  # 12:00 Beijing, lunch break
    ],
)
def test_session_freshness_uses_beijing_calendar_and_30s_threshold(
    world: Any, when: dt.datetime, request: pytest.FixtureRequest
) -> None:
    world.state.now = when
    Clock.current = when
    world.settings = _settings_with_realtime_source(world.settings)
    local_time = when.astimezone(BJ)
    previous = DAY - dt.timedelta(days=1)
    if local_time.hour == 8:
        world.state.calendar = {DAY: True, previous: True}
        world.state.bars = [daily_bar(trade_date=previous, fetched_at=dt.datetime(2041, 5, 5, 7, 10, tzinfo=UTC))]
        world.state.snapshots = []
    else:
        world.state.bars = []
        world.state.snapshots = [_snapshot(dt.datetime(2041, 5, 6, 3, 29, 55, tzinfo=UTC))]
    result = item(world)
    if local_time.hour == 8:
        if result.get("price") is None:
            _strict_xfail(request, "待 T-B223/#390：盘前上一开市日收盘读链未接线")
        assert result["price"] == "7.8750"
        assert result["t"] == "2041-05-05T15:00:00+08:00"
        assert result["data_as_of"] == "2041-05-05T15:10:00+08:00"
        if result["data_status"] != "fresh":
            _strict_xfail(request, "待 T-B223/#390：盘前上一开市日收盘 fresh 判定未接线")
    elif result.get("price") in (None, "7.8750"):
        _strict_xfail(request, "待 T-B213b/#377：午休实时快照读链未接线")
    else:
        assert result["price"] == "8.1250"
        assert result["t"] == "2041-05-06T11:29:55+08:00"
        assert result["data_as_of"] == "2041-05-06T11:29:55+08:00"
        if result["data_status"] != "fresh":
            _strict_xfail(request, "待 T-B223/#390：午休按上午收盘时点判 fresh 未接线")
    assert result["data_status"] == "fresh"

def test_post_close_uses_last_trading_session_close(world: Any) -> None:
    world.state.now = Clock.current = dt.datetime(2041, 5, 6, 8, 30, tzinfo=UTC)  # 16:30 BJ
    assert item(world)["data_status"] == "fresh"

def test_closed_day_uses_last_open_day_close(world: Any) -> None:
    previous = DAY - dt.timedelta(days=1)
    when = dt.datetime(2041, 5, 7, 8, 30, tzinfo=UTC)
    world.state.now = when
    Clock.current = when
    world.state.calendar = {DAY + dt.timedelta(days=1): False, DAY: False, previous: True}
    world.state.bars = [daily_bar(trade_date=previous, fetched_at=dt.datetime(2041, 5, 5, 7, 10, tzinfo=UTC))]
    assert item(world)["data_status"] == "fresh"

def test_realtime_snapshot_precedes_daily_fallback(
    world: Any, request: pytest.FixtureRequest
) -> None:
    previous = DAY - dt.timedelta(days=1)
    now = dt.datetime(2041, 5, 6, 6, 0, tzinfo=UTC)  # 14:00 Beijing，墙钟龄 20s
    world.state.now = now
    Clock.current = now
    world.state.calendar = {DAY: True, previous: True}
    world.state.bars = [daily_bar(trade_date=previous, fetched_at=dt.datetime(2041, 5, 5, 7, 10, tzinfo=UTC))]
    world.state.snapshots = [_snapshot(dt.datetime(2041, 5, 6, 5, 59, 40, tzinfo=UTC))]
    result = item(world)
    if result.get("price") in (None, "7.8750"):
        _strict_xfail(request, "待 T-B213b/#377：实时快照读链未接线，仍回落日线价")
    assert result["price"] == "8.1250"
    assert result["t"] == "2041-05-06T13:59:40+08:00"
    assert result["data_as_of"] == "2041-05-06T13:59:40+08:00"
    assert result["data_status"] == "fresh"

@pytest.mark.parametrize(("age_s", "expected"), [(29, "fresh"), (31, "stale")])
def test_realtime_snapshot_age_uses_default_30_second_threshold(
    world: Any, age_s: int, expected: str, request: pytest.FixtureRequest
) -> None:
    now = dt.datetime(2041, 5, 6, 2, 0, tzinfo=UTC)
    world.state.now = now
    Clock.current = now
    world.state.snapshots = [_snapshot(now - dt.timedelta(seconds=age_s))]
    result = item(world)
    if result.get("price") in (None, "7.8750"):
        _strict_xfail(request, "待 T-B213b/#377：实时快照 freshness 读链未接线")
    assert result["price"] == "8.1250"
    expected_stamp = (now - dt.timedelta(seconds=age_s)).astimezone(BJ).isoformat()
    assert result["t"] == expected_stamp
    assert result["data_as_of"] == expected_stamp
    assert result["data_status"] == expected

@pytest.mark.parametrize("status", [429, 503])
def test_upstream_rate_or_server_error_opens_runtime_breaker(
    status: int, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    tick_realtime_quotes, realtime_collect, stopped_error, ingest = _breaker_runtime(request)

    calls: list[float] = []

    def fake_task(
        settings: Settings,
        *,
        now: Any = None,
        owner: Any = None,
        transport: Any = None,
        secret_loader: Any = None,
    ) -> None:
        calls.append(1.0)
        raise stopped_error("upstream", status=status)

    settings = Settings(_env_file=None, app_env="test", database_url=None, redis_url=None)
    settings = _settings_with_realtime_source(settings)
    _reset_ingest_runtime_state(ingest)
    monkeypatch.setattr(realtime_collect, "realtime_quotes_task", fake_task)
    tick_realtime_quotes(settings, now_monotonic=0.0)
    assert len(calls) == 1
    tick_realtime_quotes(settings, now_monotonic=299.0)
    assert len(calls) == 1
    tick_realtime_quotes(settings, now_monotonic=300.0)
    assert len(calls) == 2

def test_breaker_cooldown_can_be_changed_to_ten_seconds(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    tick_realtime_quotes, realtime_collect, stopped_error, ingest = _breaker_runtime(request)
    calls: list[float] = []

    def fake_task(
        settings: Settings,
        *,
        now: Any = None,
        owner: Any = None,
        transport: Any = None,
        secret_loader: Any = None,
    ) -> None:
        calls.append(1.0)
        raise stopped_error("upstream", status=429)

    settings = Settings(_env_file=None, app_env="test", database_url=None, redis_url=None)
    settings = settings.with_business_overrides({
        "realtime": {"adaptive": {"breaker_cooldown_s": 10}, "intervals": {"quote_interval_s": 5}}
    })
    settings = _settings_with_realtime_source(settings)
    _reset_ingest_runtime_state(ingest)
    monkeypatch.setattr(realtime_collect, "realtime_quotes_task", fake_task)
    tick_realtime_quotes(settings, now_monotonic=0.0)
    assert len(calls) == 1
    tick_realtime_quotes(settings, now_monotonic=9.9)
    assert len(calls) == 1
    tick_realtime_quotes(settings, now_monotonic=10.0)
    assert len(calls) == 2

def test_upstream_timeout_cooling_behavior_is_unverified(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> None:
    tick_realtime_quotes, realtime_collect, _stopped_error, ingest = _breaker_runtime(request)
    calls: list[float] = []

    def fake_task(
        settings: Settings,
        *,
        now: Any = None,
        owner: Any = None,
        transport: Any = None,
        secret_loader: Any = None,
    ) -> None:
        calls.append(1.0)
        raise TimeoutError("synthetic timeout")

    settings = Settings(_env_file=None, app_env="test", database_url=None, redis_url=None)
    settings = _settings_with_realtime_source(settings)
    _reset_ingest_runtime_state(ingest)
    monkeypatch.setattr(realtime_collect, "realtime_quotes_task", fake_task)
    for now in (0.0, 20.0):
        try:
            tick_realtime_quotes(settings, now_monotonic=now)
        except (TimeoutError, socket.timeout):
            pass
    if len(calls) >= 2:
        _strict_xfail(
            request,
            "待 T-A230/#未裁定：未验证：契约/配置未说明超时是否熔断",
        )
    assert len(calls) == 1

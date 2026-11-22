"""T-T129 market overview acceptance through the real FastAPI application.

The connection below is a read-only SQL-shaped adapter over fictional rows.  It
returns complete table row sets and leaves PIT, source, date and eligibility
filtering to ``build_market_overview``.  No vendor, queue or external service
is contacted.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.sql import Select

from app.auth import deps
from app.config import Settings
from app.main import create_app
from app.schemas.enums import MarketSession


pytestmark = pytest.mark.unit
OWNER = uuid.UUID("00000000-0000-0000-0000-00000000c129")
LICENCE = uuid.UUID("00000000-0000-0000-0000-00000000c130")
BATCH = uuid.UUID("00000000-0000-0000-0000-00000000c131")
DAY = dt.date(2026, 11, 13)
UTC = dt.timezone.utc
NOW = dt.datetime(2026, 11, 13, 2, 0, tzinfo=UTC)


class Result:
    def __init__(self, rows: list[object] | None = None, scalar: object = None) -> None:
        self.rows = rows or []
        self.scalar = scalar

    def all(self) -> list[object]:
        return self.rows

    def first(self) -> object | None:
        return self.rows[0] if self.rows else None

    def scalar_one_or_none(self) -> object:
        return self.scalar


def row(**values: object) -> SimpleNamespace:
    return SimpleNamespace(_mapping=values)


def security(code: str, kind: str, exchange: str) -> SimpleNamespace:
    return row(
        code=code,
        name="虚构" + code,
        type=kind,
        exchange=exchange,
        listing_status="listed",
        list_date=None,
        delist_date=None,
    )


def quote(
    code: str,
    change: str,
    amount: str,
    stamp: dt.datetime,
    *,
    batch_id: uuid.UUID = BATCH,
) -> SimpleNamespace:
    return row(
        code=code,
        ts=stamp,
        fetched_at=stamp,
        source="mairui",
        source_licence_id=LICENCE,
        batch_id=batch_id,
        price=change,
        pct_change=change,
        volume="100",
        amount=amount,
        payload=None,
        is_suspended=False,
        limit_up=False,
        limit_down=False,
    )


@dataclass
class State:
    stocks: list[SimpleNamespace] = field(
        default_factory=lambda: [
            security("600000.SH", "stock", "SH"),
            security("000001.SZ", "stock", "SZ"),
        ]
    )
    indices: list[SimpleNamespace] = field(
        default_factory=lambda: [security("000300.SH", "index", "SH")]
    )
    quotes: list[SimpleNamespace] = field(default_factory=list)
    daily_rows: list[SimpleNamespace] = field(default_factory=list)
    licence: uuid.UUID | None = LICENCE
    execute_count: int = 0
    write_attempts: int = 0


class ReadOnlyConnection:
    """Return whole synthetic tables, never evaluate a SQL WHERE clause."""

    def __init__(self, state: State) -> None:
        self.state = state

    def __enter__(self) -> ReadOnlyConnection:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> Result:
        self.state.execute_count += 1
        if not isinstance(statement, Select):
            self.state.write_attempts += 1
            raise AssertionError("market overview GET attempted a non-SELECT")
        text = str(statement)
        if "user_data_licence_status" in text:
            return Result(scalar=self.state.licence)
        if "security_listing_status_history" in text:
            return Result([])
        if "quotes_snapshot" in text:
            return Result(list(self.state.quotes))
        if "daily_bars" in text:
            return Result(list(self.state.daily_rows))
        if "securities" in text:
            params = statement.compile().params
            return Result(self.state.indices if "index" in params.values() else self.state.stocks)
        raise AssertionError(f"unexpected read in fixture: {text}")


class ReadOnlyEngine:
    def __init__(self, state: State) -> None:
        self.state = state

    def connect(self) -> ReadOnlyConnection:
        return ReadOnlyConnection(self.state)


def make_client(monkeypatch: pytest.MonkeyPatch, state: State, session: MarketSession) -> TestClient:
    settings = Settings(app_env="test", database_url=None, redis_url=None, _env_file=None)
    app = create_app(settings)
    app.dependency_overrides[deps.get_engine] = lambda: ReadOnlyEngine(state)
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return NOW.astimezone(tz) if tz is not None else NOW.replace(tzinfo=None)

    from app.api.v1 import aggregates

    monkeypatch.setattr(aggregates, "dt", SimpleNamespace(datetime=FrozenDateTime, UTC=UTC))
    monkeypatch.setattr(
        aggregates,
        "market_clock",
        lambda _conn, _now, _rules: SimpleNamespace(trade_date=DAY, session=session),
    )
    return TestClient(app)


def test_http_basis_partial_batch_keeps_null_components(monkeypatch: pytest.MonkeyPatch) -> None:
    state = State(
        quotes=[
            quote("600000.SH", "1.2", "1200.00", NOW),
            quote("000300.SH", "0.5", "800.00", NOW),
        ]
    )
    with make_client(monkeypatch, state, MarketSession.MORNING) as client:
        response = client.get("/api/v1/market/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trade_date"] == DAY.isoformat()
    assert body["session"] == "morning"
    assert body["basis"] == {
        "snapshot_id": None,
        "observed_date": DAY.isoformat(),
        "mode": "intraday",
        "scope": "沪深股票口径",
        "eligible": 2,
        "observed": 1,
        "trading": 1,
        "suspended": 0,
        "missing": 1,
        "source": "mairui",
    }
    assert body["breadth"]["up"] == 1
    assert body["turnover_total"] is None
    assert body["data_status"] == "partial"
    assert {gap["key"] for gap in body["gaps"]} == {
        "market.regime",
        "market.turnover_total",
    }


def test_http_empty_state_deduplicates_gaps_and_keeps_beijing_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = State()
    with make_client(monkeypatch, state, MarketSession.PRE_OPEN) as client:
        response = client.get("/api/v1/market/overview")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["trade_date"] == "2026-11-13"
    assert body["session"] == "pre_open"
    assert body["data_as_of"] is None
    assert body["breadth"] is None
    assert body["turnover_total"] is None
    keys = [gap["key"] for gap in body["gaps"]]
    assert len(keys) == len(set(keys))
    assert keys == [
        "market.indices.000300.SH",
        "market.breadth.limit_counts",
        "market.regime",
        "market.breadth",
        "market.turnover_total",
        "market.indices",
    ]
    assert all(item["price"] is None and item["amount"] is None for item in body["indices"])


def test_http_get_is_read_only_and_supports_conditional_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = State(quotes=[quote("600000.SH", "1.2", "1200.00", NOW)])
    with make_client(monkeypatch, state, MarketSession.MORNING) as client:
        first = client.get("/api/v1/market/overview")
        tag = first.headers["etag"]
        second = client.get("/api/v1/market/overview", headers={"If-None-Match": tag})
    assert first.status_code == 200
    assert second.status_code == 304
    assert second.headers["etag"] == tag
    assert state.write_attempts == 0
    assert state.execute_count > 0

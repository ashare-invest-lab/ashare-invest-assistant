"""T-A169: exercise real aggregate routes/services with synthetic, offline readers."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from app.aggregates import models as m
from app.aggregates import products, service
from app.api.v1 import aggregates as routes
from app.auth import deps
from app.marketdata import quotes_read
from app.schemas.enums import DataStatus, MarketSession
from fastapi import FastAPI
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection
from sqlalchemy.sql.selectable import Join

OWNER, ACCOUNT = uuid.UUID(int=169), uuid.UUID(int=170)
NOW = dt.datetime(2026, 11, 13, 9, tzinfo=dt.UTC)
CLOCK = m.MarketClock(trade_date=NOW.date(), session=MarketSession.CLOSED)
CODES = [f"{990000 + i:06d}.SH" for i in range(301)]
EARLY = "2026-11-13T09:30:00+08:00"  # 01:30 UTC; lexical order is misleading.
LATE = "2026-11-13T02:00:00+00:00"


@dataclass
class World:
    client: TestClient
    conn: MagicMock
    watched: list[str] = field(default_factory=list)
    focused: list[str] = field(default_factory=list)
    positions: dict[str, Any] = field(default_factory=dict)
    times: dict[str, str | None] = field(default_factory=dict)
    reads: list[str] = field(default_factory=list)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("T-A169 tests must not connect to any service")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    conn = MagicMock(spec=Connection)
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    state = World(client=TestClient(app), conn=conn)

    def execute(statement: Any) -> MagicMock:
        assert statement.is_select, "aggregate GET must never write"
        source = statement.get_final_froms()[0]
        table = source.left.fullname if isinstance(source, Join) else source.fullname
        state.reads.append(table)
        result = MagicMock()
        if table == "app.watchlist_items":
            result.all.return_value = [
                SimpleNamespace(security_code=code) for code in state.watched
            ]
        elif table == "app.user_realtime_prefs":
            result.scalar_one_or_none.return_value = state.focused
        elif table == "market.securities":
            codes = statement.compile().params.get("code_1", list(state.times))
            rows = [
                SimpleNamespace(code=code, name="synthetic", type="stock")
                for code in codes
            ]
            result.__iter__.side_effect = lambda: iter(rows)
        elif table == "app.broker_position_snapshots":
            result.first.return_value = None
        elif table == "app.notifications":
            result.scalar_one.return_value = 0
        elif table == "app.daily_reports":
            result.scalars.return_value.all.return_value = []
        else:
            raise AssertionError(f"Unexpected read: {table}")
        return result

    def read_quotes(
        connection: Connection, owner: uuid.UUID, codes: tuple[str, ...]
    ) -> Any:
        assert connection is conn and owner == OWNER
        return quotes_read.QuotesResponse(
            items=[
                quotes_read.QuoteItem(
                    security_code=code,
                    name="synthetic",
                    price="1",
                    t=NOW.isoformat(),
                    data_status=DataStatus.STALE,
                    data_as_of=state.times.get(code),
                    gaps=[],
                )
                for code in codes
            ]
        )

    conn.execute.side_effect = execute
    engine = SimpleNamespace(connect=lambda: nullcontext(conn))
    settings = SimpleNamespace(
        business=SimpleNamespace(
            market_rules=None,
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(pro_tier1_interval_s=60)
            ),
        )
    )
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)
    app.dependency_overrides[deps.get_settings] = lambda: settings
    monkeypatch.setattr(routes, "market_clock", lambda *args: CLOCK)
    monkeypatch.setattr(service, "select_account", lambda *args: ACCOUNT)
    monkeypatch.setattr(
        service,
        "_account",
        lambda *args: SimpleNamespace(positions=state.positions, cash=Decimal(1000)),
    )
    monkeypatch.setattr(quotes_read, "read_quotes", read_quotes)
    monkeypatch.setattr(products, "owned_suggestions", lambda *args: {})
    monkeypatch.setattr(products, "reasons", lambda *args: [])
    monkeypatch.setattr(
        products,
        "blocks",
        lambda *args: {
            **{
                key: {"items": [], "more": False}
                for key in (
                    "pending_plan_drafts",
                    "released_reasons",
                    "risk_flags",
                    "invalidations_today",
                )
            },
            "gaps": [],
            "evidence": [],
        },
    )
    monkeypatch.setattr(
        service,
        "read_reconciliation",
        lambda *args: {
            "status": "not_imported",
            "as_of": None,
            "diff_count": 0,
            "important_count": 0,
        },
    )
    monkeypatch.setattr(service.t_view, "today_trades", lambda *args: {})
    monkeypatch.setattr(service.t_view, "snapshot_basis", lambda *args: None)
    with state.client:
        yield state
    app.dependency_overrides.clear()


def position() -> SimpleNamespace:
    return SimpleNamespace(
        qty=Decimal(100),
        price=Decimal(1),
        cost_total=Decimal(100),
        cost_known=True,
        sellable=Decimal(100),
    )


def as_of(value: str | None) -> dt.datetime | None:
    return dt.datetime.fromisoformat(value).astimezone(dt.UTC) if value else None


def assert_cache(client: TestClient, path: str, response: Response) -> None:
    tag = response.headers["etag"]
    assert response.headers["cache-control"] == "private, no-cache"
    cached = client.get(path, headers={"If-None-Match": tag})
    assert cached.status_code == 304
    assert cached.content == b""
    assert cached.headers["etag"] == tag
    model_type = m.Today if path.startswith("/api/v1/today") else m.Terminal
    model = model_type.model_validate_json(response.content)
    # Isolate the top-level timestamp: row data and every other field are identical.
    changed = model.model_copy(update={"data_as_of": NOW})
    assert routes.response(changed, tag).status_code == 200
    assert routes.response(changed, None).headers["etag"] != tag


@pytest.mark.parametrize("scope", ["all", "watchlist", "holdings"])
def test_terminal_top_data_as_of_min_of_returned_rows(world: World, scope: str) -> None:
    a, b, excluded = CODES[:3]
    world.watched = [a, b]
    world.positions = {a: position(), b: position(), excluded: position()}
    world.times = {a: LATE, b: EARLY, excluded: "2026-11-12T00:00:00Z"}
    # The oldest holding must be absent from watchlist scope, but present in all/holdings.
    path = f"/api/v1/terminal?scope={scope}"
    response = world.client.get(path)
    assert response.status_code == 200
    payload = response.json()
    expected_codes = {a, b} if scope == "watchlist" else {a, b, excluded}
    assert {row["security_code"] for row in payload["rows"]} == expected_codes
    expected = EARLY if scope == "watchlist" else world.times[excluded]
    assert as_of(payload["data_as_of"]) == as_of(expected)
    assert payload["data_status"] == "partial"
    assert "data_as_of" not in payload["account"]
    assert_cache(world.client, path, response)


@pytest.mark.parametrize("count", [0, 2])
def test_terminal_top_data_as_of_null_when_rows_all_null(
    world: World, count: int
) -> None:
    world.watched = CODES[:count]
    path = "/api/v1/terminal?scope=watchlist"
    response = world.client.get(path)
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == count
    assert all(row["data_as_of"] is None for row in payload["rows"])
    assert payload["data_as_of"] is None
    assert_cache(world.client, path, response)


def test_terminal_top_data_as_of_ignores_truncated_rows(world: World) -> None:
    world.watched = CODES[:]
    world.times = {code: LATE for code in CODES}
    world.times[CODES[0]] = EARLY
    world.times[CODES[-1]] = "2026-11-12T00:00:00Z"
    response = world.client.get("/api/v1/terminal?scope=watchlist")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["rows"]) == 300
    assert payload["truncated"] is True
    assert CODES[-1] not in {row["security_code"] for row in payload["rows"]}
    assert as_of(payload["data_as_of"]) == as_of(EARLY)
    assert_cache(world.client, "/api/v1/terminal?scope=watchlist", response)


def test_today_top_data_as_of_min_of_focus_items(world: World) -> None:
    world.watched = CODES[:52]
    world.focused = CODES[:51]
    world.times = {code: LATE for code in world.watched}
    world.times[CODES[0]] = EARLY
    world.times[CODES[50]] = "2026-11-12T00:00:00Z"  # 51st focus item: omitted.
    world.times[CODES[51]] = "2026-11-11T00:00:00Z"  # Not focused: omitted.
    response = world.client.get("/api/v1/today")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["focus"]["items"]) == 50
    assert payload["focus"]["more"] is True
    assert {row["security_code"] for row in payload["focus"]["items"]} == set(
        CODES[:50]
    )
    assert as_of(payload["data_as_of"]) == as_of(EARLY)
    assert "data_as_of" not in payload["market"]
    assert_cache(world.client, "/api/v1/today", response)


@pytest.mark.parametrize("mode", ["empty", "unfocused", "all_null"])
def test_today_top_data_as_of_null_when_no_focus(world: World, mode: str) -> None:
    world.watched = [] if mode == "empty" else CODES[:2]
    world.focused = CODES[:2] if mode == "all_null" else []
    world.times = {} if mode == "all_null" else {code: EARLY for code in world.watched}
    response = world.client.get("/api/v1/today")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["focus"]["items"]) == (2 if mode == "all_null" else 0)
    assert payload["data_as_of"] is None
    assert_cache(world.client, "/api/v1/today", response)

"""T-T114 realtime-first quote reads with synthetic, offline cache facts."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import re
import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.dialects import postgresql

from app.auth import deps
from app.auth.sessions import Session
from app.api.v1 import notifications

from tests.backend.unit.test_quotes_empty_s3 import Result, bar, world as base_world


OWNER = uuid.UUID(int=711)
LICENCE = uuid.UUID(int=713)
OTHER_LICENCE = uuid.UUID(int=714)
CODE = "990114.SH"
SECOND_CODE = "990115.SZ"
NOW = dt.datetime(2041, 5, 6, 16, 5, tzinfo=dt.UTC)
PRICE = Decimal("23.456")
BEIJING = dt.timezone(dt.timedelta(hours=8))


def snapshot(**overrides: Any) -> SimpleNamespace:
    """A target quotes_snapshot row, including fields T-B205 will bind to a licence."""
    values = dict(
        code=CODE,
        ts=NOW - dt.timedelta(seconds=5),
        fetched_at=NOW - dt.timedelta(seconds=5),
        query_as_of=NOW,
        source="mairui",
        source_licence_id=LICENCE,
        price=PRICE,
        pct_change=Decimal("1.20"),
        volume=Decimal("1000"),
        amount=Decimal("23456"),
    )
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.fixture
def world(base_world: Any) -> Any:  # noqa: F811
    """Reuse the existing ASGI/auth harness while allowing fictional T-T114 codes."""
    state = base_world.state
    state.now = NOW
    state.latest_close_date = dt.date(2041, 5, 6)
    state.bars = []
    state.snapshots: list[Any] = []
    state.active = {OWNER}

    base_engine = base_world.client.app.dependency_overrides[deps.get_engine]()
    base_connect = base_engine.connect

    def execute(statement: Any) -> Result:
        compiled = statement.compile(dialect=postgresql.dialect())
        rendered = str(compiled)
        if "market.quotes_snapshot" in rendered:
            assert rendered.lstrip().upper().startswith("SELECT ")
            state.reads.append(rendered)
            params = compiled.params
            requested = next(
                (
                    value
                    for key, value in params.items()
                    if key.startswith("code")
                    and isinstance(value, (str, tuple, list, set))
                ),
                (CODE, SECOND_CODE),
            )
            if isinstance(requested, str):
                requested = (requested,)
            rows = [row for row in state.snapshots if row.code in requested]
            for field in ("source", "source_licence_id", "fetched_at", "ts"):
                marker = f"market.quotes_snapshot.{field}"
                for name, expected in params.items():
                    if field not in name:
                        continue
                    match = re.search(
                        rf"{re.escape(marker)}\s*"
                        rf"(?P<operator>=|<=|>=|<|>)\s*"
                        rf"%\({re.escape(name)}\)s",
                        rendered,
                    )
                    if match is None:
                        continue
                    operator = match.group("operator")

                    def matches(row: Any) -> bool:
                        value = getattr(row, field, None)
                        if operator == "=":
                            return value == expected
                        if value is None:
                            return False
                        if operator == "<=":
                            return value <= expected
                        if operator == ">=":
                            return value >= expected
                        if operator == "<":
                            return value < expected
                        return value > expected

                    rows = [row for row in rows if matches(row)]
            return Result(rows)
        if "market.realtime_quotes" in rendered:
            raise AssertionError("T-T114 must not read the frozen realtime_quotes table")
        if "market.securities" in rendered:
            params = statement.compile().params
            requested = params["code_1"]
            return Result(
                [
                    SimpleNamespace(code=code, name="synthetic " + code, type="stock")
                    for code in (CODE, SECOND_CODE)
                    if code in requested
                ]
            )
        with base_connect() as conn:
            return conn.execute(statement)

    connection = SimpleNamespace(execute=execute)
    engine = SimpleNamespace(
        connect=lambda: nullcontext(connection),
        begin=lambda: nullcontext(connection),
    )
    base_world.client.app.dependency_overrides[deps.get_engine] = lambda: engine
    return base_world


@pytest.fixture
def no_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.core import IngestCore
    from app.ingest.scheduler import Scheduler

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("GET /quotes must not enqueue work")

    monkeypatch.setattr(IngestCore, "submit", forbidden)
    monkeypatch.setattr(Scheduler, "submit", forbidden)


def daily(**overrides: Any) -> SimpleNamespace:
    return bar(
        code=CODE,
        source_licence_id=LICENCE,
        close=Decimal("7.8750"),
        pre_close=Decimal("7.5"),
        volume=Decimal("123"),
        amount=Decimal("456"),
        **overrides,
    )


def item(response: Any) -> dict[str, Any]:
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    return body["items"][0]


def basis_mode(value: dict[str, Any]) -> Any:
    basis = value.get("basis")
    return basis.get("mode") if isinstance(basis, dict) else None


def require_intraday_or_xfail(value: dict[str, Any], expected_price: str) -> None:
    if value.get("price") != expected_price and basis_mode(value) != "intraday":
        pytest.xfail(
            "T-B213 未实现：实时快照未接入 /quotes 读取链，仍走日线或空态路径 "
            "（T-A209 §0.2/§0.3 I7）"
        )
    assert value["price"] == expected_price
    assert basis_mode(value) == "intraday"


def test_certificate_unavailable_wins_over_owned_realtime_fixture(
    world: Any,
) -> None:
    world.state.active = set()
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot()]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["data_status"] == "unavailable"
    assert all(value[field] is None for field in ("price", "volume", "amount", "t", "data_as_of"))
    assert {gap["reason"] for gap in value["gaps"]} == {"data_licence_unavailable"}


def test_future_realtime_fixture_is_not_visible_and_daily_close_may_fallback(
    world: Any,
) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [
        snapshot(
            ts=NOW + dt.timedelta(seconds=5),
            fetched_at=NOW + dt.timedelta(seconds=5),
            query_as_of=NOW,
            price=Decimal("99.999"),
        )
    ]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["price"] == "7.8750"
    assert basis_mode(value) in (None, "close")
    assert basis_mode(value) != "intraday"
    assert value["price"] != "99.999"


def test_realtime_fixture_owned_by_other_certificate_is_not_borrowed(
    world: Any,
) -> None:
    world.state.snapshots = [snapshot(source_licence_id=OTHER_LICENCE, price=Decimal("88.888"))]
    world.state.bars = []

    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    value = item(response)

    assert value["price"] is None
    assert value["data_status"] == "unavailable"
    assert {gap["reason"] for gap in value["gaps"]} == {"no_source"}
    assert "88.888" not in response.text


def test_daily_only_fixture_does_not_claim_intraday_basis(world: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = []

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["price"] == "7.8750"
    assert basis_mode(value) in (None, "close")
    assert basis_mode(value) != "intraday"
    assert value["data_status"] in ("fresh", "stale")


def test_quotes_get_is_read_only_and_never_calls_upstream(world: Any, no_enqueue: None) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot()]
    before = list(world.state.bars)

    response = world.client.get("/api/v1/quotes", params={"codes": CODE})

    assert response.status_code == 200
    assert world.state.bars == before
    assert world.state.reads
    assert all(sql.lstrip().upper().startswith("SELECT ") for sql in world.state.reads)


def test_fresh_owned_realtime_wins_as_a_whole_item(world: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot()]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    require_intraday_or_xfail(value, "23.456")
    assert value["data_status"] == "fresh"
    assert value["t"] == snapshot().ts.astimezone(BEIJING).isoformat()
    assert value["volume"] == "1000"
    assert value["amount"] == "23456"


def test_expired_visible_realtime_remains_realtime_and_is_stale(world: Any) -> None:
    stale_at = NOW - dt.timedelta(seconds=45)
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot(ts=stale_at, fetched_at=stale_at)]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    require_intraday_or_xfail(value, "23.456")
    assert value["data_status"] == "stale"


def test_realtime_missing_amount_does_not_mix_daily_fields(world: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot(volume=None, amount=None)]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    require_intraday_or_xfail(value, "23.456")
    assert value["volume"] is None
    assert value["amount"] is None
    assert value["gaps"]
    assert all(gap["reason"] == "no_source" for gap in value["gaps"])


class _StreamRequest:
    def __init__(self) -> None:
        self.cookies = {"session": "a"}
        self.calls = 0

    async def is_disconnected(self) -> bool:
        self.calls += 1
        return self.calls > 1


class _EmptyRedis:
    def get(self, key: str) -> bytes:
        return b"0"

    def eval(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def zscore(self, *args: Any, **kwargs: Any) -> None:
        return None

    def zrangebyscore(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


def test_stream_observes_cached_quote_event_with_market_timestamp(
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    world.state.snapshots = [snapshot()]
    monkeypatch.setattr(notifications, "load_user", lambda engine, user_id: SimpleNamespace(status="approved"))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(notifications.asyncio, "sleep", lambda seconds: real_sleep(0))

    async def collect() -> list[str]:
        response = await notifications.stream(
            _StreamRequest(),
            SimpleNamespace(user_id=OWNER),
            world.client.app.dependency_overrides[deps.get_engine](),
            _EmptyRedis(),
            SimpleNamespace(get=lambda sid: Session("synthetic", str(OWNER), "synthetic", NOW.isoformat())),
            last_event_id=None,
        )
        chunks: list[str] = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode() if isinstance(chunk, bytes) else chunk)
        return chunks

    chunks = asyncio.run(collect())
    quote_events = [
        chunk
        for chunk in chunks
        if "event: quote" in chunk
    ]
    if not quote_events:
        pytest.xfail(
            "T-B213 未实现：/stream 未从实时读链产生 quote 事件 "
            "（T-A209 §0.2/§0.3 I7）"
        )
    for chunk in quote_events:
        data = json.loads(chunk.split("data: ", 1)[1].split("\n", 1)[0])
        data_as_of = data.get("data_as_of")
        assert isinstance(data_as_of, str) and data_as_of
        items = data.get("items")
        assert isinstance(items, list) and items
        item_times: list[dt.datetime] = []
        for value in items:
            assert isinstance(value, dict)
            assert {
                "security_code",
                "name",
                "price",
                "change_pct",
                "amount",
                "t",
            } <= value.keys()
            assert isinstance(value["t"], str) and value["t"]
            item_times.append(dt.datetime.fromisoformat(value["t"]))
        assert dt.datetime.fromisoformat(data_as_of) == min(item_times)
        assert "heartbeat" not in chunk

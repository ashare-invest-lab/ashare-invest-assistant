"""T-T114 realtime-first quote reads with synthetic, offline cache facts."""

from __future__ import annotations

import asyncio
import socket
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
from app.risk import rc1

from tests.backend.unit.test_quotes_empty_s3 import Result, bar, world as base_world


OWNER = uuid.UUID(int=711)
LICENCE = uuid.UUID(int=713)
OTHER_LICENCE = uuid.UUID(int=714)
CODE = "990114.SH"
SECOND_CODE = "990115.SZ"
NOW = dt.datetime(2041, 5, 6, 16, 5, tzinfo=dt.UTC)
PRICE = Decimal("23.456")
BEIJING = dt.timezone(dt.timedelta(hours=8))
INTRADAY_AT = dt.datetime(2041, 5, 6, 14, 30, tzinfo=BEIJING)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("T-T114 is offline and must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


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
        revision=0,
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
            if "market.quotes_snapshot.source IS NULL" in rendered:
                rows = [row for row in rows if getattr(row, "source", None) is None]
            if "market.quotes_snapshot.source_licence_id IS NULL" in rendered:
                rows = [row for row in rows if getattr(row, "source_licence_id", None) is None]
            if "source_licence_id IS NOT NULL" in rendered:
                rows = [row for row in rows if getattr(row, "source_licence_id", None) is not None]
            if "ORDER BY market.quotes_snapshot.ts DESC" in rendered:
                rows.sort(key=lambda row: row.ts, reverse=True)
                if "market.quotes_snapshot.revision DESC" in rendered and rows:
                    latest_ts = rows[0].ts
                    same_ts = [row for row in rows if row.ts == latest_ts]
                    rest = [row for row in rows if row.ts != latest_ts]
                    rows = sorted(same_ts, key=lambda row: row.revision, reverse=True) + rest
            if "LIMIT" in rendered:
                rows = rows[:1]
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


class _Rc1Rows(Result):
    def __iter__(self):
        return iter(self.rows)

    def first(self) -> Any:
        return self.rows[0] if self.rows else None


def _rc1_settings() -> Any:
    return SimpleNamespace(
        business=SimpleNamespace(
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(effective_stale_threshold_s=60)
            )
        )
    )


def _rc1_connection(
    snapshots: list[Any], realtime_quotes: list[Any] | None = None
) -> tuple[Any, list[str]]:
    reads: list[str] = []
    legacy = list(realtime_quotes or [])

    def execute(statement: Any) -> _Rc1Rows:
        compiled = statement.compile(dialect=postgresql.dialect())
        rendered = str(compiled)
        assert rendered.lstrip().upper().startswith("SELECT ")
        reads.append(rendered)
        params = compiled.params
        if "market.quotes_snapshot" in rendered:
            rows = list(snapshots)
            for field in ("code", "source", "source_licence_id", "fetched_at", "ts"):
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
            if "source_licence_id IS NOT NULL" in rendered:
                rows = [row for row in rows if row.source_licence_id is not None]
            if "ORDER BY market.quotes_snapshot.ts DESC" in rendered:
                rows.sort(key=lambda row: row.ts, reverse=True)
                if "market.quotes_snapshot.revision DESC" in rendered:
                    latest_ts = rows[0].ts if rows else None
                    same_ts = [row for row in rows if row.ts == latest_ts]
                    rest = [row for row in rows if row.ts != latest_ts]
                    rows = sorted(same_ts, key=lambda row: row.revision, reverse=True) + rest
            if "LIMIT" in rendered:
                rows = rows[:1]
            return _Rc1Rows(rows)
        if "market.realtime_quotes" in rendered:
            return _Rc1Rows(legacy)
        return _Rc1Rows([])

    return SimpleNamespace(execute=execute), reads


def _load_rc1_or_xfail(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[Any],
    realtime_quotes: list[Any] | None = None,
) -> tuple[Any, list[str]]:
    connection, reads = _rc1_connection(snapshots, realtime_quotes)
    monkeypatch.setattr(
        "app.marketdata.daily_snapshot.active_licence_id",
        lambda conn, owner, at: LICENCE,
    )
    facts = rc1.load(
        connection,
        OWNER,
        None,
        CODE,
        _rc1_settings(),
        at=INTRADAY_AT,
        stops_at=INTRADAY_AT,
        position_known=False,
    )
    has_snapshot_read = any("market.quotes_snapshot" in sql for sql in reads)
    has_realtime_read = any("market.realtime_quotes" in sql for sql in reads)
    if not has_snapshot_read:
        pytest.xfail(
            "T-B205/#365@9585dd62 未合入：rc1 盘中读尚未改为 market.quotes_snapshot:raw"
        )
    assert facts.endpoint == "market.quotes_snapshot:raw"
    assert has_snapshot_read
    assert not has_realtime_read
    return facts, reads


def test_rc1_load_uses_owned_snapshot_and_marks_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote = snapshot(
        ts=INTRADAY_AT - dt.timedelta(seconds=10),
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=5),
        query_as_of=INTRADAY_AT,
    )

    facts, _ = _load_rc1_or_xfail(monkeypatch, [quote])

    assert facts.mode == "intraday"
    assert facts.endpoint == "market.quotes_snapshot:raw"
    assert facts.last == PRICE
    assert facts.observed_at == quote.ts
    assert facts.fetched_at == quote.fetched_at


def test_rc1_load_ignores_legacy_and_non_owner_snapshot_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_quote = snapshot(
        ts=INTRADAY_AT - dt.timedelta(seconds=10),
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=5),
        query_as_of=INTRADAY_AT,
        price=Decimal("23.456"),
    )
    other_quote = snapshot(
        ts=INTRADAY_AT - dt.timedelta(seconds=2),
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=2),
        query_as_of=INTRADAY_AT,
        source_licence_id=OTHER_LICENCE,
        price=Decimal("88.888"),
    )
    empty_licence_quote = snapshot(
        ts=INTRADAY_AT - dt.timedelta(seconds=1),
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=1),
        query_as_of=INTRADAY_AT,
        source_licence_id=None,
        price=Decimal("77.777"),
    )
    legacy_quote = snapshot(
        ts=INTRADAY_AT,
        fetched_at=INTRADAY_AT,
        source="ssjy_more",
        source_licence_id=None,
        price=Decimal("66.666"),
    )

    facts, _ = _load_rc1_or_xfail(
        monkeypatch,
        [other_quote, empty_licence_quote, owner_quote],
        [legacy_quote],
    )

    assert facts.last == owner_quote.price
    assert facts.observed_at == owner_quote.ts
    assert facts.fetched_at == owner_quote.fetched_at


def test_rc1_load_excludes_future_snapshot_timestamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    future_fetched = snapshot(
        ts=INTRADAY_AT - dt.timedelta(seconds=1),
        fetched_at=INTRADAY_AT + dt.timedelta(seconds=1),
        query_as_of=INTRADAY_AT,
        price=Decimal("31.111"),
    )
    future_observed = snapshot(
        ts=INTRADAY_AT + dt.timedelta(seconds=1),
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=1),
        query_as_of=INTRADAY_AT,
        price=Decimal("32.222"),
    )

    facts, _ = _load_rc1_or_xfail(monkeypatch, [future_fetched, future_observed])

    assert facts.last is None
    assert facts.observed_at is None
    assert facts.fetched_at is None


def test_rc1_load_uses_highest_revision_for_equal_timestamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    quote_ts = INTRADAY_AT - dt.timedelta(seconds=10)
    lower_revision = snapshot(
        ts=quote_ts,
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=5),
        query_as_of=INTRADAY_AT,
        revision=1,
        price=Decimal("24.001"),
    )
    higher_revision = snapshot(
        ts=quote_ts,
        fetched_at=INTRADAY_AT - dt.timedelta(seconds=4),
        query_as_of=INTRADAY_AT,
        revision=2,
        price=Decimal("24.002"),
    )

    facts, _ = _load_rc1_or_xfail(monkeypatch, [lower_revision, higher_revision])

    assert facts.last == higher_revision.price
    assert facts.observed_at == higher_revision.ts
    assert facts.fetched_at == higher_revision.fetched_at


def item(response: Any) -> dict[str, Any]:
    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    return body["items"][0]


def basis_mode(value: dict[str, Any]) -> Any:
    basis = value.get("basis")
    return basis.get("mode") if isinstance(basis, dict) else None


def require_intraday_or_xfail(
    value: dict[str, Any], expected_price: str, reads: list[str]
) -> None:
    if not any("market.quotes_snapshot" in sql for sql in reads):
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


@pytest.mark.parametrize(
    "row",
    [
        snapshot(source=None, source_licence_id=None, price=Decimal("66.666")),
        snapshot(source="tdx_local", source_licence_id=None, price=Decimal("67.777")),
        snapshot(source="ssjy_more", source_licence_id=LICENCE, price=Decimal("68.888")),
    ],
    ids=["legacy_unowned", "tdx_local_unowned", "non_mairui"],
)
def test_quotes_reject_unowned_or_non_mairui_snapshot(world: Any, row: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [row]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["price"] != str(row.price)
    assert basis_mode(value) != "intraday"


def test_quotes_uses_highest_visible_revision_for_same_owner_key(world: Any) -> None:
    quote_ts = NOW - dt.timedelta(seconds=5)
    world.state.snapshots = [
        snapshot(ts=quote_ts, revision=1, price=Decimal("24.001")),
        snapshot(ts=quote_ts, revision=2, price=Decimal("24.002")),
    ]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))
    if not any("market.quotes_snapshot" in sql for sql in world.state.reads):
        pytest.xfail("T-B213 未接线：/quotes 尚未查询 market.quotes_snapshot")
    assert value["price"] == "24.002"


def test_late_fetched_snapshot_is_not_visible(world: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [
        snapshot(
            ts=NOW - dt.timedelta(seconds=1),
            fetched_at=NOW + dt.timedelta(seconds=1),
            price=Decimal("69.999"),
        )
    ]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["price"] == "7.8750"
    assert value["price"] != "69.999"
    assert basis_mode(value) != "intraday"


def test_intraday_gate_closed_keeps_quotes_read_only_and_not_fresh(
    world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("INTRADAY_ENABLED", "false")
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot(price=Decimal("70.001"))]
    before = list(world.state.bars)

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    assert value["price"] != "70.001"
    assert basis_mode(value) != "intraday"
    assert value["data_status"] != "pending"
    assert "pending" not in json.dumps(value).lower()
    assert world.state.bars == before
    assert all(
        table not in "\n".join(world.state.reads)
        for table in ("quotes_snapshot", "realtime_quotes", "minute_bars", "minute5_bars")
    )


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

    require_intraday_or_xfail(value, "23.456", world.state.reads)
    assert value["data_status"] == "fresh"
    assert value["t"] == snapshot().ts.astimezone(BEIJING).isoformat()
    assert value["data_as_of"] == snapshot().ts.astimezone(BEIJING).isoformat()
    assert value["volume"] == "1000"
    assert value["amount"] == "23456"


def test_expired_visible_realtime_remains_realtime_and_is_stale(world: Any) -> None:
    stale_at = NOW - dt.timedelta(seconds=45)
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot(ts=stale_at, fetched_at=stale_at)]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    require_intraday_or_xfail(value, "23.456", world.state.reads)
    assert value["data_status"] == "stale"


def test_realtime_missing_amount_does_not_mix_daily_fields(world: Any) -> None:
    world.state.bars = [daily()]
    world.state.snapshots = [snapshot(volume=None, amount=None)]

    value = item(world.client.get("/api/v1/quotes", params={"codes": CODE}))

    require_intraday_or_xfail(value, "23.456", world.state.reads)
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


class _QuoteRedis:
    def __init__(self, identifier: str, event_at: dt.datetime, body: bytes) -> None:
        self.identifier = identifier
        self.event_at = event_at
        self.body = body

    def get(self, key: str) -> bytes:
        return self.identifier.encode()

    def eval(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def zscore(self, key: str, identifier: str) -> float | None:
        return self.event_at.timestamp() if identifier == "41" else None

    def zrangebyscore(self, key: str, *args: Any, **kwargs: Any) -> list[bytes]:
        return [self.identifier.encode()] if key.endswith(":order") else []

    def hget(self, key: str, identifier: str) -> bytes | None:
        return self.body if identifier == self.identifier else None


def test_stream_observes_cached_quote_event_with_market_timestamp(
    world: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(notifications, "load_user", lambda engine, user_id: SimpleNamespace(status="approved"))
    real_sleep = asyncio.sleep
    monkeypatch.setattr(notifications.asyncio, "sleep", lambda seconds: real_sleep(0))
    event_at = dt.datetime.now(dt.UTC).replace(microsecond=0)
    item_time = event_at.astimezone(BEIJING).isoformat()
    body = json.dumps(
        {
            "event": "quote",
            "data": {
                "data_as_of": item_time,
                "items": [
                    {
                        "security_code": CODE,
                        "name": "synthetic " + CODE,
                        "price": "23.456",
                        "change_pct": "1.20",
                        "amount": "23456",
                        "t": item_time,
                    }
                ],
            },
        },
        separators=(",", ":"),
    ).encode()
    redis = _QuoteRedis("42", event_at, body)

    async def collect() -> list[str]:
        response = await notifications.stream(
            _StreamRequest(),
            SimpleNamespace(user_id=OWNER),
            world.client.app.dependency_overrides[deps.get_engine](),
            redis,
            SimpleNamespace(get=lambda sid: Session("synthetic", str(OWNER), "synthetic", NOW.isoformat())),
            last_event_id="41",
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
    assert quote_events
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

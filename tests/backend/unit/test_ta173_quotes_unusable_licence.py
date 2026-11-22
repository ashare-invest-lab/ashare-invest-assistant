"""T-A173 checklist 1/3/4 and T-G06 §5: owner cache cannot bypass licence gates."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from app.auth import deps
from app.auth.sessions import Session
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects import postgresql

from tests.backend.unit.test_quotes_empty_s3 import (
    CODE,
    LICENCE,
    NOW,
    OTHER,
    OWNER,
    Result,
    bar,
    world,  # noqa: F401 - reuse real HTTP/auth and forbidden credential/upstream hooks
)

BEIJING = ZoneInfo("Asia/Shanghai")
NAME = "synthetic " + CODE
FIELDS = ("price", "change_pct", "volume", "amount", "t", "data_as_of")


def licence(**overrides: Any) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            "id": LICENCE,
            "user_id": OWNER,
            "deleted_at": None,
            "status": "active",
            "expires_on": None,
            "paused_until": None,
            **overrides,
        }
    )


@pytest.fixture
def no_enqueue(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.core import IngestCore
    from app.ingest.scheduler import Scheduler

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("GET /quotes must not enqueue work")

    monkeypatch.setattr(IngestCore, "submit", forbidden)
    monkeypatch.setattr(Scheduler, "submit", forbidden)


@pytest.fixture
def owned_world(world: Any, no_enqueue: None) -> Any:  # noqa: F811
    """Extend the existing SQL fake with actual licence/hold rows, not an active set."""
    state = world.state
    state.licences = [licence()]
    state.holds = []
    state.bars = [bar()]
    engine = world.client.app.dependency_overrides[deps.get_engine]()
    with engine.connect() as conn:
        original_execute = conn.execute

    def execute(statement: Any) -> Result:
        sql = str(statement.compile(dialect=postgresql.dialect()))
        if "app.user_data_licence_status" not in sql:
            return original_execute(statement)
        state.reads.append(sql)
        # Use scenario facts as the fake source; SQL only routes the query.
        today = state.now.astimezone(BEIJING).date()
        eligible = [
            row.id
            for row in state.licences
            if (
                row.user_id == OWNER
                and row.deleted_at is None
                and row.status == "active"
                and not any(hold.user_id == row.user_id for hold in state.holds)
                and (row.paused_until is None or row.paused_until <= state.now)
                and (row.expires_on is None or row.expires_on >= today)
            )
        ]
        assert len(eligible) <= 1
        return Result(eligible)

    engine.connect = lambda: nullcontext(SimpleNamespace(execute=execute))
    return world


def assert_unavailable(
    response: Any,
    *,
    code: str = CODE,
    name: str = NAME,
) -> dict[str, Any]:
    assert response.status_code == 200
    assert response.status_code != 409
    body = response.json()
    assert "error" not in body
    assert "DATA_LICENCE_UNAVAILABLE" not in response.text
    assert len(body["items"]) == 1
    item = body["items"][0]
    assert item["security_code"] == code
    assert item["name"] == name and item["name"].strip()
    assert item["data_status"] == "unavailable"
    for field in FIELDS:
        assert item[field] is None, field
    assert "data_licence_unavailable" in {gap["reason"] for gap in item["gaps"]}
    return item


def assert_cache_untouched(harness: Any, retained: list[Any]) -> None:
    assert harness.state.bars == retained
    assert harness.state.bars[0].source_licence_id == LICENCE
    assert harness.state.bars[0].close == Decimal("7.8750")
    assert len(harness.state.reads) == 2
    assert all("daily_bars" not in sql for sql in harness.state.reads)


@pytest.mark.parametrize(
    "unusable", ["missing", "expired", "invalid", "held", "cooling", "deleted"]
)
def test_ta173_quotes_unusable_licence_with_owned_daily_cache_returns_unavailable(
    owned_world: Any,
    unusable: str,
) -> None:
    state = owned_world.state
    if unusable == "missing":
        state.licences = []
    elif unusable == "expired":
        state.licences[0].expires_on = NOW.astimezone(BEIJING).date() - dt.timedelta(
            days=1
        )
    elif unusable == "invalid":
        state.licences[0].status = "invalid"
    elif unusable == "held":
        state.holds = [SimpleNamespace(user_id=OWNER, paused_at=NOW)]
        assert state.licences[0].status == "active"
    elif unusable == "cooling":
        state.licences[0].paused_until = NOW + dt.timedelta(hours=1)
        assert state.licences[0].status == "active"
    elif unusable == "deleted":
        state.licences[0].deleted_at = NOW - dt.timedelta(days=1)
    retained = list(state.bars)
    assert_unavailable(owned_world.client.get("/api/v1/quotes", params={"codes": CODE}))
    assert_cache_untouched(owned_world, retained)


def test_ta173_quotes_unusable_licence_owned_cache_combined_response(
    owned_world: Any,
) -> None:
    owned_world.state.licences = []
    retained = list(owned_world.state.bars)
    # T-G06 §5: the same HTTP response must satisfy the entire combination.
    assert_unavailable(owned_world.client.get("/api/v1/quotes", params={"codes": CODE}))
    assert_cache_untouched(owned_world, retained)


@pytest.mark.parametrize("at_boundary", [False, True])
def test_ta173_quotes_active_licence_keeps_stale_close(
    owned_world: Any,
    at_boundary: bool,
) -> None:
    if at_boundary:
        owned_world.state.licences[0].expires_on = NOW.astimezone(BEIJING).date()
        owned_world.state.licences[0].paused_until = NOW
    response = owned_world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["security_code"] == CODE and item["name"] == NAME
    assert item["data_status"] == "stale" and item["gaps"] == []
    assert item["price"] == "7.8750"
    assert Decimal(item["change_pct"]) == Decimal(5)
    assert item["t"] == "2041-05-05T15:00:00+08:00"
    assert item["data_as_of"] == item["t"]
    for field in ("t", "data_as_of"):
        assert dt.datetime.fromisoformat(item[field]) < NOW
    assert sum("market.daily_bars" in sql for sql in owned_world.state.reads) == 1


def test_ta173_quotes_cannot_borrow_other_users_cached_close(owned_world: Any) -> None:
    other_licence = uuid.uuid4()
    owned_world.state.licences = [
        licence(status="invalid"),
        licence(id=other_licence, user_id=OTHER),
    ]
    owned_world.state.bars.append(
        bar(
            source_licence_id=other_licence,
            close=Decimal("9876.54"),
            trade_date=dt.date(2041, 5, 6),
            fetched_at=dt.datetime(2041, 5, 6, 9, 5, tzinfo=dt.UTC),
        )
    )
    retained = list(owned_world.state.bars)
    response = owned_world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert_unavailable(response)
    assert "9876.54" not in response.text
    assert_cache_untouched(owned_world, retained)


@pytest.fixture
def ta173_db() -> Any:
    """Only an explicitly supplied isolated TT41 PG; never start a container."""
    url = os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip(
            "TT41_DATABASE_URL 未设置：T-A173 真实旧日线验收需要显式提供的隔离 PostgreSQL"
        )
    engine = create_engine(url)
    assert engine.dialect.name == "postgresql", (
        "TT41_DATABASE_URL 必须指向隔离 PostgreSQL"
    )
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                yield conn
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.fixture
def real_db_world(ta173_db: Any, world: Any, no_enqueue: None) -> Any:  # noqa: F811
    # Open PG before world's network guard; reuse this connection across the HTTP call.
    world.client.app.dependency_overrides[deps.get_engine] = lambda: SimpleNamespace(
        connect=lambda: nullcontext(ta173_db),
    )
    return world


def test_ta173_quotes_unusable_licence_with_owned_daily_cache_on_real_db(
    ta173_db: Any,
    real_db_world: Any,
) -> None:
    from app.db.tables.licences import user_data_licences
    from app.db.tables.market import daily_bars, securities
    from app.db.tables.users import users

    conn = ta173_db
    owner, lid = uuid.uuid4(), uuid.uuid4()
    # Dedicated code: do not reuse shared 999991.SH fixtures or overwrite existing rows.
    code, name = "999173.SH", "synthetic 999173.SH"
    # Both licence and user are fabricated; no existing user or credential is read.
    conn.execute(
        users.insert().values(
            id=owner,
            username="ta173_" + owner.hex[:24],
            password_hash="synthetic-unusable-hash",
            role="user",
            status="approved",
        )
    )
    conn.execute(
        user_data_licences.insert().values(
            id=lid,
            user_id=owner,
            ciphertext=b"synthetic-not-a-certificate",
            seal_key_version=1,
            licence_hmac=uuid.uuid4().bytes,
            tier="annual",
            status="invalid",
        )
    )
    # No upsert: a collision must fail rather than overwrite any pre-existing row.
    conn.execute(
        securities.insert().values(code=code, name=name, type="stock", exchange="SH")
    )
    old_bar = vars(bar(code=code, source_licence_id=lid))
    conn.execute(daily_bars.insert().values(**old_bar))
    retained_query = select(daily_bars).where(
        daily_bars.c.code == code,
        daily_bars.c.source_licence_id == lid,
    )
    before = conn.execute(retained_query).one()._asdict()
    assert before["close"] == old_bar["close"]
    assert before["source_licence_id"] == lid
    store = real_db_world.client.app.dependency_overrides[deps.get_session_store]()
    session = Session("synthetic", str(owner), "synthetic", NOW.isoformat())
    store.get = lambda _sid: session
    reads = []

    def read_only(_conn: Any, _cursor: Any, sql: str, *_args: Any) -> None:
        assert sql.lstrip().upper().startswith("SELECT ")
        assert "daily_bars" not in sql
        assert "ciphertext" not in sql and "licence_hmac" not in sql
        reads.append(sql)

    event.listen(conn, "before_cursor_execute", read_only)
    try:
        response = real_db_world.client.get("/api/v1/quotes", params={"codes": code})
        assert_unavailable(response, code=code, name=name)
        assert len(reads) == 2
    finally:
        event.remove(conn, "before_cursor_execute", read_only)
    assert conn.execute(retained_query).one()._asdict() == before

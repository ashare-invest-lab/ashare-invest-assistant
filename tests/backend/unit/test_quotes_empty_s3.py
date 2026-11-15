"""HTTP empty/stale quotes: real route/auth, synthetic read-only database facts."""

from __future__ import annotations

import datetime as dt
import socket
import subprocess
import sys
import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.v1 import router
from app.auth import deps
from app.auth.sessions import SESSION_COOKIE, Session
from app.common.errors import install_exception_handlers

OWNER, OTHER = uuid.UUID(int=711), uuid.UUID(int=712)
CODE, ETF = "999991.SH", "999992.SH"
LICENCE = uuid.UUID(int=713)
NOW = dt.datetime(2041, 5, 6, 16, 5, tzinfo=dt.UTC)


def test_aggregates_service_import_succeeds_in_fresh_process() -> None:
    result = subprocess.run(
        [sys.executable, "-c", "from app.aggregates.service import select_account"],
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def bar(**values: Any) -> SimpleNamespace:
    return SimpleNamespace(
        **{
            "code": CODE,
            "trade_date": dt.date(2041, 5, 5),
            "adj_type": "none",
            "source": "mairui",
            "source_licence_id": LICENCE,
            "open": Decimal("7.0"),
            "high": Decimal("8.0"),
            "low": Decimal("7.0"),
            "close": Decimal("7.8750"),
            "pre_close": Decimal("7.5"),
            "volume": Decimal("123"),
            "amount": Decimal("456"),
            "is_suspended": False,
            "fetched_at": dt.datetime(2041, 5, 5, 9, 5, tzinfo=dt.UTC),
            **values,
        }
    )


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = SimpleNamespace(
        reads=[], fail=False, approved=True, active={OWNER}, revoked=[], bars=[],
        now=NOW, latest_close_date=dt.date(2041, 5, 6)
    )

    def execute(statement: Any) -> Result:
        rendered = str(statement.compile(dialect=postgresql.dialect()))
        assert rendered.lstrip().upper().startswith("SELECT "), "GET must never write"
        state.reads.append(rendered)
        if state.fail:
            raise RuntimeError("synthetic database failure")
        params = statement.compile().params
        if "market.securities" in rendered:
            assert "market.securities.type" in rendered
            requested = params["code_1"]
            return Result(
                [
                    SimpleNamespace(
                        code=code, name="synthetic " + code, type="etf" if code == ETF else "stock"
                    )
                    for code in (CODE, ETF)
                    if code in requested
                ]
            )
        if "market.daily_bars" in rendered:
            assert params["source_1"] == "mairui"
            assert params["adj_type_1"] == "none"
            assert params["source_licence_id_1"] == LICENCE
            assert params["trade_date_1"] == state.latest_close_date
            assert params["fetched_at_1"] == state.now
            for field in ("open", "high", "low", "close"):
                assert f"market.daily_bars.{field} IS NOT NULL" in rendered
            assert "market.daily_bars.is_suspended IS false" in rendered
            assert "market.daily_bars.code IN" in rendered
            for field in ("source", "adj_type", "source_licence_id"):
                assert f"market.daily_bars.{field} = " in rendered
            for field in ("trade_date", "fetched_at"):
                assert f"market.daily_bars.{field} <= " in rendered
            assert "SELECT DISTINCT ON (market.daily_bars.code)" in rendered
            assert "ORDER BY market.daily_bars.code, market.daily_bars.trade_date DESC" in rendered
            eligible = [
                row
                for row in state.bars
                if row.code in params["code_1"]
                and row.source == params["source_1"]
                and row.adj_type == params["adj_type_1"]
                and row.source_licence_id == params["source_licence_id_1"]
                and row.is_suspended is False
                and all(getattr(row, f) is not None for f in ("open", "high", "low", "close"))
                and row.trade_date <= params["trade_date_1"]
                and row.fetched_at <= params["fetched_at_1"]
            ]
            latest: dict[str, Any] = {}
            for row in sorted(eligible, key=lambda row: row.trade_date, reverse=True):
                latest.setdefault(row.code, row)
            return Result(list(latest.values()))
        assert "app.user_data_licence_status" in rendered
        assert rendered.startswith("SELECT app.user_data_licence_status.id \nFROM ")
        assert "app.user_data_licence_holds" in rendered
        assert "deleted_at IS NULL" in rendered and "paused_until" in rendered
        assert "expires_on" in rendered and "held" not in params
        return Result([LICENCE] if params["user_id_1"] in state.active else [])

    engine = SimpleNamespace(
        connect=lambda: nullcontext(SimpleNamespace(execute=execute))
    )
    sessions = {
        key: Session(
            "synthetic", str(owner), "synthetic", dt.datetime.now(dt.UTC).isoformat()
        )
        for key, owner in (("a", OWNER), ("b", OTHER))
    }
    store = SimpleNamespace(
        get=lambda sid: sessions.get(sid),
        delete=lambda session: None,
        revoke_user=state.revoked.append,
    )
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: store
    monkeypatch.setattr(
        deps,
        "load_user",
        lambda _engine, uid: SimpleNamespace(
            id=uid, status="approved" if state.approved else "pending"
        ),
    )

    def forbidden(*args: Any, **kwargs: Any) -> None:
        pytest.fail("quote GET must never send, read credentials, or connect")

    from app.ingest import daily_lists, egress
    from app.marketdata import quotes_read

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return state.now.astimezone(tz)

    monkeypatch.setattr(
        quotes_read,
        "dt",
        SimpleNamespace(datetime=Clock, time=dt.time, timedelta=dt.timedelta, UTC=dt.UTC),
    )

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    monkeypatch.setattr(daily_lists, "credential", forbidden)
    with TestClient(app) as client:
        # Windows creates its asyncio self-pipe at portal startup, before any request.
        monkeypatch.setattr(socket.socket, "connect", forbidden)
        client.cookies.set(SESSION_COOKIE, "a")
        yield SimpleNamespace(client=client, state=state)


def test_registered_quotes_has_explicit_empty_fields_and_no_made_up_time(
    world: Any,
) -> None:
    response = world.client.get("/api/v1/quotes", params={"codes": CODE + "," + ETF})
    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["security_code"] for item in items] == [CODE, ETF]
    for item in items:
        assert set(item) == {
            "security_code",
            "name",
            "price",
            "change_pct",
            "volume",
            "amount",
            "t",
            "data_status",
            "data_as_of",
            "gaps",
        }
        assert all(
            item[key] is None
            for key in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
        )
        assert item["data_status"] == "unavailable"
        assert item["gaps"][0]["reason"] == "no_source"
    assert len(world.state.reads) == 3


def test_owner_query_cannot_borrow_another_users_active_licence(world: Any) -> None:
    world.client.cookies.set(SESSION_COOKIE, "b")
    response = world.client.get(
        "/api/v1/quotes", params={"codes": CODE, "user_id": str(OWNER)}
    )
    assert response.status_code == 200
    assert (
        response.json()["items"][0]["gaps"][0]["reason"] == "data_licence_unavailable"
    )
    assert len(world.state.reads) == 2
    assert all("daily_bars" not in sql for sql in world.state.reads)


@pytest.mark.parametrize(
    "query",
    [
        "",
        "?codes=",
        "?codes=oops",
        "?codes=999991.SH,",
        "?codes=999991.SH&codes=999992.SH",
        "?codes=" + ",".join([CODE] * 201),
    ],
)
def test_bad_quotes_query_is_400_before_database_reads(world: Any, query: str) -> None:
    response = world.client.get("/api/v1/quotes" + query)
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert world.state.reads == []


def test_two_hundred_requested_codes_are_accepted_and_duplicates_deduplicated(
    world: Any,
) -> None:
    response = world.client.get(
        "/api/v1/quotes", params={"codes": ",".join([CODE] * 200)}
    )
    assert response.status_code == 200
    assert len(response.json()["items"]) == 1


def test_quote_authentication_precedes_invalid_query_and_conditional_cache(
    world: Any,
) -> None:
    world.client.cookies.clear()
    response = world.client.get(
        "/api/v1/quotes?codes=oops", headers={"If-None-Match": "*"}
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"
    assert world.state.reads == []


def test_pending_user_is_rejected_by_existing_authentication(world: Any) -> None:
    world.state.approved = False
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 403
    assert world.state.revoked == [str(OWNER)]
    assert world.state.reads == []


def test_empty_quote_etag_is_private_and_auth_still_checked(world: Any) -> None:
    first = world.client.get(
        "/api/v1/quotes", params={"codes": CODE + "," + CODE.lower()}
    )
    assert first.status_code == 200 and len(first.json()["items"]) == 1
    assert first.headers["cache-control"].startswith("private")
    tag = first.headers["etag"]
    cached = world.client.get(
        "/api/v1/quotes", params={"codes": CODE}, headers={"If-None-Match": tag}
    )
    assert cached.status_code == 304 and cached.content == b""
    world.client.cookies.set(SESSION_COOKIE, "b")
    changed = world.client.get(
        "/api/v1/quotes", params={"codes": CODE}, headers={"If-None-Match": tag}
    )
    assert changed.status_code == 200


def test_unknown_security_is_404_without_creating_a_quote_or_querying_licence(
    world: Any,
) -> None:
    response = world.client.get("/api/v1/quotes", params={"codes": "999999.SH"})
    assert response.status_code == 404
    assert len(world.state.reads) == 1


def test_sql_failures_are_not_hidden_as_successful_empty_quotes(world: Any) -> None:
    world.state.fail = True
    with pytest.raises(RuntimeError, match="synthetic database failure"):
        world.client.get("/api/v1/quotes", params={"codes": CODE})


def test_bound_daily_close_is_stale_with_real_timestamps_and_stable_etag(world: Any) -> None:
    world.state.bars = [bar()]
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["data_status"] == "stale" and item["gaps"] == []
    assert item["price"] == "7.8750" and Decimal(item["change_pct"]) == Decimal("5")
    assert item["t"] == "2041-05-05T15:00:00+08:00"
    assert item["data_as_of"] == "2041-05-05T17:05:00+08:00"
    for field in ("t", "data_as_of"):
        assert dt.datetime.fromisoformat(item[field]) < NOW
    assert item["volume"] is None and item["amount"] is None
    cached = world.client.get(
        "/api/v1/quotes", params={"codes": CODE}, headers={"If-None-Match": response.headers["etag"]}
    )
    assert cached.status_code == 304


@pytest.mark.parametrize("pre_close", [None, Decimal("0"), Decimal("-1")])
def test_missing_or_nonpositive_pre_close_has_no_change_pct(world: Any, pre_close: Any) -> None:
    world.state.bars = [bar(pre_close=pre_close)]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "stale" and item["change_pct"] is None


def test_only_latest_eligible_bound_mairui_bar_is_used(world: Any) -> None:
    newer = {"trade_date": dt.date(2041, 5, 6), "close": Decimal("999")}
    world.state.bars = [
        bar(),
        bar(trade_date=dt.date(2041, 5, 4), close=Decimal("1")),
        bar(**newer, source="tdx_local"),
        bar(**newer, source="fake"),
        bar(**newer, source_licence_id=uuid.UUID(int=714)),
        bar(**newer, source_licence_id=None),
        bar(**newer, adj_type="qfq"),
        bar(trade_date=dt.date(2041, 5, 8)),
        bar(**newer, fetched_at=NOW + dt.timedelta(seconds=1)),
    ]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["price"] == "7.8750"
    assert item["t"] == "2041-05-05T15:00:00+08:00"
    assert len(world.state.reads) == 3


@pytest.mark.parametrize(
    "invalid",
    [
        {"close": None},
        {"is_suspended": True},
        {"is_suspended": None},
        {"open": None},
        {"high": None},
        {"low": None},
    ],
)
def test_incomplete_latest_bar_falls_back_or_reports_no_source(world: Any, invalid: Any) -> None:
    world.state.bars = [bar(trade_date=dt.date(2041, 5, 6), **invalid), bar()]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "stale" and item["price"] == "7.8750"
    world.state.bars.pop()
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "unavailable"
    assert item["gaps"][0]["reason"] == "no_source"
    assert item["gaps"][0]["message"] == "本人行情缓存尚无可用读取源"
    assert all(
        item[key] is None
        for key in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
    )


def test_no_active_licence_skips_even_existing_daily_bars(world: Any) -> None:
    world.state.active = set()
    world.state.bars = [bar()]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "unavailable" and item["price"] is None
    assert item["gaps"][0]["reason"] == "data_licence_unavailable"
    assert len(world.state.reads) == 2
    assert all("daily_bars" not in sql for sql in world.state.reads)


@pytest.mark.parametrize("with_etf_bar", [False, True])
def test_mixed_codes_keep_deduplicated_request_order_with_one_daily_select(
    world: Any, with_etf_bar: bool
) -> None:
    world.state.bars = [bar(), bar(code=ETF)] if with_etf_bar else [bar()]
    response = world.client.get("/api/v1/quotes", params={"codes": f"{ETF},{CODE},{ETF}"})
    items = response.json()["items"]
    assert [item["security_code"] for item in items] == [ETF, CODE]
    assert [item["data_status"] for item in items] == [
        "stale" if with_etf_bar else "unavailable", "stale"
    ]
    if not with_etf_bar:
        assert items[0]["gaps"][0]["reason"] == "no_source"
    else:
        assert items[0]["price"] == "7.875"
        assert Decimal(items[0]["change_pct"]) == Decimal(5)
    assert items[1]["price"] == "7.8750"
    assert sum("market.daily_bars" in sql for sql in world.state.reads) == 1
    assert len(world.state.reads) == 3


@pytest.mark.parametrize(
    "close,price", [("7.8750", "7.875"), ("7.8", "7.800"), ("7.8754", "7.875")]
)
def test_etf_price_has_three_decimals_but_change_uses_original_close(
    world: Any, close: str, price: str
) -> None:
    world.state.bars = [bar(code=ETF, close=Decimal(close))]
    item = world.client.get("/api/v1/quotes", params={"codes": ETF}).json()["items"][0]
    assert item["price"] == price
    assert Decimal(item["change_pct"]) == (Decimal(close) - Decimal("7.5")) / Decimal("7.5") * 100


@pytest.mark.parametrize("hour,minute,second", [(1, 31, 0), (6, 59, 59)])
def test_intraday_complete_bar_falls_back_to_closed_day(
    world: Any, hour: int, minute: int, second: int
) -> None:
    world.state.now = dt.datetime(2041, 5, 7, hour, minute, second, tzinfo=dt.UTC)
    # Historical backfills may be fetched before 15:00 on any day.
    historical = bar(
        trade_date=dt.date(2041, 5, 6),
        fetched_at=dt.datetime(2041, 5, 7, 1, 0, tzinfo=dt.UTC),
    )
    world.state.bars = [
        bar(trade_date=dt.date(2041, 5, 7), fetched_at=world.state.now),
        historical,
    ]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "stale"
    assert item["t"] == "2041-05-06T15:00:00+08:00"
    assert dt.datetime.fromisoformat(item["t"]) <= world.state.now
    world.state.bars.remove(historical)
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "unavailable"
    assert item["gaps"][0]["reason"] == "no_source"
    assert item["price"] is None and item["t"] is None


@pytest.mark.parametrize("minute", [0, 1])
def test_today_close_is_eligible_at_or_after_beijing_1500(world: Any, minute: int) -> None:
    world.state.now = dt.datetime(2041, 5, 7, 7, minute, tzinfo=dt.UTC)
    world.state.latest_close_date = dt.date(2041, 5, 7)
    world.state.bars = [
        bar(),
        bar(
            trade_date=dt.date(2041, 5, 7),
            close=Decimal("8.1250"),
            fetched_at=dt.datetime(2041, 5, 7, 1, 0, tzinfo=dt.UTC),
        ),
    ]
    item = world.client.get("/api/v1/quotes", params={"codes": CODE}).json()["items"][0]
    assert item["data_status"] == "stale" and item["price"] == "8.1250"
    assert item["t"] == "2041-05-07T15:00:00+08:00"
    assert dt.datetime.fromisoformat(item["t"]) <= world.state.now

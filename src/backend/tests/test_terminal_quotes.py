"""Terminal quote aggregation with synthetic connection facts and no external IO."""

# ruff: noqa: S101
from __future__ import annotations

import datetime as dt
import socket
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import Connection, Select

from app.aggregates import models, products, service
from app.marketdata import daily_snapshot, quotes_read
from app.schemas.enums import DataStatus, MarketSession

OWNER = uuid.UUID(int=167)
CODE, SECOND, UNKNOWN = "999991.SH", "999992.SH", "999993.SH"
NOW = dt.datetime(2026, 11, 15, 9, tzinfo=dt.UTC)
FETCHED_AT = dt.datetime(2026, 11, 13, 9, 5, tzinfo=dt.UTC)
CLOCK = models.MarketClock(trade_date=NOW.date(), session=MarketSession.NON_TRADING_DAY)


@dataclass
class World:
    conn: MagicMock
    reader: Mock
    watched: list[str] = field(default_factory=lambda: [CODE, SECOND])
    master: set[str] = field(default_factory=lambda: {CODE, SECOND})
    closes: dict[str, SimpleNamespace] = field(default_factory=dict)

    def terminal(self) -> models.Terminal:
        return service.terminal(self.conn, OWNER, None, CLOCK, NOW, "watchlist")


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    forbidden = Mock(side_effect=AssertionError("External connections are forbidden"))
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    conn = MagicMock(spec=Connection)
    reader = Mock(wraps=quotes_read.read_quotes)
    state = World(conn=conn, reader=reader)
    state.closes[CODE] = SimpleNamespace(
        code=CODE,
        close=Decimal("7.8750"),
        pre_close=None,
        trade_date=dt.date(2026, 11, 13),
        fetched_at=FETCHED_AT,
    )

    def execute(statement: Select[tuple[object, ...]]) -> MagicMock:
        result = MagicMock()
        table = statement.get_final_froms()[0].fullname
        if table == "app.watchlist_items":
            result.all.return_value = [
                SimpleNamespace(security_code=code) for code in state.watched
            ]
        elif table == "app.user_realtime_prefs":
            result.scalar_one_or_none.return_value = None
        elif table == "market.securities":
            requested = statement.compile().params["code_1"]
            rows = [
                SimpleNamespace(code=code, name="合成 " + code, type="stock")
                for code in sorted(state.master)
                if code in requested
            ]
            result.all.return_value = rows
            result.__iter__.side_effect = lambda: iter(rows)
        elif table == "app.notifications":
            result.scalar_one.return_value = 0
        else:
            raise AssertionError(f"Unexpected database read: {table}")
        return result

    conn.execute.side_effect = execute
    monkeypatch.setattr(products, "owned_suggestions", Mock(return_value={}))
    monkeypatch.setattr(products, "reasons", Mock(return_value=[]))
    monkeypatch.setattr(daily_snapshot, "active_licence_id", Mock(return_value=uuid.UUID(int=168)))
    monkeypatch.setattr(quotes_read, "_daily_closes", Mock(return_value=state.closes))
    monkeypatch.setattr(quotes_read, "read_quotes", reader)
    return state


@pytest.mark.parametrize("pre_close", [None, Decimal("7.5")])
def test_watchlist_reads_one_batch_and_preserves_stale_close(
    world: World, pre_close: Decimal | None
) -> None:
    world.closes[CODE].pre_close = pre_close

    terminal = world.terminal()

    world.reader.assert_called_once_with(world.conn, OWNER, (CODE, SECOND))
    row = next(row for row in terminal.rows if row.security_code == CODE)
    assert row.in_watchlist
    assert row.quote is not None
    assert row.quote.price == "7.8750"
    assert row.quote.t == dt.datetime(2026, 11, 13, 7, tzinfo=dt.UTC)
    assert row.data_status is DataStatus.STALE
    assert row.data_as_of == FETCHED_AT
    payload = row.model_dump(mode="json")
    assert payload["quote"]["amount"] is None
    if pre_close is None:
        assert payload["quote"]["change_pct"] is None
    else:
        assert Decimal(payload["quote"]["change_pct"]) == Decimal(5)
    unavailable = next(row for row in terminal.rows if row.security_code == SECOND)
    assert unavailable.quote is None
    assert unavailable.data_status is DataStatus.UNAVAILABLE
    assert unavailable.data_as_of is None


def test_unknown_security_is_excluded_from_quote_batch(world: World) -> None:
    world.watched.append(UNKNOWN)

    terminal = world.terminal()

    world.reader.assert_called_once_with(world.conn, OWNER, (CODE, SECOND))
    row = next(row for row in terminal.rows if row.security_code == UNKNOWN)
    assert row.quote is None
    assert row.name == UNKNOWN
    assert row.data_status is DataStatus.UNAVAILABLE
    assert row.data_as_of is None
    assert next(row for row in terminal.rows if row.security_code == CODE).quote is not None


@pytest.mark.parametrize("watched", [[], [UNKNOWN]])
def test_empty_master_skips_quote_read(world: World, watched: list[str]) -> None:
    world.watched = watched

    terminal = world.terminal()

    world.reader.assert_not_called()
    assert [row.security_code for row in terminal.rows] == watched
    assert all(row.quote is None for row in terminal.rows)
    assert all(row.data_status is DataStatus.UNAVAILABLE for row in terminal.rows)


@pytest.mark.parametrize("status", [DataStatus.STALE, DataStatus.UNAVAILABLE])
def test_row_preserves_quote_item_status_and_as_of(world: World, status: DataStatus) -> None:
    world.reader.side_effect = None
    world.reader.return_value = quotes_read.QuotesResponse(
        items=[
            quotes_read.QuoteItem(
                security_code=CODE,
                name="合成",
                price="8.25" if status is DataStatus.STALE else None,
                change_pct="1.25",
                amount="123.45",
                t=FETCHED_AT.isoformat(),
                data_status=status,
                data_as_of=FETCHED_AT.isoformat(),
                gaps=[],
            )
        ]
    )

    row = next(row for row in world.terminal().rows if row.security_code == CODE)

    assert row.data_status is status
    assert row.data_as_of == FETCHED_AT
    if status is DataStatus.STALE:
        assert row.quote is not None
        assert row.quote.price == "8.25"
        assert row.quote.change_pct == "1.25"
        assert row.quote.amount == "123.45"
        assert row.quote.t == FETCHED_AT
    else:
        assert row.quote is None

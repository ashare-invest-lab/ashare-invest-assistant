"""T-B213b realtime-first quote reads use synthetic rows only."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.config import get_settings
from app.marketdata import daily_snapshot, quotes_read
from sqlalchemy.dialects import postgresql

OWNER = uuid.UUID(int=2131)
CODE = "999213.SH"
NOW = dt.datetime(2026, 11, 21, 7, 0, tzinfo=dt.UTC)
SETTINGS = SimpleNamespace(
    app_env="test",
    realtime_quotes_source="fake",
    business=get_settings().business,
)
THRESHOLD = SETTINGS.business.realtime.intervals.effective_stale_threshold_s


def _identity() -> SimpleNamespace:
    return SimpleNamespace(code=CODE, name="合成行情", type="stock")


def _realtime(stamp: dt.datetime, **values: object) -> SimpleNamespace:
    values = {
        "realtime_price": Decimal("10.125"),
        "realtime_pct_change": Decimal("1.25"),
        "realtime_volume": Decimal(100),
        "realtime_amount": Decimal("1012.5"),
        **values,
    }
    return SimpleNamespace(
        code=CODE,
        realtime_ts=stamp,
        **values,
    )


def _daily(
    trade_date: dt.date = dt.date(2026, 11, 20),
    fetched_at: dt.datetime = dt.datetime(2026, 11, 20, 9, 0, tzinfo=dt.UTC),
) -> SimpleNamespace:
    return SimpleNamespace(
        code=CODE,
        close=Decimal("9.875"),
        pre_close=Decimal(10),
        trade_date=trade_date,
        fetched_at=fetched_at,
        volume=Decimal(90),
        amount=Decimal("888.75"),
    )


def _read(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[object],
    licence: uuid.UUID | None = OWNER,
    settings: object = SETTINGS,
    realtime_calls: list[None] | None = None,
) -> object:
    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return NOW.astimezone(tz)

    monkeypatch.setattr(
        quotes_read,
        "dt",
        SimpleNamespace(
            datetime=Clock, time=dt.time, timedelta=dt.timedelta, UTC=dt.UTC
        ),
    )
    monkeypatch.setattr(daily_snapshot, "active_licence_id", lambda *_: licence)
    monkeypatch.setattr(
        quotes_read,
        "_daily_closes",
        lambda *_: {
            row.code: row
            for row in rows
            if getattr(row, "trade_date", None) is not None
        },
    )
    monkeypatch.setattr(
        quotes_read,
        "_realtime_latest",
        lambda *_: (
            (realtime_calls.append(None) if realtime_calls is not None else None)
            or {
                row.code: row
                for row in rows
                if getattr(row, "realtime_ts", None) is not None
            }
        ),
    )
    conn = MagicMock()
    conn.execute.return_value.all.return_value = [_identity()]
    return quotes_read.read_quotes(conn, OWNER, (CODE,), settings).items[0]


def test_fresh_and_stale_realtime_use_snapshot_ts_and_configured_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh = _read(
        monkeypatch,
        [
            _realtime(
                NOW - dt.timedelta(seconds=THRESHOLD),
                fetched_at=NOW - dt.timedelta(days=1),
            )
        ],
    )
    assert fresh.data_status == "fresh"
    assert fresh.price == "10.125"
    assert (
        fresh.t
        == (NOW - dt.timedelta(seconds=THRESHOLD))
        .astimezone(quotes_read.BEIJING)
        .isoformat()
    )
    assert fresh.data_as_of == fresh.t
    assert fresh.gaps == []

    stale = _read(monkeypatch, [_realtime(NOW - dt.timedelta(seconds=THRESHOLD + 1))])
    assert stale.data_status == "stale"
    assert stale.price == "10.125"


def test_missing_realtime_falls_back_to_existing_daily_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(monkeypatch, [_daily()])
    assert item.data_status == "stale"
    assert item.price == "9.875"
    assert item.t == "2026-11-20T15:00:00+08:00"
    assert item.data_as_of == item.t
    assert item.gaps == []


def test_yesterday_realtime_does_not_override_today_daily_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(
        monkeypatch,
        [
            _realtime(NOW - dt.timedelta(days=1)),
            _daily(trade_date=dt.date(2026, 11, 21), fetched_at=NOW),
        ],
    )
    assert item.price == "9.875"
    assert item.t == "2026-11-21T15:00:00+08:00"


def test_today_realtime_overrides_yesterday_daily_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(
        monkeypatch,
        [
            _realtime(NOW - dt.timedelta(minutes=1)),
            _daily(),
        ],
    )
    assert item.price == "10.125"
    assert (
        item.t
        == (NOW - dt.timedelta(minutes=1)).astimezone(quotes_read.BEIJING).isoformat()
    )


def test_stale_realtime_remains_selected_when_daily_is_older(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(
        monkeypatch,
        [
            _realtime(NOW - dt.timedelta(seconds=THRESHOLD + 1)),
            _daily(),
        ],
    )
    assert item.data_status == "stale"
    assert item.price == "10.125"


def test_unusable_licence_never_returns_realtime_or_daily_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(monkeypatch, [_realtime(NOW), _daily()], licence=None)
    assert item.data_status == "unavailable"
    assert all(
        getattr(item, field) is None
        for field in ("price", "change_pct", "volume", "amount", "t", "data_as_of")
    )
    assert item.gaps[0].reason == "data_licence_unavailable"


def test_realtime_off_keeps_daily_read_and_skips_snapshot_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    realtime_calls: list[None] = []
    off = SimpleNamespace(realtime_quotes_source="off")
    monkeypatch.setattr(quotes_read, "get_settings", lambda: off)
    item = _read(
        monkeypatch,
        [_realtime(NOW), _daily()],
        settings=None,
        realtime_calls=realtime_calls,
    )
    assert item.price == "9.875"
    assert item.data_status == "stale"
    assert realtime_calls == []


def test_null_realtime_fields_are_preserved_and_no_basis_field_is_invented(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    item = _read(
        monkeypatch,
        [
            _realtime(
                NOW,
                realtime_pct_change=None,
                realtime_volume=None,
                realtime_amount=None,
            )
        ],
    )
    assert item.change_pct is None
    assert item.volume is None
    assert item.amount is None
    assert "basis" not in item.model_dump()
    assert "source" not in item.model_dump()


def test_other_licence_row_is_not_used_by_owner_scope() -> None:
    seen: list[dict[str, object]] = []

    class Result:
        def all(self) -> list[object]:
            return []

    class Connection:
        def execute(self, statement: object) -> Result:
            compiled = statement.compile(dialect=postgresql.dialect())
            seen.append(compiled.params)
            return Result()

    quotes_read._daily_closes(Connection(), (CODE,), OWNER, NOW)
    quotes_read._realtime_latest(Connection(), (CODE,), OWNER, NOW)
    assert len(seen) == 2
    assert all(sum(value == OWNER for value in params.values()) == 1 for params in seen)

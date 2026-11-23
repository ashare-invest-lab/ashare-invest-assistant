"""B1r realtime-first reads use synthetic owner-scoped snapshot rows."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest
from app.marketdata import quotes_read
from app.schemas.enums import DataStatus, SecurityType

OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
CODE = "990000.SH"


class _IdentityConnection:
    def execute(self, _statement: object) -> SimpleNamespace:
        return SimpleNamespace(
            all=lambda: [
                SimpleNamespace(code=CODE, name="Synthetic 990000", type=SecurityType.STOCK)
            ]
        )


def _snapshot(*, fetched_at: dt.datetime) -> SimpleNamespace:
    return SimpleNamespace(
        code=CODE,
        batch_id=uuid.UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1"),
        revision=0,
        ts=fetched_at - dt.timedelta(seconds=1),
        fetched_at=fetched_at,
        price=Decimal("12.34"),
        pct_change=Decimal("1.25"),
        volume=Decimal(100),
        amount=Decimal(1234),
    )


def _daily() -> SimpleNamespace:
    return SimpleNamespace(
        code=CODE,
        close=Decimal("11.00"),
        pre_close=Decimal("10.00"),
        trade_date=dt.date(2030, 6, 10),
        fetched_at=dt.datetime(2030, 6, 10, 9, 10, tzinfo=dt.UTC),
        volume=Decimal(80),
        amount=Decimal(880),
    )


def _patch_owner_licence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.marketdata.daily_snapshot.active_licence_id",
        lambda *_args: LICENCE,
    )


def test_fresh_realtime_snapshot_is_preferred(monkeypatch: pytest.MonkeyPatch) -> None:
    now = dt.datetime.now(dt.UTC)
    _patch_owner_licence(monkeypatch)
    monkeypatch.setattr(
        quotes_read,
        "_realtime_snapshots",
        lambda *_args: {CODE: _snapshot(fetched_at=now - dt.timedelta(seconds=1))},
    )
    monkeypatch.setattr(quotes_read, "_daily_closes", lambda *_args: {CODE: _daily()})
    monkeypatch.setattr(quotes_read, "_fresh_close_day", lambda *_args: None)

    result = quotes_read.read_quotes(_IdentityConnection(), OWNER, (CODE,))

    assert result.items[0].price == "12.34"
    assert result.items[0].data_status == DataStatus.FRESH
    assert result.items[0].data_as_of is not None


def test_stale_realtime_snapshot_is_returned_as_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    now = dt.datetime.now(dt.UTC)
    _patch_owner_licence(monkeypatch)
    monkeypatch.setattr(
        quotes_read,
        "_realtime_snapshots",
        lambda *_args: {CODE: _snapshot(fetched_at=now - dt.timedelta(seconds=90))},
    )
    monkeypatch.setattr(quotes_read, "_daily_closes", lambda *_args: {})

    result = quotes_read.read_quotes(_IdentityConnection(), OWNER, (CODE,))

    assert result.items[0].price == "12.34"
    assert result.items[0].data_status == DataStatus.STALE


def test_missing_realtime_snapshot_falls_back_to_daily_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_owner_licence(monkeypatch)
    monkeypatch.setattr(quotes_read, "_realtime_snapshots", lambda *_args: {})
    monkeypatch.setattr(quotes_read, "_daily_closes", lambda *_args: {CODE: _daily()})
    monkeypatch.setattr(quotes_read, "_fresh_close_day", lambda *_args: dt.date(2030, 6, 10))

    result = quotes_read.read_quotes(_IdentityConnection(), OWNER, (CODE,))

    assert result.items[0].price == "11.00"
    assert result.items[0].data_status == DataStatus.FRESH
    assert result.items[0].volume == "80"

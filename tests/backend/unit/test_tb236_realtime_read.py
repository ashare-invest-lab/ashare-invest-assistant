"""T-B236 synthetic lunch-break realtime freshness cases."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.marketdata import quotes_read
from app.schemas.enums import SecurityType

DAY = dt.date(2026, 11, 13)
THRESHOLD = 30


def _connection(*calendar_values: object) -> MagicMock:
    conn = MagicMock()
    conn.execute.return_value.scalar_one_or_none.side_effect = list(calendar_values)
    return conn


def _row(stamp: dt.datetime) -> SimpleNamespace:
    return SimpleNamespace(
        code="600236.SH",
        realtime_ts=stamp,
        realtime_price=8.1250,
        realtime_pct_change=0,
        realtime_volume=1,
        realtime_amount=1,
    )


def test_lunch_reference_is_morning_end_and_snapshot_within_threshold_is_fresh() -> None:
    now = dt.datetime.combine(DAY, dt.time(12), quotes_read.BEIJING)
    reference, in_session = quotes_read._reference_time(_connection(True), now)

    assert reference == dt.datetime.combine(DAY, dt.time(11, 30), quotes_read.BEIJING)
    assert not in_session

    item = quotes_read._realtime_item(
        _row(dt.datetime.combine(DAY, dt.time(11, 29, 55), quotes_read.BEIJING)),
        "合成证券",
        SecurityType.STOCK,
        now,
        THRESHOLD,
        reference,
    )

    assert item.data_status == "fresh"


def test_lunch_snapshot_older_than_threshold_is_stale() -> None:
    now = dt.datetime.combine(DAY, dt.time(12), quotes_read.BEIJING)
    reference, _ = quotes_read._reference_time(_connection(True), now)

    item = quotes_read._realtime_item(
        _row(dt.datetime.combine(DAY, dt.time(11, 29), quotes_read.BEIJING)),
        "合成证券",
        SecurityType.STOCK,
        now,
        THRESHOLD,
        reference,
    )

    assert item.data_status == "stale"

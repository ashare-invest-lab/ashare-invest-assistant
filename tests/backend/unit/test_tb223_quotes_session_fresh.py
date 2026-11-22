"""T-B223 synthetic session-reference freshness cases."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from app.marketdata import quotes_read

DAY = dt.date(2030, 6, 10)
PREVIOUS = dt.date(2030, 6, 7)
BEIJING = quotes_read.BEIJING
THRESHOLD = 30


def _conn(*calendar_values: object) -> MagicMock:
    conn = MagicMock()
    if calendar_values:
        conn.execute.return_value.scalar_one_or_none.side_effect = list(calendar_values)
    else:
        conn.execute.return_value.scalar_one_or_none.return_value = None
    return conn


def _row(stamp: dt.datetime) -> SimpleNamespace:
    return SimpleNamespace(
        code="600000.SH",
        realtime_ts=stamp,
        realtime_price=1,
        realtime_pct_change=0,
        realtime_volume=1,
        realtime_amount=1,
    )


@pytest.mark.parametrize(
    ("label", "now", "stamp", "calendar", "expected"),
    [
        ("morning fresh", "10:00:00", "09:59:50", (True,), "fresh"),
        ("morning stale", "10:00:00", "09:59:00", (True,), "stale"),
        ("lunch uses morning close", "11:30:00", "11:29:55", (True,), "fresh"),
        ("before lunch close fresh", "11:29:55", "11:29:50", (True,), "fresh"),
        ("after close uses close", "16:00:00", "14:59:55", (True,), "fresh"),
        ("closing time uses today's close", "15:00:00", "14:59:55", (True,), "fresh"),
        (
            "pre-open uses previous close",
            "09:00:00",
            "2030-06-07T14:59:50",
            (True, PREVIOUS),
            "fresh",
        ),
        (
            "closed day uses previous close",
            "10:00:00",
            "2030-06-07T14:59:50",
            (False, PREVIOUS),
            "fresh",
        ),
        (
            "closed day old snapshot",
            "10:00:00",
            "2030-06-07T14:59:00",
            (False, PREVIOUS),
            "stale",
        ),
        ("missing calendar remains conservative", "12:00:00", "11:59:00", (), "stale"),
    ],
    ids=lambda value: value if isinstance(value, str) else None,
)
def test_realtime_status_uses_session_reference(
    label: str,
    now: str,
    stamp: str,
    calendar: tuple[object, ...],
    expected: str,
) -> None:
    local_now = dt.datetime.combine(DAY, dt.time.fromisoformat(now), BEIJING)
    local_stamp = (
        dt.datetime.fromisoformat(stamp).replace(tzinfo=BEIJING)
        if "T" in stamp
        else dt.datetime.combine(DAY, dt.time.fromisoformat(stamp), BEIJING)
    )
    reference, _ = quotes_read._reference_time(_conn(*calendar), local_now)
    item = quotes_read._realtime_item(
        _row(local_stamp), "合成证券", "stock", local_now, THRESHOLD, reference
    )
    assert item.data_status == expected


@pytest.mark.parametrize(
    ("local_time", "open_today"), [("09:00:00", True), ("10:00:00", False)]
)
def test_previous_close_day_is_fresh_before_or_on_closed_day(
    local_time: str, open_today: bool
) -> None:
    now = dt.datetime.combine(DAY, dt.time.fromisoformat(local_time), BEIJING)
    conn = _conn(open_today, PREVIOUS)
    reference, in_session = quotes_read._reference_time(conn, now)
    assert not in_session
    assert reference.astimezone(BEIJING).date() == PREVIOUS


def test_open_day_intraday_has_no_fresh_close_day() -> None:
    now = dt.datetime.combine(DAY, dt.time(10), BEIJING)
    reference, in_session = quotes_read._reference_time(_conn(True), now)
    assert in_session
    assert reference == now

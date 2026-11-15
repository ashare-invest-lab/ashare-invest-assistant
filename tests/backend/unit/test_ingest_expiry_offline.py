"""Synthetic licence-expiry reminder selection; no external resources."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from collections.abc import Iterable

import pytest
from app.ingest.expiry import reminder_key, reminders_due

TODAY = dt.date(2026, 11, 14)
DAYS = (30, 7, 1)
LICENCE_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("expiry reminder selection attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


@pytest.mark.parametrize(
    ("expires_on", "already_sent", "expected"),
    [
        (None, (), []),
        (TODAY - dt.timedelta(days=1), (), []),
        (TODAY + dt.timedelta(days=31), (), []),
        (TODAY + dt.timedelta(days=30), (), [30]),
        (TODAY + dt.timedelta(days=7), (), [7]),
        (TODAY + dt.timedelta(days=1), (), [1]),
        (TODAY, (), [1]),
        (TODAY + dt.timedelta(days=5), (), [7]),
        (TODAY + dt.timedelta(days=5), (7,), [30]),
        (TODAY, (30, 7, 1), []),
    ],
)
def test_reminders_due_selects_only_nearest_outstanding_tier(
    expires_on: dt.date | None,
    already_sent: Iterable[int],
    expected: list[int],
) -> None:
    assert reminders_due(expires_on, TODAY, DAYS, already_sent) == expected


def test_reminders_due_accepts_one_shot_sent_iterable() -> None:
    sent = (day for day in (30, 7))
    assert reminders_due(TODAY + dt.timedelta(days=5), TODAY, DAYS, sent) == []


def test_reminders_due_uses_tier_value_not_input_order() -> None:
    assert reminders_due(TODAY, TODAY, (30, 1, 7)) == [1]


def test_reminder_key_is_stable_and_scoped_to_date_and_tier() -> None:
    expires_on = TODAY + dt.timedelta(days=30)
    key = reminder_key(LICENCE_ID, expires_on, 30)
    assert key == (f"data_licence:expiry:{LICENCE_ID}:2026-12-14:30")
    assert reminder_key(LICENCE_ID, expires_on, 30) == key
    assert reminder_key(LICENCE_ID, expires_on, 7) != key
    assert reminder_key(LICENCE_ID, expires_on + dt.timedelta(days=1), 30) != key

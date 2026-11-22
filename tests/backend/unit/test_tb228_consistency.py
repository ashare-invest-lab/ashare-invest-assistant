from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from app.aggregates import models as aggregate_models
from app.aggregates.market_overview import _dedupe_gaps
from app.api.v1.notifications import _bj_iso as notification_iso
from app.api.v1.restrictions import _bj_iso as restriction_iso, _row_out
from app.reviews.service import _bj_iso as review_iso
from app.schemas.enums import GapReason

pytestmark = pytest.mark.unit


def test_market_gaps_keep_first_message_and_order() -> None:
    gaps = [
        aggregate_models.Gap(key="market.breadth", reason=GapReason.NO_SOURCE, message="first"),
        aggregate_models.Gap(key="market.indices", reason=GapReason.NO_SOURCE, message="index"),
        aggregate_models.Gap(key="market.breadth", reason=GapReason.NO_SOURCE, message="second"),
    ]
    result = _dedupe_gaps(gaps)
    assert [(gap.key, gap.message) for gap in result] == [
        ("market.breadth", "first"),
        ("market.indices", "index"),
    ]


def test_review_restriction_and_heartbeat_times_use_beijing_offset() -> None:
    stamp = dt.datetime(2026, 11, 21, 13, 0, tzinfo=dt.UTC)
    expected = "2026-11-21T21:00:00+08:00"
    assert review_iso(stamp) == expected
    assert review_iso(dt.datetime(2026, 11, 21, 13, 0)) == expected
    assert restriction_iso(stamp) == expected
    assert notification_iso(stamp) == expected


def test_restriction_row_out_keeps_null_until() -> None:
    row = SimpleNamespace(
        id="id",
        kind="cooling_off",
        target_type="security",
        target_id="600000.SH",
        until=None,
        reason=None,
        created_at=dt.datetime(2026, 11, 21, 13, 0, tzinfo=dt.UTC),
    )
    result = _row_out(row)
    assert result["until"] is None
    assert result["created_at"] == "2026-11-21T21:00:00+08:00"

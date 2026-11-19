"""S7-04: deterministic offline coverage for the named-session return path."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml
from app.aggregates.calendar import market_clock
from app.config_files import MarketRulesConfig
from app.schemas.enums import MarketSession

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[3]


def test_market_clock_returns_morning_at_fixed_open_day_time() -> None:
    """A fixed 10:00 call must execute calendar.py:78 without a wall clock or DB."""
    rules = MarketRulesConfig.model_validate(
        yaml.safe_load((ROOT / "config/market_rules.yaml").read_text(encoding="utf-8"))
    )
    day = dt.date(2026, 11, 13)
    conn = MagicMock()
    conn.execute.side_effect = [
        SimpleNamespace(one=lambda: (day, day)),
        SimpleNamespace(first=lambda: SimpleNamespace(is_open=True)),
    ]

    result = market_clock(
        conn, dt.datetime.fromisoformat("2026-11-13T10:00:00+08:00"), rules
    )

    assert result.trade_date == day
    assert result.session is MarketSession.MORNING
    assert conn.execute.call_count == 2

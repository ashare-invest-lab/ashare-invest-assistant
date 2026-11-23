"""Offline coverage for the portfolio stale-price status branch."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.api.v1 import portfolio


def test_build_portfolio_marks_old_price_stale(monkeypatch) -> None:
    account_id = uuid.uuid4()
    old_price_at = dt.datetime(2026, 1, 2, 15, tzinfo=portfolio.BEIJING)
    position = SimpleNamespace(
        qty=Decimal(1),
        cost_total=Decimal(9),
        sellable=Decimal(1),
        cost_known=True,
        price=Decimal(10),
        price_at=old_price_at,
    )
    account = SimpleNamespace(
        positions={"600000.SH": position},
        cash=Decimal(100),
        gaps=[],
    )
    conn = MagicMock()
    conn.execute.return_value.all.return_value = [
        ("600000.SH", "Synthetic", "stock")
    ]

    monkeypatch.setattr(portfolio, "_account", lambda *_args: account)
    monkeypatch.setattr(portfolio, "latest_daily_close", lambda *_args: {})
    monkeypatch.setattr(
        portfolio,
        "latest_close_at",
        lambda *_args: old_price_at + dt.timedelta(days=1),
    )

    result = portfolio.build_portfolio(conn, [account_id])

    assert result["data_status"] == portfolio.DataStatus.STALE.value

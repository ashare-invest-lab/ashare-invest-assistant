"""T-B229 daily quote projection semantics."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.marketdata import daily_snapshot, quotes_read


def test_realtime_change_rounds_to_four_decimal_places() -> None:
    realtime_ts = dt.datetime(2026, 11, 21, 9, 30, tzinfo=dt.UTC)
    row = SimpleNamespace(
        code="999233.SH",
        realtime_ts=realtime_ts,
        realtime_price=Decimal("20"),
        realtime_pct_change=Decimal("1.23456"),
        realtime_volume=Decimal("10"),
        realtime_amount=Decimal("200"),
    )

    item = quotes_read._realtime_item(
        row, "合成", "stock", realtime_ts, threshold=60
    )

    assert item.change_pct == "1.2346"


def test_daily_change_rounds_and_data_as_of_is_trade_close(monkeypatch) -> None:
    code = "999229.SH"
    licence = uuid.UUID(int=229)
    trade_date = dt.date(2026, 11, 20)
    row = SimpleNamespace(
        code=code,
        close=Decimal("20"),
        pre_close=Decimal("19"),
        trade_date=trade_date,
        fetched_at=dt.datetime(2026, 11, 21, 1, 5, tzinfo=dt.UTC),
        volume=Decimal("10"),
        amount=Decimal("20"),
    )
    monkeypatch.setattr(
        quotes_read,
        "_identity_rows",
        lambda *_: [SimpleNamespace(code=code, name="合成", type="stock")],
    )
    monkeypatch.setattr(quotes_read, "_daily_closes", lambda *_: {code: row})
    monkeypatch.setattr(quotes_read, "_realtime_latest", lambda *_: {})
    monkeypatch.setattr(quotes_read, "_reference_time", lambda *_: (None, False))
    monkeypatch.setattr(daily_snapshot, "active_licence_id", lambda *_: licence)

    item = quotes_read.read_quotes(
        SimpleNamespace(), uuid.UUID(int=230), (code,),
        SimpleNamespace(realtime_quotes_source="off"),
    ).items[0]

    assert item.change_pct == "5.2632"
    assert item.data_as_of == item.t == "2026-11-20T15:00:00+08:00"
    assert "fetched_at" not in item.model_dump()

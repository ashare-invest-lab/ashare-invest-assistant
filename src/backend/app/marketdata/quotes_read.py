"""Read owner-visible daily closes until a realtime quote reader is available."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, select

from app.common.errors import AppError, ErrorCode
from app.db.tables.market import daily_bars, securities
from app.marketdata.subresource_read import DecimalText, Gap, Shape
from app.schemas.enums import DataStatus, GapReason, SecurityType

BEIJING = ZoneInfo("Asia/Shanghai")


class QuoteItem(Shape):
    security_code: str
    name: str
    price: DecimalText | None = None
    change_pct: DecimalText | None = None
    volume: DecimalText | None = None
    amount: DecimalText | None = None
    t: str | None = None
    data_status: DataStatus
    data_as_of: str | None = None
    gaps: list[Gap]


class QuotesResponse(Shape):
    items: list[QuoteItem]


def _daily_closes(
    conn: Connection, codes: tuple[str, ...], licence: uuid.UUID, now: dt.datetime
) -> dict[str, Row[*tuple[Any, ...]]]:
    v = daily_bars.c
    local_now = now.astimezone(BEIJING)
    latest_close_date = local_now.date()
    if local_now.time() < dt.time(15):
        latest_close_date -= dt.timedelta(days=1)
    rows = conn.execute(
        select(v.code, v.close, v.pre_close, v.trade_date, v.fetched_at)
        .where(
            v.code.in_(codes),
            v.source == "mairui",
            v.adj_type == "none",
            v.source_licence_id == licence,
            v.is_suspended.is_(False),
            # Skip incomplete OHLC rows before choosing the latest eligible date.
            *(v[field].is_not(None) for field in ("open", "high", "low", "close")),
            # Filter before DISTINCT ON so an unclosed day falls back to an older close.
            v.trade_date <= latest_close_date,
            v.fetched_at <= now,
        )
        .order_by(v.code, v.trade_date.desc())
        .distinct(v.code)
    ).all()
    return {row.code: row for row in rows}


def read_quotes(conn: Connection, owner: uuid.UUID, codes: tuple[str, ...]) -> QuotesResponse:
    # daily_snapshot -> daily_bars -> aggregates.service also imports this reader.
    from app.marketdata.daily_snapshot import active_licence_id

    rows = conn.execute(
        select(securities.c.code, securities.c.name, securities.c.type).where(
            securities.c.code.in_(codes)
        )
    ).all()
    identities = {row.code: row for row in rows}
    if set(identities) != set(codes):
        raise AppError(ErrorCode.NOT_FOUND)
    now = dt.datetime.now(dt.UTC)
    licence = active_licence_id(conn, owner, now)
    closes = _daily_closes(conn, codes, licence, now) if licence is not None else {}
    reason = GapReason.NO_SOURCE if licence is not None else GapReason.DATA_LICENCE_UNAVAILABLE
    message = "本人行情缓存尚无可用读取源" if licence is not None else "本人数据证书不可用"
    items: list[QuoteItem] = []
    for code in codes:
        row = closes.get(code)
        item = QuoteItem(
            security_code=code,
            name=identities[code].name,
            data_status=DataStatus.UNAVAILABLE,
            gaps=[Gap(key="quotes", reason=reason, message=message)],
        )
        if row is not None:
            item.price = format(
                row.close, ".3f" if identities[code].type == SecurityType.ETF else "f"
            )
            if row.pre_close is not None and row.pre_close > 0:
                item.change_pct = format((row.close - row.pre_close) / row.pre_close * 100, "f")
            item.t = dt.datetime.combine(row.trade_date, dt.time(15), BEIJING).isoformat()
            item.data_as_of = row.fetched_at.astimezone(BEIJING).isoformat()
            item.data_status = DataStatus.STALE
            item.gaps = []
        items.append(item)
    return QuotesResponse(items=items)

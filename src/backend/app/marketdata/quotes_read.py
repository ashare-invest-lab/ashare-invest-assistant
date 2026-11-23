"""Read owner-visible daily closes until a realtime quote reader is available."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, select

from app.common.errors import AppError, ErrorCode
from app.db.tables.market import daily_bars, quotes_snapshot, securities, trading_calendar
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
        select(v.code, v.close, v.pre_close, v.trade_date, v.fetched_at, v.volume, v.amount)
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
            # Compare instants: a later day's intraday backfill is still eligible.
            v.fetched_at
            >= (v.trade_date + dt.time(15)).self_group().op("AT TIME ZONE")("Asia/Shanghai"),
            v.fetched_at <= now,
        )
        .order_by(v.code, v.trade_date.desc())
        .distinct(v.code)
    ).all()
    return {row.code: row for row in rows}


def _realtime_snapshots(
    conn: Connection, codes: tuple[str, ...], licence: uuid.UUID, now: dt.datetime
) -> dict[str, Row[*tuple[Any, ...]]]:
    c = quotes_snapshot.c
    rows = conn.execute(
        select(quotes_snapshot)
        .where(
            c.code.in_(codes),
            c.source == "mairui",
            c.source_licence_id == licence,
            c.batch_id.is_not(None),
            c.ts <= now,
            c.fetched_at <= now,
        )
        .order_by(c.code, c.fetched_at.desc(), c.ts.desc(), c.revision.desc())
    ).all()
    batches: dict[object, list[Row[*tuple[Any, ...]]]] = {}
    for row in rows:
        timestamp = row.ts
        fetched_at = row.fetched_at
        if (
            row.batch_id is None
            or timestamp is None
            or fetched_at is None
            or timestamp.tzinfo is None
            or fetched_at.tzinfo is None
            or timestamp > now
            or fetched_at > now
        ):
            continue
        batches.setdefault(row.batch_id, []).append(row)
    visible: list[tuple[dt.datetime, dt.datetime, list[Row[*tuple[Any, ...]]]]] = []
    for batch_rows in batches.values():
        fetched_values = [row.fetched_at for row in batch_rows]
        timestamp_values = [row.ts for row in batch_rows]
        visible.append((max(fetched_values), max(timestamp_values), batch_rows))
    if not visible:
        return {}
    selected = max(visible, key=lambda item: (item[0], item[1]))[2]
    result: dict[str, Row[*tuple[Any, ...]]] = {}
    for row in selected:
        previous = result.get(row.code)
        if previous is None or row.revision > previous.revision:
            result[row.code] = row
    return result


def _fresh_close_day(conn: Connection, now: dt.datetime) -> dt.date | None:
    local = now.astimezone(BEIJING)
    calendar = trading_calendar.c
    is_open = conn.execute(
        select(calendar.is_open).where(calendar.date == local.date())
    ).scalar_one_or_none()
    # A daily fallback cannot satisfy the realtime.yaml intraday quote threshold.
    # Missing calendar facts and an open day's pre-close data remain stale.
    if is_open is None or (is_open and local.time() < dt.time(15)):
        return None
    return conn.execute(
        select(calendar.date)
        .where(calendar.is_open.is_(True), calendar.date <= local.date())
        .order_by(calendar.date.desc())
        .limit(1)
    ).scalar_one_or_none()


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
    realtime = _realtime_snapshots(conn, codes, licence, now) if licence is not None else {}
    closes = _daily_closes(conn, codes, licence, now) if licence is not None else {}
    fresh_day = _fresh_close_day(conn, now) if closes else None
    reason = GapReason.NO_SOURCE if licence is not None else GapReason.DATA_LICENCE_UNAVAILABLE
    message = "本人行情缓存尚无可用读取源" if licence is not None else "本人数据证书不可用"
    items: list[QuoteItem] = []
    for code in codes:
        realtime_row = realtime.get(code)
        row = closes.get(code)
        item = QuoteItem(
            security_code=code,
            name=identities[code].name,
            data_status=DataStatus.UNAVAILABLE,
            gaps=[Gap(key="quotes", reason=reason, message=message)],
        )
        if realtime_row is not None:
            item.price = (
                None
                if realtime_row.price is None
                else format(
                    realtime_row.price,
                    ".3f" if identities[code].type == SecurityType.ETF else "f",
                )
            )
            item.change_pct = (
                None
                if realtime_row.pct_change is None
                else format(realtime_row.pct_change, "f")
            )
            item.t = realtime_row.ts.astimezone(BEIJING).isoformat()
            item.data_as_of = realtime_row.fetched_at.astimezone(BEIJING).isoformat()
            item.volume = None if realtime_row.volume is None else format(realtime_row.volume, "f")
            item.amount = None if realtime_row.amount is None else format(realtime_row.amount, "f")
            age = (now - realtime_row.fetched_at).total_seconds()
            item.data_status = (
                DataStatus.FRESH if age <= 30 else DataStatus.STALE
            )
            item.gaps = []
        elif row is not None:
            item.price = format(
                row.close, ".3f" if identities[code].type == SecurityType.ETF else "f"
            )
            if row.pre_close is not None and row.pre_close > 0:
                item.change_pct = format((row.close - row.pre_close) / row.pre_close * 100, "f")
            item.t = dt.datetime.combine(row.trade_date, dt.time(15), BEIJING).isoformat()
            item.data_as_of = row.fetched_at.astimezone(BEIJING).isoformat()
            item.volume = None if row.volume is None else format(row.volume, "f")
            item.amount = None if row.amount is None else format(row.amount, "f")
            # Cross-day backfills do not prove a close fetched on its own session.
            item.data_status = (
                DataStatus.FRESH
                if row.trade_date == fresh_day
                and row.fetched_at.astimezone(BEIJING).date() == row.trade_date
                else DataStatus.STALE
            )
            item.gaps = []
        items.append(item)
    return QuotesResponse(items=items)

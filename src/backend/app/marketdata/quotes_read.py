"""Read owner-visible realtime quotes with a daily-close fallback."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, select

from app.common.errors import AppError, ErrorCode
from app.config import Settings, get_settings
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
    # 契约 /quotes 当前没有 basis/source 字段，来源标注待架构裁定，未验证。


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


def _realtime_latest(
    conn: Connection, codes: tuple[str, ...], licence: uuid.UUID, now: dt.datetime
) -> dict[str, Row[*tuple[Any, ...]]]:
    q = quotes_snapshot.c
    rows = conn.execute(
        select(
            q.code.label("code"),
            q.ts.label("realtime_ts"),
            q.price.label("realtime_price"),
            q.pct_change.label("realtime_pct_change"),
            q.volume.label("realtime_volume"),
            q.amount.label("realtime_amount"),
        )
        .where(
            q.code.in_(codes),
            q.source == "mairui",
            q.source_licence_id == licence,
            q.ts <= now,
            q.fetched_at <= now,
        )
        .order_by(q.code, q.ts.desc(), q.fetched_at.desc(), q.revision.desc())
        .distinct(q.code)
    ).all()
    return {row.code: row for row in rows}


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


def _identity_rows(conn: Connection, codes: tuple[str, ...]) -> list[Row[*tuple[Any, ...]]]:
    """Load public identities before any owner-scoped market-data read."""
    return conn.execute(
        select(securities.c.code, securities.c.name, securities.c.type).where(
            securities.c.code.in_(codes)
        )
    ).all()


def _row_value(row: object, name: str) -> object | None:
    return getattr(row, name, None)


def _realtime_item(
    row: object, name: str, security_type: SecurityType, now: dt.datetime, threshold: int
) -> QuoteItem:
    stamp = _row_value(row, "realtime_ts")
    price = _row_value(row, "realtime_price")
    pct_change = _row_value(row, "realtime_pct_change")
    volume = _row_value(row, "realtime_volume")
    amount = _row_value(row, "realtime_amount")
    age = (now - stamp).total_seconds()
    return QuoteItem(
        security_code=row.code,
        name=name,
        price=(
            None
            if price is None
            else format(price, ".3f" if security_type == SecurityType.ETF else "f")
        ),
        change_pct=None if pct_change is None else format(pct_change, "f"),
        volume=None if volume is None else format(volume, "f"),
        amount=None if amount is None else format(amount, "f"),
        t=stamp.astimezone(BEIJING).isoformat(),
        data_status=DataStatus.FRESH if 0 <= age <= threshold else DataStatus.STALE,
        data_as_of=stamp.astimezone(BEIJING).isoformat(),
        gaps=[],
    )


def read_quotes(
    conn: Connection,
    owner: uuid.UUID,
    codes: tuple[str, ...],
    settings: Settings | None = None,
) -> QuotesResponse:
    # daily_snapshot -> daily_bars -> aggregates.service also imports this reader.
    from app.marketdata.daily_snapshot import active_licence_id

    rows = _identity_rows(conn, codes)
    identities = {row.code: row for row in rows}
    if set(identities) != set(codes):
        raise AppError(ErrorCode.NOT_FOUND)
    now = dt.datetime.now(dt.UTC)
    resolved_settings = settings if settings is not None else get_settings()
    realtime_enabled = resolved_settings.realtime_quotes_source != "off"
    licence = active_licence_id(conn, owner, now)
    closes = _daily_closes(conn, codes, licence, now) if licence is not None else {}
    realtime: dict[str, Row[*tuple[Any, ...]]] = {}
    if realtime_enabled and licence is not None:
        realtime = _realtime_latest(conn, codes, licence, now)
    fresh_day = _fresh_close_day(conn, now) if closes else None
    reason = GapReason.NO_SOURCE if licence is not None else GapReason.DATA_LICENCE_UNAVAILABLE
    message = "本人行情缓存尚无可用读取源" if licence is not None else "本人数据证书不可用"
    items: list[QuoteItem] = []
    for code in codes:
        identity = identities[code]
        realtime_row = realtime.get(code)
        row = closes.get(code)
        if realtime_row is not None and row is not None:
            daily_ts = dt.datetime.combine(row.trade_date, dt.time(15), BEIJING)
            if _row_value(realtime_row, "realtime_ts") <= daily_ts:
                realtime_row = None
            else:
                row = None
        if realtime_row is not None:
            threshold = resolved_settings.business.realtime.intervals.effective_stale_threshold_s
            items.append(_realtime_item(realtime_row, identity.name, identity.type, now, threshold))
            continue
        item = QuoteItem(
            security_code=code,
            name=identity.name,
            data_status=DataStatus.UNAVAILABLE,
            gaps=[Gap(key="quotes", reason=reason, message=message)],
        )
        if row is not None:
            item.price = format(row.close, ".3f" if identity.type == SecurityType.ETF else "f")
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

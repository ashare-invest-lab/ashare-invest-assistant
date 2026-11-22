"""Read owner-visible realtime quotes with a daily-close fallback."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Sequence
from datetime import date as date_type
from datetime import datetime as datetime_type
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, select

from app.common.errors import AppError, ErrorCode
from app.config import Settings, get_settings
from app.db.tables.market import daily_bars, quotes_snapshot, securities, trading_calendar
from app.marketdata.subresource_read import DecimalText, Gap, Shape
from app.schemas.enums import DataStatus, GapReason, SecurityType

BEIJING = ZoneInfo("Asia/Shanghai")
_DEFAULT_MORNING = (dt.time(9, 30), dt.time(11, 30))
_DEFAULT_AFTERNOON = (dt.time(13), dt.time(15))


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


def _session_bounds(day: dt.date) -> tuple[dt.time, dt.time, dt.time, dt.time]:
    """Return main-board continuous-session bounds, with conservative defaults."""
    try:
        segment = get_settings().business.market_rules.segment_for(day)
        if segment is not None:
            sessions = segment.sessions
            return (
                sessions.morning[0],
                sessions.morning[1],
                sessions.afternoon[0],
                sessions.closing_auction[1],
            )
    except (AttributeError, TypeError, ValueError):
        pass
    return (
        _DEFAULT_MORNING[0],
        _DEFAULT_MORNING[1],
        _DEFAULT_AFTERNOON[0],
        _DEFAULT_AFTERNOON[1],
    )


def _reference_time(conn: Connection, now: dt.datetime) -> tuple[dt.datetime | None, bool]:
    """Return the market instant and whether the market is in session."""
    local = now.astimezone(BEIJING)
    calendar = trading_calendar.c
    is_open = conn.execute(
        select(calendar.is_open).where(calendar.date == local.date())
    ).scalar_one_or_none()
    if not isinstance(is_open, bool):
        return None, False
    if is_open:
        morning_start, morning_end, afternoon_start, closing_end = _session_bounds(
            local.date()
        )
        clock = local.time().replace(tzinfo=None)
        if morning_start <= clock < morning_end or afternoon_start <= clock < closing_end:
            return now, True
        if clock >= morning_end and clock < afternoon_start:
            return dt.datetime.combine(local.date(), morning_end, BEIJING), False
        if clock >= closing_end:
            return dt.datetime.combine(local.date(), closing_end, BEIJING), False

    previous = conn.execute(
        select(calendar.date)
        .where(
            calendar.is_open.is_(True),
            calendar.date < local.date(),
        )
        .order_by(calendar.date.desc())
        .limit(1)
    ).scalar_one_or_none()
    if not isinstance(previous, date_type):
        return None, False
    _, _, _, closing_end = _session_bounds(previous)
    return dt.datetime.combine(previous, closing_end, BEIJING), False


def _identity_rows(conn: Connection, codes: tuple[str, ...]) -> Sequence[Row[Any, Any, Any]]:
    """Load public identities before any owner-scoped market-data read."""
    return conn.execute(
        select(securities.c.code, securities.c.name, securities.c.type).where(
            securities.c.code.in_(codes)
        )
    ).all()


def _row_value(row: object, name: str) -> object | None:
    return getattr(row, name, None)


def _realtime_item(
    row: Row[Any],
    name: str,
    security_type: SecurityType,
    now: dt.datetime,
    threshold: int,
    reference: dt.datetime | None = None,
) -> QuoteItem:
    stamp = row.realtime_ts
    if not isinstance(stamp, datetime_type):
        raise ValueError("realtime timestamp must be a datetime")
    price = row.realtime_price
    pct_change = row.realtime_pct_change
    volume = row.realtime_volume
    amount = row.realtime_amount
    reference = now if reference is None else reference
    age = (reference - stamp).total_seconds()
    return QuoteItem(
        security_code=row.code,
        name=name,
        price=(
            None
            if price is None
            else format(price, ".3f" if security_type == SecurityType.ETF else "f")
        ),
        change_pct=(
            None
            if pct_change is None
            else format(
                Decimal(pct_change).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                "f",
            )
        ),
        volume=None if volume is None else format(volume, "f"),
        amount=None if amount is None else format(amount, "f"),
        t=stamp.astimezone(BEIJING).isoformat(),
        data_status=DataStatus.FRESH
        if stamp <= now and 0 <= age <= threshold
        else DataStatus.STALE,
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
    reference, in_session = (
        _reference_time(conn, now) if closes or realtime else (None, False)
    )
    fresh_day = (
        None
        if reference is None or in_session
        else reference.astimezone(BEIJING).date()
    )
    reason = GapReason.NO_SOURCE if licence is not None else GapReason.DATA_LICENCE_UNAVAILABLE
    message = "本人行情缓存尚无可用读取源" if licence is not None else "本人数据证书不可用"
    items: list[QuoteItem] = []
    for code in codes:
        identity = identities[code]
        realtime_row = realtime.get(code)
        row = closes.get(code)
        if realtime_row is not None and row is not None:
            daily_ts = dt.datetime.combine(row.trade_date, dt.time(15), BEIJING)
            if realtime_row.realtime_ts <= daily_ts:
                realtime_row = None
            else:
                row = None
        if realtime_row is not None:
            threshold = resolved_settings.business.realtime.intervals.effective_stale_threshold_s
            items.append(
                _realtime_item(
                    realtime_row,
                    identity.name,
                    identity.type,
                    now,
                    threshold,
                    reference,
                )
            )
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
                change_pct = (row.close - row.pre_close) / row.pre_close * 100
                item.change_pct = format(
                    change_pct.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP),
                    "f",
                )
            item.t = dt.datetime.combine(row.trade_date, dt.time(15), BEIJING).isoformat()
            item.data_as_of = item.t
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

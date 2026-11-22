from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import cast
from zoneinfo import ZoneInfo

from pydantic import ConfigDict
from sqlalchemy import Connection, select

from app.aggregates import models as m
from app.db.tables.market import (
    daily_bars,
    quotes_snapshot,
    securities,
    security_listing_status_history,
)
from app.schemas.enums import DataStatus, GapReason, MarketRegime, MarketSession

BEIJING = ZoneInfo("Asia/Shanghai")
FINAL_AFTER = dt.time(17, 10)
RATIO_QUANTUM = Decimal("0.0001")


class Breadth(m.Model):
    up: int | None
    down: int | None
    flat: int | None
    up_ratio: str | None
    down_ratio: str | None
    flat_ratio: str | None
    limit_up: int | None
    limit_down: int | None


class MarketIndexQuote(m.Model):
    security_code: str
    name: str
    price: str | None
    change_pct: str | None
    amount: str | None
    t: dt.datetime | None


MarketIndex = MarketIndexQuote


class MarketOverview(m.DataBlock):
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)

    basis: m.MarketBasis | None = None
    trade_date: dt.date
    session: MarketSession
    indices: list[MarketIndexQuote]
    breadth: Breadth | None
    regime: MarketRegime | None
    regime_position_range: m.Range | None
    turnover_total: str | None


def _row_value(row: object, name: str) -> object:
    mapping = cast(Mapping[str, object], row._mapping)  # type: ignore[attr-defined]
    return mapping[name]


def _decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _text(value: object) -> str | None:
    number = _decimal(value)
    return format(number, "f") if number is not None else None


def _change_pct_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    quantized = value.quantize(RATIO_QUANTUM, rounding=ROUND_HALF_UP)
    formatted = format(value, "f")
    fractional_digits = len(formatted.partition(".")[2])
    if value == quantized and fractional_digits <= 4:
        return formatted
    return format(quantized, "f")


def _aware(value: object) -> dt.datetime | None:
    return value if isinstance(value, dt.datetime) and value.tzinfo is not None else None


def _payload(row: object, key: str) -> object:
    payload = _row_value(row, "payload")
    return payload.get(key) if isinstance(payload, dict) else None


def _same_day(value: dt.datetime | None, day: dt.date) -> bool:
    return value is not None and value.astimezone(BEIJING).date() == day


def _ratio(value: int, denominator: int) -> str | None:
    if denominator == 0:
        return None
    return format((Decimal(value) / Decimal(denominator)).quantize(RATIO_QUANTUM), "f")


def _gap(key: str, message: str, reason: GapReason = GapReason.NO_SOURCE) -> m.Gap:
    return m.Gap(key=key, reason=reason, message=message)


def _dedupe_gaps(gaps: list[m.Gap]) -> list[m.Gap]:
    seen: set[str] = set()
    result: list[m.Gap] = []
    for gap in gaps:
        if gap.key not in seen:
            seen.add(gap.key)
            result.append(gap)
    return result


def _empty(
    clock: m.MarketClock,
    indices: list[MarketIndexQuote],
    gaps: list[m.Gap],
    status: DataStatus = DataStatus.UNAVAILABLE,
) -> MarketOverview:
    return MarketOverview(
        basis=None,
        trade_date=clock.trade_date,
        session=clock.session,
        indices=indices,
        breadth=None,
        regime=None,
        regime_position_range=None,
        turnover_total=None,
        data_status=status,
        data_as_of=None,
        gaps=_dedupe_gaps(gaps),
    )


def _index_cards(conn: Connection) -> list[MarketIndexQuote]:
    rows = conn.execute(
        select(securities.c.code, securities.c.name)
        .where(securities.c.type == "index")
        .order_by(securities.c.code)
    ).all()
    return [
        MarketIndexQuote(
            security_code=str(_row_value(row, "code")),
            name=str(_row_value(row, "name")),
            price=None,
            change_pct=None,
            amount=None,
            t=None,
        )
        for row in rows
    ]


def _stock_rows(conn: Connection, day: dt.date) -> list[object]:
    s = securities.c
    rows = conn.execute(
        select(
            s.code,
            s.exchange,
            s.listing_status,
            s.list_date,
            s.delist_date,
        )
        .where(
            s.type == "stock",
            s.exchange.in_(("SH", "SZ", "BJ")),
            s.list_date.is_(None) | (s.list_date <= day),
            s.delist_date.is_(None) | (s.delist_date > day),
        )
        .order_by(s.code)
    ).all()
    history = conn.execute(
        select(
            security_listing_status_history.c.code,
            security_listing_status_history.c.listing_status,
        ).where(
            security_listing_status_history.c.valid_from <= day,
            security_listing_status_history.c.valid_until.is_(None)
            | (security_listing_status_history.c.valid_until > day),
        )
    ).all()
    status = {str(_row_value(row, "code")): _row_value(row, "listing_status") for row in history}
    return [
        row
        for row in rows
        if status.get(str(_row_value(row, "code")), _row_value(row, "listing_status")) == "listed"
    ]


def _latest_intraday(
    conn: Connection,
    codes: tuple[str, ...],
    licence: uuid.UUID,
    day: dt.date,
    as_of: dt.datetime,
) -> list[object]:
    if not codes:
        return []
    c = quotes_snapshot.c
    rows = conn.execute(
        select(*c)
        .where(
            c.code.in_(codes),
            c.source == "mairui",
            c.source_licence_id == licence,
        )
        .order_by(c.code, c.ts, c.fetched_at)
    ).all()
    batches: dict[tuple[object, dt.date], list[object]] = {}
    for row in rows:
        batch_id = _row_value(row, "batch_id")
        timestamp = _aware(_row_value(row, "ts"))
        fetched = _aware(_row_value(row, "fetched_at"))
        if batch_id is None or timestamp is None or fetched is None:
            continue
        if not _same_day(timestamp, day):
            continue
        key = (batch_id, timestamp.astimezone(BEIJING).date())
        batches.setdefault(key, []).append(row)

    visible: list[tuple[dt.datetime, dt.datetime, list[object]]] = []
    for batch_rows in batches.values():
        timestamps = [_aware(_row_value(row, "ts")) for row in batch_rows]
        fetched_values = [_aware(_row_value(row, "fetched_at")) for row in batch_rows]
        if any(value is None or value > as_of for value in (*timestamps, *fetched_values)):
            continue
        valid_timestamps = [value for value in timestamps if value is not None]
        valid_fetched = [value for value in fetched_values if value is not None]
        if len(valid_timestamps) != len(batch_rows) or len(valid_fetched) != len(batch_rows):
            continue
        max_fetched = max(valid_fetched)
        max_timestamp = max(valid_timestamps)
        visible.append((max_fetched, max_timestamp, batch_rows))
    if not visible:
        return []
    _max_fetched, _max_timestamp, selected = max(visible, key=lambda item: (item[0], item[1]))
    return selected


def _daily_rows(
    conn: Connection,
    codes: tuple[str, ...],
    licence: uuid.UUID,
    day: dt.date,
    as_of: dt.datetime,
    *,
    exact_day: bool,
) -> list[object]:
    if not codes:
        return []
    b = daily_bars.c
    day_filter = b.trade_date == day if exact_day else b.trade_date < day
    clauses = [
        b.code.in_(codes),
        day_filter,
        b.adj_type == "none",
        b.source == "mairui",
        b.source_licence_id == licence,
        b.is_suspended.is_(False),
        b.close.is_not(None),
        b.pre_close.is_not(None),
        b.fetched_at <= as_of,
    ]
    if exact_day:
        clauses.append(b.fetched_at >= dt.datetime.combine(day, FINAL_AFTER, BEIJING))
    rows = conn.execute(
        select(*b).where(*clauses).order_by(b.code, b.trade_date.desc(), b.fetched_at.desc())
    ).all()
    rows = [
        row
        for row in rows
        if (fetched := _aware(_row_value(row, "fetched_at"))) is not None and fetched <= as_of
    ]
    if not exact_day:
        rows = [
            row
            for row in rows
            if (fetched := _aware(_row_value(row, "fetched_at"))) is not None
            and isinstance(trade_day := _row_value(row, "trade_date"), dt.date)
            and fetched >= dt.datetime.combine(trade_day, FINAL_AFTER, BEIJING)
        ]
        latest_trade_date = max(
            (
                trade_day
                for row in rows
                if isinstance(trade_day := _row_value(row, "trade_date"), dt.date)
            ),
            default=None,
        )
        rows = [row for row in rows if _row_value(row, "trade_date") == latest_trade_date]
    chosen: dict[str, object] = {}
    for row in rows:
        chosen.setdefault(str(_row_value(row, "code")), row)
    return list(chosen.values())


def _row_metrics(
    row: object, close_mode: bool
) -> tuple[Decimal | None, Decimal | None, Decimal | None, bool | None, Decimal | None]:
    price = _decimal(_row_value(row, "close")) if close_mode else _decimal(_row_value(row, "price"))
    if close_mode:
        previous = _decimal(_row_value(row, "pre_close"))
        change = (
            None
            if price is None or previous in (None, Decimal(0))
            else (price - previous) / previous * 100
        )
        volume = _decimal(_row_value(row, "volume"))
        amount = _decimal(_row_value(row, "amount"))
        suspended = _row_value(row, "is_suspended")
    else:
        change = _decimal(_row_value(row, "pct_change"))
        volume = _decimal(_row_value(row, "volume"))
        amount = _decimal(_row_value(row, "amount"))
        suspended = _row_value(row, "is_suspended")
        if change is None:
            change = _decimal(_payload(row, "pct_change"))
        if volume is None:
            volume = _decimal(_payload(row, "volume"))
        if amount is None:
            amount = _decimal(_payload(row, "amount"))
        if suspended is None:
            suspended = _payload(row, "is_suspended")
    return price, change, amount, suspended if isinstance(suspended, bool) else None, volume


def _limit_counts(rows: list[object], close_mode: bool) -> tuple[int | None, int | None]:
    if close_mode:
        return None, None
    up = down = 0
    usable = 0
    for row in rows:
        _price, _change, _amount, suspended, volume = _row_metrics(row, False)
        if suspended is None:
            return None, None
        if suspended or volume is None or volume <= 0:
            continue
        source_up = _row_value(row, "limit_up")
        source_down = _row_value(row, "limit_down")
        if not isinstance(source_up, bool) or not isinstance(source_down, bool):
            return None, None
        usable += 1
        up += int(source_up)
        down += int(source_down)
    return (up, down) if usable else (None, None)


def _row_time(row: object, close_mode: bool) -> dt.datetime | None:
    if close_mode:
        day = _row_value(row, "trade_date")
        return dt.datetime.combine(day, dt.time(15), BEIJING) if isinstance(day, dt.date) else None
    return _aware(_row_value(row, "ts"))


def _observed_date(rows: list[object], close_mode: bool) -> dt.date | None:
    for row in rows:
        if close_mode:
            trade_date = _row_value(row, "trade_date")
            if isinstance(trade_date, dt.date):
                return trade_date
            continue
        timestamp = _aware(_row_value(row, "ts"))
        if timestamp is not None:
            return timestamp.astimezone(BEIJING).date()
    return None


def _overview(
    conn: Connection,
    user_id: uuid.UUID,
    clock: m.MarketClock,
    query_as_of: dt.datetime,
    stale_threshold_s: int,
) -> MarketOverview:
    if query_as_of.tzinfo is None:
        raise ValueError("query_as_of must be timezone-aware")
    cards = _index_cards(conn)
    gaps: list[m.Gap] = []
    from app.marketdata.daily_snapshot import active_licence_id

    licence = active_licence_id(conn, user_id, query_as_of)
    if licence is None:
        for card in cards:
            gaps.append(_gap(f"market.indices.{card.security_code}", "指数行情缺失。"))
        gaps.append(_gap("market.basis", "没有可验证的本人行情来源。"))
        gaps.append(
            _gap("market.indices", "本人数据证书不可用。", GapReason.DATA_LICENCE_UNAVAILABLE)
        )
        gaps.extend(
            [
                _gap("market.breadth", "没有可验证的本人行情来源。"),
                _gap("market.turnover_total", "没有可验证的本人行情来源。"),
            ]
        )
        if not cards:
            gaps.append(_gap("market.regime", "F25/G-02 参数未批准，未生成市场环境结论。"))
            return _empty(clock, cards, gaps)
        gaps.append(_gap("market.regime", "F25/G-02 参数未批准，未生成市场环境结论。"))
        return _empty(clock, cards, gaps)

    if not cards:
        gaps.append(_gap("market.indices", "没有配置可展示的指数卡片。"))

    local = query_as_of.astimezone(BEIJING)
    close_mode = local.time() >= FINAL_AFTER or clock.session == MarketSession.NON_TRADING_DAY
    stocks = _stock_rows(conn, clock.trade_date)
    stock_codes = [str(_row_value(row, "code")) for row in stocks]
    had_stock_universe = bool(stock_codes)
    index_codes = [card.security_code for card in cards]
    codes = tuple(dict.fromkeys((*stock_codes, *index_codes)))
    rows = (
        _daily_rows(
            conn,
            codes,
            licence,
            clock.trade_date,
            query_as_of,
            exact_day=True,
        )
        if close_mode
        else (
            []
            if clock.session in {MarketSession.PRE_OPEN, MarketSession.CALL_AUCTION}
            else _latest_intraday(conn, codes, licence, clock.trade_date, query_as_of)
        )
    )
    used_previous_close = False
    if close_mode and not rows:
        rows = _daily_rows(conn, codes, licence, clock.trade_date, query_as_of, exact_day=False)
        used_previous_close = bool(rows)
    if not rows and not close_mode:
        close_mode = True
        rows = _daily_rows(conn, codes, licence, clock.trade_date, query_as_of, exact_day=False)
        used_previous_close = bool(rows)
    bj_codes = {code for code in stock_codes if code.endswith(".BJ")}
    bj_gate_applied = False
    if bj_codes:
        # BJ 证据字段未验证。T-A172 §10 可信证据投影未接入此读路径，门闩保持关闭。
        bj_gate_applied = True
        rows = [row for row in rows if str(_row_value(row, "code")) not in bj_codes]
        stock_codes = [code for code in stock_codes if code not in bj_codes]
        if not any(gap.key == "market.breadth" for gap in gaps):
            gaps.append(_gap("market.breadth", "BJ 门闩待 T-A172 §10 可信证据"))
    if not rows and not cards and not bj_gate_applied:
        gaps.append(_gap("market.regime", "F25/G-02 参数未批准，未生成市场环境结论。"))
        return _empty(clock, cards, gaps)
    by_code = {str(_row_value(row, "code")): row for row in rows}
    as_of_values: list[dt.datetime] = []
    for row in rows:
        stamp = _row_time(row, close_mode)
        if stamp is not None:
            as_of_values.append(stamp)
    for card in cards:
        row = by_code.get(card.security_code)
        if row is None:
            gaps.append(_gap(f"market.indices.{card.security_code}", "指数行情缺失。"))
            continue
        price, change, amount, _suspended, _volume = _row_metrics(row, close_mode)
        card.price = _text(price)
        card.change_pct = _change_pct_text(change)
        card.amount = _text(amount)
        card.t = _row_time(row, close_mode)
    candidate = set(stock_codes)
    observed = candidate & set(by_code)
    up = down = flat = trading = suspended = 0
    turnover = Decimal(0)
    turnover_complete = bool(candidate) and observed == candidate
    for code in sorted(observed):
        row = by_code[code]
        price, change, amount, is_suspended, volume = _row_metrics(row, close_mode)
        if is_suspended is None:
            turnover_complete = False
            continue
        if is_suspended is True:
            suspended += 1
            turnover_complete = False
            continue
        trading += 1
        if volume is None or volume <= 0:
            turnover_complete = False
            continue
        if change is None:
            turnover_complete = False
            continue
        if change > 0:
            up += 1
        elif change < 0:
            down += 1
        else:
            flat += 1
        if amount is None:
            turnover_complete = False
        else:
            turnover += amount
    denominator = up + down + flat
    limit_up, limit_down = _limit_counts([by_code[code] for code in sorted(observed)], close_mode)
    breadth = (
        Breadth(
            up=up if denominator else None,
            down=down if denominator else None,
            flat=flat if denominator else None,
            up_ratio=_ratio(up, denominator),
            down_ratio=_ratio(down, denominator),
            flat_ratio=_ratio(flat, denominator),
            limit_up=limit_up,
            limit_down=limit_down,
        )
        if observed
        else None
    )
    if limit_up is None or limit_down is None:
        gaps.append(_gap("market.breadth.limit_counts", "涨跌停来源字段和规则版本未验证。"))
    gaps.append(_gap("market.regime", "F25/G-02 参数未批准，未生成市场环境结论。"))
    if breadth is None and not any(gap.key == "market.breadth" for gap in gaps):
        gaps.append(_gap("market.breadth", "没有具备完整比较字段的同批次股票。"))
    if not turnover_complete:
        gaps.append(_gap("market.turnover_total", "成交额批次覆盖或单位未验证。"))
    basis = (
        m.MarketBasis(
            observed_date=_observed_date(rows, close_mode) or clock.trade_date,
            mode="close" if close_mode else "intraday",
            eligible=len(candidate),
            observed=len(observed),
            trading=trading,
            suspended=suspended,
            missing=len(candidate - observed),
            source="mairui",
        )
        if candidate or had_stock_universe
        else None
    )
    status = DataStatus.UNAVAILABLE
    if rows:
        status = DataStatus.PARTIAL if gaps or len(observed) < len(candidate) else DataStatus.FRESH
        intraday_times = (
            [stamp for row in rows if (stamp := _row_time(row, False)) is not None]
            if not close_mode
            else []
        )
        latest_intraday = max(intraday_times, default=None)
        intraday_stale = (
            not close_mode
            and latest_intraday is not None
            and query_as_of - latest_intraday > dt.timedelta(seconds=stale_threshold_s)
        )
        if (
            used_previous_close
            or clock.session == MarketSession.NON_TRADING_DAY
            or (close_mode and local.time() < FINAL_AFTER)
            or intraday_stale
        ):
            component_gap = any(
                item.key in {"market.breadth", "market.turnover_total", "market.indices"}
                or item.key.startswith("market.indices.")
                for item in gaps
            )
            if not component_gap:
                status = DataStatus.STALE
    if not rows:
        if cards:
            gaps.append(_gap("market.indices", "交易日行情全部缺失。"))
        if not any(gap.key == "market.breadth" for gap in gaps):
            gaps.append(_gap("market.breadth", "交易日行情全部缺失。"))
        gaps.append(_gap("market.turnover_total", "交易日行情全部缺失。"))
    return MarketOverview(
        basis=basis,
        trade_date=clock.trade_date,
        session=clock.session,
        indices=cards,
        breadth=breadth,
        regime=None,
        regime_position_range=None,
        turnover_total=_text(turnover) if turnover_complete else None,
        data_status=status,
        data_as_of=min(as_of_values) if as_of_values else None,
        gaps=_dedupe_gaps(gaps),
    )


def build_market_overview(
    conn: Connection,
    user_id: uuid.UUID,
    clock: m.MarketClock,
    query_as_of: dt.datetime,
    stale_threshold_s: int = 30,
) -> MarketOverview:
    """Build a PIT-filtered overview from persisted rows only."""
    return _overview(conn, user_id, clock, query_as_of, stale_threshold_s)

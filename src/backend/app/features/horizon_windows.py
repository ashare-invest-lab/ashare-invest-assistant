"""Horizon A0: one evidence-backed day and full-calendar windows (contract §2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from app.features.horizon_sources import BasisEvidence, DailyBarVersion, aware, permitted, visible

BEIJING = ZoneInfo("Asia/Shanghai")


def daily_cutoff(day: date) -> datetime:
    return datetime.combine(day, time(17, 30), BEIJING)


def intraday(as_of: datetime, *, is_open: bool) -> bool:
    local = aware(as_of).astimezone(BEIJING)
    return is_open and time(9, 30) <= local.time() < time(15)


@dataclass(frozen=True)
class DaySelection:
    d: date | None
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class CalendarWindow:
    dates: tuple[date, ...]
    bars: tuple[DailyBarVersion | None, ...]
    gaps: tuple[str, ...]


def _calendar(b: BasisEvidence, user: UUID, licence: UUID | None, a: datetime) -> dict[date, bool]:
    c = b.calendar
    if c is None or not permitted(c, user, licence, a) or len(dict(c.days)) != len(c.days):
        return {}
    return dict(c.days)


def _final(
    b: BasisEvidence, user: UUID, licence: UUID | None, code: str, day: date, a: datetime
) -> DailyBarVersion | None:
    bars = [
        v
        for v in b.bars
        if v.code == code
        and v.trade_date == day
        and v.adj_type == "none"
        and permitted(v, user, licence, a)
    ]
    if len(set(bars)) != 1 or bars[0].conflicted:
        return None
    bar = bars[0]
    proofs = [p for p in b.proofs if p.version == bar and visible(p.available_at, a)]
    if any(p.is_final is False for p in proofs):
        return None
    proofs = [p for p in proofs if p.is_final is True and p.source_final_receipt]
    if not proofs:
        return None
    if bar.source == "mairui" and day == a.astimezone(BEIJING).date():
        batches = [
            r
            for r in b.batches
            if r.kind == "daily_batch"
            and r.step == "daily_bars.fetch"
            and r.run_date == day
            and r.window_trading_days is None
            and r.licence_id == licence
            and (r.owner_id == user or (r.owner_id is None and (user, code) in r.members))
            and visible(r.available_at, a)
            and visible(r.finished_at, a)
        ]
        if not batches:
            return None
        latest = max(r.finished_at for r in batches)
        current = [r for r in batches if r.finished_at == latest]
        if len(current) != 1:
            return None
        r = current[0]
        if r.status not in {"ok", "partial"} or code in r.issues:
            return None
        if not any(p.run_id == r.run_id for p in proofs):
            return None
    return bar


def select_day(
    basis: BasisEvidence, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
) -> DaySelection:
    local = aware(as_of).astimezone(BEIJING)
    days = _calendar(basis, user_id, licence_id, as_of)
    day = local.date()
    while days and day >= min(days):
        if day not in days:
            break
        eligible = day < local.date() or local.time() >= time(17, 10)
        if days[day] and eligible and _final(basis, user_id, licence_id, code, day, as_of):
            return DaySelection(day, basis.gaps)
        day -= timedelta(days=1)
    gap = "calendar_not_covered" if not days or day >= min(days) else "completion_missing"
    return DaySelection(None, (*basis.gaps, gap))


def window(
    basis: BasisEvidence,
    *,
    d: date | None,
    n: int,
    user_id: UUID,
    licence_id: UUID | None,
    code: str,
    as_of: datetime,
) -> CalendarWindow:
    aware(as_of)
    if n <= 0:
        raise ValueError("window length must be positive")
    days = _calendar(basis, user_id, licence_id, as_of)
    dates: list[date] = []
    bars: list[DailyBarVersion | None] = []
    gaps = list(basis.gaps)
    day = d
    if day is None or day > as_of.astimezone(BEIJING).date():
        return CalendarWindow((), (), (*gaps, "day_unavailable"))
    while len(dates) < n:
        if day not in days:
            gaps.append(f"calendar_not_covered:{day}")
            break
        if days[day]:
            dates.append(day)
            bar = _final(basis, user_id, licence_id, code, day, as_of)
            bars.append(bar)
            if bar is None:
                gaps.append(f"completion_missing:{day}")
        day -= timedelta(days=1)
    return CalendarWindow(tuple(reversed(dates)), tuple(reversed(bars)), tuple(gaps))

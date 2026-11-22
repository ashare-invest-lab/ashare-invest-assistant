"""Pure in-memory P0 planning.  This module never starts work or performs IO."""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.ingest.state import Priority
from app.schemas.enums import MarketSession

INTRADAY_ENABLED = False  # 待 I2-C 裁定
ACTIVE_SESSIONS = frozenset((MarketSession.MORNING, MarketSession.AFTERNOON))


@dataclass(frozen=True, slots=True)
class CertificateUniverse:
    licence_id: Any
    holdings: Collection[str] = ()
    focus: Collection[str] = ()
    watchlist: Collection[str] = ()
    suspended: Collection[str] | Mapping[str, bool] = ()
    budget: int | None = None


@dataclass(frozen=True, slots=True)
class PoolEntry:
    code: str
    layer: str
    tier: int


@dataclass(frozen=True, slots=True)
class P0PlanRecord:
    plan_id: str
    licence_id: Any
    security_code: str
    trade_date: dt.date
    session: MarketSession
    layer: str
    tier: int
    priority: Priority = Priority.P0
    status: str = "planned"
    reason: str | None = None
    budget_cost: int = 1

    @property
    def code(self) -> str:
        return self.security_code

    @property
    def dispatchable(self) -> bool:
        return self.status == "planned"


@dataclass(frozen=True, slots=True)
class P0PlanResult:
    records: tuple[P0PlanRecord, ...]
    reasons: tuple[str, ...] = ()
    budget_used: Mapping[Any, int] = field(default_factory=dict)
    duplicate_count: int = 0

    @property
    def scheduled(self) -> tuple[P0PlanRecord, ...]:
        return tuple(r for r in self.records if r.dispatchable)

    @property
    def skipped(self) -> tuple[P0PlanRecord, ...]:
        return tuple(r for r in self.records if r.status == "skipped")


ClockInput = Any | Callable[[dt.datetime], Any]


class P0Planner:
    """Plan a bounded, layered universe and retain replay keys in process memory."""

    def __init__(
        self,
        *,
        tier1_cap: int,
        universe_hard_cap: int,
        focus_cap: int | None = None,
        watchlist_cap: int | None = None,
        intraday_enabled: bool = INTRADAY_ENABLED,
    ) -> None:
        if min(tier1_cap, universe_hard_cap) < 1 or tier1_cap > universe_hard_cap:
            raise ValueError("invalid universe caps")
        self.tier1_cap, self.universe_hard_cap = tier1_cap, universe_hard_cap
        self.focus_cap, self.watchlist_cap = focus_cap, watchlist_cap
        self.intraday_enabled = intraday_enabled
        self._seen: dict[str, P0PlanRecord] = {}

    @property
    def records(self) -> tuple[P0PlanRecord, ...]:
        return tuple(self._seen.values())

    def pool(
        self,
        *,
        holdings: Iterable[str] = (),
        focus: Iterable[str] = (),
        watchlist: Iterable[str] = (),
    ) -> tuple[PoolEntry, ...]:
        def unique(values: Iterable[str], cap: int | None = None) -> list[str]:
            out: list[str] = []
            for code in values:
                code = str(code)
                if code and code not in out:
                    out.append(code)
            return out if cap is None else out[:cap]

        held = unique(holdings)
        focused = [c for c in unique(focus) if c not in held]
        if self.focus_cap is not None:
            focused = focused[: self.focus_cap]
        used = set(held) | set(focused)
        watched = [c for c in unique(watchlist) if c not in used]
        if self.watchlist_cap is not None:
            watched = watched[: self.watchlist_cap]
        ordered = [(c, "holding") for c in held]
        ordered += [(c, "focus") for c in focused]
        ordered += [(c, "watchlist") for c in watched]
        return tuple(
            PoolEntry(c, layer, 1 if i < self.tier1_cap else 2)
            for i, (c, layer) in enumerate(ordered[: self.universe_hard_cap])
        )

    def plan(
        self,
        now: dt.datetime,
        certificates: Mapping[Any, CertificateUniverse | Mapping[str, Any]]
        | Sequence[CertificateUniverse],
        *,
        clock: ClockInput,
        budgets: Mapping[Any, int] | None = None,
    ) -> P0PlanResult:
        if now.tzinfo is None:
            raise ValueError("planner requires an aware instant")
        try:
            market = clock(now) if callable(clock) else clock
            day, session = market.trade_date, market.session
        except Exception:  # noqa: BLE001 - missing calendar coverage fails closed
            return P0PlanResult((), ("calendar_unavailable",))
        if not isinstance(day, dt.date) or not isinstance(session, MarketSession):
            return P0PlanResult((), ("calendar_unavailable",))
        if session not in ACTIVE_SESSIONS:
            return P0PlanResult((), (f"session:{session.value}",))
        records: list[P0PlanRecord] = []
        reasons: list[str] = []
        used: dict[Any, int] = {}
        duplicates = 0
        for cert in sorted(self._certificates(certificates), key=lambda c: str(c.licence_id)):
            cap = cert.budget if budgets is None else budgets.get(cert.licence_id, cert.budget)
            if cap is not None and cap < 0:
                raise ValueError("budget must be non-negative")
            stopped = (
                {str(c) for c in cert.suspended}
                if not isinstance(cert.suspended, Mapping)
                else {str(c) for c, flag in cert.suspended.items() if flag}
            )
            for entry in self.pool(
                holdings=cert.holdings, focus=cert.focus, watchlist=cert.watchlist
            ):
                key = f"p0:{cert.licence_id}:{day.isoformat()}:{session.value}:{entry.code}"
                if key in self._seen:
                    duplicates += 1
                    continue
                status, reason, cost = "planned", None, 1
                if entry.code in stopped:
                    status, reason, cost = "skipped", "suspended", 0
                elif cap is not None and used.get(cert.licence_id, 0) >= cap:
                    status, reason, cost = "skipped", "budget_exhausted", 0
                elif cap is not None:
                    used[cert.licence_id] = used.get(cert.licence_id, 0) + 1
                record = P0PlanRecord(
                    key,
                    cert.licence_id,
                    entry.code,
                    day,
                    session,
                    entry.layer,
                    entry.tier,
                    status=status,
                    reason=reason,
                    budget_cost=cost,
                )
                self._seen[key] = record
                records.append(record)
                if reason:
                    reasons.append(f"{cert.licence_id}:{entry.code}:{reason}")
        return P0PlanResult(tuple(records), tuple(reasons), used, duplicates)

    def manual_replan(self, plan_id: str) -> bool:
        """Allow one explicitly requested retry of a budget-skipped plan."""
        record = self._seen.get(plan_id)
        if record is None or record.status != "skipped" or record.reason != "budget_exhausted":
            return False
        del self._seen[plan_id]
        return True

    @staticmethod
    def _certificates(
        values: Mapping[Any, CertificateUniverse | Mapping[str, Any]]
        | Sequence[CertificateUniverse],
    ) -> list[CertificateUniverse]:
        if not isinstance(values, Mapping):
            return list(values)
        return [
            v if isinstance(v, CertificateUniverse) else CertificateUniverse(k, **dict(v))
            for k, v in values.items()
        ]


__all__ = [
    "ACTIVE_SESSIONS",
    "INTRADAY_ENABLED",
    "CertificateUniverse",
    "P0PlanRecord",
    "P0PlanResult",
    "P0Planner",
    "PoolEntry",
]

# ruff: noqa: ANN401
"""Owner-transactional candidate admission. No shared signal-event dependency or IO."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from collections.abc import Callable
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection, and_, func, insert, or_, select, text, update
from sqlalchemy.exc import SQLAlchemyError

from app.common.errors import AppError, ErrorCode
from app.config import get_settings
from app.config_files import MarketRulesConfig
from app.db.tables.accounts import accounts
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities, trading_calendar
from app.db.tables.research import action_plans, plan_versions, watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.signals import (
    candidate_signal_events as events,
)
from app.db.tables.signals import (
    candidate_signals as signals,
)
from app.db.tables.signals import (
    non_executable_reasons as reasons,
)
from app.db.tables.signals import (
    reason_status_events,
    user_restrictions,
)
from app.db.tables.strategy import (
    strategy_card_versions,
)
from app.db.tables.strategy import (
    strategy_instances as instances,
)
from app.db.tables.strategy import (
    strategy_versions as versions,
)
from app.db.tables.users import users
from app.importing.pipeline import live_snapshots
from app.market_rules.lots import lot_spec
from app.schemas.enums import Action, DataStatus, GapReason
from app.signals.admission import run_with_master_guard
from app.signals.execution import assess, condition
from app.signals.models import Gap, MarketFacts, SignalInput
from app.signals.screen import screen_membership
from app.strategy.instances.service import owned
from app.strategy.universe_norm import board_in_universe, normalize_universe
from app.suggestions.risk import effective_config

BJT = dt.timezone(dt.timedelta(hours=8))
SAME_TEMPLATE_COOLDOWN_TEXT = "同模板同证券冷却至到期交易日15:00（北京时间）"
TERMINAL = {"confirmed", "dismissed", "expired", "invalidated", "superseded"}
RESTRICTION_REASON_CODES = {
    "blocklist": "BLOCKLISTED",
    "mute": "USER_MUTED",
    "cooling_off": "COOLING_OFF",
}


def owned_signal(
    conn: Connection, user_id: uuid.UUID, signal_id: uuid.UUID, *, lock: bool = False
) -> Any:
    query = select(signals).where(signals.c.id == signal_id, signals.c.user_id == user_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).one_or_none()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def transition(
    conn: Connection,
    row: Any,
    target: str,
    cause: str,
    at: dt.datetime,
    detail: dict[str, Any] | None = None,
) -> None:
    if row.state == target:
        return
    conn.execute(
        update(signals)
        .where(signals.c.id == row.id, signals.c.created_at == row.created_at)
        .values(state=target, state_changed_at=at)
    )
    conn.execute(
        insert(events).values(
            id=uuid.uuid4(),
            signal_id=row.id,
            from_state=row.state,
            to_state=target,
            cause=cause,
            at=at,
            detail=detail,
        )
    )


def calendar_state(
    conn: Connection, at: dt.datetime, rules: MarketRulesConfig
) -> tuple[bool, dt.datetime | None]:
    day = at.astimezone(BJT).date()
    current = conn.execute(
        select(trading_calendar).where(trading_calendar.c.date == day)
    ).one_or_none()
    if current is None:
        lo, hi = conn.execute(
            select(func.min(trading_calendar.c.date), func.max(trading_calendar.c.date))
        ).one()
        raise AppError(
            ErrorCode.CALENDAR_NOT_COVERED,
            details={
                "date": day.isoformat(),
                "coverage_start": lo.isoformat() if lo else None,
                "coverage_end": hi.isoformat() if hi else None,
            },
        )
    segment = rules.segment_for(day)
    if segment is None:
        raise ValueError("market_rule_segment_missing")
    periods = segment.sessions
    clock = at.astimezone(BJT).time().replace(tzinfo=None)
    trading = bool(
        current.is_open
        and (
            periods.morning[0] <= clock < periods.morning[1]
            or periods.afternoon[0] <= clock < periods.closing_auction[1]
        )
    )
    # Only exchange-seeded dates; no weekday/holiday inference.
    next_day = (
        day
        if current.is_open and clock < periods.morning[0]
        else conn.execute(
            select(trading_calendar.c.date)
            .where(trading_calendar.c.date > day, trading_calendar.c.is_open.is_(True))
            .order_by(trading_calendar.c.date)
            .limit(1)
        ).scalar_one_or_none()
    )
    next_open = dt.datetime.combine(next_day, periods.morning[0], BJT) if next_day else None
    if not trading and next_open is None:
        raise AppError(
            ErrorCode.CALENDAR_NOT_COVERED,
            details={"date": day.isoformat(), "issue": "next_session_missing"},
        )
    return trading, next_open


def same_template_expiry(
    conn: Connection,
    previous_created_at: dt.datetime,
    cooldown_days: int,
) -> dt.datetime | None:
    """Return the Beijing 15:00 expiry using only sourced trading-calendar rows."""
    if cooldown_days <= 0:
        return dt.datetime.combine(previous_created_at.astimezone(BJT).date(), dt.time(15), BJT)
    start = previous_created_at.astimezone(BJT).date()
    rows = conn.execute(
        select(trading_calendar.c.date, trading_calendar.c.is_open)
        .where(trading_calendar.c.date >= start)
        .order_by(trading_calendar.c.date)
    ).all()
    if not rows or rows[0].date != start:
        return None
    local_time = previous_created_at.astimezone(BJT).time().replace(tzinfo=None)
    count_from = (
        start if rows[0].is_open and local_time < dt.time(15) else start + dt.timedelta(days=1)
    )

    open_days = 0
    for row in rows:
        if row.date < count_from:
            continue
        if row.is_open:
            open_days += 1
            if open_days == cooldown_days:
                return dt.datetime.combine(row.date, dt.time(15), BJT)
    return None


def same_template_release(expiry_at: dt.datetime) -> dict[str, Any]:
    return {
        "kind": "time",
        "expr": None,
        "at": expiry_at.isoformat(),
        "event": None,
        "action": None,
        "check_on": ["schedule"],
        "human_text": SAME_TEMPLATE_COOLDOWN_TEXT,
        "machine_checkable": True,
    }


def same_template_cooldown(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    security_code: str,
    strategy_version_id: uuid.UUID,
    created_at: dt.datetime,
    cooldown_days: int,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Find a visible same-template predecessor and derive its cooldown."""
    previous = conn.execute(
        select(signals.c.created_at)
        .where(
            signals.c.user_id == user_id,
            signals.c.security_code == security_code,
            signals.c.strategy_version_id == strategy_version_id,
            signals.c.created_at <= created_at,
        )
        .order_by(signals.c.created_at.desc(), signals.c.id.desc())
        .limit(1)
    ).one_or_none()
    if previous is None:
        return None, None
    expiry_at = same_template_expiry(conn, previous.created_at, cooldown_days)
    if expiry_at is None:
        return None, {
            "key": "same_template_cooldown",
            "reason": GapReason.NO_SOURCE.value,
            "message": "同模板冷却交易日历缺失或覆盖不足",
        }
    if created_at >= expiry_at:
        return None, None
    return same_template_release(expiry_at), None


def add_reason(
    conn: Connection,
    *,
    signal_id: uuid.UUID,
    user_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    code: str,
    release: dict[str, Any],
    at: dt.datetime,
    evidence: list[dict[str, Any]],
    salt: str = "",
) -> uuid.UUID:
    identifier = uuid.uuid5(signal_id, code + salt)
    if conn.execute(select(reasons.c.id).where(reasons.c.id == identifier)).first():
        return identifier
    conn.execute(
        insert(reasons).values(
            id=identifier,
            signal_id=signal_id,
            user_id=user_id,
            code=code,
            description=release["human_text"],
            evidence=evidence,
            epistemic_type="hypothesis"
            if any(item["epistemic_type"] == "hypothesis" for item in evidence)
            else "fact",
            detected_at=at,
            snapshot_id=snapshot_id,
            release_condition=release,
            check_on=release["check_on"],
            machine_checkable=release["machine_checkable"],
            next_check_at=release["at"],
            status="active",
            released_by="system",
        )
    )
    conn.execute(
        insert(reason_status_events).values(
            id=uuid.uuid4(), reason_id=identifier, from_status=None, to_status="active", at=at
        )
    )
    return identifier


def release_due_schedule_reasons(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    at: dt.datetime,
) -> list[uuid.UUID]:
    """Apply the existing schedule check to due time-based reasons."""
    candidate_signal_ids = {
        row.signal_id
        for row in conn.execute(
            select(reasons.c.signal_id).where(
                reasons.c.user_id == user_id, reasons.c.status == "active"
            )
        ).all()
    }
    candidate_rows = (
        conn.execute(
            select(signals)
            .where(signals.c.user_id == user_id, signals.c.id.in_(candidate_signal_ids))
            .order_by(signals.c.id)
            .with_for_update()
        ).all()
        if candidate_signal_ids
        else []
    )
    candidate_by_id = {row.id: row for row in candidate_rows}
    rows = conn.execute(
        select(reasons)
        .where(reasons.c.user_id == user_id, reasons.c.status == "active")
        .order_by(reasons.c.id)
        .with_for_update()
    ).all()
    released: list[uuid.UUID] = []
    for reason in rows:
        release = reason.release_condition or {}
        if release.get("kind") != "time" or "schedule" not in (release.get("check_on") or []):
            continue
        due = release.get("at")
        if not due:
            continue
        try:
            due_at = dt.datetime.fromisoformat(str(due))
        except ValueError:
            continue
        if due_at.tzinfo is None or due_at > at:
            continue
        evidence = {"scheduled_at": due_at.isoformat(), "rechecked_at": at.isoformat()}
        conn.execute(
            update(reasons)
            .where(reasons.c.id == reason.id, reasons.c.status == "active")
            .values(
                status="released",
                released_at=at,
                released_by="system",
                release_evidence=evidence,
            )
        )
        conn.execute(
            insert(reason_status_events).values(
                id=uuid.uuid4(),
                reason_id=reason.id,
                from_status="active",
                to_status="released",
                at=at,
                evaluated_value=evidence,
            )
        )
        released.append(reason.id)
        if not conn.execute(
            select(reasons.c.id).where(
                reasons.c.signal_id == reason.signal_id,
                reasons.c.user_id == user_id,
                reasons.c.status == "active",
            )
        ).first():
            signal = candidate_by_id.get(reason.signal_id)
            if signal is not None:
                transition(conn, signal, "released", "reason_released", at)
    return released


def recheck_restriction(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    restriction: Any,
    at: dt.datetime,
) -> tuple[list[uuid.UUID], list[uuid.UUID], list[dict[str, Any]]]:
    """Release reasons whose deleted restriction is their last active blocker.

    The restriction table has no foreign key to reasons.  The existing reason
    code and candidate ownership/target fields are therefore the association
    used by the admission path.  All rows are locked in the caller's write
    transaction before status events and signal transitions are written.
    """
    code = RESTRICTION_REASON_CODES.get(restriction.kind)
    if code is None:
        return [], [], []

    restriction_created_at = restriction.created_at
    candidate_conditions = [
        signals.c.user_id == user_id,
        signals.c.created_at < at,
    ]
    candidate_conditions.append(signals.c.created_at >= restriction_created_at)
    restriction_until = restriction.until
    if restriction_until is not None:
        candidate_conditions.append(signals.c.created_at < restriction_until)
    candidate_query = select(signals)
    if restriction.target_type == "security":
        candidate_conditions.append(signals.c.security_code == restriction.target_id)
    elif restriction.target_type == "instance":
        candidate_conditions.append(signals.c.instance_id == restriction.target_id)
    elif restriction.target_type == "strategy":
        try:
            strategy_id = uuid.UUID(str(restriction.target_id))
        except ValueError:
            return (
                [],
                [],
                [
                    {
                        "key": f"restriction:{restriction.id}",
                        "reason": "no_source",
                        "message": "关联策略标识无效，无法重查",
                    }
                ],
            )
        candidate_query = candidate_query.join(
            versions, versions.c.id == signals.c.strategy_version_id
        )
        candidate_conditions.append(versions.c.strategy_id == strategy_id)
    else:
        return (
            [],
            [],
            [
                {
                    "key": f"restriction:{restriction.id}",
                    "reason": "no_source",
                    "message": "限制目标类型未知，无法重查",
                }
            ],
        )

    # Lock candidates before locking their reasons.  The delete endpoint has
    # already marked the restriction removed in this same transaction, while
    # candidate.created_at keeps the historical point-in-time boundary.
    candidate_rows = conn.execute(
        candidate_query.where(*candidate_conditions).with_for_update()
    ).all()
    candidate_by_id = {row.id: row for row in candidate_rows}
    candidate_ids = set(candidate_by_id)
    if not candidate_ids:
        return [], [], []
    reason_conditions = [
        reasons.c.user_id == user_id,
        reasons.c.code == code,
        reasons.c.status == "active",
    ]
    reason_conditions.append(reasons.c.signal_id.in_(candidate_ids))
    reason_rows = conn.execute(
        select(reasons).where(*reason_conditions).order_by(reasons.c.id).with_for_update()
    ).all()
    if not reason_rows:
        return [], [], []

    strategy_ids = {
        row.strategy_version_id for row in candidate_rows if row.strategy_version_id is not None
    }
    strategy_rows = (
        conn.execute(
            select(versions.c.id, versions.c.strategy_id).where(versions.c.id.in_(strategy_ids))
        ).all()
        if strategy_ids
        else []
    )
    strategies_by_version = {row.id: row.strategy_id for row in strategy_rows}
    remaining_restrictions = conn.execute(
        select(user_restrictions)
        .where(
            user_restrictions.c.user_id == user_id,
            user_restrictions.c.id != restriction.id,
            user_restrictions.c.removed_at.is_(None),
        )
        .with_for_update()
    ).all()

    def matches_target(candidate: Any, r: Any = restriction) -> bool:
        target_type = r.target_type
        if target_type == "security":
            return bool(candidate.security_code == r.target_id)
        if target_type == "instance":
            return bool(str(candidate.instance_id) == r.target_id)
        if target_type == "strategy":
            return bool(
                str(strategies_by_version.get(candidate.strategy_version_id)) == str(r.target_id)
            )
        return False

    def covered_by_other_restriction(candidate: Any) -> bool:
        candidate_created_at = candidate.created_at
        for other in remaining_restrictions:
            if other.kind != restriction.kind or not matches_target(candidate, other):
                continue
            if other.created_at > candidate_created_at:
                continue
            if other.until is not None and candidate_created_at >= other.until:
                continue
            return True
        return False

    released: list[uuid.UUID] = []
    remaining: list[uuid.UUID] = []
    gaps: list[dict[str, Any]] = []
    released_signal_ids: set[uuid.UUID] = set()
    for reason in reason_rows:
        reason_id = reason.id
        candidate = candidate_by_id.get(reason.signal_id)
        if candidate is None:
            remaining.append(reason_id)
            gaps.append(
                {
                    "key": f"reason:{reason_id}",
                    "reason": "no_source",
                    "message": "关联候选信号缺失，无法重查",
                }
            )
            continue
        if restriction.target_type == "strategy" and candidate.strategy_version_id not in (
            strategies_by_version
        ):
            gaps.append(
                {
                    "key": f"reason:{reason_id}",
                    "reason": "no_source",
                    "message": "关联策略版本缺失，无法重查",
                }
            )
            continue
        if not matches_target(candidate):
            continue
        if covered_by_other_restriction(candidate):
            remaining.append(reason_id)
            continue
        evidence = {
            "restriction_id": str(restriction.id),
            "rechecked_at": at.isoformat(),
        }
        conn.execute(
            update(reasons)
            .where(reasons.c.id == reason_id, reasons.c.status == "active")
            .values(
                status="released",
                released_at=at,
                released_by="system",
                release_evidence=evidence,
            )
        )
        conn.execute(
            insert(reason_status_events).values(
                id=uuid.uuid4(),
                reason_id=reason_id,
                from_status="active",
                to_status="released",
                at=at,
                evaluated_value=evidence,
            )
        )
        released.append(reason_id)
        released_signal_ids.add(candidate.id)

    for signal_id in released_signal_ids:
        signal = conn.execute(
            select(signals)
            .where(signals.c.id == signal_id, signals.c.user_id == user_id)
            .with_for_update()
        ).one_or_none()
        if signal is None or signal.state != "blocked":
            continue
        if (
            conn.execute(
                select(reasons.c.id).where(
                    reasons.c.signal_id == signal_id,
                    reasons.c.user_id == user_id,
                    reasons.c.status == "active",
                )
            ).first()
            is None
        ):
            transition(conn, signal, "released", "reason_released", at)
    return released, remaining, gaps


def snapshot_items(content: SignalInput, facts: MarketFacts) -> dict[str, Any]:
    """Opaque immutable input payload for the existing data_snapshots table.

    The trusted producer persists this under content.snapshot_id with the owner;
    values/evidence and execution facts remain traceable, not merely a status label.
    """
    return {
        "schema_version": "tb74-evaluated-v1",
        "signal_input": content.model_dump(mode="json"),
        "market_facts": facts.model_dump(mode="json"),
        "data_status_block": {
            "data_status": content.data_status.value,
            "data_as_of": content.data_as_of.isoformat(),
            "gaps": [gap.model_dump(mode="json") for gap in content.gaps],
        },
    }


def add_same_template_gap(content: SignalInput, gap: dict[str, str] | None) -> SignalInput:
    """Include a cooldown source gap in the immutable signal input once."""
    if gap is None or any(item.key == gap["key"] for item in content.gaps):
        return content
    return content.model_copy(
        update={
            "data_status": (
                DataStatus.PARTIAL
                if content.data_status == DataStatus.FRESH
                else content.data_status
            ),
            "gaps": [*content.gaps, Gap.model_validate(gap)],
        }
    )


def configured_same_template_days(
    conn: Connection, user_id: uuid.UUID, explicit: int | None
) -> int:
    if explicit is not None:
        return explicit
    return effective_config(
        conn, user_id, get_settings().business.risk_controls
    ).executability.same_template_cooldown_days


def write_candidate(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    instance_id: uuid.UUID,
    content: SignalInput,
    facts: MarketFacts,
    market_rules: MarketRulesConfig,
    same_template_cooldown_days: int | None = None,
    origin_signal_event_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    """Trusted producer input, never a public user-authored signal. Caller owns transaction."""
    if (
        conn.execute(select(users.c.status).where(users.c.id == user_id)).scalar_one_or_none()
        != "approved"
    ):
        return {"id": None, "diagnostic": "user_not_approved"}
    if content.proposed_action in {"hold", "wait"}:
        return {"id": None, "diagnostic": "no_candidate_action"}
    same_template_cooldown_days = configured_same_template_days(
        conn, user_id, same_template_cooldown_days
    )
    # Shared owner lock serializes opposite strategies as well as snapshot replays.
    conn.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"), {"owner": str(user_id)}
    )
    instance = owned(conn, user_id, instance_id, lock=True)
    if instance.status != "active":
        return {"id": None, "diagnostic": "instance_not_active"}
    actual = instance.derived_strategy_version_id or instance.strategy_version_id
    version = conn.execute(select(versions).where(versions.c.id == actual)).one()
    cooldown, cooldown_gap = same_template_cooldown(
        conn,
        user_id=user_id,
        security_code=content.security_code,
        strategy_version_id=actual,
        created_at=content.created_at,
        cooldown_days=same_template_cooldown_days,
    )
    content = add_same_template_gap(content, cooldown_gap)
    from app.db.tables.strategy import strategies

    template_owner = conn.execute(
        select(strategies.c.owner_user_id).where(strategies.c.id == version.strategy_id)
    ).scalar_one()
    if template_owner is not None and template_owner != user_id:
        raise AppError(ErrorCode.NOT_FOUND)
    from app.strategy.runtime import runnable

    role = conn.execute(select(users.c.role).where(users.c.id == user_id)).scalar_one()
    if not runnable(version.lifecycle, role):
        return {"id": None, "diagnostic": "version_not_runnable"}
    declared_rules = {
        rule["id"]: rule for rule in version.config.get("spec", version.config).get("rules", [])
    }
    if not declared_rules:
        return {"id": None, "diagnostic": "version_rules_not_defined"}
    for reference in content.rule_refs:
        declared = declared_rules.get(reference.rule_id)
        if (
            declared is None
            or declared.get("role") != reference.role
            or declared.get("dimension") != reference.dimension
            or declared.get("expr") != reference.threshold
        ):
            raise AppError(ErrorCode.SIGNAL_NOT_EXPLAINABLE)
    if instance.scope == "watch_group":
        return {"id": None, "diagnostic": "scope_deferred"}
    if instance.scope == "security" and instance.security_code != content.security_code:
        return {"id": None, "diagnostic": "scope_mismatch"}
    account = conn.execute(
        select(accounts)
        .where(
            accounts.c.id == instance.account_id,
            accounts.c.user_id == user_id,
            accounts.c.archived_at.is_(None),
        )
        .with_for_update()
    ).one_or_none()
    if account is None:
        raise AppError(ErrorCode.NOT_FOUND)
    snapshot = conn.execute(
        select(data_snapshots).where(
            data_snapshots.c.id == content.snapshot_id, data_snapshots.c.user_id == user_id
        )
    ).one_or_none()
    if snapshot is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if (
        snapshot.licence_id is not None
        and not conn.execute(
            select(user_data_licences.c.id).where(
                user_data_licences.c.id == snapshot.licence_id,
                user_data_licences.c.user_id == user_id,
            )
        ).first()
    ):
        raise AppError(ErrorCode.NOT_FOUND)
    if snapshot.created_at > content.created_at:
        raise ValueError("future_snapshot")
    day = content.created_at.astimezone(BJT).date()
    from app.api.v1.portfolio import _account

    portfolio = _account(conn, account.id, day)
    position = portfolio.positions.get(content.security_code)
    qty = position.qty if position else Decimal(0)
    sellable = position.sellable if position else Decimal(0)
    watched = bool(
        conn.execute(
            select(watchlist_items.c.id).where(
                watchlist_items.c.user_id == user_id,
                watchlist_items.c.security_code == content.security_code,
                watchlist_items.c.removed_at.is_(None),
            )
        ).first()
    )
    fields = (
        conn.execute(
            select(strategy_card_versions.c.fields).where(
                strategy_card_versions.c.id == version.card_version_id
            )
        ).scalar_one_or_none()
        if version.card_version_id
        else None
    )
    universe = normalize_universe(
        (fields or {}).get("universe", version.config.get("universe")),
        screen=(version.config or {}).get("screen", (fields or {}).get("screen")),
    )
    mount_policy = (fields or {}).get("mount_policy", version.config.get("mount_policy", "user"))
    diag = screen_membership(
        universe=universe,
        quantity=qty,
        on_watchlist=watched,
        mount_policy=str(mount_policy or "user"),
        proposed_action=content.proposed_action,
    )
    if diag is not None:
        return {"id": None, "diagnostic": diag}
    identity = f"{user_id}:{instance_id}:{actual}:{content.snapshot_id}:{content.security_code}"
    key = hashlib.sha256(identity.encode()).hexdigest()
    existing = conn.execute(
        select(signals.c.id).where(
            signals.c.user_id == user_id,
            signals.c.instance_id == instance_id,
            signals.c.cooldown_key == key,
        )
    ).scalar_one_or_none()
    if existing:
        return {"id": str(existing), "diagnostic": "snapshot_already_evaluated"}

    def persist(locked: Connection) -> dict[str, Any]:
        master = locked.execute(
            select(securities).where(securities.c.code == content.security_code)
        ).one()
        if master.type not in (universe or {}).get("security_types", []) or not board_in_universe(
            (universe or {}).get("boards"),
            master.board,
        ):
            return {"id": None, "diagnostic": "outside_universe"}
        if (fields or {}).get(
            "mount_policy", version.config.get("mount_policy")
        ) == "system_only" and content.proposed_action not in {"reduce", "sell"}:
            return {"id": None, "diagnostic": "system_exit_only"}
        segment = market_rules.segment_for(day)
        if segment is None:
            raise ValueError("market_rule_segment_missing")
        lot = lot_spec(segment, board=master.board, security_type=master.type)
        snap = locked.execute(
            live_snapshots(account.id).order_by(text("version_no DESC")).limit(1)
        ).one_or_none()
        cash = snap.cash_available if snap and snap.cash_available is not None else portfolio.cash
        trading, next_open = calendar_state(locked, content.created_at, market_rules)
        blockers = assess(
            content,
            facts,
            qty=qty,
            sellable=sellable,
            cash=cash,
            min_buy=lot.min_buy,
            min_sell=lot.min_buy,
            risk_flag=master.risk_flag,
            trading=trading,
            next_open=next_open,
        )
        for flag in content.risk_flags:
            if content.proposed_action not in flag.gated_actions:
                continue
            if (
                flag.control in {"total_exposure", "sector_concentration"}
                and content.t_leg is not None
            ):
                continue
            code = {
                "position_cap": "POSITION_CAP_REACHED",
                "total_exposure": "REGIME_MISMATCH",
                "sector_concentration": "SECTOR_EXPOSURE_EXCEEDED",
                "loss_streak_drawdown": "LOSS_STREAK_PAUSE",
            }.get(flag.control)
            if code is None:
                return {"id": None, "diagnostic": "risk_hook_mapping_not_defined"}
            details = [
                d for d in content.risk_details if d.control == flag.control and d.code == code
            ]
            blockers.append(
                {
                    "code": code,
                    "release_condition": condition(code),
                    "risk_details": [d.model_dump(mode="json") for d in details],
                }
            )
        for restriction in locked.execute(
            select(user_restrictions).where(
                user_restrictions.c.user_id == user_id,
                user_restrictions.c.created_at <= content.created_at,
                or_(
                    user_restrictions.c.removed_at.is_(None),
                    user_restrictions.c.removed_at > content.created_at,
                ),
                or_(
                    and_(
                        user_restrictions.c.target_type == "security",
                        user_restrictions.c.target_id == content.security_code,
                    ),
                    and_(
                        user_restrictions.c.target_type == "instance",
                        user_restrictions.c.target_id == str(instance_id),
                    ),
                    and_(
                        user_restrictions.c.target_type == "strategy",
                        user_restrictions.c.target_id == str(version.strategy_id),
                    ),
                ),
            )
        ):
            if restriction.until is not None and restriction.until <= content.created_at:
                continue
            code = {"blocklist": "BLOCKLISTED", "mute": "USER_MUTED", "cooling_off": "COOLING_OFF"}[
                restriction.kind
            ]
            blockers.append(
                {"code": code, "release_condition": condition(code, at=restriction.until)}
            )
        plans = (
            locked.execute(
                select(plan_versions.c.action)
                .select_from(
                    action_plans.join(
                        plan_versions, action_plans.c.current_version_id == plan_versions.c.id
                    )
                )
                .where(
                    action_plans.c.user_id == user_id,
                    action_plans.c.security_code == content.security_code,
                    action_plans.c.status.in_(["active", "triggered"]),
                )
            )
            .scalars()
            .all()
        )
        buy = content.proposed_action in {"buy", "add"}
        for action in plans:
            same = (action in {"buy", "add"}) == buy
            code = "SAME_DIRECTION_PLAN_EXISTS" if same else "CONFLICTS_CONFIRMED_PLAN"
            blockers.append(
                {
                    "code": code,
                    "release_condition": {
                        "kind": "event" if same else "user_action",
                        "expr": None,
                        "at": None,
                        "event": "plan.closed" if same else None,
                        "action": None if same else "modify_or_close_plan",
                        "check_on": ["plan_change"] if same else ["user_action"],
                        "human_text": "该计划进入终止状态"
                        if same
                        else "用户修改或关闭相反方向计划",
                        "machine_checkable": same,
                    },
                }
            )
        identifier = uuid.uuid5(uuid.NAMESPACE_URL, "tb74:" + identity)
        body = content.model_dump(mode="json")
        body.pop("risk_details", None)
        for name in ["data_status", "data_as_of", "gaps", "snapshot_id", "created_at"]:
            body.pop(name)
        body["confidence_level"] = body["confidence"]["level"]
        body["confidence"] = body["confidence"]["value"]
        # DataStatusBlock stays with the immutable owned input snapshot; no schema invention.
        status_block = (
            snapshot.items.get("data_status_block") if isinstance(snapshot.items, dict) else None
        )
        expected = {
            "data_status": content.data_status.value,
            "data_as_of": content.data_as_of.isoformat(),
            "gaps": [gap.model_dump(mode="json") for gap in content.gaps],
        }
        if snapshot.items.get("signal_input") != content.model_dump(
            mode="json"
        ) or snapshot.items.get("market_facts") != facts.model_dump(mode="json"):
            raise ValueError("snapshot_evaluation_or_market_facts_mismatch")
        if status_block != expected:
            raise ValueError("snapshot_data_status_block_missing_or_mismatch")
        opposites = locked.execute(
            select(signals)
            .where(
                signals.c.user_id == user_id,
                signals.c.security_code == content.security_code,
                signals.c.instance_id != instance_id,
                signals.c.state.in_(["open", "blocked", "released", "drafted"]),
                signals.c.proposed_action.in_(["reduce", "sell"] if buy else ["buy", "add"]),
            )
            .with_for_update()
        ).all()
        conflict = {
            "kind": "user_action",
            "expr": None,
            "at": None,
            "event": None,
            "action": "choose_strategy",
            "check_on": ["user_action", "tick"],
            "human_text": "用户选择采用某一方或重评后冲突消失",
            "machine_checkable": False,
        }
        if opposites:
            blockers.append({"code": "STRATEGY_CONFLICT", "release_condition": conflict})
        gaps: list[dict[str, str]] = []
        gap = cooldown_gap
        if gap is not None:
            gaps.append(gap)
        if cooldown is not None:
            blockers.append(
                {
                    "code": "SAME_TEMPLATE_COOLDOWN",
                    "release_condition": cooldown,
                }
            )
        state = "blocked" if blockers else "open"
        locked.execute(
            insert(signals).values(
                **body,
                origin_signal_event_id=origin_signal_event_id,
                id=identifier,
                user_id=user_id,
                instance_id=instance_id,
                strategy_version_id=actual,
                horizon=instance.horizon,
                snapshot_id=content.snapshot_id,
                created_at=content.created_at,
                state=state,
                state_changed_at=content.created_at,
                cooldown_key=key,
                gate_results=[
                    {
                        "gate": "gate_tradability",
                        "passed": not any(
                            b["code"]
                            in {"SUSPENDED", "ST_OR_DELISTING", "NEW_LISTING", "LIMIT_LOCKED"}
                            for b in blockers
                        ),
                    }
                ]
                + [
                    {
                        "gate": "gate_risk_" + detail["control"],
                        "passed": False,
                        "code": detail["code"],
                        "detail": detail["detail"],
                        "evidence_ids": detail["evidence_ids"],
                    }
                    for blocker in blockers
                    for detail in blocker.get("risk_details", [])
                ],
            )
        )
        locked.execute(
            insert(events).values(
                id=uuid.uuid4(),
                signal_id=identifier,
                from_state=None,
                to_state=state,
                cause="executability_check",
                detail={"signal_event_id": str(origin_signal_event_id)}
                if origin_signal_event_id
                else None,
                at=content.created_at,
            )
        )

        def conflict_evidence(peer_id: uuid.UUID) -> list[dict[str, Any]]:
            return [
                {
                    "id": "conflict-" + str(peer_id),
                    "key": "signal.conflict_signal_id",
                    "value": str(peer_id),
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "epistemic_type": "fact",
                    "data_as_of": content.created_at.isoformat(),
                    "fetched_at": content.created_at.isoformat(),
                }
            ]

        for peer in opposites:
            add_reason(
                locked,
                signal_id=peer.id,
                user_id=user_id,
                snapshot_id=peer.snapshot_id,
                code="STRATEGY_CONFLICT",
                release=conflict,
                at=content.created_at,
                evidence=conflict_evidence(identifier),
                salt=str(identifier),
            )
            transition(locked, peer, "blocked", "executability_check", content.created_at)
        for blocker in blockers:
            add_reason(
                locked,
                signal_id=identifier,
                user_id=user_id,
                snapshot_id=content.snapshot_id,
                code=blocker["code"],
                release=blocker["release_condition"],
                at=content.created_at,
                evidence=(
                    [item for peer in opposites for item in conflict_evidence(peer.id)]
                    if blocker["code"] == "STRATEGY_CONFLICT"
                    else content.model_dump(mode="json")["evidence"]
                ),
            )
        result: dict[str, Any] = {"id": str(identifier), "diagnostic": state}
        if gaps:
            result["gaps"] = gaps
        return result

    admission, result = run_with_master_guard(
        conn,
        security_code=content.security_code,
        action=Action(content.proposed_action),
        trade_date=day,
        operation=persist,
    )
    return result if result is not None else {"id": None, "diagnostic": admission.diagnostic}


def post_close_for_user(
    conn: Connection,
    *,
    user_id: uuid.UUID,
    produce: Callable[[Any], list[tuple[SignalInput, MarketFacts]]],
    market_rules: MarketRulesConfig,
) -> list[dict[str, Any]]:
    """Direct owner branch. Supplied producer must be deterministic T-B72 + output assembler.

    This is not Celery/signal-rt registration and never consumes shared market events.
    Individual instances use savepoints; caller decides transaction/retry policy.
    """
    result = []
    for instance in conn.execute(
        select(instances)
        .where(instances.c.user_id == user_id, instances.c.status == "active")
        .order_by(instances.c.id)
    ).all():
        try:
            instance_result = []
            cooldown_days = configured_same_template_days(conn, user_id, None)
            with conn.begin_nested():
                for content, facts in produce(instance):
                    instance_result.append(
                        write_candidate(
                            conn,
                            user_id=user_id,
                            instance_id=instance.id,
                            content=content,
                            facts=facts,
                            market_rules=market_rules,
                            same_template_cooldown_days=cooldown_days,
                        )
                    )
            result.extend(instance_result)
        except (AppError, ValueError, SQLAlchemyError) as error:
            result.append(
                {
                    "id": None,
                    "instance_id": str(instance.id),
                    "diagnostic": "instance_failed",
                    "error_type": type(error).__name__,
                }
            )
    return result

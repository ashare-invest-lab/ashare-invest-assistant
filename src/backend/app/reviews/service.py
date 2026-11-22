"""复盘读写服务，版本内容由不可变快照投影。"""
# ruff: noqa: ANN401, E501

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Sequence
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, insert, select, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import trades
from app.db.tables.market import securities
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.reviews import data_snapshots, review_versions, reviews
from app.reviews.metrics import (
    METRIC_NAMES,
    _stat,
    empty_metrics,
    normalise_gaps,
    project_metrics,
    status_block,
)

# fmt: off

SHANGHAI = ZoneInfo("Asia/Shanghai")


def _bad(field: str, issue: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]})


def _owned(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, *, lock: bool = False) -> Row[Any]:
    statement = select(reviews).where(reviews.c.id == identifier, reviews.c.user_id == owner)
    row = conn.execute(statement.with_for_update() if lock else statement).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def _code(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip().upper()
    if len(value) == 6 and value.isdigit():
        value = f"{value}.SH" if value.startswith(("5", "6", "9")) else f"{value}.SZ"
    if len(value) != 9 or value[6] != "." or not value[:6].isdigit() or value[7:] not in {"SH", "SZ", "BJ"}:
        raise _bad("security_code", "invalid")
    return value


def _validate_links(
    conn: Connection,
    owner: uuid.UUID,
    *,
    plan_id: uuid.UUID | None,
    security_code: str | None,
    plan_version_ids: Sequence[uuid.UUID],
    trade_ids: Sequence[uuid.UUID],
) -> tuple[str | None, Row[Any] | None]:
    plan = None
    code = _code(security_code)
    if plan_id is None and code is None:
        raise _bad("plan_id", "plan_or_security_required")
    if plan_id is not None:
        plan = conn.execute(select(action_plans).where(action_plans.c.id == plan_id, action_plans.c.user_id == owner)).first()
        if plan is None:
            raise _bad("plan_id", "not_found")
        if code is not None and plan.security_code != code:
            raise _bad("security_code", "inconsistent_with_plan")
        code = str(plan.security_code)
    if plan_version_ids:
        rows = conn.execute(select(plan_versions.c.id, plan_versions.c.plan_id, action_plans.c.security_code).join(action_plans, action_plans.c.id == plan_versions.c.plan_id).where(plan_versions.c.id.in_(plan_version_ids), action_plans.c.user_id == owner)).all()
        if len(rows) != len(set(plan_version_ids)):
            raise _bad("plan_version_ids", "not_owned")
        if plan_id is not None and any(r.plan_id != plan_id for r in rows):
            raise _bad("plan_version_ids", "inconsistent_with_plan")
        if code is not None and any(r.security_code != code for r in rows):
            raise _bad("plan_version_ids", "inconsistent_with_security")
        if code is None:
            code = str(rows[0].security_code)
    if trade_ids:
        # source is deliberately not filtered here. The table's source enum has
        # only real-import values. Simulated rows are excluded in the metric
        # projection, where their epistemic type is visible.
        rows = conn.execute(select(trades.c.id, trades.c.security_code, trades.c.plan_version_id).where(trades.c.id.in_(trade_ids), trades.c.user_id == owner, trades.c.voided_at.is_(None))).all()
        if len(rows) != len(set(trade_ids)):
            raise _bad("trade_ids", "not_owned")
        if code is not None and any(r.security_code != code for r in rows):
            raise _bad("trade_ids", "inconsistent_with_security")
        if plan_version_ids and any(r.plan_version_id not in plan_version_ids for r in rows):
            raise _bad("trade_ids", "inconsistent_with_plan")
        if plan_id is not None and not plan_version_ids:
            valid = {r.id for r in conn.execute(select(plan_versions.c.id).where(plan_versions.c.plan_id == plan_id)).all()}
            if any(r.plan_version_id not in valid for r in rows):
                raise _bad("trade_ids", "inconsistent_with_plan")
        if code is None:
            code = str(rows[0].security_code)
    return code, plan


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_datetime(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _executed_at(row: Any) -> dt.datetime | None:
    traded_at = _as_datetime(getattr(row, "traded_at", None))
    if traded_at is not None:
        return traded_at
    trade_date = getattr(row, "trade_date", None)
    if isinstance(trade_date, dt.datetime):
        trade_date = trade_date.date()
    if isinstance(trade_date, dt.date):
        return dt.datetime.combine(
            trade_date,
            dt.time(15),
            tzinfo=SHANGHAI,
        ).astimezone(dt.UTC)
    return None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _trade_rows(conn: Connection, owner: uuid.UUID, trade_ids: Sequence[uuid.UUID]) -> list[Any]:
    if not trade_ids:
        return []
    return list(conn.execute(select(trades).where(trades.c.id.in_(trade_ids), trades.c.user_id == owner)).all())


def _fifo_holding(rows: Sequence[Any]) -> tuple[list[Decimal], bool]:
    """Pair execution cash flows FIFO and report returns for closed lots."""
    openings_by_code: dict[str, list[tuple[Decimal, Decimal]]] = {}
    holding: list[Decimal] = []
    for row in sorted(rows, key=lambda item: (_executed_at(item), str(item.id))):
        quantity = _decimal(row.quantity)
        net_amount = _decimal(row.net_amount)
        openings = openings_by_code.setdefault(str(row.security_code), [])
        if quantity is None or quantity <= 0 or net_amount is None:
            continue
        unit_cash = abs(net_amount) / quantity
        if unit_cash <= 0:
            continue
        if row.side == "buy":
            openings.append((unit_cash, quantity))
            continue
        if row.side != "sell":
            continue
        remaining = quantity
        while remaining > 0 and openings:
            buy_unit_cash, buy_quantity = openings[0]
            matched = min(remaining, buy_quantity)
            holding.append((unit_cash / buy_unit_cash - Decimal(1)) * Decimal(100))
            remaining -= matched
            buy_quantity -= matched
            if buy_quantity == 0:
                openings.pop(0)
            else:
                openings[0] = (buy_unit_cash, buy_quantity)
    return holding, any(openings_by_code.values())


def _observations(
    rows: Sequence[Any],
    calculation_as_of: dt.datetime,
    period_start: dt.date,
    period_end: dt.date,
) -> tuple[list[Decimal], list[Decimal], list[Decimal], list[str], dt.datetime | None, bool]:
    visible: list[Any] = []
    evidence_ids: list[str] = []
    data_as_of: dt.datetime | None = None
    calculation_as_of_normalized = (
        calculation_as_of
        if calculation_as_of.tzinfo
        else calculation_as_of.replace(tzinfo=dt.UTC)
    )
    for row in rows:
        traded_at = _executed_at(row)
        if row.voided_at is not None or row.epistemic_type != "execution":
            continue
        if traded_at is None or traded_at > calculation_as_of_normalized:
            continue
        if traded_at.date() < period_start or traded_at.date() > period_end:
            continue
        visible.append(row)
        evidence_ids.append("trade:" + str(row.id))
        data_as_of = max(data_as_of, traded_at) if data_as_of else traded_at
    holding, has_open_positions = _fifo_holding(visible)
    return holding, [], [], evidence_ids, data_as_of, has_open_positions


def _compute_outcome_metrics(
    conn: Connection,
    owner: uuid.UUID,
    start: dt.date,
    end: dt.date,
    trade_ids: Sequence[uuid.UUID],
    calculation_as_of: dt.datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], dt.datetime | None]:
    window = f"{start.isoformat()}/{end.isoformat()}"
    rows = _trade_rows(conn, owner, trade_ids)
    _, _, _, evidence_ids, data_as_of, _ = _observations(rows, calculation_as_of, start, end)
    evidence = [{"id": evidence_id, "key": "trade", "value": evidence_id.removeprefix("trade:"), "source": "本人成交快照"} for evidence_id in evidence_ids]
    reason = "user_input_missing" if not trade_ids else "no_source"
    metrics = {name: _stat(window) | {"gaps": [reason]} for name in METRIC_NAMES}
    return metrics, evidence, data_as_of


def _snapshot_items(
    start: dt.date,
    end: dt.date,
    lessons: str | None,
    tags: list[str],
    judgement: list[dict[str, Any]],
    has_trades: bool,
    *,
    conn: Connection | None = None,
    owner: uuid.UUID | None = None,
    trade_ids: Sequence[uuid.UUID] = (),
    plan_version_ids: Sequence[uuid.UUID] = (),
    calculation_as_of: dt.datetime | None = None,
) -> dict[str, Any]:
    calculation_as_of = calculation_as_of or _now()
    if conn is not None and owner is not None:
        metrics, evidence, data_as_of = _compute_outcome_metrics(conn, owner, start, end, trade_ids, calculation_as_of)
    else:
        metrics, evidence, data_as_of = empty_metrics(start, end), [], None
    has_metric_value = any(metric.get("value") is not None for metric in metrics.values())
    if has_metric_value:
        block = status_block(has_observation=True)
    else:
        block = status_block(reason="no_source" if has_trades else "user_input_missing")
    metric_messages = {
        "holding_return": "未验证：以 traded_at 作可见时点；未平仓部分未计入",
        "benchmark_return": "基准价格缺失，指标未验证（待回测）",
        "excess_return": "基准价格缺失，超额收益未验证（待回测）",
        "max_drawdown": "复权价格路径缺失，最大回撤未验证（待回测）",
    }
    metric_gaps = [
        {
            "key": f"outcome_metrics.{name}",
            "reason": reason,
            "message": metric_messages[name],
        }
        for name, metric in metrics.items()
        for reason in metric.get("gaps", [])
    ]
    if metric_gaps:
        block["gaps"] = metric_gaps
    plan_snapshot = {
        "plan_version_ids": [str(identifier) for identifier in plan_version_ids],
        "judgement": judgement,
        "lessons": lessons,
        "tags": tags,
    }
    if not evidence:
        evidence = [
            {
                "id": "trade:" + str(identifier),
                "key": "trade",
                "value": str(identifier),
                "source": "本人成交快照",
            }
            for identifier in trade_ids
        ]
    plan_evidence = [
        {
            "id": "plan:" + str(identifier),
            "key": "plan_version",
            "value": str(identifier),
            "source": "本人计划版本快照",
        }
        for identifier in plan_version_ids
    ]
    evidence = plan_evidence + evidence
    outcome_snapshot = {"trade_ids": [str(identifier) for identifier in trade_ids], "metrics": metrics, "evidence": evidence}
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "outcome_metrics": metrics,
        "attribution": {
            "judgement": judgement,
            "execution": ([{"text": "本人实际成交已冻结", "evidence_ids": [item["id"] for item in evidence]}] if evidence else []),
            "market": [],
        },
        "lessons": lessons,
        "tags": tags,
        "plan_snapshot": plan_snapshot,
        "outcome_snapshot": outcome_snapshot,
        "plan": plan_snapshot,
        "outcome": outcome_snapshot,
        "calculation_as_of": calculation_as_of.isoformat(),
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "evidence": evidence,
        **block,
    }


def _new_version(
    conn: Connection,
    owner: uuid.UUID,
    review_id: uuid.UUID,
    version_no: int,
    *,
    start: dt.date,
    end: dt.date,
    plan_version_ids: list[uuid.UUID],
    trade_ids: list[uuid.UUID],
    lessons: str | None,
    tags: list[str],
    judgement: list[dict[str, Any]],
) -> Row[Any]:
    snapshot_id, version_id = uuid.uuid4(), uuid.uuid4()
    calculation_as_of = _now()
    items = _snapshot_items(start, end, lessons, tags, judgement, bool(trade_ids), conn=conn, owner=owner, trade_ids=trade_ids, plan_version_ids=plan_version_ids, calculation_as_of=calculation_as_of)
    raw = json.dumps(items, sort_keys=True, default=str, ensure_ascii=False).encode()
    conn.execute(insert(data_snapshots).values(id=snapshot_id, user_id=owner, purpose="review", items=items, hash=hashlib.sha256(raw).hexdigest()))
    conn.execute(insert(review_versions).values(id=version_id, review_id=review_id, version_no=version_no, plan_version_ids=plan_version_ids, trade_ids=trade_ids, outcome_metrics=items["outcome_metrics"], attribution=items["attribution"], lessons=lessons, tags=tags, snapshot_id=snapshot_id))
    return conn.execute(select(review_versions).where(review_versions.c.id == version_id)).one()


def create(conn: Connection, owner: uuid.UUID, body: Any) -> uuid.UUID:
    if body.period_end < body.period_start:
        raise _bad("period_end", "before_period_start")
    code, _ = _validate_links(conn, owner, plan_id=body.plan_id, security_code=body.security_code, plan_version_ids=body.plan_version_ids, trade_ids=body.trade_ids)
    review_id = uuid.uuid4()
    conn.execute(insert(reviews).values(id=review_id, user_id=owner, plan_id=body.plan_id, security_code=code, period_start=body.period_start, period_end=body.period_end))
    version = _new_version(conn, owner, review_id, 1, start=body.period_start, end=body.period_end, plan_version_ids=list(body.plan_version_ids), trade_ids=list(body.trade_ids), lessons=body.lessons, tags=list(body.tags), judgement=[j.model_dump(mode="json") for j in body.judgement])
    conn.execute(update(reviews).where(reviews.c.id == review_id).values(current_version_id=version.id))
    return review_id


def revise(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, body: Any) -> uuid.UUID:
    review = _owned(conn, owner, identifier, lock=True)
    if review.current_version_id is None:
        raise AppError(ErrorCode.NOT_FOUND)
    current = conn.execute(select(review_versions).where(review_versions.c.id == review.current_version_id)).first()
    if current is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if body.base_version_no != current.version_no:
        raise AppError(ErrorCode.VERSION_CONFLICT, details={"current_version_no": current.version_no})
    plan_id, code = body.plan_id, body.security_code
    start, end = body.period_start, body.period_end
    if end < start:
        raise _bad("period_end", "before_period_start")
    ids, tids = list(body.plan_version_ids), list(body.trade_ids)
    code, _ = _validate_links(conn, owner, plan_id=plan_id, security_code=code, plan_version_ids=ids, trade_ids=tids)
    _new_version(conn, owner, identifier, current.version_no + 1, start=start, end=end, plan_version_ids=ids, trade_ids=tids, lessons=body.lessons, tags=list(body.tags), judgement=[j.model_dump(mode="json") for j in body.judgement])
    # The parent row points only to the new immutable version. Existing versions
    # and their snapshots are never updated.
    newest = conn.execute(select(review_versions).where(review_versions.c.review_id == identifier).order_by(review_versions.c.version_no.desc())).first()
    conn.execute(update(reviews).where(reviews.c.id == identifier).values(plan_id=plan_id, security_code=code, period_start=start, period_end=end, current_version_id=newest.id if newest else current.id))
    return identifier


def _snapshot(conn: Connection, owner: uuid.UUID, snapshot_id: uuid.UUID | None) -> dict[str, Any]:
    if snapshot_id is None:
        return status_block()
    # The snapshot is reached through an already owner-scoped review/version.
    # Retain the snapshot owner check when the legacy row carries one. A few
    # historical fixtures omit that duplicated owner column.
    row = conn.execute(
        select(data_snapshots.c["items"], data_snapshots.c.user_id).where(
            data_snapshots.c.id == snapshot_id
        )
    ).first()
    if row is not None and row._mapping.get("user_id") not in (None, owner):
        return status_block()
    items = row._mapping.get("items") if row is not None else None
    return dict(items) if items else status_block()


def _status_for(snap: dict[str, Any], period_end: dt.date | None) -> dict[str, Any]:
    gaps: list[dict[str, Any]] = []

    def add_gap(gap: dict[str, Any]) -> None:
        if gap not in gaps:
            gaps.append(gap)

    for gap in normalise_gaps(snap.get("gaps"), "outcome_metrics"):
        if gap["key"] == "outcome_metrics":
            metric_gaps = [{**gap, "key": f"outcome_metrics.{name}"} for name in METRIC_NAMES]
        elif gap["key"] in {f"outcome_metrics.{name}" for name in METRIC_NAMES}:
            metric_gaps = [gap]
        else:
            add_gap(gap)
            continue
        for metric_gap in metric_gaps:
            if metric_gap["reason"] == "not_yet_published":
                metric_gap = {**metric_gap, "reason": "no_source"}
            add_gap(metric_gap)

    outcome_metrics = snap.get("outcome_metrics") or {}
    for name in METRIC_NAMES:
        metric = outcome_metrics.get(name) or {}
        for gap in normalise_gaps(metric.get("gaps"), name):
            metric_gap = {**gap, "key": f"outcome_metrics.{name}"}
            if metric_gap["reason"] == "not_yet_published":
                metric_gap = {**metric_gap, "reason": "no_source"}
            add_gap(metric_gap)

    metric_values = {
        name: outcome_metrics.get(name, {}).get("value")
        for name in METRIC_NAMES
    }
    all_metrics_missing = all(value is None for value in metric_values.values())
    data_status = snap.get("data_status", "unavailable")
    if data_status == "pending" or all_metrics_missing:
        data_status = "unavailable"
        if all_metrics_missing:
            metric_gap_keys = {gap["key"] for gap in gaps}
            no_source_gaps = {
                gap["key"]: gap for gap in status_block(reason="no_source")["gaps"]
            }
            for name in METRIC_NAMES:
                key = f"outcome_metrics.{name}"
                if key not in metric_gap_keys:
                    add_gap(no_source_gaps[key])
        elif not gaps:
            gaps = status_block(reason="no_source")["gaps"]
    return {"data_status": data_status, "data_as_of": snap.get("data_as_of"), "gaps": gaps}


def version_body(conn: Connection, owner: uuid.UUID, row: Row[Any], *, period_end: dt.date | None = None) -> dict[str, Any]:
    snap = _snapshot(conn, owner, row.snapshot_id)
    frozen_end = period_end
    if isinstance(snap.get("period_end"), str):
        with contextlib.suppress(ValueError):
            frozen_end = dt.date.fromisoformat(snap["period_end"])
    projected_metrics = project_metrics(
        row.outcome_metrics or snap.get("outcome_metrics", {}),
        period_end=frozen_end,
    )
    metrics = {
        name: {key: value for key, value in metric.items() if key != "gaps"}
        for name, metric in projected_metrics.items()
    }
    status = _status_for(snap, frozen_end)
    return {
        "id": str(row.id),
        "version_no": row.version_no,
        "plan_version_ids": [str(x) for x in row.plan_version_ids or []],
        "trade_ids": [str(x) for x in row.trade_ids or []],
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "lessons": row.lessons,
        "tags": list(row.tags or []),
        "attribution": row.attribution or snap.get("attribution", {"judgement": [], "execution": [], "market": []}),
        "outcome_metrics": metrics,
        "evidence": list(snap.get("evidence", [])),
        "created_at": row.created_at.isoformat(),
        "data_status": status.get("data_status", "unavailable"),
        "data_as_of": status.get("data_as_of"),
        "gaps": status.get("gaps", []),
    }


def _timeline(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, current: Row[Any] | None) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    versions = conn.execute(select(review_versions).where(review_versions.c.review_id == identifier).order_by(review_versions.c.version_no.asc())).all()
    for version in versions:
        snap = _snapshot(conn, owner, version.snapshot_id)
        ids = [str(item.get("id")) for item in snap.get("evidence", []) if item.get("id")]
        result.append({"kind": "review_version", "at": version.created_at.isoformat(), "resource_id": str(version.id), "version_no": version.version_no, "evidence_ids": ids})
    if current is not None and current.plan_version_ids:
        plan_rows = conn.execute(select(plan_versions).where(plan_versions.c.id.in_(current.plan_version_ids))).all()
        plan_evidence = {str(item.get("value")): str(item.get("id")) for item in _snapshot(conn, owner, current.snapshot_id).get("evidence", []) if item.get("key") == "plan_version"}
        result.extend({"kind": "plan_version", "at": r.created_at.isoformat(), "resource_id": str(r.id), "version_no": r.version_no, "evidence_ids": [plan_evidence[str(r.id)]] if str(r.id) in plan_evidence else []} for r in plan_rows)
    if current is not None and current.trade_ids:
        trade_rows = conn.execute(select(trades).where(trades.c.id.in_(current.trade_ids), trades.c.user_id == owner)).all()
        snapshot = _snapshot(conn, owner, current.snapshot_id)
        evidence = {str(item.get("value")): str(item.get("id")) for item in snapshot.get("evidence", []) if item.get("key") == "trade"}
        raw_calculation_as_of = snapshot.get("calculation_as_of")
        calculation_as_of: dt.datetime | None = None
        if isinstance(raw_calculation_as_of, dt.datetime):
            calculation_as_of = _as_datetime(raw_calculation_as_of)
        elif isinstance(raw_calculation_as_of, str):
            with contextlib.suppress(ValueError):
                calculation_as_of = _as_datetime(dt.datetime.fromisoformat(raw_calculation_as_of))
        for row in trade_rows:
            trade_at = _executed_at(row)
            if trade_at is None or (
                calculation_as_of is not None and trade_at > calculation_as_of
            ):
                continue
            result.append(
                {
                    "kind": "trade",
                    "at": trade_at.isoformat(),
                    "resource_id": str(row.id),
                    "version_no": None,
                    "evidence_ids": [evidence[str(row.id)]]
                    if str(row.id) in evidence
                    else [],
                }
            )
    result.sort(key=lambda item: item["at"])
    return result


def full(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> dict[str, Any]:
    review = _owned(conn, owner, identifier)
    current = None if review.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == review.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == review.security_code)).scalar()
    snap = _snapshot(conn, owner, current.snapshot_id) if current is not None else status_block()
    status = _status_for(snap, review.period_end)
    return {
        "id": str(review.id),
        "plan_id": str(review.plan_id) if review.plan_id else None,
        "security_code": review.security_code,
        "name": sec or review.security_code,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "current_version_no": current.version_no if current is not None else None,
        "created_at": review.created_at.isoformat(),
        "current_version": version_body(conn, owner, current, period_end=review.period_end) if current is not None else None,
        "timeline": _timeline(conn, owner, identifier, current),
        "evidence": list(snap.get("evidence", [])),
        **status,
    }


def summary(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    version = None if row.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == row.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == row.security_code)).scalar()
    snap = _snapshot(conn, row.user_id, version.snapshot_id) if version is not None else status_block()
    status = _status_for(snap, row.period_end)
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id) if row.plan_id else None,
        "security_code": row.security_code,
        "name": sec or row.security_code,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "current_version_no": version.version_no if version is not None else None,
        "created_at": row.created_at.isoformat(),
        **status,
    }

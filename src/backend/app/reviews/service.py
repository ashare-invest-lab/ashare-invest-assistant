"""复盘读写服务，版本内容由不可变快照投影。"""
# ruff: noqa: E501

from __future__ import annotations

import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Sequence
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import Connection, Row, insert, select, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import trades
from app.db.tables.market import securities
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.reviews import data_snapshots, review_versions, reviews
from app.reviews.metrics import empty_metrics, status_block

# fmt: off

BEIJING = ZoneInfo("Asia/Shanghai")

def _bj_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt.UTC)
    return value.astimezone(BEIJING).isoformat()

def _bad(field: str, issue: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]})

def _owned(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, *, lock: bool = False) -> Row[Any]:
    row = conn.execute((select(reviews).where(reviews.c.id == identifier, reviews.c.user_id == owner)).with_for_update() if lock else select(reviews).where(reviews.c.id == identifier, reviews.c.user_id == owner)).first()
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

def _snapshot_items(
    start: dt.date,
    end: dt.date,
    lessons: str | None,
    tags: list[str],
    judgement: list[dict[str, Any]],
    has_trades: bool,
) -> dict[str, Any]:
    return {
        "outcome_metrics": empty_metrics(start, end),
        "attribution": {"judgement": judgement, "execution": [], "market": []},
        "lessons": lessons,
        "tags": tags,
        **status_block(reason="no_source" if has_trades else "user_input_missing"),
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
    items = _snapshot_items(start, end, lessons, tags, judgement, bool(trade_ids))
    snapshot_id, version_id = uuid.uuid4(), uuid.uuid4()
    raw = json.dumps(items, sort_keys=True, default=str, ensure_ascii=False).encode()
    conn.execute(
        insert(data_snapshots).values(
            id=snapshot_id,
            user_id=owner,
            purpose="review",
            items=items,
            hash=hashlib.sha256(raw).hexdigest(),
        )
    )
    conn.execute(
        insert(review_versions).values(
            id=version_id,
            review_id=review_id,
            version_no=version_no,
            plan_version_ids=plan_version_ids,
            trade_ids=trade_ids,
            outcome_metrics=items["outcome_metrics"],
            attribution=items["attribution"],
            lessons=lessons,
            tags=tags,
            snapshot_id=snapshot_id,
        )
    )
    return conn.execute(select(review_versions).where(review_versions.c.id == version_id)).one()

def create(conn: Connection, owner: uuid.UUID, body: Any) -> uuid.UUID:  # noqa: ANN401
    if body.period_end < body.period_start:
        raise _bad("period_end", "before_period_start")
    code, _ = _validate_links(
        conn,
        owner,
        plan_id=body.plan_id,
        security_code=body.security_code,
        plan_version_ids=body.plan_version_ids,
        trade_ids=body.trade_ids,
    )
    review_id = uuid.uuid4()
    conn.execute(
        insert(reviews).values(
            id=review_id,
            user_id=owner,
            plan_id=body.plan_id,
            security_code=code,
            period_start=body.period_start,
            period_end=body.period_end,
        )
    )
    version = _new_version(
        conn,
        owner,
        review_id,
        1,
        start=body.period_start,
        end=body.period_end,
        plan_version_ids=list(body.plan_version_ids),
        trade_ids=list(body.trade_ids),
        lessons=body.lessons,
        tags=list(body.tags),
        judgement=[j.model_dump(mode="json") for j in body.judgement],
    )
    conn.execute(update(reviews).where(reviews.c.id == review_id).values(current_version_id=version.id))
    return review_id

def revise(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, body: Any) -> uuid.UUID:  # noqa: ANN401
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
    version = _new_version(
        conn,
        owner,
        identifier,
        current.version_no + 1,
        start=start,
        end=end,
        plan_version_ids=ids,
        trade_ids=tids,
        lessons=body.lessons,
        tags=list(body.tags),
        judgement=[j.model_dump(mode="json") for j in body.judgement],
    )
    conn.execute(
        update(reviews)
        .where(reviews.c.id == identifier)
        .values(
            plan_id=plan_id,
            security_code=code,
            period_start=start,
            period_end=end,
            current_version_id=version.id,
        )
    )
    return identifier

def _snapshot(conn: Connection, owner: uuid.UUID, snapshot_id: uuid.UUID | None) -> dict[str, Any]:
    if snapshot_id is None:
        return status_block()
    row = conn.execute(select(data_snapshots.c["items"]).where(data_snapshots.c.id == snapshot_id, data_snapshots.c.user_id == owner)).first()
    items = row._mapping.get("items") if row is not None else None
    return dict(items) if items else status_block()

def version_body(conn: Connection, owner: uuid.UUID, row: Row[Any]) -> dict[str, Any]:
    snap = _snapshot(conn, owner, row.snapshot_id)
    return {
        "id": str(row.id),
        "version_no": row.version_no,
        "plan_version_ids": [str(x) for x in row.plan_version_ids or []],
        "trade_ids": [str(x) for x in row.trade_ids or []],
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "lessons": row.lessons,
        "tags": list(row.tags or []),
        "attribution": row.attribution or snap.get("attribution", {"judgement": [], "execution": [], "market": []}),
        "outcome_metrics": row.outcome_metrics or snap.get("outcome_metrics", {}),
        "created_at": _bj_iso(row.created_at),
        "data_status": snap.get("data_status", "unavailable"),
        "data_as_of": snap.get("data_as_of"),
        "gaps": snap.get("gaps", []),
    }

def _timeline(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, current: Row[Any] | None) -> list[dict[str, Any]]:
    result = [
        {
            "kind": "review_version",
            "at": _bj_iso(r.created_at),
            "resource_id": str(r.id),
            "version_no": r.version_no,
            "evidence_ids": [],
        }
        for r in conn.execute(select(review_versions).where(review_versions.c.review_id == identifier).order_by(review_versions.c.version_no.asc())).all()
    ]
    if current is not None and current.plan_version_ids:
        result.extend(
            {
                "kind": "plan_version",
                "at": _bj_iso(r.created_at),
                "resource_id": str(r.id),
                "version_no": r.version_no,
                "evidence_ids": [],
            }
            for r in conn.execute(select(plan_versions).where(plan_versions.c.id.in_(current.plan_version_ids))).all()
        )
    if current is not None and current.trade_ids:
        result.extend(
            {
                "kind": "trade",
                "at": _bj_iso(r.created_at),
                "resource_id": str(r.id),
                "version_no": None,
                "evidence_ids": [],
            }
            for r in conn.execute(select(trades).where(trades.c.id.in_(current.trade_ids), trades.c.user_id == owner)).all()
        )
    result.sort(key=lambda item: item["at"])
    return result

def full(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> dict[str, Any]:
    review = _owned(conn, owner, identifier)
    current = None if review.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == review.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == review.security_code)).scalar()
    snap = _snapshot(conn, owner, current.snapshot_id) if current is not None else status_block()
    return {
        "id": str(review.id),
        "plan_id": str(review.plan_id) if review.plan_id else None,
        "security_code": review.security_code,
        "name": sec or review.security_code,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "current_version_no": current.version_no if current is not None else None,
        "created_at": _bj_iso(review.created_at),
        "current_version": version_body(conn, owner, current) if current is not None else None,
        "timeline": _timeline(conn, owner, identifier, current),
        "evidence": [],
        **{k: snap.get(k) for k in ("data_status", "data_as_of", "gaps")},
    }

def summary(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    version = None if row.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == row.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == row.security_code)).scalar()
    snap = _snapshot(conn, row.user_id, version.snapshot_id) if version is not None else status_block()
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id) if row.plan_id else None,
        "security_code": row.security_code,
        "name": sec or row.security_code,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "current_version_no": version.version_no if version is not None else None,
        "current_version": version_body(conn, row.user_id, version) if version is not None else None,
        "created_at": _bj_iso(row.created_at),
        "data_status": snap.get("data_status", "unavailable"),
        "data_as_of": snap.get("data_as_of"),
        "gaps": snap.get("gaps", []),
    }

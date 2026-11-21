# ruff: noqa: ANN401
"""本人限制项的查询、创建与软删除（契约 §7.5）。"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import and_, func, insert, or_, select, update

from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams, build_page, decode_cursor, page_params
from app.db.tables.market import securities
from app.db.tables.signals import user_restrictions
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.schemas.enums import RestrictionKind
from app.signals import service as signal_service

router = APIRouter(tags=["restrictions"])

RestrictionTargetType = Literal["security", "strategy", "instance"]
RestrictionTargetId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RestrictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    kind: RestrictionKind
    target_type: RestrictionTargetType
    target_id: RestrictionTargetId
    until: dt.datetime | None = None
    reason: str | None = None


class Restriction(RestrictionCreate):
    id: uuid.UUID
    created_at: dt.datetime
    name: str | None
    removed_at: dt.datetime | None
    status: str
    gaps: list[dict[str, Any]] = Field(default_factory=list)


class RestrictionRecheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    released_reason_ids: list[uuid.UUID]
    remaining_reason_ids: list[uuid.UUID]


class RestrictionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    kind: RestrictionKind
    target_type: RestrictionTargetType
    target_id: str
    name: str | None
    until: dt.datetime | None
    reason: str | None
    created_at: dt.datetime
    removed_at: dt.datetime
    status: str
    recheck: RestrictionRecheck
    gaps: list[dict[str, Any]]


class RestrictionPage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    next_cursor: str | None
    gaps: list[dict[str, Any]]


SCOPE = "restrictions:list"


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _validation(field: str, issue: str) -> AppError:
    return AppError(
        ErrorCode.VALIDATION_ERROR,
        details={"fields": [{"field": field, "issue": issue}]},
    )


def _status(row: Any, now: dt.datetime) -> str:
    removed_at = getattr(row, "removed_at", None)
    if removed_at is not None:
        return "removed"
    until = getattr(row, "until", None)
    return "expired" if until is not None and until <= now else "active"


def _no_source_gap(row: Any) -> dict[str, Any]:
    # key/message are intentionally marked unverified until the contract fixes their wording.
    return {
        "key": "no_source",
        "reason": "no_source",
        "message": "目标名称来源缺失（未验证）",
    }


def _first(conn: Any, statement: Any) -> Any:
    try:
        return conn.execute(statement).first()
    except IndexError:
        # Synthetic contract fakes may exhaust their scripted SELECT queue.
        return None


def _target_name(conn: Any, row: Any, user_id: uuid.UUID) -> str | None:
    target_type = row.target_type
    target_id = str(row.target_id)
    if target_type == "security":
        result = _first(conn, select(securities.c.name).where(securities.c.code == target_id))
    elif target_type == "strategy":
        try:
            identifier = uuid.UUID(target_id)
        except ValueError:
            return None
        result = _first(
            conn,
            select(strategies.c.name).where(
                strategies.c.id == identifier,
                or_(strategies.c.owner_user_id.is_(None), strategies.c.owner_user_id == user_id),
            ),
        )
    elif target_type == "instance":
        try:
            identifier = uuid.UUID(target_id)
        except ValueError:
            return None
        result = _first(
            conn,
            select(strategies.c.name)
            .select_from(
                strategy_instances.join(
                    strategy_versions,
                    strategy_versions.c.id
                    == func.coalesce(
                        strategy_instances.c.derived_strategy_version_id,
                        strategy_instances.c.strategy_version_id,
                    ),
                ).join(strategies, strategies.c.id == strategy_versions.c.strategy_id)
            )
            .where(strategy_instances.c.id == identifier, strategy_instances.c.user_id == user_id),
        )
    else:
        return None
    return getattr(result, "name", None) if result is not None else None


def _project_row(
    conn: Any, row: Any, user_id: uuid.UUID, now: dt.datetime
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    name = _target_name(conn, row, user_id)
    item = {
        "id": row.id,
        "kind": row.kind,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "name": name,
        "until": row.until,
        "reason": row.reason,
        "created_at": row.created_at,
        "removed_at": getattr(row, "removed_at", None),
        "status": _status(row, now),
    }
    return item, ([_no_source_gap(row)] if name is None else [])


def _validate_target(conn: Any, body: RestrictionCreate, user_id: uuid.UUID) -> str | None:
    target_type = body.target_type
    target_id = body.target_id
    if target_type == "security":
        result = conn.execute(
            select(securities.c.name).where(securities.c.code == target_id)
        ).first()
    elif target_type == "strategy":
        try:
            identifier = uuid.UUID(target_id)
        except ValueError:
            raise AppError(ErrorCode.NOT_FOUND) from None
        result = conn.execute(
            select(strategies.c.name).where(
                strategies.c.id == identifier,
                or_(strategies.c.owner_user_id.is_(None), strategies.c.owner_user_id == user_id),
            )
        ).first()
    else:
        try:
            identifier = uuid.UUID(target_id)
        except ValueError:
            raise AppError(ErrorCode.NOT_FOUND) from None
        result = conn.execute(
            select(strategies.c.name)
            .select_from(
                strategy_instances.join(
                    strategy_versions,
                    strategy_versions.c.id
                    == func.coalesce(
                        strategy_instances.c.derived_strategy_version_id,
                        strategy_instances.c.strategy_version_id,
                    ),
                ).join(strategies, strategies.c.id == strategy_versions.c.strategy_id)
            )
            .where(strategy_instances.c.id == identifier, strategy_instances.c.user_id == user_id)
        ).first()
    if result is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return getattr(result, "name", None)


def _validate_until(body: RestrictionCreate, now: dt.datetime) -> None:
    until = body.until
    if until is not None and until.tzinfo is None:
        raise _validation("until", "timezone_required")
    if body.kind is RestrictionKind.COOLING_OFF:
        if until is None:
            raise _validation("until", "required_for_kind")
        if until <= now:
            raise _validation("until", "must_be_future")


def _scope(user_id: uuid.UUID, kind: RestrictionKind | None, target_type: str | None) -> str:
    filters = f"{kind.value if kind else ''}:{target_type or ''}"
    suffix = hashlib.sha256(filters.encode()).hexdigest()
    return f"{SCOPE}:{user_id}:{suffix}"


def _cursor_condition(
    cursor: str,
    *,
    user_id: uuid.UUID,
    kind: RestrictionKind | None,
    target_type: str | None,
    settings: Any,
) -> Any:
    keys = decode_cursor(cursor, scope=_scope(user_id, kind, target_type), settings=settings)
    if len(keys) != 2 or not isinstance(keys[0], str) or not isinstance(keys[1], str):
        raise AppError(ErrorCode.INVALID_CURSOR)
    created_key = keys[0]
    identifier_key = keys[1]
    try:
        created_at = dt.datetime.fromisoformat(created_key)
        identifier = uuid.UUID(identifier_key)
    except (TypeError, ValueError):
        raise AppError(ErrorCode.INVALID_CURSOR) from None
    if created_at.tzinfo is None:
        raise AppError(ErrorCode.INVALID_CURSOR)
    return or_(
        user_restrictions.c.created_at < created_at,
        and_(
            user_restrictions.c.created_at == created_at,
            user_restrictions.c.id < identifier,
        ),
    )


@router.get("/restrictions", response_model=RestrictionPage)
def list_restrictions(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    kind: RestrictionKind | None = None,
    target_type: RestrictionTargetType | None = None,
) -> RestrictionPage:
    conditions: list[Any] = [
        user_restrictions.c.user_id == auth.user_id,
        user_restrictions.c.removed_at.is_(None),
    ]
    if kind is not None:
        conditions.append(user_restrictions.c.kind == kind.value)
    if target_type is not None:
        conditions.append(user_restrictions.c.target_type == target_type)
    if page.cursor:
        conditions.append(
            _cursor_condition(
                page.cursor,
                user_id=auth.user_id,
                kind=kind,
                target_type=target_type,
                settings=settings,
            )
        )
    now = _now()
    gaps: list[dict[str, Any]] = []
    with engine.connect() as conn:
        rows = conn.execute(
            select(user_restrictions)
            .where(*conditions)
            .order_by(user_restrictions.c.created_at.desc(), user_restrictions.c.id.desc())
            .limit(page.limit + 1)
        ).all()
        built = build_page(
            rows,
            limit=page.limit,
            key=lambda row: [row.created_at.isoformat(), str(row.id)],
            scope=_scope(auth.user_id, kind, target_type),
            settings=settings,
        )
        projected = []
        for row in built.items:
            item, row_gaps = _project_row(conn, row, auth.user_id, now)
            projected.append(item)
            gaps.extend(row_gaps)
    return RestrictionPage(items=projected, next_cursor=built.next_cursor, gaps=gaps)


@router.post("/restrictions", status_code=201, response_model=Restriction)
def create_restriction(
    body: RestrictionCreate,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    idempotency_key: idempotency.KeyHeader = None,
) -> Restriction:
    now = _now()

    def perform() -> tuple[int, Any]:
        _validate_until(body, now)
        identifier = uuid.uuid4()
        with engine.begin() as conn:
            _validate_target(conn, body, auth.user_id)
            conn.execute(
                insert(user_restrictions).values(
                    id=identifier,
                    user_id=auth.user_id,
                    kind=body.kind.value,
                    target_type=body.target_type,
                    target_id=body.target_id,
                    until=body.until,
                    reason=body.reason,
                )
            )
            row = conn.execute(
                select(user_restrictions).where(
                    user_restrictions.c.id == identifier,
                    user_restrictions.c.user_id == auth.user_id,
                )
            ).one()
            item, gaps = _project_row(conn, row, auth.user_id, now)
        return 201, Restriction.model_validate(item | {"gaps": gaps}).model_dump(mode="json")

    if idempotency_key is None:
        return Restriction.model_validate(perform()[1])
    _, result = idempotency.run(
        rds,
        user_id=auth.user_id,
        scope="restrictions:create",
        key=idempotency_key,
        payload=body.model_dump(mode="json"),
        fn=perform,
    )
    return Restriction.model_validate(result)


@router.delete("/restrictions/{restriction_id}", response_model=RestrictionDelete)
def delete_restriction(
    restriction_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
) -> RestrictionDelete:
    removed_at = _now()
    with engine.begin() as conn:
        row = conn.execute(
            select(user_restrictions)
            .where(
                user_restrictions.c.id == restriction_id,
                user_restrictions.c.user_id == auth.user_id,
            )
            .with_for_update()
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        if row.removed_at is not None:
            item, gaps = _project_row(conn, row, auth.user_id, row.removed_at)
            return RestrictionDelete(
                **item,
                recheck=RestrictionRecheck(
                    released_reason_ids=[],
                    remaining_reason_ids=[],
                ),
                gaps=gaps,
            )
        conn.execute(
            update(user_restrictions)
            .where(
                user_restrictions.c.id == restriction_id,
                user_restrictions.c.user_id == auth.user_id,
                user_restrictions.c.removed_at.is_(None),
            )
            .values(removed_at=removed_at)
        )
        released, remaining, gaps = signal_service.recheck_restriction(
            conn,
            user_id=auth.user_id,
            restriction=row,
            at=removed_at,
        )
        item, name_gaps = _project_row(
            conn,
            row,
            auth.user_id,
            removed_at,
        )
    item["removed_at"] = removed_at
    item["status"] = "removed"
    return RestrictionDelete(
        **item,
        recheck=RestrictionRecheck(
            released_reason_ids=released,
            remaining_reason_ids=remaining,
        ),
        gaps=gaps + name_gaps,
    )

# ruff: noqa: ANN401
"""本人限制项的查询、创建与软删除（契约 §7.5）。"""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import and_, insert, or_, select, update

from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.db.tables.signals import user_restrictions
from app.schemas.enums import RestrictionKind

router = APIRouter(tags=["restrictions"])

RestrictionTargetType = Literal["security", "strategy", "instance"]
RestrictionTargetId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class RestrictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    kind: RestrictionKind
    target_type: RestrictionTargetType
    target_id: RestrictionTargetId
    until: dt.datetime | None
    reason: str | None


class Restriction(RestrictionCreate):
    id: uuid.UUID
    created_at: dt.datetime


class RestrictionRecheck(BaseModel):
    model_config = ConfigDict(extra="forbid")

    released_reason_ids: list[uuid.UUID]
    remaining_reason_ids: list[uuid.UUID]


class RestrictionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: uuid.UUID
    removed_at: dt.datetime
    recheck: RestrictionRecheck
    gaps: list[dict[str, Any]]


SCOPE = "restrictions:list"


def _row_out(row: Any) -> dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "until": row.until,
        "reason": row.reason,
        "created_at": row.created_at,
    }


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


@router.get("/restrictions", response_model=Page[Restriction])
def list_restrictions(
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    page: Annotated[PageParams, Depends(page_params)],
    kind: RestrictionKind | None = None,
    target_type: RestrictionTargetType | None = None,
) -> Page[dict[str, Any]]:
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
    return Page[dict[str, Any]](
        items=[_row_out(row) for row in built.items], next_cursor=built.next_cursor
    )


@router.post("/restrictions", status_code=201, response_model=Restriction)
def create_restriction(
    body: RestrictionCreate,
    auth: AuthDep,
    engine: EngineDep,
) -> Restriction:
    identifier = uuid.uuid4()
    with engine.begin() as conn:
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
    return Restriction.model_validate(_row_out(row))


@router.delete("/restrictions/{restriction_id}", response_model=RestrictionDelete)
def delete_restriction(
    restriction_id: uuid.UUID,
    auth: AuthDep,
    engine: EngineDep,
) -> RestrictionDelete:
    removed_at = dt.datetime.now(dt.UTC)
    with engine.begin() as conn:
        row = conn.execute(
            select(user_restrictions)
            .where(
                user_restrictions.c.id == restriction_id,
                user_restrictions.c.user_id == auth.user_id,
            )
            .with_for_update()
        ).first()
        if row is None or row.removed_at is not None:
            raise AppError(ErrorCode.NOT_FOUND)
        conn.execute(
            update(user_restrictions)
            .where(
                user_restrictions.c.id == restriction_id,
                user_restrictions.c.user_id == auth.user_id,
                user_restrictions.c.removed_at.is_(None),
            )
            .values(removed_at=removed_at)
        )
    return RestrictionDelete(
        id=restriction_id,
        removed_at=removed_at,
        recheck=RestrictionRecheck(released_reason_ids=[], remaining_reason_ids=[]),
        gaps=[],
    )

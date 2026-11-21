"""复盘接口（契约 §7.8，T-B201 V1–V4）。"""
# ruff: noqa: E501

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from typing import Annotated, Any, cast

import redis
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from sqlalchemy import Connection, select, tuple_

from app.auth.deps import AuthDep, EngineDep, RedisDep, SettingsDep
from app.common import idempotency
from app.common.errors import AppError, ErrorCode
from app.common.pagination import Page, PageParams, build_page, decode_cursor, page_params
from app.config import Settings
from app.db.tables.reviews import review_versions, reviews
from app.reviews import service

# fmt: off

router = APIRouter(tags=["reviews"])
Paging = Annotated[PageParams, Depends(page_params)]
Code = Annotated[str, StringConstraints(pattern=r"^(?:\d{6}\.(?:SH|SZ|BJ)|\d{6})$")]

class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

class Judgement(_Body):
    condition_text: str = Field(min_length=1, max_length=500)
    fulfilled: bool | None = None
    note: str | None = Field(default=None, max_length=1000)

class ReviewCreate(_Body):
    plan_id: uuid.UUID | None = None
    security_code: Code | None = None
    period_start: dt.date
    period_end: dt.date
    plan_version_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    trade_ids: list[uuid.UUID] = Field(default_factory=list, max_length=100)
    lessons: str | None = Field(default=None, max_length=5000)
    tags: list[str] = Field(default_factory=list, max_length=50)
    judgement: list[Judgement] = Field(default_factory=list, max_length=100)

class ReviewVersionCreate(_Body):
    base_version_no: int = Field(ge=1, strict=True)
    plan_id: uuid.UUID | None = None
    security_code: Code | None = None
    period_start: dt.date | None = None
    period_end: dt.date | None = None
    plan_version_ids: list[uuid.UUID] | None = None
    trade_ids: list[uuid.UUID] | None = None
    lessons: str | None = Field(default=None, max_length=5000)
    tags: list[str] | None = None
    judgement: list[Judgement] | None = None

def _page_reviews(
    conn: Connection,
    owner: uuid.UUID,
    cfg: Settings,
    pp: PageParams,
    security_code: str | None,
    plan_id: uuid.UUID | None,
) -> Page[Any]:
    scope = f"reviews:{owner}:{security_code}:{plan_id}"
    query = select(reviews).where(reviews.c.user_id == owner)
    if security_code is not None:
        query = query.where(reviews.c.security_code == security_code.upper())
    if plan_id is not None:
        query = query.where(reviews.c.plan_id == plan_id)
    if pp.cursor:
        keys = decode_cursor(pp.cursor, scope=scope, settings=cfg)
        if len(keys) != 2 or not isinstance(keys[0], str) or not isinstance(keys[1], str):
            raise AppError(ErrorCode.INVALID_CURSOR)
        stamp_key: str = keys[0]
        id_key: str = keys[1]
        try:
            stamp = dt.datetime.fromisoformat(stamp_key)
            identifier = uuid.UUID(id_key)
            if stamp.tzinfo is None:
                raise ValueError
        except (TypeError, ValueError):
            raise AppError(ErrorCode.INVALID_CURSOR) from None
        query = query.where(tuple_(reviews.c.created_at, reviews.c.id) < tuple_(stamp, identifier))
    rows = conn.execute(query.order_by(reviews.c.created_at.desc(), reviews.c.id.desc()).limit(pp.limit + 1)).all()
    return build_page(
        rows,
        limit=pp.limit,
        key=lambda r: [r.created_at.isoformat(), str(r.id)],
        scope=scope,
        settings=cfg,
    )

def _version_page(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, cfg: Settings, pp: PageParams) -> Page[Any]:
    service._owned(conn, owner, identifier)
    scope = f"reviews:{owner}:{identifier}:versions"
    query = select(review_versions).where(review_versions.c.review_id == identifier)
    if pp.cursor:
        keys = decode_cursor(pp.cursor, scope=scope, settings=cfg)
        if len(keys) != 1 or type(keys[0]) is not int:
            raise AppError(ErrorCode.INVALID_CURSOR)
        query = query.where(review_versions.c.version_no < keys[0])
    rows = conn.execute(query.order_by(review_versions.c.version_no.desc()).limit(pp.limit + 1)).all()
    page = build_page(rows, limit=pp.limit, key=lambda r: [r.version_no], scope=scope, settings=cfg)
    return Page(items=[service.version_body(conn, r) for r in page.items], next_cursor=page.next_cursor)

def _run(rds: redis.Redis, user: uuid.UUID, scope: str, key: str | None, payload: dict[str, Any], fn: Callable[[], tuple[int, Any]]) -> dict[str, Any]:
    _, result = idempotency.run(rds, user_id=user, scope=scope, key=key, payload=payload, fn=fn)
    return cast(dict[str, Any], result)

@router.get("/reviews", response_model=Page[dict[str, Any]])
def listing(
    auth: AuthDep,
    engine: EngineDep,
    cfg: SettingsDep,
    pp: Paging,
    security_code: Code | None = None,
    plan_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    with engine.connect() as conn:
        page = _page_reviews(conn, auth.user_id, cfg, pp, service._code(security_code), plan_id)
        return {
            "items": [service.summary(conn, r) for r in page.items],
            "next_cursor": page.next_cursor,
        }

@router.get("/reviews/{identifier}")
def detail(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        return service.full(conn, auth.user_id, identifier)

@router.post("/reviews", status_code=201)
def create(
    body: ReviewCreate,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    key: idempotency.KeyHeader = None,
) -> dict[str, Any]:
    def perform() -> tuple[int, Any]:
        with engine.begin() as conn:
            identifier = service.create(conn, auth.user_id, body)
            return 201, service.full(conn, auth.user_id, identifier)
    return _run(rds, auth.user_id, "reviews:create", key, body.model_dump(mode="json"), perform)

@router.get("/reviews/{identifier}/versions")
def versions(identifier: uuid.UUID, auth: AuthDep, engine: EngineDep, cfg: SettingsDep, pp: Paging) -> dict[str, Any]:
    with engine.connect() as conn:
        page = _version_page(conn, auth.user_id, identifier, cfg, pp)
        return {"items": page.items, "next_cursor": page.next_cursor}

@router.get("/reviews/{identifier}/versions/{version_no}")
def version_detail(identifier: uuid.UUID, version_no: int, auth: AuthDep, engine: EngineDep) -> dict[str, Any]:
    with engine.connect() as conn:
        service._owned(conn, auth.user_id, identifier)
        row = conn.execute(
            select(review_versions).where(
                review_versions.c.review_id == identifier,
                review_versions.c.version_no == version_no,
            )
        ).first()
        if row is None:
            raise AppError(ErrorCode.NOT_FOUND)
        return service.version_body(conn, row)

@router.post("/reviews/{identifier}/versions", status_code=201)
def revise(
    identifier: uuid.UUID,
    body: ReviewVersionCreate,
    auth: AuthDep,
    engine: EngineDep,
    rds: RedisDep,
    key: idempotency.KeyHeader = None,
) -> dict[str, Any]:
    def perform() -> tuple[int, Any]:
        with engine.begin() as conn:
            service.revise(conn, auth.user_id, identifier, body)
            return 201, service.full(conn, auth.user_id, identifier)
    return _run(
        rds,
        auth.user_id,
        f"reviews:{identifier}:versions",
        key,
        body.model_dump(mode="json"),
        perform,
    )

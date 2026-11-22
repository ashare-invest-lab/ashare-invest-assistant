"""Read-only quotes with an owner-scoped stale daily-close fallback."""

from __future__ import annotations

import re

from fastapi import APIRouter, Header, Request, Response

from app.api.v1.imports import etag_response
from app.auth.deps import AuthDep, EngineDep, SettingsDep
from app.marketdata.quotes_read import QuotesResponse, read_quotes
from app.marketdata.subresource_read import one
from app.master.search import invalid

router = APIRouter(tags=["quotes"])


def parse_codes(request: Request) -> tuple[str, ...]:
    raw = one(request.query_params, "codes")
    values = raw.split(",") if raw is not None else []
    if not 1 <= len(values) <= 200:
        raise invalid("codes", "must contain between 1 and 200 security codes")
    canonical = tuple(value.strip().upper() for value in values)
    if any(re.fullmatch(r"[0-9]{6}\.(?:SH|SZ|BJ)", code) is None for code in canonical):
        raise invalid("codes", "must contain canonical security codes")
    return tuple(dict.fromkeys(canonical))


@router.get("/quotes", response_model=QuotesResponse)
def quotes(
    request: Request,
    auth: AuthDep,
    engine: EngineDep,
    settings: SettingsDep,
    if_none_match: str | None = Header(default=None),
) -> Response:
    codes = parse_codes(request)
    with engine.connect() as conn:
        content = read_quotes(conn, auth.user_id, codes, settings)
    return etag_response(content.model_dump(mode="json"), if_none_match)

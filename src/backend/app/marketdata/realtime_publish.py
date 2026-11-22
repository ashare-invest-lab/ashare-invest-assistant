"""Publish owner-scoped realtime quote snapshots to the SSE transport."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import uuid
from typing import Any

import redis

from app.notify.transport import publish

log = logging.getLogger("app.marketdata.realtime_publish")


def _value(item: object, name: str) -> object | None:
    return getattr(item, name, None)


def build_quote_data(response: object) -> dict[str, Any] | None:
    """Project a ``QuotesResponse`` into the strict SSE quote shape."""
    raw_items = getattr(response, "items", ()) or ()
    items: list[dict[str, object]] = []
    for raw in raw_items:
        stamp = _value(raw, "t")
        if not isinstance(stamp, str) or not stamp:
            continue
        items.append(
            {
                "security_code": _value(raw, "security_code"),
                "name": _value(raw, "name"),
                "price": _value(raw, "price"),
                "change_pct": _value(raw, "change_pct"),
                "amount": _value(raw, "amount"),
                "t": stamp,
            }
        )
    if not items:
        return None
    data_as_of = min(
        (item["t"] for item in items if isinstance(item["t"], str)),
        key=lambda stamp: dt.datetime.fromisoformat(stamp),
    )
    return {"items": items, "data_as_of": data_as_of}


def _content_token(data: dict[str, Any]) -> str:
    fingerprint = [
        {
            "security_code": item["security_code"],
            "price": item["price"],
            "change_pct": item["change_pct"],
            "amount": item["amount"],
            "t": item["t"],
        }
        for item in data["items"]
    ]
    fingerprint.sort(key=lambda item: str(item["security_code"]))
    raw = json.dumps(fingerprint, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def publish_quote(
    rds: redis.Redis,
    owner: uuid.UUID,
    response: object,
    at: dt.datetime,
) -> bool:
    """Best-effort quote publication. Redis failures never fail collection."""
    data = build_quote_data(response)
    if data is None:
        return False
    try:
        return bool(publish(rds, owner, "quote", data, at, _content_token(data)))
    except Exception as exc:  # noqa: BLE001 - publication is deliberately best effort
        log.warning("实时行情 SSE 发布失败：%s", type(exc).__name__)
        return False

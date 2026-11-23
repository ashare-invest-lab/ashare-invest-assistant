"""交易时段内按用户证书采集并写入 ``market.quotes_snapshot``。

``REALTIME_QUOTES_SOURCE=off`` 是默认值，关闭时不会创建数据库或麦蕊连接。
生产请求必须经过既有 ``single_egress`` / ``mairui_get``，测试可通过登记的窄缝
注入无网络 ``transport``。一轮先完成所有响应校验，再在一个事务中写入同一 ``batch_id``。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import quote

from sqlalchemy import Connection, Engine, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.aggregates.calendar import market_clock
from app.aggregates.models import MarketClock
from app.aggregates.service import select_account
from app.api.v1.portfolio import _account
from app.common.errors import AppError
from app.config import Settings
from app.db.tables.market import quotes_snapshot, securities
from app.db.tables.research import watchlist_items
from app.db.tables.users import users
from app.ingest.daily_lists import HALT as DAILY_HALT
from app.ingest.daily_lists import STOP, credential, limited
from app.ingest.egress import EgressDenied, mairui_get, single_egress
from app.ingest.mode import verification_is_offline
from app.ingest.runtime import get_ingest_core
from app.ingest.state import Priority
from app.ingest.upstream import Signal, classify
from app.marketdata.daily_snapshot import active_licence_id

log = logging.getLogger("app.marketdata.realtime_collect")

# 麦蕊既有 egress halt 路径；不为实时任务另造 halt 文件。
HALT = DAILY_HALT
SOURCE = "mairui"
# Endpoint documented in docs/plan.md §2.1 and §0A.6.
PATH = "/hsrl/ssjy_more?stock_codes="
# docs/plan.md §0A.6 / §2.1: the multi-stock endpoint accepts at most 20 codes.
MAX_CODES_PER_REQUEST = 20
OPEN_SESSIONS = frozenset({"morning", "afternoon"})
_TIMESTAMP_TEXT = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)

# 原始字段名均未验证（U8，T-B195）。每个系统字段只允许一个原始字段名。
REALTIME_FIELD_MAP: Final[Mapping[str, str]] = {
    "code": "code",
    "ts": "ts",
    "price": "price",
    "pct_change": "pct_change",
    "volume": "volume",
    "amount": "amount",
    "is_suspended": "is_suspended",
    "limit_up": "limit_up",
    "limit_down": "limit_down",
}

Transport = Callable[[str, str], tuple[int, object]]
SecretLoader = Callable[[Engine, uuid.UUID], str]


class RealtimeCollectionStoppedError(RuntimeError):
    """本轮因 STOP、上游错误或响应校验失败而停止，调用方不得重试。"""


def _now(value: dt.datetime | None) -> dt.datetime:
    stamp = value if value is not None else dt.datetime.now(dt.UTC)
    if stamp.tzinfo is None:
        raise ValueError("now must be timezone-aware")
    return stamp


def _chunks(values: Sequence[str], size: int) -> Iterable[tuple[str, ...]]:
    for start in range(0, len(values), size):
        yield tuple(values[start : start + size])


def _response_rows(body: object) -> list[Mapping[str, object]]:
    value = body
    if isinstance(value, Mapping) and "data" in value:
        value = value["data"]
    if not isinstance(value, list):
        raise RealtimeCollectionStoppedError("realtime_json_invalid")
    rows: list[Mapping[str, object]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RealtimeCollectionStoppedError("realtime_json_invalid")
        rows.append(item)
    return rows


def _mapped_value(row: Mapping[str, object], field: str) -> object | None:
    return row.get(REALTIME_FIELD_MAP[field])


def _quote_timestamp(value: object) -> dt.datetime:
    if value is None:
        raise RealtimeCollectionStoppedError("realtime_timestamp_missing")
    if isinstance(value, dt.datetime):
        stamp = value
    elif isinstance(value, str):
        text = value.strip()
        if not _TIMESTAMP_TEXT.fullmatch(text):
            raise RealtimeCollectionStoppedError("realtime_timestamp_invalid")
        try:
            stamp = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError as exc:
            raise RealtimeCollectionStoppedError("realtime_timestamp_invalid") from exc
    else:
        raise RealtimeCollectionStoppedError("realtime_timestamp_invalid")
    if stamp.tzinfo is None or stamp.utcoffset() is None:
        raise RealtimeCollectionStoppedError("realtime_timestamp_invalid")
    return stamp.astimezone(dt.UTC)


def _normalise_rows(
    requested: Sequence[str], rows: Iterable[Mapping[str, object]], fetched_at: dt.datetime
) -> list[dict[str, object]]:
    expected = set(requested)
    raw_codes: dict[str, list[str]] = {}
    for code in requested:
        raw_codes.setdefault(code.split(".", 1)[0], []).append(code)
    found: set[str] = set()
    output: list[dict[str, object]] = []
    for row in rows:
        # 既有测试入口使用规范 code，ssjy_more 的响应使用六位无后缀 dm。
        code_value = _mapped_value(row, "code")
        dm_value = row.get("dm")
        if dm_value is None:
            raise RealtimeCollectionStoppedError("realtime_code_invalid")
        if not isinstance(dm_value, str) or not re.fullmatch(r"\d{6}", dm_value):
            raise RealtimeCollectionStoppedError("realtime_code_invalid")
        dm_candidates = raw_codes.get(dm_value, [])
        if len(dm_candidates) != 1:
            raise RealtimeCollectionStoppedError("realtime_code_invalid")
        dm_code = dm_candidates[0]
        if code_value is not None and code_value != dm_code:
            raise RealtimeCollectionStoppedError("realtime_code_invalid")
        code_value = dm_code
        if not isinstance(code_value, str) or code_value not in expected or code_value in found:
            raise RealtimeCollectionStoppedError("realtime_code_invalid")
        found.add(code_value)
        payload = dict(row)
        quote_ts = _quote_timestamp(_mapped_value(row, "ts"))
        output.append(
            {
                "code": code_value,
                "ts": quote_ts,
                "price": _mapped_value(row, "price"),
                "pct_change": _mapped_value(row, "pct_change"),
                "payload": payload,
                "source": SOURCE,
                "volume": _mapped_value(row, "volume"),
                "amount": _mapped_value(row, "amount"),
                # T-B195 未验证（U8）：响应字段不足以确认这些状态。
                "is_suspended": None,
                "limit_up": None,
                "limit_down": None,
            }
        )
    if found != expected:
        raise RealtimeCollectionStoppedError("realtime_code_invalid")
    return output


def _validate_response(status: int, body: object) -> list[Mapping[str, object]]:
    if status in (101, 103, 429, 503) or status != 200:
        if status in (103, 429):
            log.error("实时行情上游触发限流，停止本轮")
        raise RealtimeCollectionStoppedError(f"realtime_http_{status}")
    if limited(status, body) or classify(status, body) is not Signal.OK:
        raise RealtimeCollectionStoppedError("realtime_upstream_error")
    return _response_rows(body)


def _reject_credential_echo(secret: str, body: object) -> None:
    encoded = json.dumps(body, ensure_ascii=False, default=str)
    if secret in encoded or quote(secret, safe="") in encoded:
        raise RealtimeCollectionStoppedError("credential_echo_rejected")


def _fingerprint(row: Mapping[str, object]) -> str:
    content = {
        key: row.get(key)
        for key in (
            "price",
            "pct_change",
            "payload",
            "volume",
            "amount",
            "is_suspended",
            "limit_up",
            "limit_down",
        )
    }
    return hashlib.sha256(
        json.dumps(content, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _revision_key(row: Mapping[str, object]) -> str:
    return "|".join(
        (
            str(row["code"]),
            str(row["ts"]),
            str(row["source"]),
            str(row["source_licence_id"]),
        )
    )


def _lock_revision_keys(conn: Connection, rows: Sequence[Mapping[str, object]]) -> None:
    """Serialize revision allocation for each ownership key in this transaction."""
    for key in sorted({_revision_key(row) for row in rows}):
        conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:revision_key, 0))"),
            {"revision_key": key},
        )


def _write_rows(conn: Connection, rows: Sequence[dict[str, object]], batch_id: uuid.UUID) -> int:
    if not rows:
        return 0
    _lock_revision_keys(conn, rows)
    fingerprints = [_fingerprint(row) for row in rows]
    source_licences = {row["source_licence_id"] for row in rows}
    codes = {row["code"] for row in rows}
    timestamps = {row["ts"] for row in rows}
    existing = conn.execute(
        select(
            quotes_snapshot.c.code,
            quotes_snapshot.c.ts,
            quotes_snapshot.c.source_licence_id,
            quotes_snapshot.c.revision,
            quotes_snapshot.c.content_fingerprint,
        ).where(
            quotes_snapshot.c.source == SOURCE,
            quotes_snapshot.c.source_licence_id.in_(source_licences),
            quotes_snapshot.c.code.in_(codes),
            quotes_snapshot.c.ts.in_(timestamps),
        )
    ).mappings()
    revisions: dict[tuple[object, object, object], list[tuple[int, object | None]]] = {}
    for item in existing:
        key = (item["code"], item["ts"], item["source_licence_id"])
        revisions.setdefault(key, []).append(
            (int(item["revision"]), item["content_fingerprint"])
        )
    values: list[dict[str, object]] = []
    for row, fingerprint in zip(rows, fingerprints, strict=True):
        key = (row["code"], row["ts"], row["source_licence_id"])
        known = revisions.setdefault(key, [])
        same = next((revision for revision, fp in known if fp == fingerprint), None)
        if same is None:
            revision = max((item[0] for item in known), default=-1) + 1
            known.append((revision, fingerprint))
        else:
            revision = same
        values.append(
            {
                **row,
                "batch_id": batch_id,
                "revision": revision,
                "content_fingerprint": fingerprint,
            }
        )
    stmt = pg_insert(quotes_snapshot).values(values)
    stmt = stmt.on_conflict_do_nothing(
        index_elements=[
            quotes_snapshot.c.code,
            quotes_snapshot.c.ts,
            quotes_snapshot.c.source,
            quotes_snapshot.c.source_licence_id,
            quotes_snapshot.c.revision,
        ],
        index_where=quotes_snapshot.c.source_licence_id.is_not(None)
        & quotes_snapshot.c.source.in_([SOURCE]),
    )
    result = conn.execute(stmt)
    return max(int(result.rowcount or 0), 0)


def _owned_codes(conn: Connection, owner: uuid.UUID, trade_date: dt.date) -> list[str]:
    raw: set[str] = set()
    account_id = select_account(conn, owner, None)
    if account_id is not None:
        raw.update(_account(conn, account_id, trade_date).positions)
    raw.update(
        conn.execute(
            select(watchlist_items.c.security_code).where(
                watchlist_items.c.user_id == owner,
                watchlist_items.c.removed_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    if not raw:
        return []
    listed = (
        conn.execute(
            select(securities.c.code).where(
                securities.c.code.in_(sorted(raw)),
                securities.c.type.in_({"stock", "etf"}),
                securities.c.listing_status == "listed",
            )
        )
        .scalars()
        .all()
    )
    return sorted(listed)


def _approved_owners(conn: Connection) -> list[uuid.UUID]:
    return list(
        conn.execute(
            select(users.c.id).where(users.c.status == "approved", users.c.deleted_at.is_(None))
        )
        .scalars()
        .all()
    )


def _open_clock(conn: Connection, settings: Settings, now: dt.datetime) -> MarketClock | None:
    try:
        return market_clock(conn, now, settings.business.market_rules)
    except AppError as exc:
        log.info("实时行情跳过：交易日历不可用（%s）", exc.code.value)
        return None


def realtime_quotes_seam[T](
    operation: Callable[..., T],
    *args: object,
    sender: Transport | None,
    **options: object,
) -> T:
    if sender is None:
        return operation(*args, **options)
    return operation(*args, transport=sender, **options)


def _fetch_with_egress(
    engine: Engine,
    settings: Settings,
    *,
    owner: uuid.UUID,
    licence_id: uuid.UUID,
    now: dt.datetime,
    path: str,
    upstream: Transport | None,
    secret_loader: SecretLoader,
    stop: Path,
    halt: Path,
) -> tuple[int, object]:
    if stop.is_file() or halt.is_file():
        raise RealtimeCollectionStoppedError("STOP_or_halt_present")
    core = get_ingest_core()
    if core is None:
        raise RealtimeCollectionStoppedError("ingest_core_unavailable")
    try:
        with single_egress(engine) as lease:
            if lease is None:
                raise RealtimeCollectionStoppedError("egress_lease_unavailable")
            secret = secret_loader(engine, licence_id)
            result = realtime_quotes_seam(
                mairui_get,
                lease=lease,
                core=core,
                engine=engine,
                licence_id=licence_id,
                user_id=owner,
                path=path,
                secret=secret,
                priority=Priority.P0,
                clock=lambda: _now(None),
                stop=stop,
                halt=halt,
                sender=upstream,
            )
    except EgressDenied as exc:
        raise RealtimeCollectionStoppedError(f"egress_{exc.code}") from None
    if result.status == 200:
        _reject_credential_echo(secret, result.body)
    return result.status, result.body


def collect_realtime_quotes(
    conn: Connection,
    settings: Settings,
    *,
    owner: uuid.UUID,
    now: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    upstream: Transport | None = None,
    transport: Transport | None = None,
    secret_loader: SecretLoader = credential,
    engine: Engine | None = None,
    stop: Path = STOP,
    halt: Path = HALT,
) -> int:
    """采集一个用户持仓与自选的一轮行情，所有响应通过后才写库。"""
    hook = transport if transport is not None else upstream
    if verification_is_offline():
        log.info("实时行情跳过：当前为 replay/离线模式")
        return 0
    if settings.realtime_quotes_source != "mairui":
        return 0
    read_clock = clock or (lambda: _now(now))
    stamp = _now(read_clock())
    initial_clock = _open_clock(conn, settings, stamp)
    if initial_clock is None:
        return 0
    if initial_clock.session.value not in OPEN_SESSIONS:
        log.info("实时行情跳过：交易时段为 %s", initial_clock.session.value)
        return 0
    licence_id = active_licence_id(conn, owner, stamp)
    if licence_id is None:
        log.info("实时行情跳过：用户没有 active 证书")
        return 0
    codes = _owned_codes(conn, owner, initial_clock.trade_date)
    if not codes:
        return 0
    if engine is None:
        raise ValueError("engine is required for a live realtime collection")
    fetched_rows: list[dict[str, object]] = []
    for group in _chunks(codes, MAX_CODES_PER_REQUEST):
        request_stamp = _now(read_clock())
        request_clock = _open_clock(conn, settings, request_stamp)
        if request_clock is None or request_clock.session.value not in OPEN_SESSIONS:
            raise RealtimeCollectionStoppedError("realtime_session_closed")
        request_licence = active_licence_id(conn, owner, request_stamp)
        if request_licence is None:
            raise RealtimeCollectionStoppedError("realtime_licence_unavailable")
        path = PATH + quote(",".join(group), safe=",")
        status, body = _fetch_with_egress(
            engine,
            settings,
            owner=owner,
            licence_id=request_licence,
            now=request_stamp,
            path=path,
            upstream=hook,
            secret_loader=secret_loader,
            stop=stop,
            halt=halt,
        )
        fetched_rows.extend(
            {
                **row,
                "source_licence_id": request_licence,
                "fetched_at": request_stamp,
            }
            for row in _normalise_rows(group, _validate_response(status, body), request_stamp)
        )
    if stop.is_file() or halt.is_file():
        raise RealtimeCollectionStoppedError("STOP_or_halt_present")
    with engine.begin() as write_conn:
        return _write_rows(write_conn, fetched_rows, uuid.uuid4())


def realtime_quotes_task(
    settings: Settings,
    *,
    now: dt.datetime | None = None,
    clock: Callable[[], dt.datetime] | None = None,
    owner: uuid.UUID | str | None = None,
    upstream: Transport | None = None,
    transport: Transport | None = None,
    secret_loader: SecretLoader = credential,
    engine: Engine | None = None,
) -> int:
    """运维入口：``market.realtime_quotes_fetch``，依赖 DB、日历、market_rules 与 active 证书。"""
    hook = transport if transport is not None else upstream
    if verification_is_offline():
        log.info("实时行情跳过：当前为 replay/离线模式")
        return 0
    if settings.realtime_quotes_source != "mairui":
        return 0
    if engine is None:
        raise RealtimeCollectionStoppedError("engine_unavailable")

    selected_owner: uuid.UUID | None
    if isinstance(owner, uuid.UUID):
        selected_owner = owner
    elif isinstance(owner, str):
        try:
            selected_owner = uuid.UUID(owner)
        except (ValueError, TypeError) as exc:
            raise ValueError("owner must be a UUID string") from exc
    else:
        selected_owner = None
    read_clock = clock or (lambda: _now(now))
    if selected_owner is not None:
        owners = [selected_owner]
    else:
        with engine.connect() as owner_conn:
            owners = _approved_owners(owner_conn)

    total = 0
    for current_owner in owners:
        with engine.connect() as owner_conn:
            total += collect_realtime_quotes(
                owner_conn,
                settings,
                owner=current_owner,
                clock=read_clock,
                upstream=hook,
                secret_loader=secret_loader,
                engine=engine,
                stop=STOP,
                halt=HALT,
            )
    return total

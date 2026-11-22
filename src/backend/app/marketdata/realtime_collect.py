"""交易时段内按用户证书采集并写入 ``market.quotes_snapshot``。

入口是 :func:`realtime_quotes_task`，由 ingest 心跳按间隔调度。
``REALTIME_QUOTES_SOURCE=off`` 是默认值，关闭时不会创建数据库或麦蕊连接。
生产请求必须经过既有 ``single_egress`` / ``mairui_get``，测试可注入无网络
``transport``。一轮先完成所有响应校验，再在一个事务中写入同一 ``batch_id``。
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import uuid
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path
from typing import Final
from urllib.parse import quote

from sqlalchemy import Connection, Engine, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.aggregates.calendar import BEIJING, market_clock
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
REALTIME_QUOTES_FETCH: Final = "market.realtime_quotes_fetch"
# Endpoint documented in docs/plan.md §2.1 and §0A.6.
PATH = "/hsrl/ssjy_more?stock_codes="
# docs/plan.md §0A.6 / §2.1: the multi-stock endpoint accepts at most 20 codes.
MAX_CODES_PER_REQUEST = 20
OPEN_SESSIONS = frozenset({"morning", "afternoon"})

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

    def __init__(self, reason: str, status: int | None = None) -> None:
        super().__init__(reason)
        self.status = status


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
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            stamp = dt.datetime.fromtimestamp(float(value), dt.UTC)
        except (OverflowError, OSError, ValueError) as exc:
            raise RealtimeCollectionStoppedError("realtime_timestamp_invalid") from exc
    elif isinstance(value, str):
        text = value.strip().replace("Z", "+00:00")
        try:
            stamp = dt.datetime.fromisoformat(text)
        except ValueError as exc:
            raise RealtimeCollectionStoppedError("realtime_timestamp_invalid") from exc
    else:
        raise RealtimeCollectionStoppedError("realtime_timestamp_invalid")
    if stamp.tzinfo is None:
        # 无时区值按北京时区解析，原始时点语义未验证（U8，T-B195）。
        stamp = stamp.replace(tzinfo=BEIJING)
    return stamp.astimezone(dt.UTC)


def _normalise_rows(
    requested: Sequence[str], rows: Iterable[Mapping[str, object]], fetched_at: dt.datetime
) -> list[dict[str, object]]:
    expected = set(requested)
    found: set[str] = set()
    output: list[dict[str, object]] = []
    for row in rows:
        # 代码格式转换未验证（U8，T-B195）；仓库没有可复用转换工具，只接受规范代码。
        code_value = _mapped_value(row, "code")
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
        raise RealtimeCollectionStoppedError("realtime_code_missing")
    return output


def _validate_response(status: int, body: object) -> list[Mapping[str, object]]:
    if status in (101, 103, 429, 503) or status != 200:
        if status in (103, 429):
            log.error("实时行情上游触发限流，停止本轮")
        raise RealtimeCollectionStoppedError(f"realtime_http_{status}", status=status)
    if limited(status, body) or classify(status, body) is not Signal.OK:
        raise RealtimeCollectionStoppedError("realtime_upstream_error")
    return _response_rows(body)


def _fingerprint(row: Mapping[str, object]) -> str:
    return hashlib.sha256(
        json.dumps(row, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _write_rows(conn: Connection, rows: Sequence[dict[str, object]], batch_id: uuid.UUID) -> int:
    if not rows:
        return 0
    values = [
        {
            **row,
            "source_licence_id": row["source_licence_id"],
            "batch_id": batch_id,
            "fetched_at": row["fetched_at"],
            "revision": 0,
            "content_fingerprint": _fingerprint(row),
        }
        for row in rows
    ]
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


def _fetch_with_egress(
    engine: Engine,
    settings: Settings,
    *,
    owner: uuid.UUID,
    licence_id: uuid.UUID,
    now: dt.datetime,
    path: str,
    transport: Transport | None,
    secret_loader: SecretLoader,
    stop: Path,
    halt: Path,
) -> tuple[int, object]:
    if stop.is_file() or halt.is_file():
        raise RealtimeCollectionStoppedError("STOP_or_halt_present")
    secret = secret_loader(engine, licence_id)
    core = get_ingest_core()
    if core is None:
        from app.ingest.core import IngestCore

        core = IngestCore(cfg=settings.business.ingest.licences, engine=engine)
    kwargs: dict[str, object] = {
        "lease": None,
        "core": core,
        "engine": engine,
        "licence_id": licence_id,
        "user_id": owner,
        "path": path,
        "secret": secret,
        "priority": Priority.P0,
        "clock": lambda: now,
        "stop": stop,
        "halt": halt,
    }
    if transport is not None:
        kwargs["transport"] = transport
    try:
        with single_egress(engine) as lease:
            kwargs["lease"] = lease
            result = mairui_get(**kwargs)  # type: ignore[arg-type]
    except EgressDenied as exc:
        raise RealtimeCollectionStoppedError(f"egress_{exc.code}") from None
    return result.status, result.body


def collect_realtime_quotes(
    conn: Connection,
    settings: Settings,
    *,
    owner: uuid.UUID,
    now: dt.datetime | None = None,
    transport: Transport | None = None,
    secret_loader: SecretLoader = credential,
    engine: Engine | None = None,
    stop: Path = STOP,
    halt: Path = HALT,
) -> int:
    """采集一个用户持仓与自选的一轮行情，所有响应通过后才写库。"""
    if verification_is_offline():
        log.info("实时行情跳过：当前为 replay/离线模式")
        return 0
    if settings.realtime_quotes_source != "mairui":
        return 0
    stamp = _now(now)
    clock = _open_clock(conn, settings, stamp)
    if clock is None:
        return 0
    if clock.session.value not in OPEN_SESSIONS:
        log.info("实时行情跳过：交易时段为 %s", clock.session.value)
        return 0
    licence_id = active_licence_id(conn, owner, stamp)
    if licence_id is None:
        log.info("实时行情跳过：用户没有 active 证书")
        return 0
    codes = _owned_codes(conn, owner, clock.trade_date)
    if not codes:
        return 0
    if engine is None:
        raise ValueError("engine is required for a live realtime collection")
    fetched_rows: list[dict[str, object]] = []
    for group in _chunks(codes, MAX_CODES_PER_REQUEST):
        path = PATH + quote(",".join(group), safe=",")
        status, body = _fetch_with_egress(
            engine,
            settings,
            owner=owner,
            licence_id=licence_id,
            now=stamp,
            path=path,
            transport=transport,
            secret_loader=secret_loader,
            stop=stop,
            halt=halt,
        )
        fetched_rows.extend(
            {
                **row,
                "source_licence_id": licence_id,
                "fetched_at": stamp,
            }
            for row in _normalise_rows(group, _validate_response(status, body), stamp)
        )
    if stop.is_file() or halt.is_file():
        raise RealtimeCollectionStoppedError("STOP_or_halt_present")
    with engine.begin() as write_conn:
        return _write_rows(write_conn, fetched_rows, uuid.uuid4())


def realtime_quotes_task(
    settings: Settings,
    *,
    now: dt.datetime | None = None,
    owner: uuid.UUID | str | None = None,
    transport: Transport | None = None,
    secret_loader: SecretLoader = credential,
) -> int:
    """ingest 心跳入口，依赖 DB、日历、market_rules 与 active 证书。"""
    if verification_is_offline():
        log.info("实时行情跳过：当前为 replay/离线模式")
        return 0
    if settings.realtime_quotes_source != "mairui":
        return 0
    from app.workers.jobs import _engine

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
    stamp = _now(now)
    engine = _engine(settings)
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
                now=stamp,
                transport=transport,
                secret_loader=secret_loader,
                engine=engine,
                stop=STOP,
                halt=HALT,
            )
    return total

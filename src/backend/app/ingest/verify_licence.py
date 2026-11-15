"""``verify_licence`` 意图消费者（T-B141）。

语义出处：
- 流程：``docs/plan.md`` §2.1B 第 1 点「验证」——PUT 或 ``POST /me/data-licence/test`` 后
  ``api`` 向 ``ingest:requests`` 投递 ``verify_licence``（只带 ``licence_id``），``ingest`` 用一次
  轻量接口验证，结果写回状态表；``docs/api-contract.md`` §7.1 ``/me/data-licence/test`` 同义；
  §7.11.5 第 1 条要求 ``verify_licence`` 必须经 ``mairui_get`` 外呼。
- docs 没有「验证结果 → 状态」的专门契约，按编排者裁定用**最小语义**：
  调用一次轻量接口；HTTP 200 且业务正常 → ``active``；其他保持原状态并记因；
  STOP/HALT/103/429/503 不重试、不改 ``active``、记因；103/429/503 写 HALT。
- 写库失败也已 ACK，只记日志（``persist_failed``），绝不重领再调。
- 裁定出处——编排者 T-B141 裁定（用户点 /me/data-licence/test 触发的单次轻量调用，
  接口 /tcalendar/list/{year}，产品功能），响应不写入 trading_calendar。

每条意图至多一次 HTTP：先拿单活锁、先 ACK 再处理（崩溃不重放）。明文只在本进程内存中。
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from redis.exceptions import ResponseError
from sqlalchemy import Engine, select, update

from app.db.tables.licences import data_licence_events, user_data_licences
from app.ingest.daily_lists import HALT, STOP, DailyHaltError, credential
from app.ingest.egress import EgressDenied, EgressLease, mairui_get, single_egress
from app.ingest.intents import VerifyIntent, parse_intent
from app.ingest.mode import VERIFY_OFFLINE_REASON, verification_is_offline
from app.ingest.runtime import get_ingest_core
from app.ingest.upstream import Signal
from app.licences.service import INGEST_REQUESTS_STREAM
from app.schemas.enums import DATA_LICENCE_ERROR_CODES, DataLicenceStatus

log = logging.getLogger(__name__)

BEIJING = ZoneInfo("Asia/Shanghai")
GROUP = "mairui-verify-v1"
CONSUMER = "verify-single"
_ACTIVATABLE = frozenset(
    {DataLicenceStatus.PENDING_VERIFICATION.value, DataLicenceStatus.ACTIVE.value}
)

SecretLoader = Callable[[Engine, uuid.UUID], str]
Clock = Callable[[], dt.datetime]


@dataclass(frozen=True)
class VerifyResult:
    status: str
    activated: bool
    reason: str | None
    calls: int


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def light_path(now: dt.datetime) -> str:
    """Trading-calendar list of the Beijing year (T-B141 ruling); response is not stored."""
    return f"/tcalendar/list/{now.astimezone(BEIJING).year}/"


def reason_for(status_code: int, body: object, signal: Signal) -> str:
    """Upstream outcome → reason token (``DATA_LICENCE_ERROR_CODES`` where possible)."""
    if signal == Signal.IP_LIMITED:
        return "429" if status_code == 429 and "103" not in str(body) else "103"
    if signal == Signal.INVALID:
        return "102"
    if signal == Signal.QUOTA:
        return "101"
    if status_code == 503 or signal in {Signal.RATE_LIMITED, Signal.DATA_MISSING}:
        return "503"
    if signal == Signal.OK:
        return "empty_body"
    return f"http_{status_code}"


def _keep(
    engine: Engine, lid: uuid.UUID, status: str, reason: str, calls: int, now: dt.datetime
) -> VerifyResult:
    """Keep status; persist the reason when the column enum allows it, always log it."""
    if reason in DATA_LICENCE_ERROR_CODES:
        with engine.begin() as conn:
            conn.execute(
                update(user_data_licences)
                .where(user_data_licences.c.id == lid, user_data_licences.c.deleted_at.is_(None))
                .values(last_error_code=reason, last_error_at=now, updated_at=now)
            )
    log.info("verify_licence kept licence=%s status=%s reason=%s", lid, status, reason)
    return VerifyResult(status=status, activated=False, reason=reason, calls=calls)


def _activate(
    engine: Engine, lid: uuid.UUID, uid: uuid.UUID, current: str, now: dt.datetime
) -> VerifyResult:
    t = user_data_licences.c
    with engine.begin() as conn:
        done = conn.execute(
            update(user_data_licences)
            .where(t.id == lid, t.deleted_at.is_(None), t.status == current)
            .values(
                status=DataLicenceStatus.ACTIVE.value,
                status_changed_at=now,
                updated_at=now,
                last_verified_at=now,
                last_error_code=None,
                last_error_at=None,
            )
        ).rowcount
        if done != 1:
            # Status changed concurrently (e.g. admin pause / delete): do not override.
            return VerifyResult(status=current, activated=False, reason="status_changed", calls=1)
        conn.execute(
            data_licence_events.insert().values(
                licence_id=lid,
                user_id=uid,
                event="verified",
                actor="ingest",
                from_status=current,
                to_status=DataLicenceStatus.ACTIVE.value,
                at=now,
            )
        )
    log.info("verify_licence activated licence=%s", lid)
    return VerifyResult(status=DataLicenceStatus.ACTIVE.value, activated=True, reason=None, calls=1)


def process_verify_intent(
    engine: Engine,
    intent: VerifyIntent,
    *,
    lease: EgressLease | None,
    clock: Clock = _utcnow,
    secret_loader: SecretLoader = credential,
    stop: Path = STOP,
    halt: Path = HALT,
    core: Any = None,  # noqa: ANN401 - IngestCore | None
) -> VerifyResult:
    """At most one light call for ``intent``; never retries."""
    lid = intent.licence_id
    with engine.connect() as conn:
        row = conn.execute(
            select(
                user_data_licences.c.user_id,
                user_data_licences.c.status,
                user_data_licences.c.deleted_at,
            ).where(user_data_licences.c.id == lid)
        ).first()
    if row is None or row.deleted_at is not None:
        return VerifyResult(
            status="not_set", activated=False, reason="licence_unavailable", calls=0
        )
    current = str(row.status)
    calls = 0
    reason: str | None = None
    if verification_is_offline():
        reason = VERIFY_OFFLINE_REASON
    elif current not in _ACTIVATABLE:
        reason = "licence_unavailable"
    elif stop.exists() or halt.exists():
        reason = "STOP"
    else:
        try:
            secret = secret_loader(engine, lid)
        except Exception:  # noqa: BLE001 - never surface vault/credential errors
            reason = "secret_unavailable"
        else:
            try:
                ingest_core = core if core is not None else get_ingest_core()
                now = clock()
                if (
                    current == DataLicenceStatus.PENDING_VERIFICATION.value
                    and ingest_core is not None
                    and lid in ingest_core.licences
                ):
                    ingest_core.user_reset(lid, now)
                result = mairui_get(
                    lease=lease,
                    core=ingest_core,
                    engine=engine,
                    licence_id=lid,
                    user_id=row.user_id,
                    path=light_path(now),
                    secret=secret,
                    priority=intent.priority,
                    clock=clock,
                    stop=stop,
                    halt=halt,
                    verify=True,
                )
                calls = 1
                if not (result.status == 200 and result.signal == Signal.OK and result.body):
                    reason = reason_for(result.status, result.body, result.signal)
            except EgressDenied as exc:
                reason = "STOP" if exc.code == "halt_present" else exc.code
            except DailyHaltError:
                reason, calls = "network", 1
            finally:
                secret = ""
    try:
        if reason is None:
            return _activate(engine, lid, row.user_id, current, clock())
        return _keep(engine, lid, current, reason, calls, clock())
    except Exception:  # noqa: BLE001 - persistence failures must not replay a call
        log.warning(
            "verify_licence persist failed licence=%s reason=%s", lid, reason or "persist_failed"
        )
        return VerifyResult(status=current, activated=False, reason="persist_failed", calls=calls)


def tick(
    engine: Engine,
    rds: Any,  # noqa: ANN401 - redis.Redis
    *,
    clock: Clock = _utcnow,
    secret_loader: SecretLoader = credential,
    stop: Path = STOP,
    halt: Path = HALT,
    core: Any = None,  # noqa: ANN401 - IngestCore | None
) -> int:
    """Consume at most one ``ingest:requests`` record in our own group (others unaffected).

    The group starts at ``$`` (only new requests). The single-egress lock is taken before
    reading, and the record is ACKed before processing: a crash never replays a call.
    """
    try:
        rds.xgroup_create(INGEST_REQUESTS_STREAM, GROUP, id="$", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise
    with single_egress(engine) as lease:
        if lease is None:
            return 0
        batch = rds.xreadgroup(GROUP, CONSUMER, {INGEST_REQUESTS_STREAM: ">"}, count=1)
        handled = 0
        for _stream, messages in batch or []:
            for mid, fields in messages:
                rds.xack(INGEST_REQUESTS_STREAM, GROUP, mid)
                try:
                    intent = parse_intent(fields)
                    if isinstance(intent, VerifyIntent):
                        process_verify_intent(
                            engine,
                            intent,
                            lease=lease,
                            clock=clock,
                            secret_loader=secret_loader,
                            stop=stop,
                            halt=halt,
                            core=core,
                        )
                        handled += 1
                except Exception:  # noqa: BLE001 - already ACKed; never replay
                    log.warning("verify_licence message processing failed")
        return handled

"""行情采集 ingest 入口（占位）：``python -m app.workers.ingest``。

占位实现**不发任何外部请求**（不调用麦蕊，不读取 licence），只按契约 v0.2 §7.10 每
``ingest.yaml`` 的 ``heartbeat.interval_s``（默认 15 秒）写一次 Redis 心跳：
``SET <heartbeat.key> <json> EX <heartbeat.ttl_s>``，JSON 为
``{"ts", "instance_id", "leader", "version", "budget_used_last_minute", "queue_depth"}``。
键名可由环境变量 ``INGEST_HEARTBEAT_KEY`` 覆盖（与 /health/ready 读取同一个设置）。

T-A07（plan §2.1B 第 7 点、契约 v0.2.6）：生产与预发**不再使用**全站 ``MAIRUI_LICENCE``，
每位用户的证书以 HPKE 密文存库。``ingest`` 发现环境变量 ``MAIRUI_LICENCE`` 非空即**拒绝启动**
（退出码 78 = EX_CONFIG），且不输出它的值、长度或任何片段。只有本机实测脚本（``probes/``，
不属于本服务）可以在用户本人电脑的 shell 中临时设置它。

T-B114：启动时正式接线 ``set_ingest_core(IngestCore(..., engine=...))``，限流升级计数落库；
``DATABASE_URL`` / engine 不可用则拒绝启动（与 L-1′ 一致）。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import suppress
from decimal import Decimal
from pathlib import Path
from typing import cast

import redis
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import Settings
from app.ingest import daily_bars as daily_bars_config
from app.ingest import netguard as _netguard
from app.marketdata.daily_bars import DailyBar, DailyBarsResult
from app.version import APP_VERSION
from app.workers.runner import run

INSTANCE_ID = f"{socket.gethostname()}:{os.getpid()}"

#: 已废弃的全站证书变量（T-A07）；只判断是否非空，从不读取或输出它的值
LEGACY_LICENCE_ENV = "MAIRUI_LICENCE"
#: sysexits.h EX_CONFIG
EXIT_LEGACY_LICENCE = 78
LEGACY_LICENCE_MESSAGE = (
    "ingest 拒绝启动：环境变量 MAIRUI_LICENCE 非空。T-A07 起每位用户的麦蕊证书加密存库"
    "（plan §2.1B），生产与预发不再使用全站证书；请从 compose / env 文件中删除该变量"
)


#: T-B49（T-O11 裁定）：ingest 不得持有 APP_MASTER_KEY；发现即拒绝启动（同样退出码 78）
MASTER_KEY_ENV = "APP_MASTER_KEY"
MASTER_KEY_MESSAGE = (
    "ingest 拒绝启动：发现 APP_MASTER_KEY。主密钥只给 api / worker，ingest 不得派生任何 HMAC / "
    "签名密钥；请从 ingest 的 environment / secrets 中删除它"
)


def _daily_bar_rows(body: object) -> list[Mapping[str, object]]:
    if isinstance(body, list):
        return [row for row in body if isinstance(row, Mapping)]
    if isinstance(body, Mapping):
        if "t" in body:
            return [body]
        for key in ("data", "rows", "items", "list"):
            value = body.get(key)
            if isinstance(value, list):
                return [row for row in value if isinstance(row, Mapping)]
    return []


def _daily_bar_date(value: object) -> dt.date | None:
    try:
        text = str(value)
        if len(text) == 8 and text.isdigit():
            return dt.datetime.strptime(text, "%Y%m%d").date()
        return dt.date.fromisoformat(text[:10])
    except (TypeError, ValueError):
        return None


def _daily_bar_decimal(value: object) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (ArithmeticError, TypeError, ValueError):
        return None


def _decode_daily_bars(
    code: str, start: dt.date, end: dt.date, body: object
) -> DailyBarsResult:
    bars: list[DailyBar] = []
    for row in _daily_bar_rows(body):
        day = _daily_bar_date(row.get("t"))
        if day is None or not start <= day <= end:
            continue
        flag = row.get("sf")
        if flag in (1, "1", True):
            bars.append(DailyBar(code, day, "none", None, None, None, None, None, None, None, True))
            continue
        if flag not in (0, "0", False):
            continue
        values = tuple(
            _daily_bar_decimal(row.get(key)) for key in ("o", "h", "l", "c", "pc", "a")
        )
        volume = _daily_bar_decimal(row.get("v"))
        if any(value is None for value in values) or volume is None:
            continue
        open_, high, low, close, pre_close, amount = values
        bars.append(
            DailyBar(
                code,
                day,
                "none",
                open_,
                high,
                low,
                close,
                pre_close,
                volume * Decimal(100),
                amount,
                False,
            )
        )
    return DailyBarsResult(bars=tuple(bars))


class MairuiDailyBarsTransport:
    """Bind the daily-bar callback to the consumer's held egress lease."""

    def bind(
        self,
        *,
        engine: Engine,
        lease: object,
        item: Mapping[str, object],
        clock: Callable[[], dt.datetime],
        stop: Path,
        halt: Path,
    ) -> Callable[[str, dt.date, dt.date], tuple[int, DailyBar | DailyBarsResult | None]]:
        from app.ingest.daily_lists import credential
        from app.ingest.egress import EgressLease, mairui_get
        from app.ingest.runtime import get_ingest_core
        from app.ingest.state import Priority

        licence_id = cast(uuid.UUID, item["source_licence_id"])
        user_id = cast(uuid.UUID, item["user_id"])
        egress_lease = cast(EgressLease, lease)
        secret = credential(engine, licence_id)
        core = get_ingest_core()

        def send(
            code: str, start: dt.date, end: dt.date
        ) -> tuple[int, DailyBar | DailyBarsResult | None]:
            path = (
                f"/hsstock/history/{code}/d/n/?st={start.strftime('%Y%m%d')}"
                f"&et={end.strftime('%Y%m%d')}&"
            )
            result = mairui_get(
                lease=egress_lease,
                core=core,
                engine=engine,
                licence_id=licence_id,
                user_id=user_id,
                path=path,
                secret=secret,
                priority=Priority.P1,
                clock=clock,
                stop=stop,
                halt=halt,
            )
            if result.status in {101, 103, 429, 503}:
                return result.status, DailyBarsResult(halted=str(result.status))
            return result.status, _decode_daily_bars(code, start, end, result.body)

        return send


DAILY_BARS_TRANSPORT = MairuiDailyBarsTransport()


#: T-B114：无 DATABASE_URL / engine 不可用时拒绝启动（退出码 78，与 L-1′ 一致）
NO_DATABASE_URL_MESSAGE = (
    "ingest 拒绝启动：DATABASE_URL 未设置。T-B114 起 IngestCore 必须持有真实 engine"
    "（限流升级计数落库，与 L-1′ 一致）；请在 compose / env 中为 ingest 配置 DATABASE_URL"
)
ENGINE_UNAVAILABLE_MESSAGE = (
    "ingest 拒绝启动：无法从 DATABASE_URL 取得可用 engine（连接探测失败）。"
    "T-B114 / L-1′：无 engine 不得启动 ingest"
)


def master_key_present(environ: Mapping[str, str] | None = None) -> bool:
    """环境里是否有非空 ``APP_MASTER_KEY``。只返回布尔值。"""
    env = os.environ if environ is None else environ
    return bool(env.get(MASTER_KEY_ENV, "").strip())


def legacy_licence_present(environ: Mapping[str, str] | None = None) -> bool:
    """``MAIRUI_LICENCE`` 是否非空（去首尾空白后）。只返回布尔值。"""
    env = os.environ if environ is None else environ
    return bool(env.get(LEGACY_LICENCE_ENV, "").strip())


def heartbeat_payload(now: float | None = None) -> str:
    return json.dumps(
        {
            "ts": int(time.time() if now is None else now),
            "instance_id": INSTANCE_ID,
            "leader": True,
            "version": APP_VERSION,
            "budget_used_last_minute": 0,
            "queue_depth": {"p0": 0, "p1": 0, "p2": 0},
        },
        separators=(",", ":"),
    )


def bootstrap_ingest_core(settings: Settings) -> Engine:
    """Construct ``IngestCore`` with a real engine and register it for the process.

    T-B114 / L-1′: refuse (raise ``RuntimeError``) when ``DATABASE_URL`` is missing
    or the engine cannot answer ``SELECT 1``. Call once from ingest ``main`` before
    the heartbeat loop. Returns the shared engine (do not dispose while the core
    is wired).
    """
    from app.db.engine import engine_for
    from app.ingest.core import IngestCore
    from app.ingest.runtime import set_ingest_core

    if settings.database_url is None:
        raise RuntimeError(NO_DATABASE_URL_MESSAGE)

    engine = engine_for(settings.database_url.get_secret_value(), profile="ingest")
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        raise RuntimeError(f"{ENGINE_UNAVAILABLE_MESSAGE}: {type(exc).__name__}") from exc

    _probe_halt_directory()

    core = IngestCore(cfg=settings.business.ingest.licences, engine=engine)
    set_ingest_core(core)
    return engine


def write_heartbeat(settings: Settings) -> None:
    if not settings.redis_url:
        raise RuntimeError("REDIS_URL 未设置")
    hb = settings.business.ingest.heartbeat
    timeout = settings.health_check_timeout_s
    client = redis.Redis.from_url(
        settings.redis_url, socket_connect_timeout=timeout, socket_timeout=timeout
    )
    try:
        client.set(settings.ingest_heartbeat_key, heartbeat_payload(), ex=hb.ttl_s)
        from app.db.engine import engine_for
        from app.ingest.daily_bars_consumer import tick as tick_bars
        from app.ingest.daily_bars_consumer import wake_delayed
        from app.ingest.daily_lists import tick
        from app.ingest.runtime import get_ingest_core, tick_ingest_core

        # No live I/O is possible without the operator receipt; absent receipt
        # does not load the HPKE vault. Existing heartbeat remains available.
        def heartbeat_wait(seconds: float) -> None:
            import time

            remaining = seconds
            while remaining > 0:
                client.set(settings.ingest_heartbeat_key, heartbeat_payload(), ex=hb.ttl_s)
                duration = min(1, remaining)
                time.sleep(duration)
                remaining -= duration

        # Prefer the process-lifetime engine from bootstrap (T-B114). Do not dispose
        # a shared engine_for handle — that would break IngestCore mid-flight.
        core = get_ingest_core()
        shared_engine = core.engine if core is not None else None
        if not client.exists(settings.ingest_paused_key):
            from app.ingest.verify_licence import tick as tick_verify

            if shared_engine is not None:
                tick(shared_engine, client, pause=heartbeat_wait)
                try:
                    tick_verify(shared_engine, client)
                except Exception:  # noqa: BLE001 - keep heartbeat running
                    logging.warning("verify_licence tick failed")
                if getattr(settings, "daily_bars_source", "off") == "mairui":
                    daily_bars_config.configure_daily_bars_from_settings(settings)
                    tick_bars(
                        shared_engine,
                        transport=DAILY_BARS_TRANSPORT,
                    )
                    wake_delayed(shared_engine, client)
            elif settings.database_url is not None:
                engine = engine_for(settings.database_url.get_secret_value(), profile="ingest")
                try:
                    tick(engine, client, pause=heartbeat_wait)
                    try:
                        tick_verify(engine, client)
                    except Exception:  # noqa: BLE001 - keep heartbeat running
                        logging.warning("verify_licence tick failed")
                    if getattr(settings, "daily_bars_source", "off") == "mairui":
                        daily_bars_config.configure_daily_bars_from_settings(settings)
                        tick_bars(
                            engine,
                            transport=DAILY_BARS_TRANSPORT,
                        )
                        wake_delayed(engine, client)
                finally:
                    engine.dispose()
        # T-B113 / T-A84: every heartbeat round must tick IngestCore (pending IP-limit flush).
        tick_ingest_core()
    finally:
        client.close()


def _probe_halt_directory() -> None:
    """T-A91 M-c: halt dir must be writable; never touch existing HALT files."""
    from app.ingest.daily_lists import HALT

    directory = HALT.parent
    probe = directory / f".probe-{os.getpid()}"
    fd = None
    try:
        fd = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.write(fd, b"probe")
        os.fsync(fd)
    except Exception as exc:
        raise RuntimeError("ingest 拒绝启动：停机标志目录不可写") from exc
    finally:
        if fd is not None:
            os.close(fd)
        with suppress(FileNotFoundError):
            os.unlink(probe)


def main() -> int:
    _netguard.install()
    if legacy_licence_present():
        # 在读取配置、建立任何连接之前退出；消息不含变量值
        print(LEGACY_LICENCE_MESSAGE, file=sys.stderr)
        return EXIT_LEGACY_LICENCE
    if master_key_present():
        print(MASTER_KEY_MESSAGE, file=sys.stderr)
        return EXIT_LEGACY_LICENCE

    # T-A87 L-2: any Settings/bootstrap failure → exit 78; fixed text + type name only
    # (never str(exc) — ValidationError may embed input_value / secrets).
    try:
        from app.config import get_settings

        settings = get_settings()
        bootstrap_ingest_core(settings)
    except Exception as exc:  # noqa: BLE001
        # M-c: halt-dir refusal uses a fixed sentence (no path/secret). Other
        # bootstrap failures stay type-name only (L-2).
        if isinstance(exc, RuntimeError) and "停机标志目录不可写" in str(exc):
            print(str(exc), file=sys.stderr)
        else:
            print(f"ingest 拒绝启动：{type(exc).__name__}", file=sys.stderr)
        return EXIT_LEGACY_LICENCE

    interval = settings.business.ingest.heartbeat.interval_s
    return run("ingest", tick=write_heartbeat, interval_s=interval)


if __name__ == "__main__":
    sys.exit(main())

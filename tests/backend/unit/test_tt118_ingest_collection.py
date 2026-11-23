"""T-T118：实时行情只能经 ingest 公共入口采集并写入。"""

from __future__ import annotations

import datetime as dt
import importlib
import json
import os
import socket
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from alembic import command
from alembic.config import Config
from app.config import Settings, load_yaml_dir
from app.db.tables.licences import user_data_licences
from app.db.tables.market import securities, trading_calendar
from app.db.tables.research import watchlist_items
from app.db.tables.users import users
from app.workers import jobs
from sqlalchemy import create_engine, delete, insert, text
from sqlalchemy.engine import make_url

TASK = "market.realtime_quotes_fetch"
OWNER = UUID("00000000-0000-4000-8000-000000001118")
LICENCE = UUID("00000000-0000-4000-8000-000000001119")
CODES = ("600001.SH", "600002.SH")
NOW = dt.datetime(2030, 6, 11, 10, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
SOCKET_ATTEMPTS: list[object] = []


class _Queue:
    def __init__(self) -> None:
        self.item: bytes | None = json.dumps({"task": TASK, "args": {}}).encode()
        self.locks: dict[str, bytes] = {}

    def rpop(self, _key: str) -> bytes | None:
        item, self.item = self.item, None
        return item

    def set(self, key: str, value: str, *, nx: bool, ex: int) -> bool:
        del nx, ex
        if key in self.locks:
            return False
        self.locks[key] = value.encode()
        return True

    def get(self, key: str) -> bytes | None:
        return self.locks.get(key)

    def delete(self, key: str) -> int:
        return int(self.locks.pop(key, None) is not None)


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    SOCKET_ATTEMPTS.clear()

    def reject(*_args: object, **_kwargs: object) -> None:
        SOCKET_ATTEMPTS.append(_args)
        raise AssertionError("T-T118 禁止真实网络连接")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def _probe_entry() -> tuple[object, str, object] | None:
    for module_name, names in (
        (
            "app.marketdata.realtime_collect",
            ("collect_realtime_quotes", "realtime_quotes_task"),
        ),
        ("app.workers.ingest", ("tick_realtime_quotes",)),
    ):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        for name in names:
            value = getattr(module, name, None)
            if callable(value):
                return module, name, value
    return None


_ENTRY_AVAILABLE = _probe_entry() is not None


def _require_entry() -> tuple[object, str, object]:
    found = _probe_entry()
    if found is None:
        pytest.xfail("T-B221 未实现：没有可调用的 ingest 公共实时采集入口")
    return found


def _worker_registered() -> bool:
    return TASK in jobs.TASKS or any(
        isinstance(value, dict) and TASK in value for value in vars(jobs).values()
    )


def _worker_tick() -> list[tuple[str, str]]:
    return jobs.worker_tick(Settings.model_construct(), client=_Queue())


def _settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(
        Settings,
        "settings_customise_sources",
        classmethod(lambda cls, settings_cls, init_settings, **kwargs: (init_settings,)),
    )
    config_dir = Path(__file__).resolve().parents[3] / "config"
    return Settings(
        _env_file=None,
        app_env="test",
        database_url="postgresql://invalid/invalid",
        redis_url="redis://invalid/0",
        config_dir=config_dir,
        business=load_yaml_dir(config_dir),
        realtime_quotes_source="mairui",
    )


def _engine() -> object:
    pg_url = os.environ.get("AIA_TEST_DATABASE_URL") or os.environ["DATABASE_URL"]
    backend = Path(__file__).resolve().parents[3] / "src" / "backend"
    alembic = Config(str(backend / "alembic.ini"))
    alembic.cmd_opts = SimpleNamespace(x=[f"url={pg_url}"])
    command.upgrade(alembic, "head")
    return create_engine(make_url(pg_url).set(drivername="postgresql+psycopg"))


def _cleanup(conn: object) -> None:
    conn.execute(  # type: ignore[union-attr]
        text("DELETE FROM market.quotes_snapshot WHERE code IN (:a, :b)"),
        {"a": CODES[0], "b": CODES[1]},
    )
    conn.execute(delete(watchlist_items).where(watchlist_items.c.user_id == OWNER))  # type: ignore[union-attr]
    conn.execute(delete(user_data_licences).where(user_data_licences.c.id == LICENCE))  # type: ignore[union-attr]
    conn.execute(delete(users).where(users.c.id == OWNER))  # type: ignore[union-attr]
    conn.execute(delete(securities).where(securities.c.code.in_(CODES)))  # type: ignore[union-attr]
    conn.execute(delete(trading_calendar).where(trading_calendar.c.date == NOW.date()))  # type: ignore[union-attr]


def _seed(engine: object) -> None:
    with engine.begin() as conn:  # type: ignore[union-attr]
        _cleanup(conn)
        conn.execute(
            insert(users).values(
                id=OWNER,
                username="tt118b_user",
                password_hash="synthetic-password-hash",
                role="user",
                status="approved",
            )
        )
        conn.execute(
            insert(user_data_licences).values(
                id=LICENCE,
                user_id=OWNER,
                provider="mairui",
                status="active",
                ciphertext=b"\x00",
                licence_hmac=uuid4().bytes,
                seal_key_version=1,
                tier="annual",
                has_quant_pro=False,
            )
        )
        conn.execute(
            insert(securities),
            [
                {
                    "code": code,
                    "type": "stock",
                    "name": f"Synthetic {code}",
                    "exchange": "SH",
                    "listing_status": "listed",
                }
                for code in CODES
            ],
        )
        conn.execute(
            insert(watchlist_items),
            [
                {"user_id": OWNER, "security_code": code, "group_name": "synthetic"}
                for code in CODES
            ],
        )
        conn.execute(insert(trading_calendar).values(date=NOW.date(), is_open=True))


@pytest.fixture
def isolated_engine() -> Iterator[object]:
    engine = _engine()
    try:
        yield engine
    finally:
        with engine.begin() as conn:  # type: ignore[union-attr]
            _cleanup(conn)
        engine.dispose()  # type: ignore[union-attr]


def _patch_replay(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[tuple[str, str]],
) -> tuple[object, dict[str, list[object]]]:
    from app.ingest.egress import EgressResult
    from app.ingest.upstream import Signal

    audit: dict[str, list[object]] = {
        "single_egress": [],
        "leases": [],
        "mairui_get": [],
    }
    body = [
        {
            "code": CODES[0],
            "dm": "600001",
            "ts": "2030-06-11T10:00:00+08:00",
            "price": "10.00",
            "pct_change": "1.25",
            "volume": "100",
            "amount": "1000",
        },
        {
            "code": CODES[1],
            "dm": "600002",
            "ts": "2030-06-11T10:00:00+08:00",
            "price": "20.00",
            "pct_change": "2.50",
            "volume": "200",
            "amount": "4000",
        },
    ]

    def replay_transport(path: str, secret: str) -> tuple[int, object]:
        calls.append((path, secret))
        return 200, body

    def replay_get(
        *,
        lease: object,
        core: object,
        engine: object,
        licence_id: UUID,
        user_id: UUID,
        path: str,
        secret: str,
        priority: object,
        clock: object,
        stop: Path,
        halt: Path,
        transport: object = replay_transport,
        verify: bool = False,
    ) -> EgressResult:
        del lease, core, engine, licence_id, user_id, priority, clock, stop, halt, verify
        audit["mairui_get"].append(path)
        runner = transport if callable(transport) else replay_transport
        status, response = runner(str(path), str(secret))
        return EgressResult(status=status, body=response, signal=Signal.OK, transitions=[])

    egress = importlib.import_module("app.ingest.egress")
    monkeypatch.setattr(egress, "mairui_get", replay_get)
    collect_module = sys.modules.get("app.marketdata.realtime_collect")
    if collect_module is not None and getattr(collect_module, "mairui_get", None) is not None:
        monkeypatch.setattr(collect_module, "mairui_get", replay_get)

    original_single_egress = egress.single_egress

    @contextmanager
    def counting_single_egress(engine: object):
        audit["single_egress"].append(engine)
        with original_single_egress(engine) as lease:
            audit["leases"].append(lease)
            yield lease

    monkeypatch.setattr(egress, "single_egress", counting_single_egress)
    if collect_module is not None and getattr(collect_module, "single_egress", None) is not None:
        monkeypatch.setattr(collect_module, "single_egress", counting_single_egress)
    if collect_module is not None and getattr(collect_module, "verification_is_offline", None) is not None:
        monkeypatch.setattr(collect_module, "verification_is_offline", lambda: False)
    if collect_module is not None and getattr(collect_module, "get_ingest_core", None) is not None:
        monkeypatch.setattr(collect_module, "get_ingest_core", lambda: object())
    return replay_transport, audit


def _call_entry(
    entry: tuple[object, str, object],
    engine: object,
    tmp_path: Path,
    transport: object,
    monkeypatch: pytest.MonkeyPatch,
) -> object:
    _module, name, function = entry
    settings = _settings(monkeypatch)

    def load_secret(engine: object, licence_id: UUID) -> str:
        del engine, licence_id
        return "synthetic-secret"

    kwargs = {
        "owner": OWNER,
        "now": NOW,
        "transport": transport,
        "secret_loader": load_secret,
        "engine": engine,
        "stop": tmp_path / "stop",
        "halt": tmp_path / "halt",
    }
    from app.ingest.core import IngestCore
    from app.ingest.runtime import set_ingest_core

    set_ingest_core(IngestCore(cfg=settings.business.ingest.licences, engine=engine))  # type: ignore[arg-type]
    try:
        if name == "collect_realtime_quotes":
            with engine.connect() as conn:  # type: ignore[union-attr]
                return function(conn, settings, **kwargs)
        return function(settings, **kwargs)
    finally:
        set_ingest_core(None)


def _rows(engine: object) -> list[object]:
    with engine.connect() as conn:  # type: ignore[union-attr]
        return conn.execute(
            text(
                "SELECT code, batch_id::text AS batch_id "
                "FROM market.quotes_snapshot "
                "WHERE code IN (:a, :b) ORDER BY code"
            ),
            {"a": CODES[0], "b": CODES[1]},
        ).mappings().all()


def test_realtime_collection_is_ingest_registered() -> None:
    assert _worker_registered(), "实时采集任务应登记到 worker 注册表"
    assert _worker_tick() == [(TASK, "ok")], "worker_tick 应执行关闭开关的实时任务"
    _require_entry()


def test_worker_mairui_client_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _worker_registered(), "实时采集任务应登记到 worker 注册表"
    assert _worker_tick() == [(TASK, "ok")], "关闭开关的 worker 任务应安全返回"
    entry = _require_entry()
    egress = importlib.import_module("app.ingest.egress")
    calls: list[object] = []

    def forbidden(
        *,
        lease: object,
        core: object,
        engine: object,
        licence_id: UUID,
        user_id: UUID,
        path: str,
        secret: str,
        priority: object,
        clock: object,
        stop: Path,
        halt: Path,
        transport: object = None,
        verify: bool = False,
    ) -> None:
        calls.append(
            (
                lease,
                core,
                engine,
                licence_id,
                user_id,
                path,
                secret,
                priority,
                clock,
                stop,
                halt,
                transport,
                verify,
            )
        )
        raise AssertionError("worker 不得调用 mairui_get")

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    if getattr(entry[0], "mairui_get", None) is not None:
        monkeypatch.setattr(entry[0], "mairui_get", forbidden)
    collect_module = sys.modules.get("app.marketdata.realtime_collect")
    if collect_module is not None and getattr(collect_module, "mairui_get", None) is not None:
        monkeypatch.setattr(collect_module, "mairui_get", forbidden)
    assert calls == []


@pytest.mark.xfail(
    condition=not _ENTRY_AVAILABLE,
    strict=True,
    reason="T-B221 未实现：没有可调用的 ingest 公共实时采集入口",
)
def test_replay_injected_transport_has_zero_socket_calls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_engine: object
) -> None:
    entry = _require_entry()
    _seed(isolated_engine)
    calls: list[tuple[str, str]] = []
    transport, audit = _patch_replay(monkeypatch, calls)
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    _call_entry(entry, isolated_engine, tmp_path, transport, monkeypatch)
    rows = _rows(isolated_engine)
    assert calls, "注入 transport 未被调用"
    assert audit["single_egress"], "采集未进入 single_egress 单一出口"
    assert audit["leases"] and all(lease is not None for lease in audit["leases"])
    assert all(not hasattr(lease, "held") or lease.held for lease in audit["leases"])
    assert audit["mairui_get"], "采集未调用 mairui_get"
    assert rows, "行情响应未解析并写入 market.quotes_snapshot"
    assert SOCKET_ATTEMPTS == []


@pytest.mark.xfail(
    condition=not _ENTRY_AVAILABLE,
    strict=True,
    reason="T-B221 未实现：没有可调用的 ingest 公共实时采集入口",
)
def test_quote_batch_has_uuid_and_is_idempotent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, isolated_engine: object
) -> None:
    entry = _require_entry()
    _seed(isolated_engine)
    calls: list[tuple[str, str]] = []
    transport, audit = _patch_replay(monkeypatch, calls)
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    _call_entry(entry, isolated_engine, tmp_path, transport, monkeypatch)
    first = _rows(isolated_engine)
    assert first and len({row["batch_id"] for row in first}) == 1
    batch_id = UUID(first[0]["batch_id"])
    assert batch_id.int
    assert audit["single_egress"], "采集未进入 single_egress 单一出口"
    assert audit["leases"] and all(lease is not None for lease in audit["leases"])
    assert all(not hasattr(lease, "held") or lease.held for lease in audit["leases"])
    assert audit["mairui_get"], "采集未调用 mairui_get"
    _call_entry(entry, isolated_engine, tmp_path, transport, monkeypatch)
    second = _rows(isolated_engine)
    assert len(second) == len(first)
    assert calls

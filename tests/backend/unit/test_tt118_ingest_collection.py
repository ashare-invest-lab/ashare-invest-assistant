"""T-T118：T-B221 实时采集只能由 ingest 出口执行。"""

from __future__ import annotations

import importlib
import inspect
import json
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from app.config import Settings
from app.workers import jobs

TASK = "market.realtime_quotes_fetch"
OWNER = UUID("00000000-0000-4000-8000-000000001118")
SOCKET_ATTEMPTS: list[object] = []


class _Queue:
    def __init__(self) -> None:
        self.item: bytes | None = json.dumps({"task": TASK, "args": {}}).encode()

    def rpop(self, _key: str) -> bytes | None:
        item, self.item = self.item, None
        return item


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    SOCKET_ATTEMPTS.clear()

    def reject(*_args: object, **_kwargs: object) -> None:
        SOCKET_ATTEMPTS.append(_args)
        raise AssertionError("T-T118 禁止真实网络连接")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def _worker_registered() -> bool:
    return TASK in jobs.TASKS or any(
        isinstance(value, dict) and TASK in value for value in vars(jobs).values()
    )


def _worker_holds_egress() -> bool:
    root = Path(jobs.__file__).parent
    return any(token in path.read_text(encoding="utf-8") for path in root.glob("*.py") if path.name != "ingest.py" for token in ("mairui_get", "app.ingest.egress"))


def _worker_tick() -> list[tuple[str, str]]:
    return jobs.worker_tick(Settings.model_construct(), client=_Queue())


def _ingest_source(*, writer: bool = False) -> tuple[str, Path] | None:
    for module_name in ("app.marketdata.realtime_collect", "app.workers.ingest"):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        path = Path(module.__file__)
        known = any(callable(getattr(module, name, None)) for name in ("collect_realtime_quotes", "realtime_quotes_task"))
        source = path.read_text(encoding="utf-8")
        if known or TASK in source or (writer and "quotes_snapshot" in source and "batch_id" in source):
            return module_name, path
    import app.ingest

    root = Path(app.ingest.__file__).parent
    for path in sorted(root.glob("*.py")):
        if path.name in {"__init__.py", "owned_quotes.py"}:
            continue
        source = path.read_text(encoding="utf-8")
        if TASK in source or (writer and "quotes_snapshot" in source and "batch_id" in source):
            return f"app.ingest.{path.stem}", path
    return None


def _require_ingest(*, writer: bool = False) -> tuple[str, Path]:
    found = _ingest_source(writer=writer)
    if found is None:
        pytest.xfail("T-B221 未实现：未发现 ingest 实时采集消费/写入入口")
    return found


def _callable_probe(source: tuple[str, Path]) -> Any:
    module_name, _ = source
    module = importlib.import_module(module_name)
    for name in ("realtime_quotes_task", "collect_realtime_quotes"):
        value = getattr(module, name, None)
        if callable(value):
            return value
    pytest.xfail("T-B221 未实现：入口模块没有可调用采集函数")


def _invoke(function: Any, fake_transport: Any) -> Any:
    kwargs: dict[str, object] = {}
    for name, parameter in inspect.signature(function).parameters.items():
        if name in {"transport", "fetcher", "client"}:
            kwargs[name] = fake_transport
        elif name == "settings":
            kwargs[name] = Settings.model_construct()
        elif name == "owner":
            kwargs[name] = OWNER
        elif name in {"conn", "connection", "engine"}:
            kwargs[name] = object()
        elif parameter.default is inspect.Parameter.empty:
            pytest.xfail(f"T-B221 未验证：入口需要未冻结参数 {name}")
    return function(**kwargs)


def test_realtime_collection_is_ingest_only() -> None:
    assert not _worker_registered(), "T-B221 违约：采集任务已登记到 worker 注册表"
    assert _worker_tick() == [(TASK, "unknown")], "T-B221 违约：worker_tick 已消费采集任务"
    assert _require_ingest()


def test_worker_mairui_client_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest import egress

    calls: list[object] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        raise AssertionError("worker 不得调用 mairui_get")

    monkeypatch.setattr(egress, "mairui_get", forbidden)
    assert not _worker_holds_egress(), "T-B221 违约：worker 持有麦蕊客户端"
    assert not _worker_registered(), "T-B221 违约：worker 注册了实时采集任务"
    assert _worker_tick() == [(TASK, "unknown")], "worker 不得成功执行实时采集"
    assert calls == []
    assert _require_ingest()


def test_replay_injected_transport_has_zero_socket_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "replay")

    def fake_transport(path: str, secret: str) -> tuple[int, object]:
        return 200, {"code": "SYN001.SH", "price": "10.00"}

    function = _callable_probe(_require_ingest())
    _invoke(function, fake_transport)
    assert SOCKET_ATTEMPTS == []


def test_quote_batch_has_uuid_and_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name, _ = _require_ingest(writer=True)
    module = importlib.import_module(module_name)
    function = getattr(module, "realtime_quotes_task", None)
    if not callable(function):
        function = getattr(module, "collect_realtime_quotes", None)
    if not callable(function):
        pytest.xfail("T-B221 未实现：未发现公开行情写入口")
    class Context:
        def __init__(self, value: object) -> None:
            self.value = value

        def __enter__(self) -> object:
            return self.value

        def __exit__(self, *_args: object) -> None:
            return None

    conn = object()
    engine = SimpleNamespace(connect=lambda: Context(conn), begin=lambda: Context(conn))
    rows: set[tuple[object, object]] = set()
    batches: list[UUID] = []
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    if hasattr(module, "verification_is_offline"):
        monkeypatch.setattr(module, "verification_is_offline", lambda: False)
    monkeypatch.setattr(module, "_open_clock", lambda *_args: SimpleNamespace(session=SimpleNamespace(value="morning"), trade_date=None))
    monkeypatch.setattr(module, "active_licence_id", lambda *_args: OWNER)
    monkeypatch.setattr(module, "_owned_codes", lambda *_args: ["SYN001.SH", "SYN002.SH"])
    monkeypatch.setattr(module, "_fetch_with_egress", lambda *_args, **_kwargs: (200, [{"code": "SYN001.SH", "ts": "2030-06-11T10:00:00+08:00", "price": "10.00"}, {"code": "SYN002.SH", "ts": "2030-06-11T10:00:00+08:00", "price": "20.00"}]))

    def write(_conn: object, quote_rows: list[dict[str, object]], batch_id: UUID) -> int:
        assert isinstance(batch_id, UUID) and batch_id.int
        batches.append(batch_id)
        before = len(rows)
        rows.update((row["code"], row["ts"]) for row in quote_rows)
        return len(rows) - before

    monkeypatch.setattr(module, "_write_rows", write)
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    for _ in range(2):
        if function.__name__ == "realtime_quotes_task":
            monkeypatch.setattr(jobs, "_engine", lambda _settings: engine)
            function(settings, owner=OWNER, transport=lambda *_args: (200, []))
        else:
            function(conn, settings, owner=OWNER, engine=engine, transport=lambda *_args: (200, []))
    assert len(batches) == 2 and all(batch.int for batch in batches)
    assert len(rows) == 2

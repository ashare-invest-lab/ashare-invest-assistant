"""T-B141：verify_licence 消费者最小语义（离线：HTTP 桩、假证书值，不读环境变量/证书文件）。"""

from __future__ import annotations

import datetime as dt
import functools
import sys
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from redis.exceptions import ResponseError
from sqlalchemy import insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config_files import IngestConfig
from app.db.tables.licences import data_licence_events, user_data_licences
from app.ingest import egress as eg
from app.ingest import verify_licence as vl
from app.ingest.core import IngestCore
from app.ingest.intents import VerifyIntent
from app.ingest.state import Priority
from app.ingest.upstream import Signal
from app.licences.service import INGEST_REQUESTS_STREAM
from daily_bars_t70_support import ROOT, _open_temp_db

NOW = dt.datetime(2026, 11, 13, 10, 0, tzinfo=dt.UTC)
FAKE = "tb141-fake-licence-not-a-real-key"
CFG = IngestConfig.model_validate(
    yaml.safe_load((ROOT / "config/ingest.yaml").read_text(encoding="utf-8"))
).licences
CALENDAR_OK = [{"date": "2026-11-13", "is_open": 1}]
PENDING, ACTIVE = "pending_verification", "active"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[SimpleNamespace]:
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    gen = _open_temp_db()
    ctx = next(gen)
    try:
        ctx.lid = uuid.uuid4()
        with ctx.engine.begin() as conn:
            conn.execute(
                insert(user_data_licences).values(
                    id=ctx.lid,
                    user_id=ctx.u1,
                    provider="mairui",
                    ciphertext=b"\x00",
                    seal_key_version=1,
                    licence_hmac=uuid.uuid4().bytes,
                    tier="annual",
                    has_quant_pro=False,
                    status=PENDING,
                )
            )
        ctx.core = IngestCore(CFG, engine=ctx.engine)
        ctx.stop, ctx.halt = tmp_path / "STOP", tmp_path / "HALT"
        ctx.calls = []
        ctx.monkeypatch = monkeypatch
        yield ctx
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def _stub(ctx: SimpleNamespace, status: int | None, body: object = None, hook: Any = None) -> None:
    """唯一的 HTTP：注入到真实 mairui_get 的假 transport（app 代码不注入 transport）。"""

    def transport(path: str, secret: str) -> tuple[int, object]:
        assert secret == FAKE
        ctx.calls.append(path)
        if hook is not None:
            hook()
        if status is None:
            raise OSError("connection reset")
        return status, body

    ctx.monkeypatch.setattr(vl, "mairui_get", functools.partial(eg.mairui_get, transport=transport))


def _loader(_engine: Any, _lid: uuid.UUID) -> str:
    return FAKE


def _run(ctx: SimpleNamespace, *, loader: Callable[[Any, uuid.UUID], str] = _loader,
         hold: bool = True) -> vl.VerifyResult:
    intent = VerifyIntent(ctx.lid, uuid.uuid4(), Priority.P0)
    kw: dict[str, Any] = {"clock": lambda: NOW, "secret_loader": loader, "stop": ctx.stop,
                          "halt": ctx.halt, "core": ctx.core}
    if not hold:
        return vl.process_verify_intent(ctx.engine, intent, lease=None, **kw)
    with eg.single_egress(ctx.engine) as lease:
        assert lease is not None
        return vl.process_verify_intent(ctx.engine, intent, lease=lease, **kw)


def _row(ctx: SimpleNamespace) -> Any:
    with ctx.engine.connect() as conn:
        return conn.execute(
            select(user_data_licences).where(user_data_licences.c.id == ctx.lid)
        ).one()


def _events(ctx: SimpleNamespace) -> list[Any]:
    with ctx.engine.connect() as conn:
        return list(
            conn.execute(
                select(data_licence_events).where(data_licence_events.c.licence_id == ctx.lid)
            )
        )


def _set_status(ctx: SimpleNamespace, status: str) -> None:
    with ctx.engine.begin() as conn:
        conn.execute(
            update(user_data_licences)
            .where(user_data_licences.c.id == ctx.lid)
            .values(status=status)
        )


# ---------------------------------------------------------------- 200 → active


@pytest.mark.parametrize("start", [PENDING, ACTIVE])
def test_200_business_ok_sets_active_with_one_call(world: SimpleNamespace, start: str) -> None:
    _set_status(world, start)
    _stub(world, 200, CALENDAR_OK)
    result = _run(world)
    assert (result.activated, result.status, result.reason, result.calls) == (
        True, ACTIVE, None, 1,
    )
    assert world.calls == ["/tcalendar/list/2026/"]
    row = _row(world)
    assert row.status == ACTIVE
    assert row.last_verified_at is not None and row.last_error_code is None
    verified = [e for e in _events(world) if e.event == "verified"]
    assert [(e.from_status, e.to_status, e.actor) for e in verified] == [(start, ACTIVE, "ingest")]
    assert not world.halt.exists()


# ------------------------------------------------- 非 200 / 业务异常 → 保持并记因


@pytest.mark.parametrize(
    ("status", "body", "reason", "error_code"),
    [
        (404, "not found", "http_404", None),
        (500, "boom", "http_500", None),
        (200, {"error": "102 证书无效"}, "102", "102"),
        (200, {"error": "101 当日额度用完"}, "101", "101"),
        (200, [], "empty_body", None),
        (200, {"error": "未知错误"}, "http_200", None),
    ],
)
def test_non_ok_keeps_status_and_records_reason(
    world: SimpleNamespace, status: int, body: object, reason: str, error_code: str | None
) -> None:
    _stub(world, status, body)
    result = _run(world)
    assert (result.activated, result.status, result.reason, result.calls) == (
        False, PENDING, reason, 1,
    )
    assert world.calls == ["/tcalendar/list/2026/"]
    row = _row(world)
    assert row.status == PENDING  # 102 也不改 invalid：最小语义保持原状态
    assert row.last_verified_at is None
    assert row.last_error_code == error_code
    assert _events(world) == []


def test_network_failure_keeps_status(world: SimpleNamespace) -> None:
    _stub(world, None)
    result = _run(world)
    assert (result.status, result.reason, result.calls) == (PENDING, "network", 1)
    assert world.calls == ["/tcalendar/list/2026/"]
    assert _row(world).last_error_code == "network"


# ---------------------------------------- 103 / 429 / 503 / STOP：不重试、不改 active


@pytest.mark.parametrize(
    ("status", "body", "reason", "halts"),
    [
        (429, "103:同一证书60秒内IP超限", "103", True),
        (429, "too many", "429", True),
        (200, {"error": "103 IP 超限"}, "103", True),
        (503, "请求过于频繁", "503", True),
    ],
)
@pytest.mark.parametrize("start", [PENDING, ACTIVE])
def test_limit_codes_no_retry_no_activate(
    world: SimpleNamespace, status: int, body: object, reason: str, halts: bool, start: str
) -> None:
    _set_status(world, start)
    _stub(world, status, body)
    result = _run(world)
    assert (result.activated, result.status, result.reason, result.calls) == (
        False, start, reason, 1,
    )
    assert world.calls == ["/tcalendar/list/2026/"]  # 恰好一次，不重试
    row = _row(world)
    assert row.status == start and row.last_error_code == reason
    assert world.halt.exists() is halts
    assert _events(world) == []
    if halts:  # HALT 之后再来一条验证：零调用
        result2 = _run(world)
        assert (result2.reason, result2.calls) == ("STOP", 0)
        assert world.calls == ["/tcalendar/list/2026/"]


@pytest.mark.parametrize("flag", ["stop", "halt"])
def test_stop_or_halt_present_zero_calls(world: SimpleNamespace, flag: str) -> None:
    getattr(world, flag).write_bytes(b"x")
    _stub(world, 200, CALENDAR_OK)
    result = _run(world)
    assert (result.status, result.reason, result.calls) == (PENDING, "STOP", 0)
    assert world.calls == []
    assert _row(world).last_error_code is None


# ------------------------------------------------------------- 不发起调用的分支


def test_non_activatable_status_zero_calls(world: SimpleNamespace) -> None:
    _set_status(world, "invalid")
    _stub(world, 200, CALENDAR_OK)
    result = _run(world)
    assert (result.status, result.reason, result.calls) == ("invalid", "licence_unavailable", 0)
    assert world.calls == [] and _row(world).status == "invalid"


def test_missing_licence_not_set(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK)
    world.lid = uuid.uuid4()
    result = _run(world)
    assert (result.status, result.reason, result.calls) == ("not_set", "licence_unavailable", 0)
    assert world.calls == []


def test_secret_loader_failure_zero_calls(world: SimpleNamespace) -> None:
    def broken(_engine: Any, _lid: uuid.UUID) -> str:
        raise RuntimeError("vault unavailable")

    _stub(world, 200, CALENDAR_OK)
    result = _run(world, loader=broken)
    assert (result.status, result.reason, result.calls) == (PENDING, "secret_unavailable", 0)
    assert world.calls == []


def test_without_single_egress_lease_denied_zero_calls(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK)
    result = _run(world, hold=False)
    assert (result.status, result.reason, result.calls) == (
        PENDING, "single_egress_not_held", 0,
    )
    assert world.calls == []


def test_concurrent_status_change_not_overridden(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK, hook=lambda: _set_status(world, "paused_by_admin"))
    result = _run(world)
    assert (result.activated, result.reason) == (False, "status_changed")
    assert _row(world).status == "paused_by_admin"
    assert _events(world) == []


def test_reason_for_mapping() -> None:
    assert vl.reason_for(200, [], Signal.DATA_MISSING) == "503"
    assert vl.reason_for(403, "", Signal.NOT_ENTITLED) == "http_403"


# ------------------------------------------------------------------ tick 消费


class FakeRedis:
    def __init__(self, messages: list[tuple[bytes, dict[bytes, bytes]]], group_exists: bool):
        self.messages, self.group_exists = messages, group_exists
        self.acked: list[bytes] = []
        self.created: list[tuple[str, str, str]] = []
        self.reads = 0

    def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:  # noqa: A002
        assert mkstream
        if self.group_exists:
            raise ResponseError("BUSYGROUP Consumer Group name already exists")
        self.created.append((stream, group, id))

    def xreadgroup(self, group: str, consumer: str, streams: dict[str, str], count: int) -> Any:
        assert (group, streams, count) == (vl.GROUP, {INGEST_REQUESTS_STREAM: ">"}, 1)
        self.reads += 1
        batch, self.messages = self.messages[:count], self.messages[count:]
        return [(INGEST_REQUESTS_STREAM.encode(), batch)] if batch else []

    def xack(self, stream: str, group: str, mid: bytes) -> None:
        assert (stream, group) == (INGEST_REQUESTS_STREAM, vl.GROUP)
        self.acked.append(mid)


def _tick(world: SimpleNamespace, rds: FakeRedis) -> int:
    return vl.tick(world.engine, rds, clock=lambda: NOW, secret_loader=_loader,
                   stop=world.stop, halt=world.halt, core=world.core)


def _verify_msg(world: SimpleNamespace, mid: bytes) -> tuple[bytes, dict[bytes, bytes]]:
    return mid, {b"kind": b"verify_licence", b"licence_id": str(world.lid).encode(),
                 b"verification_id": str(uuid.uuid4()).encode()}


def test_tick_consumes_one_verify_ack_first(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK)
    rds = FakeRedis([_verify_msg(world, b"1-0"), _verify_msg(world, b"2-0")], group_exists=False)
    assert _tick(world, rds) == 1
    assert rds.created == [(INGEST_REQUESTS_STREAM, vl.GROUP, "$")]
    assert rds.acked == [b"1-0"] and world.calls == ["/tcalendar/list/2026/"]
    assert _row(world).status == ACTIVE
    assert _tick(world, rds) == 1  # 第二条照常（复验 active）
    assert rds.acked == [b"1-0", b"2-0"] and len(world.calls) == 2
    assert _tick(world, rds) == 0


def test_tick_acks_other_and_bad_records_without_calls(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK)
    rds = FakeRedis(
        [
            (b"1-0", {b"kind": b"something_else"}),
            (b"2-0", {b"kind": b"verify_licence", b"licence_id": b"bad"}),
        ],
        group_exists=True,
    )
    assert _tick(world, rds) == 0
    assert _tick(world, rds) == 0
    assert rds.acked == [b"1-0", b"2-0"] and world.calls == []


def test_tick_busy_lock_reads_nothing(world: SimpleNamespace) -> None:
    _stub(world, 200, CALENDAR_OK)
    rds = FakeRedis([_verify_msg(world, b"1-0")], group_exists=True)
    with eg.single_egress(world.engine) as held:
        assert held is not None
        assert _tick(world, rds) == 0
    assert rds.reads == 0 and rds.acked == [] and world.calls == []


def test_tick_group_create_other_error_raises(world: SimpleNamespace) -> None:
    class Broken(FakeRedis):
        def xgroup_create(self, stream: str, group: str, id: str, mkstream: bool) -> None:  # noqa: A002
            raise ResponseError("WRONGTYPE")

    with pytest.raises(ResponseError):
        _tick(world, Broken([], group_exists=False))


# ------------------------------------------------------------------ 静态约束


def test_write_heartbeat_wires_tick_verify() -> None:
    src = (ROOT / "src/backend/app/workers/ingest.py").read_text(encoding="utf-8")
    wh = src.split("def write_heartbeat", 1)[1].split("\ndef ", 1)[0]
    assert wh.count("tick_verify(") == 2


def test_verify_module_has_no_env_or_transport_injection() -> None:
    src = (ROOT / "src/backend/app/ingest/verify_licence.py").read_text(encoding="utf-8")
    for banned in ("MAIRUI_LICENCE", "os.environ", "transport", "getenv"):
        assert banned not in src


def test_default_clock_is_utc() -> None:
    assert vl._utcnow().tzinfo is dt.UTC


@pytest.mark.parametrize(("persist", "status", "body"), [
    ("_activate", 200, CALENDAR_OK),
    ("_keep", 404, "not found"),
])
def test_persist_failure_keeps_status_and_does_not_retry(
    world: SimpleNamespace, persist: str, status: int, body: object
) -> None:
    def broken(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("persist failed")

    world.monkeypatch.setattr(vl, persist, broken)
    _stub(world, status, body)
    result = _run(world)
    assert (result.status, result.activated, result.reason, result.calls) == (
        PENDING, False, "persist_failed", 1,
    )
    assert world.calls == ["/tcalendar/list/2026/"]


def test_tick_persist_failure_is_acked_and_not_replayed(world: SimpleNamespace) -> None:
    rds = FakeRedis([_verify_msg(world, b"1-0")], group_exists=True)

    def broken(*args: Any, **kwargs: Any) -> None:
        assert rds.acked == [b"1-0"]
        raise RuntimeError("persist failed")

    world.monkeypatch.setattr(vl, "_activate", broken)
    _stub(world, 200, CALENDAR_OK)
    assert _tick(world, rds) == 1
    assert rds.acked == [b"1-0"]
    assert _tick(world, rds) == 0
    assert world.calls == ["/tcalendar/list/2026/"]


def test_light_path_uses_shanghai_year() -> None:
    assert vl.light_path(dt.datetime(2026, 12, 31, 17, 0, tzinfo=dt.UTC)) == "/tcalendar/list/2027/"


def test_102_status_view_keeps_pending_and_reports_error(world: SimpleNamespace) -> None:
    from app.licences.service import status_view

    _stub(world, 200, {"error": "102 证书无效"})
    _run(world)
    view = status_view(_row(world))
    assert view["status"] == PENDING
    assert view["last_error_code"] == "102"


def test_unknown_reason_logged_without_body(world: SimpleNamespace,
                                           caplog: pytest.LogCaptureFixture) -> None:
    body = "tb141-fake-response-body-do-not-log"
    _stub(world, 404, body)
    with caplog.at_level("INFO", logger=vl.__name__):
        _run(world)
    assert _row(world).last_error_code is None
    assert "verify_licence kept" in caplog.text
    assert "http_404" in caplog.text
    assert body not in caplog.text

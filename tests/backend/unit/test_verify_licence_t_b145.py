"""T-B145：离线验证拒绝外呼；只用既有 core/FakeRedis、合成值和 HTTP/DB 桩。"""

from __future__ import annotations

import functools
import socket
import sys
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.api.v1 import data_licence as api
from app.common.errors import AppError
from app.ingest import egress as eg
from app.ingest import verify_licence as vl
from app.ingest.core import IngestCore
from app.ingest.intents import VerifyIntent
from app.ingest.state import Priority
from app.licences import service
from app.schemas.enums import DataLicenceStatus, DataLicenceTier
from test_verify_licence_t_b141 import CFG, NOW, FakeRedis


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch, tmp_path) -> SimpleNamespace:
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.setenv("SERVICE_NAME", "api")
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("MAIRUI_MODE", "replay")
    network = Mock(side_effect=AssertionError("T-B145 forbids all real network"))
    monkeypatch.setattr(socket, "getaddrinfo", network)
    monkeypatch.setattr(socket.socket, "connect", network)
    monkeypatch.setattr(socket.socket, "connect_ex", network)
    lid, uid = uuid.uuid4(), uuid.uuid4()
    row = SimpleNamespace(id=lid, user_id=uid, status="pending_verification", deleted_at=None)
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value.execute.return_value.first.return_value = row
    engine.begin.return_value.__enter__.return_value.execute.return_value.rowcount = 1
    core = IngestCore(CFG)
    core.upsert(lid, user_id=uid, tier=DataLicenceTier.ANNUAL,
                status=DataLicenceStatus.INVALID, now=NOW)
    reset = Mock(wraps=core.user_reset)
    monkeypatch.setattr(core, "user_reset", reset)
    monkeypatch.setattr(eg, "_lease_is_valid", lambda *_args: True)
    monkeypatch.setattr(eg, "_admit", lambda **_kw: (DataLicenceTier.ANNUAL, row.status, None))
    monkeypatch.setattr(eg.ng, "egress_window", lambda *_a, **_kw: nullcontext())
    monkeypatch.setattr(vl, "single_egress", lambda _engine: nullcontext(object()))
    transport = Mock(return_value=(200, [{"date": "2026-11-13", "is_open": 1}]))
    get = functools.partial(eg.mairui_get, transport=transport)
    monkeypatch.setattr(vl, "mairui_get", get)
    loader = Mock(return_value="synthetic")
    monkeypatch.setattr(api, "_require_settings_enabled", lambda _s: None)
    monkeypatch.setattr(api, "_limiter", lambda *_a: None)
    monkeypatch.setattr(service, "live_row", lambda *_a: row)
    monkeypatch.setattr(service, "is_held", lambda *_a: False)
    rds = Mock()
    rds.exists.return_value = False
    settings = SimpleNamespace(
        business=SimpleNamespace(ingest=SimpleNamespace(
            licences=SimpleNamespace(verify_rate_limit_per_hour=10))),
        ingest_paused_key="test:ingest:paused",
    )
    return SimpleNamespace(
        lid=lid, uid=uid, row=row, engine=engine, core=core, reset=reset,
        transport=transport, network=network, loader=loader, get=get,
        stop=tmp_path / "STOP", halt=tmp_path / "HALT", rds=rds, settings=settings,
    )


def _run(world: SimpleNamespace) -> vl.VerifyResult:
    return vl.process_verify_intent(
        world.engine, VerifyIntent(world.lid, uuid.uuid4(), Priority.P0),
        lease=object(), core=world.core, secret_loader=world.loader,
        clock=lambda: NOW, stop=world.stop, halt=world.halt,
    )


def _get(world: SimpleNamespace, *, default_transport: bool = False, verify: bool = True) -> object:
    get = eg.mairui_get if default_transport else world.get
    return get(
        lease=object(), core=world.core, engine=world.engine,
        licence_id=world.lid, user_id=world.uid, path=vl.light_path(NOW),
        secret="synthetic", priority=Priority.P0, clock=lambda: NOW,
        stop=world.stop, halt=world.halt, verify=verify,
    )


def _offline_unchanged(world: SimpleNamespace) -> None:
    world.transport.assert_not_called()
    world.network.assert_not_called()
    world.loader.assert_not_called()
    world.reset.assert_not_called()
    world.engine.begin.assert_not_called()
    assert world.row.status == "pending_verification"


def test_t_b145_replay_api_test_refuses_with_explicit_notice(world: SimpleNamespace) -> None:
    with pytest.raises(AppError) as caught:
        api.test_licence(SimpleNamespace(user_id=world.uid), world.settings, world.engine, world.rds)
    assert caught.value.status_code >= 400
    assert "replay" in caught.value.message.lower()
    assert "未" in caught.value.message
    world.rds.xadd.assert_not_called()
    _offline_unchanged(world)


def test_t_b145_replay_enqueue_refuses_with_explicit_notice(world: SimpleNamespace) -> None:
    with pytest.raises(AppError) as caught:
        service.enqueue_verify(world.rds, licence_id=world.lid, verification_id=uuid.uuid4())
    assert "replay" in caught.value.message.lower()
    assert "未" in caught.value.message
    world.rds.xadd.assert_not_called()
    _offline_unchanged(world)


def test_t_b145_replay_consumer_keeps_pending_without_loading_secret(world: SimpleNamespace) -> None:
    result = _run(world)
    assert (result.activated, result.calls, result.status) == (False, 0, "pending_verification")
    assert "replay" in result.reason and "no_request" in result.reason
    _offline_unchanged(world)


def test_t_b145_replay_tick_acks_old_message_without_call(
    world: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    rds = FakeRedis([(b"1-0", {
        b"kind": b"verify_licence", b"licence_id": str(world.lid).encode(),
        b"verification_id": str(uuid.uuid4()).encode(),
    })], group_exists=True)
    with caplog.at_level("INFO", logger=vl.__name__):
        assert vl.tick(world.engine, rds, core=world.core, secret_loader=world.loader,
                       clock=lambda: NOW, stop=world.stop, halt=world.halt) == 1
    assert rds.acked == [b"1-0"]
    assert "replay" in caplog.text and "no_request" in caplog.text
    _offline_unchanged(world)


@pytest.mark.parametrize("default_transport", [False, True])
def test_t_b145_replay_final_egress_refuses_before_transport(
    world: SimpleNamespace, default_transport: bool,
) -> None:
    # 即便绕过消费者直接调用，包括捕获了默认 _https_get 的路径，也不能进入 DNS/socket。
    world.core.user_reset(world.lid, NOW)
    world.reset.reset_mock()
    with pytest.raises(eg.EgressDenied, match="replay.*no_request"):
        _get(world, default_transport=default_transport)
    _offline_unchanged(world)


@pytest.mark.parametrize("mode", ["offline", "unrecognized-mode"])
def test_t_b145_explicit_non_live_modes_fail_closed(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mode: str,
) -> None:
    monkeypatch.setenv("MAIRUI_MODE", mode)
    with pytest.raises(AppError, match="replay"):
        service.enqueue_verify(world.rds, licence_id=world.lid, verification_id=uuid.uuid4())
    assert _run(world).calls == 0
    with pytest.raises(eg.EgressDenied, match="replay.*no_request"):
        _get(world)
    _offline_unchanged(world)


def test_t_b145_replay_best_effort_does_not_fail_committed_put(
    world: SimpleNamespace, caplog: pytest.LogCaptureFixture,
) -> None:
    service.enqueue_verify_best_effort(
        world.rds, licence_id=world.lid, verification_id=uuid.uuid4(),
    )
    world.rds.xadd.assert_not_called()
    assert "replay" in caplog.text and "no_request" in caplog.text
    _offline_unchanged(world)


def test_t_b145_replay_non_verify_egress_keeps_existing_transport(world: SimpleNamespace) -> None:
    world.core = IngestCore(CFG)
    world.core.upsert(world.lid, user_id=world.uid, tier=DataLicenceTier.ANNUAL,
                      status=DataLicenceStatus.ACTIVE, now=NOW)
    result = _get(world, verify=False)
    assert result.status == 200
    world.transport.assert_called_once()
    world.network.assert_not_called()


@pytest.mark.parametrize("mode", ["live", None])
def test_t_b145_live_and_default_api_enqueue_and_consumer_keep_existing_flow(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch, mode: str | None,
) -> None:
    if mode is None:
        monkeypatch.delenv("MAIRUI_MODE")
    else:
        monkeypatch.setenv("MAIRUI_MODE", mode)
    result = api.test_licence(
        SimpleNamespace(user_id=world.uid), world.settings, world.engine, world.rds,
    )
    assert uuid.UUID(result.verification_id)
    world.rds.xadd.assert_called_once()
    service.enqueue_verify(world.rds, licence_id=world.lid, verification_id=uuid.uuid4())
    assert world.rds.xadd.call_count == 2
    outcome = _run(world)
    assert (outcome.activated, outcome.status, outcome.calls) == (True, "active", 1)
    world.reset.assert_called_once_with(world.lid, NOW)
    world.transport.assert_called_once_with("/tcalendar/list/2026/", "synthetic")
    world.network.assert_not_called()


def test_t_b145_live_failed_verification_keeps_pending(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")
    world.transport.return_value = (404, "synthetic failure")
    result = _run(world)
    assert (result.activated, result.status, result.reason, result.calls) == (
        False, "pending_verification", "http_404", 1,
    )
    world.transport.assert_called_once()
    world.network.assert_not_called()
    world.engine.begin.assert_not_called()


def test_t_b145_live_best_effort_enqueue_and_tick_still_verify(
    world: SimpleNamespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")
    service.enqueue_verify_best_effort(
        world.rds, licence_id=world.lid, verification_id=uuid.uuid4(),
    )
    world.rds.xadd.assert_called_once()
    fields = world.rds.xadd.call_args.args[1]
    rds = FakeRedis([(b"1-0", {k.encode(): v.encode() for k, v in fields.items()})],
                    group_exists=True)
    assert vl.tick(world.engine, rds, core=world.core, secret_loader=world.loader,
                   clock=lambda: NOW, stop=world.stop, halt=world.halt) == 1
    assert rds.acked == [b"1-0"]
    world.reset.assert_called_once_with(world.lid, NOW)
    world.transport.assert_called_once()
    world.network.assert_not_called()
    world.engine.begin.assert_called_once()

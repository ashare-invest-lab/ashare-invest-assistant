"""Offline endpoint wiring and fixture restoration; no real Unix services."""

from __future__ import annotations

import runpy
import socket
import uuid
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from selfchecks import test_p2n02_risk_controls as shared
from selfchecks import test_p2n03_tracking as tracking
from selfchecks import test_p2n04_daily_dimensions as daily
from selfchecks import test_tb70_replay as replay
from selfchecks.unix_test_resources import from_env
from sqlalchemy.engine import make_url

PG = "/tmp/tb70-rb2-synthetic-pg"
REDIS = "unix:///tmp/rb2-synthetic-redis/redis.sock?db=0"


@pytest.fixture(autouse=True)
def no_connections(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("R-B2 wiring tests must not connect to any service")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@pytest.fixture(autouse=True)
def clean_test_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    for prefix in ("AIA_TEST_TB70", "AIA_TEST_P2N04", "AIA_TEST_RB2"):
        for suffix in ("_PG_SOCKET", "_REDIS_URL"):
            monkeypatch.delenv(prefix + suffix, raising=False)


def test_historical_defaults_and_application_urls_do_not_select_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/do-not-use")
    monkeypatch.setenv("REDIS_URL", "redis://example.invalid/9")
    resources = from_env("AIA_TEST_RB2", pg_socket=PG, redis_url=REDIS)
    assert (resources.pg_socket, resources.redis_url) == (PG, REDIS)
    url = make_url(resources.database_url("tb70_synthetic"))
    assert url.database == "tb70_synthetic"
    assert url.query == {"host": PG}
    assert url.host is None and url.password is None


def test_tb70_import_uses_explicit_test_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIA_TEST_TB70_PG_SOCKET", PG)
    monkeypatch.setenv("AIA_TEST_TB70_REDIS_URL", REDIS)
    fresh = runpy.run_path(replay.__file__)
    assert make_url(fresh["DB"]).query["host"] == PG
    assert make_url(fresh["DB"]).database == "tb70_replay"
    assert fresh["REDIS"] == REDIS
    assert fresh["RESOURCES"].pg_socket == PG


@pytest.mark.parametrize(
    "value",
    [
        "",
        "relative/socket",
        "/tmp/other",
        "/tmp/tb70-x/../shared",
        "localhost",
        "/tmp/tb70-x\n",
    ],
)
def test_postgres_override_rejects_non_dedicated_paths(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("AIA_TEST_RB2_PG_SOCKET", value)
    with pytest.raises(ValueError, match="dedicated absolute"):
        from_env("AIA_TEST_RB2", pg_socket=PG, redis_url=REDIS)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "redis://127.0.0.1/0",
        "unix://host/tmp/r.sock?db=0",
        "unix:///tmp/r.sock?db=1",
        "unix:///tmp/r.sock?db=0&db=1",
        "unix:///tmp/../r.sock?db=0",
        "unix:///tmp/%2e%2e/r.sock?db=0",
        "unix:///tmp/r\n.sock?db=0",
        "unix:///tmp/r.sock?db=0#other",
    ],
)
def test_redis_override_rejects_network_or_ambiguous_endpoints(
    monkeypatch: pytest.MonkeyPatch,
    value: str,
) -> None:
    monkeypatch.setenv("AIA_TEST_RB2_REDIS_URL", value)
    with pytest.raises(ValueError):
        from_env("AIA_TEST_RB2", pg_socket=PG, redis_url=REDIS)


def test_p2n04_default_endpoints_and_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    before = tracking.SOCKET, tracking.REDIS, shared.REDIS

    def database() -> Any:
        assert tracking.SOCKET == "/tmp/tb70-p2n04-pg-socket"
        assert tracking.REDIS == "unix:///tmp/p2n04-redis/redis.sock?db=0"
        assert shared.REDIS == tracking.REDIS
        yield "synthetic-db"

    monkeypatch.setattr(tracking, "database", SimpleNamespace(__wrapped__=database))
    generator = daily.database.__wrapped__()
    assert next(generator) == "synthetic-db"
    with pytest.raises(StopIteration):
        next(generator)
    assert (tracking.SOCKET, tracking.REDIS, shared.REDIS) == before


@pytest.mark.parametrize(
    "ending", ["normal", "close", "setup_error", "teardown_error", "skip"]
)
def test_p2n04_override_restores_both_shared_modules_on_every_exit(
    monkeypatch: pytest.MonkeyPatch,
    ending: str,
) -> None:
    monkeypatch.setenv("AIA_TEST_P2N04_PG_SOCKET", PG)
    monkeypatch.setenv("AIA_TEST_P2N04_REDIS_URL", REDIS)
    before = tracking.SOCKET, tracking.REDIS, shared.REDIS

    def database() -> Any:
        assert tracking.SOCKET == PG and tracking.REDIS == REDIS
        assert shared.REDIS == REDIS
        shared.REDIS = "synthetic-inner-mutation"
        if ending == "setup_error":
            raise RuntimeError("synthetic setup failure")
        if ending == "skip":
            pytest.skip("synthetic missing socket")
        yield "synthetic-db"
        if ending == "teardown_error":
            raise RuntimeError("synthetic teardown failure")

    monkeypatch.setattr(tracking, "database", SimpleNamespace(__wrapped__=database))
    generator = daily.database.__wrapped__()
    if ending == "skip":
        with pytest.raises(pytest.skip.Exception, match="synthetic missing"):
            next(generator)
    elif ending == "setup_error":
        with pytest.raises(RuntimeError, match="setup failure"):
            next(generator)
    else:
        assert next(generator) == "synthetic-db"
        if ending == "close":
            generator.close()
        elif ending == "teardown_error":
            with pytest.raises(RuntimeError, match="teardown failure"):
                next(generator)
        else:
            with pytest.raises(StopIteration):
                next(generator)
    assert (tracking.SOCKET, tracking.REDIS, shared.REDIS) == before


def test_p2n04_real_inherited_missing_socket_path_restores_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AIA_TEST_P2N04_PG_SOCKET", PG)
    monkeypatch.setenv("AIA_TEST_P2N04_REDIS_URL", REDIS)
    before = tracking.SOCKET, tracking.REDIS, shared.REDIS
    exists = Path.exists

    def no_pg_socket(path: Path) -> bool:
        return False if str(path) == PG + "/.s.PGSQL.5432" else exists(path)

    monkeypatch.setattr(Path, "exists", no_pg_socket)
    with pytest.raises(pytest.skip.Exception, match="dedicated networkless"):
        next(daily.database.__wrapped__())
    assert (tracking.SOCKET, tracking.REDIS, shared.REDIS) == before


def test_original_cli_case_uses_integration_engine_endpoint_and_keeps_rejection(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app.replay import __main__ as cli

    snapshot = uuid.uuid4()
    owner = uuid.uuid4()
    url = make_url("postgresql+psycopg://postgres@/tb70_rb2_cli?host=" + PG)
    connection = object()
    engine = SimpleNamespace(
        url=url,
        begin=lambda: nullcontext(connection),
        connect=lambda: nullcontext(connection),
        dispose=lambda: None,
    )
    urls: list[Any] = []

    def create_engine(selected: Any) -> Any:
        urls.append(selected)
        return engine

    def load(conn: Any, selected_owner: uuid.UUID, *, app_env: str) -> uuid.UUID:
        assert conn is connection and selected_owner == owner and app_env == "test"
        return snapshot

    def read(conn: Any, selected_owner: uuid.UUID, selected_snapshot: uuid.UUID) -> Any:
        assert (
            conn is connection
            and selected_owner == owner
            and selected_snapshot == snapshot
        )
        return replay.payload()

    monkeypatch.setattr(cli, "create_engine", create_engine)
    monkeypatch.setattr(cli, "load", load)
    monkeypatch.setattr(replay, "read", read)
    replay.test_cli_job((engine, None, None, owner, None), monkeypatch, capsys)
    assert (
        len(urls) == 1
    )  # The original production-name rejection still occurs before connect.
    assert urls[0].database == "tb70_rb2_cli" and urls[0].query["host"] == PG


@pytest.mark.parametrize("entry", ["legacy", "tt21", "tt71b"])
def test_tb70_fixture_entrypoints_probe_selected_socket_and_keep_missing_policy(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    entry: str,
) -> None:
    root = Path(__file__).resolve().parents[3]
    monkeypatch.setattr(replay, "RESOURCES", SimpleNamespace(pg_socket=PG))
    if entry == "legacy":
        fixture = replay.integration
        missing = pytest.skip.Exception
    elif entry == "tt21":
        directory = root / "tests/backend/milestone"
        monkeypatch.syspath_prepend(str(directory))
        fixture = runpy.run_path(str(directory / "tt21_plugin.py"))["tt21_integration"]
        missing = pytest.fail.Exception
    else:
        fixture = runpy.run_path(str(root / "tests/backend/tt71b_regress_plugin.py"))[
            "tt71b_integration"
        ]
        missing = pytest.fail.Exception
    probes: list[str] = []
    original = Path.exists

    def absent(path: Path) -> bool:
        if path.name == ".s.PGSQL.5432":
            probes.append(str(path))
            return False
        return original(path)

    monkeypatch.setattr(Path, "exists", absent)
    with pytest.raises(missing):
        next(fixture.__wrapped__(tmp_path))
    assert probes == [PG + "/.s.PGSQL.5432"]

"""Isolated synthetic snapshots of the exact CI template seal protocol (no real service)."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "template_connections.py"
OWNER = {"run_id": "44174156220", "attempt": "1", "sha": "a" * 40,
         "container_id": "b" * 64, "system_identifier": "synthetic-cluster"}
AUTOVACUUM = (167, None, None, "autovacuum worker", "")
CLIENT = (168, "idle", None, "client backend", "autovacuum")  # Name cannot spoof backend_type.


def sample(*sessions, oid=22398, owner="aia", allowed=False):
    return {"oid": oid, "owner": owner, "allowed": allowed, "sessions": sessions}


@pytest.fixture
def world(monkeypatch, tmp_path):
    # The self-test workflow only installs pytest/pyyaml; fake the driver, not the SQL snapshots.
    class SQL(str):
        def format(self, *args):
            return SQL(super().format(*args))

    driver = ModuleType("psycopg")
    driver.sql = SimpleNamespace(SQL=SQL, Identifier=lambda name: '"' + name + '"')
    monkeypatch.setitem(sys.modules, "psycopg", driver)
    owned = ModuleType("owned_unix_resources")
    owned.now = lambda: "synthetic-time"
    owned.save = lambda path, value: path.write_text(json.dumps(value), encoding="utf-8")
    owned.check_runner = lambda: {"GITHUB_RUN_ID": OWNER["run_id"],
                                  "GITHUB_RUN_ATTEMPT": OWNER["attempt"], "GITHUB_SHA": OWNER["sha"]}
    monkeypatch.setitem(sys.modules, "owned_unix_resources", owned)
    preparer = ModuleType("prepare_tt50_template")
    preparer.identity = lambda _env: dict(OWNER)
    monkeypatch.setitem(sys.modules, "prepare_tt50_template", preparer)
    spec = importlib.util.spec_from_file_location("isolated_template_connections_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    clock = SimpleNamespace(value=0.0, sleeps=[])

    def sleep(seconds):
        assert 0 < seconds <= 0.25
        clock.value += seconds
        clock.sleeps.append(seconds)

    monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: clock.value, sleep=sleep), raising=False)
    path = tmp_path / "receipt.json"
    receipt = {"schema": "aia-ci-templates-v1", "owner": dict(OWNER),
               "databases": [{"name": "o61_tmp_0030", "oid": 22398, "owner": "aia",
                              "template": "template0", "fresh_empty": True}]}

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

        def fetchall(self):
            return self.value

    state = SimpleNamespace(samples=[], index=0, current=None, queries=[], receipt=receipt,
                            path=path, clock=clock, module=module)

    class Conn:
        def execute(self, statement, params=None):
            text = str(statement)
            state.queries.append((text, params))
            if "FROM pg_database" in text:
                current = state.samples[min(state.index, len(state.samples) - 1)]
                state.current = current
                assert params == ("o61_tmp_0030",)
                return Result((current["oid"], current["owner"], current["allowed"]))
            if "FROM pg_stat_activity" in text:
                assert params == (22398,)
                state.index += 1
                return Result(state.current["sessions"])
            assert text == 'ALTER DATABASE "o61_tmp_0030" ALLOW_CONNECTIONS false'
            return Result(None)

    state.conn = Conn()
    state.run = lambda: module.seal(state.conn, receipt, path)
    return state


def test_original_zero_then_autovacuum_race_is_stable_red_before_fix(world):
    world.samples = [sample(), sample(AUTOVACUUM), sample(), sample()]
    world.run()
    saved = json.loads(world.path.read_text(encoding="utf-8"))
    assert saved["template_connection_lifecycle"]["before"]["session_count"] == 0
    assert saved["template_connection_lifecycle"]["after"]["session_count"] == 0
    assert saved["template_connection_lifecycle"]["sessions_terminated"] == 0
    assert world.clock.sleeps and world.clock.value <= 15
    assert not any("terminate" in sql.lower() or "cancel" in sql.lower() for sql, _ in world.queries)


def test_autovacuum_after_first_zero_is_detected_at_boundary(world):
    world.samples = [sample(), sample(), sample(AUTOVACUUM), sample(), sample()]
    world.run()
    assert world.clock.sleeps == [0.25, 0.25, 0.25]
    assert world.receipt["template_connection_lifecycle"]["after"]["sessions"] == []


def test_autovacuum_reenters_during_final_service_identity_check(world):
    world.samples = [sample(), sample(), sample(), sample(AUTOVACUUM),
                     sample(), sample(), sample()]
    world.run()
    assert world.clock.sleeps == [0.25, 0.25, 0.25]
    assert world.receipt["template_connection_lifecycle"]["after"]["session_count"] == 0


def test_persistent_autovacuum_times_out_without_session_kill(world):
    world.samples = [sample(), sample(AUTOVACUUM)]
    with pytest.raises(RuntimeError, match="drain|timeout"):
        world.run()
    assert world.clock.value == 15 and world.receipt["template_connection_lifecycle"]["after"]["session_count"] == 1
    assert not any("terminate" in sql.lower() or "cancel" in sql.lower() for sql, _ in world.queries)


@pytest.mark.parametrize("after", [sample(CLIENT), sample(AUTOVACUUM, CLIENT)])
def test_unknown_or_mixed_client_is_rejected_without_wait(world, after):
    world.samples = [sample(), after]
    with pytest.raises(RuntimeError, match="session|worker"):
        world.run()
    assert world.clock.sleeps == []


@pytest.mark.parametrize("after", [sample(AUTOVACUUM, oid=999), sample(AUTOVACUUM, owner="other")])
def test_oid_or_owner_change_is_rejected_without_wait(world, after):
    world.samples = [sample(), after]
    with pytest.raises(RuntimeError, match="OID or owner"):
        world.run()
    assert world.clock.sleeps == []


def test_run_identity_mismatch_rejected_before_any_sql(world):
    world.samples = [sample()]
    world.receipt["owner"]["attempt"] = "2"
    with pytest.raises(RuntimeError, match="service or run"):
        world.run()
    assert world.queries == []


def test_service_identity_drift_during_drain_is_rejected(world, monkeypatch):
    world.samples = [sample(), sample(), sample()]
    checks = iter((dict(OWNER), {**OWNER, "container_id": "c" * 64}))
    monkeypatch.setattr(sys.modules["prepare_tt50_template"], "identity", lambda _env: next(checks))
    with pytest.raises(RuntimeError, match="service or run"):
        world.run()


def test_before_unknown_client_is_rejected_before_fence(world):
    world.samples = [sample(CLIENT)]
    with pytest.raises(RuntimeError, match="non-autovacuum"):
        world.run()
    assert not any(sql.startswith("ALTER DATABASE") for sql, _ in world.queries)


def test_connections_must_already_be_disabled_before_seal(world):
    world.samples = [sample(allowed=True)]
    with pytest.raises(RuntimeError, match="connection fence"):
        world.run()
    assert world.clock.sleeps == []
    assert not any(sql.startswith("ALTER DATABASE") for sql, _ in world.queries)

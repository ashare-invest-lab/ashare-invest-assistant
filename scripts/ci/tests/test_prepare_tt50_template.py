"""T-O86：假连接与虚拟时钟验证阶段、占用重试和安全边界，不连接数据库。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "prepare_tt50_template.py"


@pytest.fixture
def world(monkeypatch, tmp_path):
    # 自测工作流只有 pytest/pyyaml；缺少驱动时注入最小替身，不增加运行依赖。
    try:
        import psycopg
    except ModuleNotFoundError:
        psycopg = ModuleType("psycopg")

        class Error(Exception):
            pass

        class ObjectInUse(Error):
            pass

        class OperationalError(Error):
            pass

        class SQL(str):
            def format(self, *args):
                return SQL(super().format(*args))

            def as_string(self):
                return str(self)

        psycopg.Error = Error
        psycopg.errors = SimpleNamespace(ObjectInUse=ObjectInUse, OperationalError=OperationalError)
        psycopg.sql = SimpleNamespace(SQL=SQL, Identifier=lambda name: '"' + name.replace('"', '""') + '"')

    # 独立加载脚本，替身不会污染其他模块或后端测试的真实驱动。
    with monkeypatch.context() as imports:
        imports.setitem(sys.modules, "psycopg", psycopg)
        spec = importlib.util.spec_from_file_location("tt50_retry_test", SCRIPT)
        prep = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(prep)

    path = tmp_path / "receipt.json"
    receipt = {"databases": [], "retries": []}
    state = SimpleNamespace(prep=prep, receipt=receipt, path=path, clock=0, sleeps=[],
                            outcomes=[], sql=[], databases={}, creates=0, drop_error=None,
                            metadata_error=None, create_seconds=0)
    state.sessions = [(301, "TimescaleDB Background Worker Scheduler", "background worker"),
                      (302, "", "autovacuum worker"), (303, "未知客户端", "client backend")]

    class Result:
        def __init__(self, value):
            self.value = value

        def fetchone(self):
            return self.value

        def fetchall(self):
            return self.value

    class Admin:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def execute(self, statement, params=None):
            text = statement if isinstance(statement, str) else statement.as_string()
            state.sql.append((text, params))
            if "FROM pg_control_system()" in text:
                return Result(("测试实例",))
            if "FROM pg_database" in text:
                return Result(state.databases.get(params[0]))
            if "FROM pg_stat_activity" in text:
                assert text == ("SELECT pid, application_name, backend_type FROM pg_stat_activity "
                                "WHERE datname=%s ORDER BY pid")
                if state.metadata_error:
                    raise state.metadata_error
                return Result(state.sessions)
            # 执行任何建库/删库前，阶段必须已经持久化。
            assert json.loads(path.read_text(encoding="utf-8"))["phase"] == state.receipt["phase"]
            if text.startswith("CREATE DATABASE"):
                state.creates += 1
                state.clock += state.create_seconds
                outcome = state.outcomes.pop(0) if state.outcomes else None
                if outcome:
                    raise outcome
                state.databases[text.split('"')[1]] = (100 + state.creates, "aia")
            else:
                assert text.startswith("DROP DATABASE")
                if state.drop_error:
                    raise state.drop_error
                del state.databases[text.split('"')[1]]
            return Result(None)

    def sleep(seconds):
        saved = json.loads(path.read_text(encoding="utf-8"))
        assert saved["retries"][-1]["delay_seconds"] == seconds
        state.sleeps.append(seconds)
        state.clock += seconds

    monkeypatch.setenv("PGUSER", "aia")
    monkeypatch.setenv("GITHUB_RUN_ID", "11")
    monkeypatch.setenv("GITHUB_RUN_ATTEMPT", "1")
    monkeypatch.setenv("AIA_CI_TEMPLATE_RECEIPT", str(path))
    monkeypatch.setattr(prep, "time", SimpleNamespace(monotonic=lambda: state.clock, sleep=sleep))
    monkeypatch.setattr(prep, "check_runner", lambda: {"RUNNER_TEMP": str(tmp_path)})
    monkeypatch.setattr(prep, "identity", lambda env: {"system_identifier": "测试实例"})
    monkeypatch.setattr(prep, "connect", lambda name: state.conn)
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])
    state.conn = Admin()
    state.run = lambda name, source, phase: prep.create(state.conn, name, source, state.receipt,
                                                       path, phase=phase)
    return state


@pytest.mark.parametrize("name,source,phase", [
    ("o61_tmp_0030", "template0", "create_template"),
    ("oci1_tpl_probe_11_1", "o61_tmp_0030", "clone_probe"),
    ("o67_selfcheck", "aia", "create_selfcheck"),
])
def test_one_object_in_use_then_success_records_source_sessions(world, capsys, name, source, phase):
    world.outcomes = [world.prep.psycopg.errors.ObjectInUse("禁止输出的异常详情"), None]
    row = world.run(name, source, phase)
    saved = json.loads(world.path.read_text(encoding="utf-8"))
    assert world.creates == 2 and world.sleeps == [1]
    assert saved["databases"] == [row] and row["template"] == source
    assert len(saved["retries"]) == 1
    retry = saved["retries"][0]
    assert (retry["phase"], retry["source"], retry["attempt"]) == (phase, source, 1)
    assert retry["sessions"] == [dict(zip(("pid", "application_name", "backend_type"), s))
                                 for s in world.sessions]
    assert [params for text, params in world.sql if "pg_stat_activity" in text] == [(source,)]
    assert f"当前阶段 {phase}" in capsys.readouterr().err
    assert "禁止输出的异常详情" not in json.dumps(saved, ensure_ascii=False)
    assert all("terminate_backend" not in text and "cancel_backend" not in text for text, _ in world.sql)


@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_exhaustion_fails_with_original_phase_even_after_cleanup(world, monkeypatch, capsys, cleanup_fails):
    prep = world.prep
    original = prep.psycopg.errors.ObjectInUse("禁止输出的异常详情")
    world.outcomes = [None] + [original] * 5
    if cleanup_fails:
        world.drop_error = prep.psycopg.errors.OperationalError("禁止输出的清理详情")

    def prepare(conn, receipt, path, env):
        world.receipt = receipt
        prep.create(conn, prep.TEMPLATE, "template0", receipt, path, phase="create_template")
        prep.create(conn, prep.SELFCHECK, "aia", receipt, path, phase="create_selfcheck")

    monkeypatch.setattr(prep, "prepare", prepare)
    assert prep.main() == 1
    output = capsys.readouterr()
    assert "::error title=tt50-template::create_selfcheck ObjectInUse; details withheld" in output.err
    assert "当前阶段 drop_template" in output.err
    assert "禁止输出" not in output.err + output.out
    saved = json.loads(world.path.read_text(encoding="utf-8"))
    assert world.creates == 6 and world.sleeps == [1, 2, 4, 4] and world.clock == 11
    assert len(saved["retries"]) == 4
    assert [r["attempt"] for r in saved["retries"]] == [1, 2, 3, 4]
    assert saved["failure"] == {"phase": "create_selfcheck", "error_type": "ObjectInUse"}
    assert saved["state"] == ("cleanup_failed" if cleanup_fails else "cleaned")
    assert bool(saved["cleanup_failures"]) == cleanup_fails
    assert bool(saved["databases"][0].get("dropped_at")) != cleanup_fails


def test_other_create_exception_is_not_retried(world):
    error = world.prep.psycopg.errors.OperationalError("禁止输出的异常详情")
    world.outcomes = [error]
    with pytest.raises(type(error)) as caught:
        world.run("o67_selfcheck", "aia", "create_selfcheck")
    assert caught.value is error
    assert world.creates == 1 and world.sleeps == [] and world.receipt["retries"] == []
    assert not any("pg_stat_activity" in text for text, _ in world.sql)


def test_existing_name_is_never_adopted_between_attempts(world):
    world.outcomes = [world.prep.psycopg.errors.ObjectInUse()]
    sleep = world.prep.time.sleep

    def concurrent_create(seconds):
        sleep(seconds)
        world.databases["o67_selfcheck"] = (999, "aia")

    world.prep.time.sleep = concurrent_create
    with pytest.raises(RuntimeError, match="拒绝接管"):
        world.run("o67_selfcheck", "aia", "create_selfcheck")
    assert world.creates == 1 and world.receipt["databases"] == []


def test_retry_time_budget_stops_further_attempts(world):
    world.create_seconds = 5
    error = world.prep.psycopg.errors.ObjectInUse()
    world.outcomes = [error] * 5
    with pytest.raises(type(error)) as caught:
        world.run("o67_selfcheck", "aia", "create_selfcheck")
    assert caught.value is error
    assert world.creates == 3 and world.sleeps == [1, 2]


def test_metadata_failure_is_not_retried(world):
    error = world.prep.psycopg.errors.ObjectInUse()
    world.outcomes = [error]
    world.metadata_error = error
    with pytest.raises(type(error)):
        world.run("o67_selfcheck", "aia", "create_selfcheck")
    assert world.creates == 1 and world.sleeps == []


def test_drop_object_in_use_is_not_retried(world):
    row = world.run("o67_selfcheck", "aia", "create_selfcheck")
    error = world.prep.psycopg.errors.ObjectInUse()
    world.drop_error = error
    with pytest.raises(type(error)):
        world.prep.drop(world.conn, row, world.receipt, world.path)
    assert world.receipt["phase"] == "drop_selfcheck"
    assert world.sleeps == [] and world.receipt["retries"] == []
    assert not row.get("dropped_at")

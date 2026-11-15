"""Synthetic Docker state checks for PR168; no live containers or keys."""
import pytest

from test_app_master_key_ensure import Env, FAKE_DOCKER, PREFIX


@pytest.mark.parametrize("inspect_command", ["echo false; exit 0", "exit 1"])
def test_nonrunning_or_uninspectable_container_is_refused(tmp_path, inspect_command):
    e = Env(tmp_path)
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "synthetic-container\n")
    e.docker.write_text(
        FAKE_DOCKER.replace("inspect) echo true; exit 0", f"inspect) {inspect_command}"),
        encoding="utf-8",
    )
    result = e.run()
    assert result.returncode == 3
    assert "没有运行中的 postgres" in result.stderr
    assert not e.key.exists()
    assert "exec " not in e.calls()


def test_running_container_is_filtered_and_inspected_before_query(tmp_path):
    e = Env(tmp_path)
    e.volume("pgdata")
    e.set(f"ps_{PREFIX}_pgdata", "synthetic-container\n")
    e.set("psql_out", "0|0|0|0|0|0\n")
    result = e.run()
    assert result.returncode == 0, result.stderr
    calls = e.calls().splitlines()
    assert f"ps -q --filter volume={PREFIX}_pgdata --filter status=running" in calls
    inspect = "inspect --format {{.State.Running}} synthetic-container"
    assert inspect in calls
    assert calls.index(inspect) < next(i for i, call in enumerate(calls) if call.startswith("exec "))
    assert e.key.exists()

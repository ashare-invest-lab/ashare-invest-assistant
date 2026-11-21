"""盘中健康检查脚本的离线行为测试。"""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/intraday-health.sh"
COMPOSE = REPO / "deploy/compose/docker-compose.yml"


def _epoch() -> int:
    return int(datetime(2026, 11, 20, 2, 0, tzinfo=UTC).timestamp())


def _heartbeat(ts: int) -> str:
    return (
        f'{{"ts":{ts},"instance_id":"x","leader":true,"version":"v",'
        '"budget_used_last_minute":0,"queue_depth":{"p0":0,"p1":0,"p2":0}}'
    )


def _run(tmp_path: Path, *, now: int, enabled: str = "true", heartbeat: str | None = None,
         queue: str | None = None, queue_key: str | None = None,
         queue_alert: int = 900) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    if heartbeat is not None:
        (source / "heartbeat").write_text(f"{heartbeat}\n", encoding="utf-8")
    if queue is not None:
        (source / "queue_len").write_text(f"{queue}\n", encoding="utf-8")
    env = {
        "INTRADAY_ENABLED": enabled,
        "INTRADAY_HEALTH_LOG": str(tmp_path / "health.log"),
        "INTRADAY_HEALTH_STATE": str(tmp_path / "health.state"),
        "INTRADAY_QUEUE_ZERO_ALERT_S": str(queue_alert),
    }
    if queue_key is not None:
        env["INTRADAY_QUEUE_KEY"] = queue_key
    return subprocess.run(
        ["sh", str(SCRIPT), "--from-dir", str(source), "--now", str(now)],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
        check=False,
    )


def test_intraday_health_offline_states(tmp_path: Path) -> None:
    now = _epoch()

    disabled = _run(tmp_path / "disabled", now=now, enabled="false")
    assert disabled.returncode == 0
    assert "状态=未启用" in disabled.stdout

    normal = _run(tmp_path / "normal", now=now, heartbeat=_heartbeat(now), queue="2")
    assert normal.returncode == 0
    assert "状态=正常" in normal.stdout
    assert "队列=未接入" in normal.stdout
    assert "队列检查未接入（待 I4 定稿）" in normal.stdout

    stale = _run(tmp_path / "stale", now=now, heartbeat=_heartbeat(now - 121), queue="2")
    assert stale.returncode == 2
    assert "状态=心跳过期" in stale.stdout

    missing = _run(tmp_path / "missing", now=now, queue="2")
    assert missing.returncode == 2
    assert "状态=心跳缺失" in missing.stdout


def test_intraday_health_rejects_non_json_heartbeats(tmp_path: Path) -> None:
    now = _epoch()
    invalid_values = [
        str(now),
        '{"ts":"123"}',
        '{"ts":true}',
        '{"ts":1.5}',
        "not-json",
    ]
    for index, heartbeat in enumerate(invalid_values):
        result = _run(tmp_path / f"invalid-{index}", now=now, heartbeat=heartbeat)
        assert result.returncode == 2
        assert "状态=心跳缺失" in result.stdout
        assert "说明=心跳格式无效" in result.stdout


def test_intraday_health_queue_zero_and_off_hours(tmp_path: Path) -> None:
    now = _epoch()
    first = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        queue="0",
        queue_key="jobs:worker",
        queue_alert=900,
    )
    assert first.returncode == 0 and "状态=正常" in first.stdout

    long_zero = _run(
        tmp_path,
        now=now + 900,
        heartbeat=_heartbeat(now + 900),
        queue="0",
        queue_key="jobs:worker",
        queue_alert=900,
    )
    assert long_zero.returncode == 3
    assert "状态=队列长期为0" in long_zero.stdout

    off_hours = _run(
        tmp_path / "off-hours",
        now=now - 60 * 60 * 4,
        heartbeat=_heartbeat(now),
        queue="0",
    )
    assert off_hours.returncode == 0
    assert "状态=非交易时段" in off_hours.stdout


def test_intraday_health_has_no_redis_write_command() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"redis-cli[^\n]*(?:SET|DEL|LPUSH|RPUSH|LPOP|RPOP|INCR|EXPIRE)\b", text)


def test_compose_intraday_health_profile_and_default() -> None:
    document = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    service = document["services"]["intraday-health"]
    assert service["profiles"] == ["monitor"]
    assert service["environment"]["INTRADAY_ENABLED"] == "${INTRADAY_ENABLED:-false}"
    assert "ingest:heartbeat" in service["environment"]["INTRADAY_HEARTBEAT_KEY"]
    assert service["environment"]["INTRADAY_QUEUE_KEY"] == "${INTRADAY_QUEUE_KEY:-}"
    assert service["image"] == document["services"]["redis"]["image"]

    deploy_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in (REPO / "deploy").rglob("*")
        if path.is_file()
    )
    assert "intraday:heartbeat" not in deploy_text

from __future__ import annotations

import json
import re
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/intraday-health.sh"
COMPOSE = REPO / "deploy/compose/docker-compose.yml"
def _epoch() -> int:
    return int(datetime(2026, 11, 20, 2, 0, tzinfo=UTC).timestamp())
def _heartbeat(ts: int) -> str:
    return (f'{{"ts":{ts},"instance_id":"x","leader":true,"version":"v",'
            '"budget_used_last_minute":0,"queue_depth":{"p0":0,"p1":0,"p2":0}}')
def _reference_parse_heartbeat_ts(raw: str) -> int | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict): return None
    ts = payload.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0: return None
    return ts
def _run(tmp_path: Path, *, now: int, enabled: str = "true", heartbeat: str | None = None,
         queue: str | None = None, queue_key: str | None = None,
         queue_alert: int = 900, quotes_ts: int | str | None = None,
         quotes_source: str | None = None, trading_day: int | str | None = None,
         config_text: str | None = None, config_missing: bool = False,
         stale_override: str | None = None) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    if heartbeat is not None: (source / "heartbeat").write_text(f"{heartbeat}\n", encoding="utf-8")
    if queue is not None: (source / "queue_len").write_text(f"{queue}\n", encoding="utf-8")
    if quotes_ts is not None: (source / "quotes_ts").write_text(f"{quotes_ts}\n", encoding="utf-8")
    if trading_day is not None: (source / "trading_day").write_text(f"{trading_day}\n", encoding="utf-8")
    config = tmp_path / "realtime.yaml"
    config.write_text(config_text or "intervals:\n  quote_interval_s: 15\n  stale_threshold_s: null\n", encoding="utf-8")
    if config_missing: config.unlink()
    env = {
        "INTRADAY_ENABLED": enabled,
        "INTRADAY_HEALTH_LOG": str(tmp_path / "health.log"),
        "INTRADAY_HEALTH_STATE": str(tmp_path / "health.state"),
        "INTRADAY_QUEUE_ZERO_ALERT_S": str(queue_alert),
        "INTRADAY_REALTIME_CONFIG": str(config),
    }
    if queue_key is not None: env["INTRADAY_QUEUE_KEY"] = queue_key
    if quotes_source is not None: env["REALTIME_QUOTES_SOURCE"] = quotes_source
    if stale_override is not None: env["INTRADAY_QUOTES_STALE_S"] = stale_override
    return subprocess.run(["sh", str(SCRIPT), "--from-dir", str(source), "--now", str(now)],
                          capture_output=True, text=True, env=env, timeout=30, check=False)
def test_intraday_health_offline_states(tmp_path: Path) -> None:
    now = _epoch()
    disabled = _run(tmp_path / "disabled", now=now, enabled="false")
    assert disabled.returncode == 0
    assert "状态=未启用" in disabled.stdout
    normal = _run(tmp_path / "normal", now=now, heartbeat=_heartbeat(now), queue="2")
    assert normal.returncode == 0
    assert all(item in normal.stdout for item in ("状态=正常", "队列=未接入", "队列检查未接入（待 I4 定稿）"))
    stale = _run(tmp_path / "stale", now=now, heartbeat=_heartbeat(now - 121), queue="2")
    assert stale.returncode == 2
    assert "状态=心跳过期" in stale.stdout
    missing = _run(tmp_path / "missing", now=now, queue="2")
    assert missing.returncode == 2
    assert "状态=心跳缺失" in missing.stdout
@pytest.mark.parametrize(
    "heartbeat",
    [
        str(_epoch()),
        '{"ts":1792548000,"broken":}',
        '{"ts" : 1792548000,"instance_id":"x"}',
        '{\n  "ts": 1792548000\n}',
        '{"ts":1.0}',
        '{"ts":1e9}',
        '{"ts":true}',
        '{"ts":"1"}',
        '{"a":{"ts":1}}',
        "[1]",
        '{"ts":1} x',
        '{"ts":1,}',
        '{"s":"\\\"ts\\\":5","ts":7}',
        '{"ts":1,"ts":2}',
        '{"ts":-1}',
        '{"ts":-0}',
    ],
)
def test_intraday_health_json_parser_matches_python(tmp_path: Path, heartbeat: str) -> None:
    now = _epoch()
    expected = _reference_parse_heartbeat_ts(heartbeat)
    result = _run(tmp_path, now=now, heartbeat=heartbeat)
    assert result.returncode == 2
    if expected is None: assert "状态=心跳缺失" in result.stdout and "说明=心跳格式无效" in result.stdout
    else:
        assert "说明=心跳格式无效" not in result.stdout
        age = max(now - expected, 0)
        assert f"心跳龄={age}" in result.stdout
def test_intraday_health_queue_zero_and_off_hours(tmp_path: Path) -> None:
    now = _epoch()
    first = _run(tmp_path, now=now, heartbeat=_heartbeat(now), queue="0", queue_key="q", queue_alert=900)
    assert first.returncode == 0 and "状态=正常" in first.stdout
    long_zero = _run(tmp_path, now=now + 900, heartbeat=_heartbeat(now + 900), queue="0", queue_key="q",
                     queue_alert=900)
    assert long_zero.returncode == 3
    assert "状态=队列长期为0" in long_zero.stdout
    off_hours = _run(tmp_path / "off-hours", now=now - 60 * 60 * 4, heartbeat=_heartbeat(now), queue="0")
    assert off_hours.returncode == 0
    assert "状态=非交易时段" in off_hours.stdout

@pytest.mark.parametrize(
    ("label", "now_delta", "expected"),
    [("fresh", 0, "状态=正常"), ("stale", 40, "状态=行情过期"),
     ("lunch", 2 * 60 * 60, "状态=非交易时段"),
     ("preopen", -60 * 60, "状态=非交易时段"),
     ("closed", 8 * 60 * 60, "状态=非交易时段")],
)
def test_intraday_health_quotes_session_states(tmp_path: Path, label: str, now_delta: int, expected: str) -> None:
    now = _epoch()
    result = _run(tmp_path / label, now=now + now_delta, heartbeat=_heartbeat(now + now_delta),
                  quotes_ts=now, quotes_source="fake")
    assert expected in result.stdout
    if label == "fresh": assert "行情龄=0秒" in result.stdout
    if label == "stale": assert result.returncode == 2 and "阈值=30" in result.stdout

def test_intraday_health_quotes_off_and_nontrading_day(tmp_path: Path) -> None:
    now = _epoch()
    off = _run(tmp_path / "off", now=now, heartbeat=_heartbeat(now), quotes_ts=now)
    assert off.returncode == 0 and "行情采集未启用" in off.stdout
    holiday = _run(tmp_path / "holiday", now=now, heartbeat=_heartbeat(now), quotes_ts=now,
                   quotes_source="fake", trading_day=0)
    assert holiday.returncode == 0 and "状态=非交易时段" in holiday.stdout and "非交易日" in holiday.stdout

def test_intraday_health_quotes_config_and_override(tmp_path: Path) -> None:
    now = _epoch()
    derived = _run(tmp_path / "derived", now=now + 31, heartbeat=_heartbeat(now + 31),
                   quotes_ts=now, quotes_source="fake")
    assert derived.returncode == 2 and "状态=行情过期" in derived.stdout
    missing = _run(tmp_path / "missing-config", now=now, heartbeat=_heartbeat(now), quotes_ts=now,
                   quotes_source="fake", config_missing=True)
    assert missing.returncode == 2 and "状态=配置错误" in missing.stdout
    override = _run(tmp_path / "override", now=now + 20, heartbeat=_heartbeat(now + 20),
                    quotes_ts=now, quotes_source="fake", stale_override="30")
    assert override.returncode == 0 and "行情龄=20秒" in override.stdout
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

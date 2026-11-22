from __future__ import annotations

import ast
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


def _heartbeat_payload(ts: int) -> dict[str, object]:
    return {
        "ts": ts,
        "instance_id": "ingest-fixture-01",
        "leader": True,
        "version": "0.0.0-fixture",
        "budget_used_last_minute": 0,
        "queue_depth": {"p0": 0, "p1": 0, "p2": 0},
    }


def _epoch() -> int:
    return int(datetime(2026, 11, 20, 2, 0, tzinfo=UTC).timestamp())


def _heartbeat(
    ts: int, *, indent: int | None = None, separators: tuple[str, str] = (",", ":")
) -> str:
    return json.dumps(_heartbeat_payload(ts), indent=indent, separators=separators)


def test_heartbeat_fixture_matches_producer_shape() -> None:
    source = (REPO / "src/backend/app/workers/ingest.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    heartbeat_functions = [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "heartbeat_payload"
    ]
    assert heartbeat_functions, "heartbeat_payload function not found"

    dumps_calls = [
        node
        for node in ast.walk(heartbeat_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "json"
        and node.func.attr == "dumps"
    ]
    assert dumps_calls, "heartbeat_payload json.dumps call not found"
    dumps_call = dumps_calls[0]
    assert dumps_call.args and isinstance(dumps_call.args[0], ast.Dict), (
        "heartbeat_payload json.dumps dict literal not found"
    )
    payload_dict = dumps_call.args[0]
    keys = [key.value for key in payload_dict.keys if isinstance(key, ast.Constant)]
    assert keys == list(_heartbeat_payload(0))

    queue_node = next(
        (
            value
            for key, value in zip(payload_dict.keys, payload_dict.values)
            if isinstance(key, ast.Constant) and key.value == "queue_depth"
        ),
        None,
    )
    assert isinstance(queue_node, ast.Dict), "queue_depth dict literal not found"
    queue_keys = [key.value for key in queue_node.keys if isinstance(key, ast.Constant)]
    assert queue_keys == list(_heartbeat_payload(0)["queue_depth"])

    separators = next(
        (kw.value for kw in dumps_call.keywords if kw.arg == "separators"),
        None,
    )
    assert isinstance(separators, ast.Tuple) and len(separators.elts) == 2
    assert [elt.value for elt in separators.elts] == [",", ":"]


def _reference_parse_heartbeat_ts(raw: str) -> int | None:
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    ts = payload.get("ts")
    if isinstance(ts, bool) or not isinstance(ts, int) or ts < 0:
        return None
    return ts


def _run(
    tmp_path: Path,
    *,
    now: int,
    enabled: str = "true",
    heartbeat: str | None = None,
    queue: str | None = None,
    queue_key: str | None = None,
    queue_alert: int = 900,
    quotes_ts: int | str | None = None,
    quotes_source: str | None = None,
    trading_day: int | str | None = None,
    config_text: str | None = None,
    config_missing: bool = False,
    stale_override: str | None = None,
    future_tolerance: str | None = None,
) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "source"
    source.mkdir(parents=True, exist_ok=True)
    if heartbeat is not None:
        (source / "heartbeat").write_text(f"{heartbeat}\n", encoding="utf-8")
    if queue is not None:
        (source / "queue_len").write_text(f"{queue}\n", encoding="utf-8")
    if quotes_ts is not None:
        (source / "quotes_ts").write_text(f"{quotes_ts}\n", encoding="utf-8")
    if trading_day is not None:
        (source / "trading_day").write_text(f"{trading_day}\n", encoding="utf-8")
    config = tmp_path / "realtime.yaml"
    config.write_text(
        config_text
        or "intervals:\n  quote_interval_s: 15\n  stale_threshold_s: null\n",
        encoding="utf-8",
    )
    if config_missing:
        config.unlink()
    env = {
        "INTRADAY_ENABLED": enabled,
        "INTRADAY_HEALTH_LOG": str(tmp_path / "health.log"),
        "INTRADAY_HEALTH_STATE": str(tmp_path / "health.state"),
        "INTRADAY_QUEUE_ZERO_ALERT_S": str(queue_alert),
        "INTRADAY_REALTIME_CONFIG": str(config),
    }
    if queue_key is not None:
        env["INTRADAY_QUEUE_KEY"] = queue_key
    if quotes_source is not None:
        env["REALTIME_QUOTES_SOURCE"] = quotes_source
    if quotes_ts is not None:
        env["INTRADAY_QUOTES_TS_KEY"] = "quotes:timestamp"
    if stale_override is not None:
        env["INTRADAY_QUOTES_STALE_S"] = stale_override
    if future_tolerance is not None:
        env["INTRADAY_QUOTES_FUTURE_TOLERANCE_S"] = future_tolerance
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
    assert all(
        item in normal.stdout
        for item in ("状态=正常", "队列=未接入", "队列检查未接入（待 I4 定稿）")
    )
    stale = _run(
        tmp_path / "stale", now=now, heartbeat=_heartbeat(now - 121), queue="2"
    )
    assert stale.returncode == 2
    assert "状态=心跳过期" in stale.stdout
    missing = _run(tmp_path / "missing", now=now, queue="2")
    assert missing.returncode == 2
    assert "状态=心跳缺失" in missing.stdout


@pytest.mark.parametrize(
    "heartbeat",
    [
        _heartbeat(_epoch()),
        _heartbeat(_epoch(), indent=2),
        _heartbeat(_epoch(), separators=(", ", ": ")),
    ],
)
def test_intraday_health_fresh_heartbeat_whitespace_variants(
    tmp_path: Path, heartbeat: str
) -> None:
    result = _run(tmp_path, now=_epoch(), heartbeat=heartbeat)
    assert result.returncode == 0
    assert "状态=正常" in result.stdout


@pytest.mark.parametrize("suffix", ["", ","])
def test_intraday_health_fresh_heartbeat_malformed_suffix(tmp_path: Path, suffix: str) -> None:
    heartbeat = _heartbeat(_epoch())
    malformed = heartbeat[:-1] if not suffix else heartbeat + suffix
    result = _run(tmp_path, now=_epoch(), heartbeat=malformed)
    assert result.returncode == 2
    assert "心跳格式无效" in result.stdout


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
        '{"s":"\\"ts\\":5","ts":7}',
        '{"ts":1,"ts":2}',
        '{"ts":-1}',
        '{"ts":-0}',
    ],
)
def test_intraday_health_json_parser_matches_python(
    tmp_path: Path, heartbeat: str
) -> None:
    now = _epoch()
    expected = _reference_parse_heartbeat_ts(heartbeat)
    result = _run(tmp_path, now=now, heartbeat=heartbeat)
    assert result.returncode == 2
    if expected is None:
        assert "状态=心跳缺失" in result.stdout and "说明=心跳格式无效" in result.stdout
    else:
        assert "说明=心跳格式无效" not in result.stdout
        age = max(now - expected, 0)
        assert f"心跳龄={age}" in result.stdout


def test_intraday_health_queue_zero_and_off_hours(tmp_path: Path) -> None:
    now = _epoch()
    first = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        queue="0",
        queue_key="q",
        queue_alert=900,
    )
    assert first.returncode == 0 and "状态=正常" in first.stdout
    long_zero = _run(
        tmp_path,
        now=now + 900,
        heartbeat=_heartbeat(now + 900),
        queue="0",
        queue_key="q",
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


@pytest.mark.parametrize(
    ("label", "now_delta", "expected"),
    [
        ("fresh", 0, "状态=正常"),
        ("stale", 40, "状态=行情过期"),
        ("lunch", 2 * 60 * 60, "状态=非交易时段"),
        ("preopen", -60 * 60, "状态=非交易时段"),
        ("closed", 8 * 60 * 60, "状态=非交易时段"),
    ],
)
def test_intraday_health_quotes_session_states(
    tmp_path: Path, label: str, now_delta: int, expected: str
) -> None:
    now = _epoch()
    result = _run(
        tmp_path / label,
        now=now + now_delta,
        heartbeat=_heartbeat(now + now_delta),
        quotes_ts=now,
        quotes_source="fake",
    )
    assert expected in result.stdout
    if label == "fresh":
        assert "行情龄=0秒" in result.stdout
    if label == "stale":
        assert result.returncode == 2 and "阈值=30" in result.stdout


def test_intraday_health_quotes_off_and_nontrading_day(tmp_path: Path) -> None:
    now = _epoch()
    off = _run(tmp_path / "off", now=now, heartbeat=_heartbeat(now), quotes_ts=now)
    assert off.returncode == 0 and "行情采集未启用" in off.stdout
    holiday = _run(
        tmp_path / "holiday",
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now,
        quotes_source="fake",
        trading_day=0,
    )
    assert (
        holiday.returncode == 0
        and "状态=非交易时段" in holiday.stdout
        and "非交易日" in holiday.stdout
    )


def test_intraday_health_quotes_config_and_override(tmp_path: Path) -> None:
    now = _epoch()
    derived = _run(
        tmp_path / "derived",
        now=now + 31,
        heartbeat=_heartbeat(now + 31),
        quotes_ts=now,
        quotes_source="fake",
    )
    assert derived.returncode == 2 and "状态=行情过期" in derived.stdout
    missing = _run(
        tmp_path / "missing-config",
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now,
        quotes_source="fake",
        config_missing=True,
    )
    assert missing.returncode == 2 and "状态=配置错误" in missing.stdout
    override = _run(
        tmp_path / "override",
        now=now + 20,
        heartbeat=_heartbeat(now + 20),
        quotes_ts=now,
        quotes_source="fake",
        stale_override="30",
    )
    assert override.returncode == 0 and "行情龄=20秒" in override.stdout


@pytest.mark.parametrize(
    ("minute_delta", "expected"),
    [
        (-30, "状态=正常"),
        (-31, "状态=非交易时段"),
        (90, "状态=正常"),
        (91, "状态=非交易时段"),
        (179, "状态=非交易时段"),
        (180, "状态=正常"),
        (300, "状态=正常"),
        (301, "状态=非交易时段"),
    ],
)
def test_intraday_health_session_boundaries(
    tmp_path: Path, minute_delta: int, expected: str
) -> None:
    now = _epoch() + minute_delta * 60
    result = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now,
        quotes_source="fake",
    )
    assert expected in result.stdout


@pytest.mark.parametrize("age, expected_rc", [(30, 0), (31, 2)])
def test_intraday_health_quotes_stale_boundary(
    tmp_path: Path, age: int, expected_rc: int
) -> None:
    now = _epoch()
    result = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now - age,
        quotes_source="fake",
        stale_override="30",
    )
    assert result.returncode == expected_rc
    assert ("状态=正常" in result.stdout) is (age == 30)
    assert ("状态=行情过期" in result.stdout) is (age == 31)


def test_intraday_health_quotes_future_timestamp(tmp_path: Path) -> None:
    now = _epoch()
    result = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now + 1,
        quotes_source="fake",
        future_tolerance="0",
    )
    assert result.returncode == 2
    assert "状态=行情时间异常" in result.stdout
    assert "行情时间差=-1秒" in result.stdout


@pytest.mark.parametrize(
    ("offset", "tolerance", "expected_rc", "expected_state"),
    [
        (1, "5", 0, "状态=正常"),
        (5, "5", 0, "状态=正常"),
        (6, "5", 2, "状态=行情时间异常"),
    ],
)
def test_intraday_health_quotes_future_tolerance(
    tmp_path: Path,
    offset: int,
    tolerance: str,
    expected_rc: int,
    expected_state: str,
) -> None:
    now = _epoch()
    result = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now + offset,
        quotes_source="fake",
        future_tolerance=tolerance,
    )
    assert result.returncode == expected_rc
    assert expected_state in result.stdout
    if offset <= int(tolerance):
        assert "行情龄=0秒" in result.stdout


def test_intraday_health_quotes_future_tolerance_invalid(tmp_path: Path) -> None:
    now = _epoch()
    result = _run(
        tmp_path,
        now=now,
        heartbeat=_heartbeat(now),
        quotes_ts=now,
        quotes_source="fake",
        future_tolerance="-1",
    )
    assert result.returncode == 2
    assert "状态=配置错误" in result.stdout


def test_intraday_health_quotes_enabled_without_timestamp_key(tmp_path: Path) -> None:
    now = _epoch()
    result = _run(tmp_path, now=now, heartbeat=_heartbeat(now), quotes_source="fake")
    assert result.returncode == 2
    assert "状态=行情未接入" in result.stdout


def test_intraday_health_has_no_redis_write_command() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(
        r"redis-cli[^\n]*(?:SET|DEL|LPUSH|RPUSH|LPOP|RPOP|INCR|EXPIRE)\b", text
    )


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
    healthcheck = service["healthcheck"]["test"][1]
    assert "行情过期" not in healthcheck
    assert "行情时间异常" not in healthcheck
    assert "行情未接入" not in healthcheck

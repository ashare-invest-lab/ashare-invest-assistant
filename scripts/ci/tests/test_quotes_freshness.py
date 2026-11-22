"""盘中行情新鲜度脚本的离线验收。"""

from __future__ import annotations

import os
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from conftest import REPO

SCRIPT = REPO / "deploy/scripts/quotes-freshness.sh"
SHANGHAI = timezone(timedelta(hours=8))


def epoch(hour: int = 10, minute: int = 0) -> int:
    return int(datetime(2024, 1, 2, hour, minute, tzinfo=SHANGHAI).timestamp())


def run(tmp_path: Path, now: int, max_ts: int | None = None, is_open: str | None = "true", **extra: str) -> subprocess.CompletedProcess[str]:
    source = tmp_path / "snapshot"
    source.mkdir(exist_ok=True)
    if max_ts is not None:
        (source / "max_ts").write_text(str(max_ts), encoding="utf-8")
    else:
        (source / "max_ts").unlink(missing_ok=True)
    if is_open is not None:
        (source / "is_open").write_text(is_open, encoding="utf-8")
    else:
        (source / "is_open").unlink(missing_ok=True)
    env = {**os.environ, "QUOTES_FRESHNESS_ENABLED": "true", **extra}
    return subprocess.run(
        [str(SCRIPT), "--from-dir", str(source), "--now", str(now)],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_disabled() -> None:
    result = subprocess.run([str(SCRIPT)], capture_output=True, text=True, env={**os.environ, "QUOTES_FRESHNESS_ENABLED": "false"}, check=False)
    assert result.returncode == 0
    assert "状态=未启用" in result.stdout


def test_normal_expired_and_no_data(tmp_path: Path) -> None:
    now = epoch()
    normal = run(tmp_path, now, now - 10)
    assert normal.returncode == 0
    assert "状态=正常" in normal.stdout and "阈值=30s" in normal.stdout
    expired = run(tmp_path, now, now - 31)
    assert expired.returncode == 2
    assert "状态=过期" in expired.stdout
    empty = run(tmp_path, now, None)
    assert empty.returncode == 2
    assert "状态=无数据" in empty.stdout


def test_time_closed_and_calendar_inference(tmp_path: Path) -> None:
    outside = run(tmp_path, epoch(8), epoch(8) - 1)
    assert outside.returncode == 0
    assert "状态=非交易时段" in outside.stdout
    closed = run(tmp_path, epoch(), epoch() - 1, "false")
    assert closed.returncode == 0
    assert "状态=休市" in closed.stdout
    inferred = run(tmp_path, epoch(), epoch() - 1, None)
    assert inferred.returncode == 0
    assert "交易日历缺当日，按工作日推断（未验证）" in inferred.stdout


def test_threshold_override_and_invalid_value(tmp_path: Path) -> None:
    now = epoch()
    overridden = run(tmp_path, now, now - 31, QUOTES_STALE_S="60")
    assert overridden.returncode == 0
    assert "阈值=60s" in overridden.stdout
    invalid = run(tmp_path, now, now - 1, QUOTES_STALE_S="0")
    assert invalid.returncode == 4
    assert "状态=配置错误" in invalid.stdout


def test_script_contains_no_write_sql() -> None:
    text = SCRIPT.read_text(encoding="utf-8")
    assert not re.search(r"\b(?:INSERT|UPDATE|DELETE|TRUNCATE|DROP|ALTER|CREATE)\b", text)


def test_holiday_without_data_is_not_alarm(tmp_path: Path) -> None:
    result = run(tmp_path, epoch(), None, "false")
    assert result.returncode == 0
    assert "状态=休市" in result.stdout


def test_online_query_empty_first_field_and_project_filter(tmp_path: Path) -> None:
    calls = tmp_path / "calls"
    fake = tmp_path / "docker"
    fake.write_text(
        f'#!/bin/sh\necho "$*" >> {calls}\ncase "$1" in ps) echo pgid ;; exec) cat >/dev/null; echo "|true" ;; esac\n',
        encoding="utf-8",
    )
    fake.chmod(0o755)
    env = {**os.environ, "QUOTES_FRESHNESS_ENABLED": "true", "AIA_DOCKER": str(fake), "COMPOSE_PROJECT": "aia-x"}
    result = subprocess.run([str(SCRIPT), "--now", str(epoch())], capture_output=True, text=True, env=env, check=False)
    assert result.returncode == 2
    assert "状态=无数据" in result.stdout
    assert "label=com.docker.compose.project=aia-x" in calls.read_text(encoding="utf-8")

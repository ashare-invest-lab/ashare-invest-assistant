"""Offline checks for the box-only milestone migration drill."""

from __future__ import annotations

import os
import re
import subprocess
import tempfile
from pathlib import Path

from conftest import REPO

DRILL = REPO / "deploy/scripts/milestone-sync-drill.sh"
RUNBOOK = REPO / "deploy/runbooks/milestone-sync.md"


def _drill_source() -> str:
    return DRILL.read_text(encoding="utf-8")


def test_drill_bash_syntax() -> None:
    result = subprocess.run(
        ["bash", "-n", str(DRILL)],
        capture_output=True,
        check=False,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_drill_isolated_cleanup_and_forbidden_operations() -> None:
    source = _drill_source()
    assert "docker rm -f" in source
    cleanup = re.search(r"cleanup\(\) \{(?P<body>.*?)\n\}", source, re.DOTALL)
    assert cleanup, "cleanup trap is required"
    body = cleanup.group("body")
    assert '"$container" == aia-o131-drill-*' in body
    assert "docker volume rm" not in source
    assert "down -v" not in source
    assert "worktree prune" not in source
    assert ".env" not in source


def test_drill_defaults_and_safe_runtime_defaults() -> None:
    source = _drill_source()
    assert 'from_ref="2dbfdee"' in source
    assert 'to_ref="origin/main"' in source
    assert '-c "port=${host_port}" -c listen_addresses=127.0.0.1' in source
    assert "timescale/timescaledb:2.31.0-pg16@sha256:" in source
    assert '[[ -s "$dump_file" ]]' in source

    env = os.environ.copy()
    env["DRILL_SELFTEST_ENV"] = "1"
    result = subprocess.run(
        ["bash", str(DRILL), "--from", "fixture", "--to", "target"],
        capture_output=True,
        check=False,
        text=True,
        env=env,
        timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "export MAIRUI_MODE=replay" in result.stdout
    assert "export DAILY_BARS_SOURCE=off" in result.stdout
    assert "export INTRADAY_ENABLED=false" in result.stdout
    assert "export APP_ENV=test" in result.stdout


def test_backup_restore_gate_is_before_upgrade() -> None:
    with tempfile.TemporaryDirectory(prefix="milestone-drill-test-") as temp:
        root = Path(temp)
        bin_dir = root / "bin"
        bin_dir.mkdir()
        log_file = root / "calls.log"
        docker = bin_dir / "docker"
        docker.write_text(
            """#!/usr/bin/env bash
set -u
log=${FAKE_LOG:?}
printf 'docker %s\\n' "$*" >> "$log"
case "${1:-}" in
  run|cp|rm) exit 0 ;;
  exec)
    joined="$*"
    [[ "$joined" == *" pg_isready "* ]] && exit 0
    [[ "$joined" == *"pg_dump"* ]] && { [[ "${FAKE_DUMP_EMPTY:-0}" == 1 ]] || printf 'synthetic dump'; exit 0; }
    [[ "$joined" == *"pg_restore --list"* ]] && { [[ "${FAKE_LIST_FAIL:-0}" == 1 ]] && exit 1 || exit 0; }
    [[ "$joined" == *"psql"* ]] || exit 0
    [[ "$joined" == *"SELECT version_num"* ]] && { printf 'abc123\\n'; exit 0; }
    [[ "$joined" == *"count(*) FROM public.t_o131_drill"* ]] && { printf '3\\n'; exit 0; }
    [[ "$joined" == *"count(*) FROM app.dimension_definitions"* ]] && { printf '1\\n'; exit 0; }
    exit 0
    ;;
esac
exit 0
"""
        )
        uv = bin_dir / "uv"
        uv.write_text(
            """#!/usr/bin/env bash
set -u
printf 'uv %s env=%s/%s/%s/%s\\n' "$*" "${APP_ENV-}" "${MAIRUI_MODE-}" \\
  "${DAILY_BARS_SOURCE-}" "${INTRADAY_ENABLED-}" >> "${FAKE_LOG:?}"
if [[ "$*" == *"alembic heads"* ]]; then printf 'abc123 (head)\\n'; fi
exit 0
"""
        )
        docker.chmod(0o755)
        uv.chmod(0o755)

        env = os.environ.copy()
        for key in ("APP_ENV", "MAIRUI_MODE", "DAILY_BARS_SOURCE", "INTRADAY_ENABLED"):
            env.pop(key, None)
        env.update(
            PATH=f"{bin_dir}:{env['PATH']}",
            FAKE_LOG=str(log_file),
            DRILL_OUT=str(root / "out"),
            UV_CACHE_DIR=str(root / "uv-cache"),
        )
        result = subprocess.run(
            ["bash", str(DRILL), "--from", "HEAD", "--to", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            env=env,
            timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        calls = log_file.read_text(encoding="utf-8").splitlines()
        list_index = next(
            i for i, line in enumerate(calls) if "pg_restore --list" in line
        )
        verify_index = next(
            i
            for i, line in enumerate(calls)
            if "pg_restore -U aia -d aia_o131_verify_" in line
        )
        upgrades = [
            i
            for i, line in enumerate(calls)
            if "uv run --frozen alembic upgrade head" in line
        ]
        assert len(upgrades) >= 2
        assert list_index < verify_index < upgrades[1]
        assert all(
            line.endswith("env=test/replay/off/false")
            for line in calls
            if line.startswith("uv run")
        )

        env["FAKE_LIST_FAIL"] = "1"
        failed = subprocess.run(
            ["bash", str(DRILL), "--from", "HEAD", "--to", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            env=env,
            timeout=30,
        )
        assert failed.returncode != 0, failed.stdout + failed.stderr
        summary = next(
            line for line in failed.stdout.splitlines() if line.startswith("{")
        )
        assert '"backup_verify":{"seconds":' in summary
        assert '"result":"failed"' in summary
        assert '"to_upgrade":{"seconds":0,"result":"not_run"}' in summary
        failed_calls = log_file.read_text(encoding="utf-8").splitlines()
        failed_start = max(
            i for i, line in enumerate(failed_calls) if "pg_restore --list" in line
        )
        assert not any(
            "uv run --frozen alembic upgrade head" in line
            for line in failed_calls[failed_start + 1 :]
        )

        env.pop("FAKE_LIST_FAIL")
        env["FAKE_DUMP_EMPTY"] = "1"
        empty_dump = subprocess.run(
            ["bash", str(DRILL), "--from", "HEAD", "--to", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
            env=env,
            timeout=30,
        )
        assert empty_dump.returncode != 0
        assert '"pg_dump":{"seconds":' in empty_dump.stdout
        assert '"result":"failed"' in empty_dump.stdout


def test_runbook_migration_and_smoke_markers() -> None:
    source = RUNBOOK.read_text(encoding="utf-8")
    for revision in ("0037", "0038", "0039"):
        assert revision in source
    for feature in ("实时行情", "市场概览", "禁投冷静期", "复盘页"):
        assert feature in source
    assert "未验证" in source
    assert "本脚本默认真跑" in source
    assert "备份可恢复性校验" in source
    assert "升级前校验备份可恢复，通过后才执行升级" in source

"""Offline checks for the box-only milestone migration drill."""

from __future__ import annotations

import re
import subprocess

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
    assert "MAIRUI_MODE=replay" in source
    assert "DAILY_BARS_SOURCE=off" in source
    assert "INTRADAY_ENABLED=false" in source
    assert '-c "port=${host_port}" -c listen_addresses=127.0.0.1' in source
    assert "timescale/timescaledb:2.31.0-pg16@sha256:" in source


def test_runbook_migration_and_smoke_markers() -> None:
    source = RUNBOOK.read_text(encoding="utf-8")
    for revision in ("0037", "0038", "0039"):
        assert revision in source
    for feature in ("实时行情", "市场概览", "禁投冷静期", "复盘页"):
        assert feature in source
    assert "未验证" in source

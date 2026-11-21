"""T-O123：会真调麦蕊的开关默认关闭。"""

from __future__ import annotations

from pathlib import Path

import check_mairui_defaults as cmd
from conftest import REPO, write


def test_repo_defaults_are_safe() -> None:
    assert cmd.check(REPO) == []


def baseline(repo: Path) -> None:
    write(repo, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: ${MAIRUI_MODE:-replay}\n      DAILY_BARS_SOURCE: off\n")
    write(repo, "deploy/compose/docker-compose.dev.yml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: replay\n")
    write(repo, "deploy/env/.env.example", "MAIRUI_MODE=replay\nDAILY_BARS_SOURCE=off\n")
    write(repo, "src/backend/app/config.py", 'daily_bars_source: Literal["off", "fake"] = "off"\n')


def test_minimal_baseline_is_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    assert cmd.check(tmp_path) == []


def test_mapping_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: live\n")
    assert any("docker-compose.yml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_list_live_interpolation_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      - MAIRUI_MODE=${MAIRUI_MODE:-live}\n")
    assert any("docker-compose.yml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_dev_ingest_is_required_and_replay(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.dev.yml", "services:\n  api:\n    environment: {}\n")
    errors = cmd.check(tmp_path)
    assert any("docker-compose.dev.yml:ingest/MAIRUI_MODE" in error for error in errors)
    write(tmp_path, "deploy/compose/docker-compose.dev.yml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: ${MAIRUI_MODE:-replay}\n")
    assert any("docker-compose.dev.yml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_source_live_interpolation_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      DAILY_BARS_SOURCE: ${DAILY_BARS_SOURCE:-mairui}\n")
    errors = cmd.check(tmp_path)
    assert any("DAILY_BARS_SOURCE" in error for error in errors)


def test_env_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=live\n")
    errors = cmd.check(tmp_path)
    assert any(".env.example:MAIRUI_MODE" in error for error in errors)


def test_config_mairui_default_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "src/backend/app/config.py", 'daily_bars_source: Literal["off", "mairui"] = "mairui"\n')
    assert any("config.py:daily_bars_source" in error for error in cmd.check(tmp_path))

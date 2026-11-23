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
    write(
        repo,
        ".github/workflows/ci.yml",
        """env:
  MAIRUI_MODE: replay
  DAILY_BARS_SOURCE: off
jobs:
  backend:
    env:
      MAIRUI_MODE: ${MAIRUI_MODE:-replay}
    steps:
      - run: echo test
        env:
          DAILY_BARS_SOURCE: ${DAILY_BARS_SOURCE:-off}
""",
    )
    write(
        repo,
        "src/backend/app/config.py",
        'from typing import Literal\n\nclass Settings:\n    daily_bars_source: Literal["off", "fake"] = "off"\n',
    )


def test_minimal_baseline_is_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    assert cmd.check(tmp_path) == []


def test_mapping_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: live\n")
    assert any("docker-compose.yml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_mixed_case_spaced_keys_are_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  ingest:\n    environment:\n      ' mairui_mode': live\n")
    assert any("docker-compose.yml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))
    write(tmp_path, ".github/workflows/ci.yml", "env:\n  ' Daily_Bars_Source ': mairui\n")
    assert any(".github/workflows/ci.yml:env/DAILY_BARS_SOURCE" in error for error in cmd.check(tmp_path))


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


def test_env_get_normalization_and_last_value(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        "deploy/env/.env.example",
        'MAIRUI_MODE="replay"\nMAIRUI_MODE= replay\n',
    )
    assert cmd.check(tmp_path) == []
    write(
        tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=replay\nMAIRUI_MODE = live\n"
    )
    assert any(".env.example:MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_env_any_unsafe_line_or_interpolation_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=live\nMAIRUI_MODE=replay\n")
    assert any(".env.example:MAIRUI_MODE" in error for error in cmd.check(tmp_path))
    write(tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=${MAIRUI_MODE:-replay}\n")
    assert any(".env.example:MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_env_comments_and_inline_comment_cannot_hide_live(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=live # replay\n")
    assert any(".env.example:MAIRUI_MODE" in error for error in cmd.check(tmp_path))
    write(
        tmp_path, "deploy/env/.env.example", "# MAIRUI_MODE=replay\nMAIRUI_MODE=live\n"
    )
    assert any(".env.example:MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_workflow_comment_decoy_does_not_hide_live(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        "# MAIRUI_MODE: replay\nenv:\n  MAIRUI_MODE: live\n",
    )
    assert any(
        ".github/workflows/ci.yml:env/MAIRUI_MODE" in error
        for error in cmd.check(tmp_path)
    )


def test_workflow_mode_aliases_are_rejected_at_each_scope(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        """env:
  ' mairui_mode ': "live"
jobs:
  backend:
    env:
      mairui_mode: live
    steps:
      - env:
          'MAIRUI_MODE ': live
""",
    )
    errors = cmd.check(tmp_path)
    assert sum("MAIRUI_MODE" in error for error in errors) >= 3


def test_config_mairui_default_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        "src/backend/app/config.py",
        """from typing import Literal

class Settings:
    daily_bars_source: Literal["off", "mairui"] = "mairui"

# daily_bars_source: Literal["off", "mairui"] = "off"
DECOY = 'daily_bars_source: Literal["off", "mairui"] = "off"'
""",
    )
    assert any("config.py:daily_bars_source" in error for error in cmd.check(tmp_path))


def test_new_switch_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n      MAIRUI_QUOTES_ENABLED: true\n")
    errors = cmd.check(tmp_path)
    assert any("services/api/MAIRUI_QUOTES_ENABLED：默认必须关闭" in error for error in errors)


def test_new_switch_off_is_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n      MAIRUI_QUOTES_ENABLED: ${MAIRUI_QUOTES_ENABLED:-off}\n      INTRADAY_QUOTES_ENABLED: false\n      PRICES_SOURCE: replay\n")
    assert cmd.check(tmp_path) == []


def test_non_switch_mairui_key_is_exempt(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n      MAIRUI_QUOTES_URL: https://example.invalid\n      MAIRUI_QUOTES_TIMEOUT_S: 30\n      MAIRUI_QUOTES_TOKEN_FILE: /run/secrets/token\n")
    assert cmd.check(tmp_path) == []


def test_env_example_open_switch_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/env/.env.example", "MAIRUI_MODE=replay\nDAILY_BARS_SOURCE=off\nMAIRUI_QUOTES_ENABLED=true\n")
    assert any(".env.example:MAIRUI_QUOTES_ENABLED：默认必须关闭" in error for error in cmd.check(tmp_path))


def test_inherited_switch_values_are_rejected(tmp_path: Path) -> None:
    # 空值、无等号列表项、裸 $VAR、无默认值 ${VAR} 都会继承主机环境。
    for env in (
        "      MAIRUI_QUOTES_ENABLED:\n",
        "      MAIRUI_QUOTES_ENABLED: $MAIRUI_QUOTES_ENABLED\n",
        "      MAIRUI_QUOTES_ENABLED: ${MAIRUI_QUOTES_ENABLED}\n",
        "      MAIRUI_QUOTES_ENABLED: ${MAIRUI_QUOTES_ENABLED:-true}\n",
    ):
        baseline(tmp_path)
        write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n" + env)
        errors = cmd.check(tmp_path)
        assert any("services/api/MAIRUI_QUOTES_ENABLED：默认必须关闭" in error for error in errors), env
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n      - INTRADAY_QUOTES_ENABLED\n")
    errors = cmd.check(tmp_path)
    assert any("services/api/INTRADAY_QUOTES_ENABLED：默认必须关闭" in error for error in errors)


def test_empty_fallback_interpolation_is_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/docker-compose.yml", "services:\n  api:\n    environment:\n      MAIRUI_QUOTES_ENABLED: ${MAIRUI_QUOTES_ENABLED:-}\n")
    assert cmd.check(tmp_path) == []


def test_workflow_job_mode_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        "jobs:\n  backend:\n    env:\n      MAIRUI_MODE: live\n",
    )
    assert any(".github/workflows/ci.yml:jobs/backend/env/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_workflow_step_source_mairui_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        "jobs:\n  backend:\n    steps:\n      - env:\n          DAILY_BARS_SOURCE: mairui\n",
    )
    assert any(
        ".github/workflows/ci.yml:jobs/backend/steps[0]/env/DAILY_BARS_SOURCE" in error
        for error in cmd.check(tmp_path)
    )


def test_workflow_top_level_mode_live_is_rejected(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, ".github/workflows/ci.yml", "env:\n  MAIRUI_MODE: live\n")
    assert any(".github/workflows/ci.yml:env/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_workflow_yaml_suffix_is_checked(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, ".github/workflows/extra.yaml", "env:\n  MAIRUI_MODE: live\n")
    assert any(".github/workflows/extra.yaml:env/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_compose_yaml_suffix_is_checked(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(tmp_path, "deploy/compose/extra.yaml", "services:\n  ingest:\n    environment:\n      MAIRUI_MODE: live\n")
    assert any("extra.yaml:ingest/MAIRUI_MODE" in error for error in cmd.check(tmp_path))


def test_workflow_unquoted_allowed_values_are_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        ".github/workflows/ci.yml",
        """env:
  MAIRUI_MODE: replay
  DAILY_BARS_SOURCE: off
""",
    )
    assert cmd.check(tmp_path) == []


def test_config_field_default_with_single_quotes_is_accepted(tmp_path: Path) -> None:
    baseline(tmp_path)
    write(
        tmp_path,
        "src/backend/app/config.py",
        """from typing import Literal
from pydantic import Field

class Settings:
    daily_bars_source: Literal['off', 'mairui'] = Field(default='off')
""",
    )
    assert cmd.check(tmp_path) == []

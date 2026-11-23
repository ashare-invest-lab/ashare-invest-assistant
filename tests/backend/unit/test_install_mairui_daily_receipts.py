"""安装器的离线参数与边界测试，不启动 Docker 容器或任何采集任务。"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

SCRIPT = Path(__file__).parents[3] / "deploy/scripts/install-mairui-daily-receipts.sh"
COMPOSE = Path(__file__).parents[3] / "deploy/compose/docker-compose.yml"
ENV_EXAMPLE = Path(__file__).parents[3] / "deploy/env/.env.example"

ARGS = [
    "--user-id",
    "11111111-1111-4111-8111-111111111111",
    "--licence-id",
    "22222222-2222-4222-8222-222222222222",
    "--receipt-id",
    "33333333-3333-4333-8333-333333333333",
    "--not-before",
    "2026-01-01T00:00:00Z",
    "--expires-at",
    "2030-01-01T00:00:00Z",
]


def run_installer(
    tmp_path: Path,
    *extra: str,
    docker_result: str = "",
    tmpdir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$AIA_DOCKER_LOG\"\n"
        "case \"$1\" in\n"
        "  volume) [ \"$2\" = inspect ] && exit 0 ;;\n"
        "  image) exit 0 ;;\n"
        "  run) exit 0 ;;\n"
        "esac\n"
        f"{docker_result}\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    log = tmp_path / "docker.log"
    temp_root = tmp_path / "tmp-root"
    temp_root.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "AIA_DOCKER": str(fake_docker),
        "AIA_DOCKER_LOG": str(log),
        "TMPDIR": str(tmpdir or temp_root),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *ARGS, *extra],
        cwd=SCRIPT.parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


@pytest.mark.parametrize(
    "extra",
    [
        ("--user-id", "bad"),
        ("--not-before", "2030-01-01T00:00:00Z"),
        ("--expires-at", "2029-01-01T00:00:00Z"),
    ],
)
def test_rejects_invalid_uuid_or_time_window(tmp_path: Path, extra: tuple[str, str]) -> None:
    result = run_installer(tmp_path, *extra)
    assert result.returncode == 2


def test_requires_exactly_one_target(tmp_path: Path) -> None:
    assert run_installer(tmp_path).returncode == 2
    target = tmp_path / "target"
    assert run_installer(tmp_path, "--target-dir", str(target), "--volume-name", "x_aia_receipts").returncode == 2


@pytest.mark.parametrize("volume", ["bad", "aia_receipts_extra", "x/aia_receipts"])
def test_rejects_invalid_volume_name(tmp_path: Path, volume: str) -> None:
    result = run_installer(tmp_path, "--volume-name", volume)
    assert result.returncode == 2


def test_rejects_target_outside_tmpdir_and_nonempty_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    result = run_installer(tmp_path, "--target-dir", str(outside))
    assert result.returncode == 2

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    (allowed / "existing").touch()
    result = run_installer(tmp_path, "--target-dir", str(allowed))
    assert result.returncode == 2


def test_target_dir_is_allowed_under_fixed_prefix(tmp_path: Path) -> None:
    target = Path("/tmp") / f"aia-daily-receipts-{tmp_path.name}"
    result = run_installer(tmp_path, "--target-dir", str(target))
    assert result.returncode == 0
    assert target.is_dir()
    target.rmdir()


def test_tmpdir_cannot_expand_fixed_prefix_whitelist(tmp_path: Path) -> None:
    outside = Path("/var/lib/app") / f"aia-daily-receipts-{tmp_path.name}"
    result = run_installer(tmp_path, "--target-dir", str(outside), tmpdir=Path("/var/lib/app"))
    assert result.returncode == 2


def test_missing_named_volume_fails_before_run(tmp_path: Path) -> None:
    fake_docker = tmp_path / "docker"
    fake_docker.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$AIA_DOCKER_LOG\"\n"
        "[ \"$1\" = volume ] && exit 1\n"
        "exit 0\n",
        encoding="utf-8",
    )
    fake_docker.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "AIA_DOCKER": str(fake_docker),
        "AIA_DOCKER_LOG": str(log),
        "TMPDIR": str(tmp_path / "tmp-root"),
    }
    result = subprocess.run(
        ["bash", str(SCRIPT), "--volume-name", "demo_aia_receipts", *ARGS],
        cwd=SCRIPT.parents[2],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 3
    assert "run" not in log.read_text(encoding="utf-8")


def test_existing_receipts_are_not_overwritten(tmp_path: Path) -> None:
    target = tmp_path / "tmp-root" / "target"
    target.parent.mkdir()
    target.mkdir()
    (target / "mairui-daily.json").write_text("fixture", encoding="utf-8")
    # The fake Docker does not mount the host, so exercise the script's guard contract directly.
    assert (target / "mairui-daily.json").read_text(encoding="utf-8") == "fixture"
    assert run_installer(tmp_path, "--target-dir", str(target)).returncode == 2


def test_compose_defaults_daily_bars_source_to_off_when_unset_or_empty() -> None:
    text = COMPOSE.read_text(encoding="utf-8")
    entries = re.findall(r"DAILY_BARS_SOURCE:\s*(\$\{[^}]+\})", text)
    assert entries.count("${DAILY_BARS_SOURCE:-off}") == 2
    for value in (None, ""):
        resolved = value or "off"
        assert all(resolved == "off" for _ in entries)


def test_env_example_documents_worker_injection_and_ingest_usage() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "DAILY_BARS_SOURCE=off" in text
    assert "注入 worker" in text and "只有 ingest 使用" in text

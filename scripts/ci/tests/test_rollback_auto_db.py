"""T-O137：rollback 自动库名必须满足共享库名校验。"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/wrapup/rollback.sh"
LIB = SCRIPT.parent / "lib.sh"

FAKE_DOCKER = r"""#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$*" >>"${FAKE_DOCKER_LOG:?}"
cmd="$1"
shift
case "$cmd" in
  info) exit 0 ;;
  cp) exit 0 ;;
  exec)
    while [ "$#" -gt 0 ]; do
      case "$1" in
        -e) shift 2 ;;
        *) break ;;
      esac
    done
    [ "$#" -ge 2 ] || exit 90
    shift
    sub="$1"
    shift
    case "$sub" in
      sh) exit 0 ;; # wrapup_pg_port probe
      psql)
        if [[ "$*" == *"CREATE DATABASE"* ]] && [[ "$*" =~ aia_rollback_[0-9]{8}T[0-9]{6} ]]; then
          echo "uppercase T rejected by fixture" >&2
          exit 91
        fi
        exit 0
        ;;
      pg_restore|rm) exit 0 ;;
      *) exit 90 ;;
    esac
    ;;
  *) exit 90 ;;
esac
"""


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "ci",
        "GIT_AUTHOR_EMAIL": "ci@example.invalid",
        "GIT_COMMITTER_NAME": "ci",
        "GIT_COMMITTER_EMAIL": "ci@example.invalid",
    }
    return subprocess.run(
        ["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True
    )


def _run(
    tmp_path: Path, *, mutate: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "README").write_text("fixture\n", encoding="utf-8")
    _git(repo, "add", "README")
    _git(repo, "commit", "-q", "-m", "fixture")
    old_head = _git(repo, "rev-parse", "HEAD").stdout.strip()
    wrapup = repo / "deploy/scripts/wrapup"
    wrapup.mkdir(parents=True)
    script = wrapup / "rollback.sh"
    text = SCRIPT.read_text(encoding="utf-8")
    if mutate:
        text = text.replace("+%Y%m%dt%H%M%S", "+%Y%m%dT%H%M%S", 1)
        assert text != SCRIPT.read_text(encoding="utf-8")
    script.write_text(text, encoding="utf-8")
    script.chmod(0o755)
    shutil.copy(LIB, wrapup / "lib.sh")

    backup = tmp_path / "backup" / "20260101T000000Z"
    backup.mkdir(parents=True)
    (backup / "manifest.json").write_text("{}\n", encoding="utf-8")
    (backup / "fixture.dump").write_bytes(b"dump")
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(FAKE_DOCKER, encoding="utf-8")
    docker.chmod(0o755)
    log = tmp_path / "docker.log"
    env = {
        "PATH": str(bindir) + os.pathsep + os.environ["PATH"],
        "HOME": str(tmp_path),
        "FAKE_DOCKER_LOG": str(log),
    }
    result = subprocess.run(
        [
            "bash",
            str(script),
            "--apply",
            "--backup-dir",
            str(backup),
            "--container",
            "fakepg",
            "--rollback-head",
            old_head,
        ],
        cwd=repo,
        check=False,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result, log


def test_auto_rollback_db_name_uses_lowercase_timestamp_separator(
    tmp_path: Path,
) -> None:
    result, log = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    names = re.findall(
        r"aia_rollback_[0-9]{8}[tT][0-9]{6}", log.read_text(encoding="utf-8")
    )
    assert names
    assert all("T" not in name for name in names)


def test_uppercase_timestamp_mutation_is_rejected(tmp_path: Path) -> None:
    result, log = _run(tmp_path, mutate=True)
    assert result.returncode != 0
    assert "库名不合法" in result.stderr
    assert "aia_rollback_" in result.stderr
    assert not re.search(
        r"aia_rollback_[0-9]{8}[tT][0-9]{6}", log.read_text(encoding="utf-8")
    )

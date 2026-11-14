"""T-O80：deploy/scripts/sync-main-worktree.sh（同步最新 origin/main 到 .worktrees/<短哈希>）。

全部在临时 git 仓库 + wrapup 桩里跑，不碰用户电脑、不调 docker/麦蕊。
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "deploy/scripts/sync-main-worktree.sh"

STUB = r"""#!/usr/bin/env bash
set -euo pipefail
name="$(basename "$0")"
log="${CALL_LOG:?}"
printf '%s\t%s\n' "$name" "$*" >>"$log"
if [ "$name" = backup.sh ]; then
  dest="${FAKE_DEST:?}"
  mkdir -p "$dest"
  echo "$dest"
  exit 0
fi
if [ "$name" = start-stack.sh ] && [ "${START_FAIL:-0}" = 1 ]; then
  echo "stub start-stack failed" >&2
  exit 1
fi
if [ "$name" = halt-check.sh ] && [ "${HALT_FAIL:-0}" = 1 ]; then
  echo "stub halt-check failed" >&2
  exit 1
fi
exit 0
"""


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        env={
            "PATH": os.environ["PATH"],
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@t",
            "HOME": os.environ.get("HOME", "/tmp"),
        },
    )


def _init_tree(tmp_path: Path) -> tuple[Path, str]:
    bare = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    seed.mkdir()
    _git(seed, "init", "-b", "main")
    (seed / "README").write_text("seed\n", encoding="utf-8")
    wr = seed / "deploy/scripts/wrapup"
    wr.mkdir(parents=True)
    dest_script = seed / "deploy/scripts/sync-main-worktree.sh"
    dest_script.write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    dest_script.chmod(0o755)
    for name in ("backup.sh", "start-stack.sh", "rollback.sh", "halt-check.sh", "verify.sh"):
        sp = wr / name
        sp.write_text(STUB, encoding="utf-8")
        sp.chmod(0o755)
    _git(seed, "add", "README", "deploy")
    _git(seed, "commit", "-m", "seed")
    _git(seed, "clone", "--bare", str(seed), str(bare))
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", str(bare), str(repo))
    short = _git(repo, "rev-parse", "--short=7", "HEAD").stdout.strip()
    (tmp_path / "calls.log").write_text("", encoding="utf-8")
    return repo, short


def _env(repo: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "AIA_SYNC_ROOT": str(repo),
        "AIA_SYNC_WRAPUP_DIR": str(repo / "deploy/scripts/wrapup"),
        "CALL_LOG": str(tmp_path / "calls.log"),
        "FAKE_DEST": str(tmp_path / "backup" / "20260101T000000Z"),
        "START_FAIL": "0",
    }
    env.update(extra)
    return env


def _run(repo: Path, tmp_path: Path, *args: str, **extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(repo / "deploy/scripts/sync-main-worktree.sh"), *args],
        capture_output=True,
        text=True,
        env=_env(repo, tmp_path, **extra),
        timeout=30,
    )


def _calls(tmp_path: Path) -> list[str]:
    raw = (tmp_path / "calls.log").read_text(encoding="utf-8")
    return [ln for ln in raw.splitlines() if ln.strip()]


def test_first_statement_disables_xtrace() -> None:
    code = [
        ln
        for ln in SCRIPT.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    assert code[0] == "{ set +x; } 2>/dev/null"


def test_rejects_down_v_flag(tmp_path: Path) -> None:
    repo, _ = _init_tree(tmp_path)
    for flag in ("-v", "--volumes", "--down-v"):
        r = _run(repo, tmp_path, flag)
        assert r.returncode == 2, (flag, r.stderr)
        assert "禁止" in r.stderr and "down -v" in r.stderr
        assert not (repo / ".worktrees").exists()
    r = _run(repo, tmp_path, "--repair")
    assert r.returncode == 2 and "解 HALT" in r.stderr


def test_dry_run_does_not_fetch_or_create_worktree(tmp_path: Path) -> None:
    repo, short = _init_tree(tmp_path)
    before = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, tmp_path)
    assert r.returncode == 0, r.stderr
    assert "dry-run 结束" in r.stderr
    assert "未 fetch" in r.stderr
    assert not (repo / ".worktrees").exists()
    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == before
    calls = _calls(tmp_path)
    assert any(c.startswith("backup.sh\t") and "--apply" not in c.split("\t", 1)[1] for c in calls)
    assert any(c.startswith("start-stack.sh\t") and "--apply" not in c.split("\t", 1)[1] for c in calls)
    assert not any(c.startswith("rollback.sh") for c in calls)
    # 计划路径含短哈希
    assert f".worktrees/{short}" in r.stderr


def test_apply_creates_short_hash_worktree_and_calls_wrapup_in_order(tmp_path: Path) -> None:
    repo, short = _init_tree(tmp_path)
    r = _run(repo, tmp_path, "--apply")
    assert r.returncode == 0, r.stderr
    wt = repo / ".worktrees" / short
    assert wt.is_dir()
    assert _git(wt, "rev-parse", "HEAD").stdout.strip() == _git(repo, "rev-parse", "origin/main").stdout.strip()
    names = [c.split("\t", 1)[0] for c in _calls(tmp_path)]
    assert names == ["backup.sh", "start-stack.sh", "halt-check.sh", "verify.sh"]
    start = _calls(tmp_path)[1]
    assert "--apply" in start and "--backup-dir" in start
    assert "20260101T000000Z" in start
    # halt-check 不得带 --repair
    assert "--repair" not in _calls(tmp_path)[2]
    assert "不 down -v" in r.stderr or "不要 down -v" in r.stderr or "禁止 down -v" in SCRIPT.read_text(encoding="utf-8")


def test_start_failure_runs_rollback_with_dest(tmp_path: Path) -> None:
    repo, short = _init_tree(tmp_path)
    r = _run(repo, tmp_path, "--apply", START_FAIL="1")
    assert r.returncode != 0, r.stderr
    calls = _calls(tmp_path)
    names = [c.split("\t", 1)[0] for c in calls]
    assert names[0] == "backup.sh"
    assert names[1] == "start-stack.sh"
    assert "rollback.sh" in names
    rb = [c for c in calls if c.startswith("rollback.sh")][0]
    assert "--apply" in rb and "--backup-dir" in rb and "20260101T000000Z" in rb
    assert "halt-check.sh" not in names
    # 失败时工作树仍在，未删除
    assert (repo / ".worktrees" / short).is_dir()


def test_mutation_removing_rollback_is_caught(tmp_path: Path) -> None:
    """关键断言的变异验证：去掉失败后 rollback_once 调用，则 start 失败不会再跑 rollback.sh。"""
    repo, _ = _init_tree(tmp_path)
    src = repo / "deploy/scripts/sync-main-worktree.sh"
    text = src.read_text(encoding="utf-8")
    needle = "  rollback_once\n  die \"启动或校验失败，已尝试回滚。新工作树仍在 $WT，数据卷未删。\"\n"
    assert needle in text, "脚本应在失败路径调用 rollback_once"
    mutated = text.replace("  rollback_once\n", "  # mutated: rollback_once removed\n", 1)
    assert mutated != text
    src.write_text(mutated, encoding="utf-8")
    r = _run(repo, tmp_path, "--apply", START_FAIL="1")
    assert r.returncode != 0, r.stderr
    names = [c.split("\t", 1)[0] for c in _calls(tmp_path)]
    assert "start-stack.sh" in names
    assert "rollback.sh" not in names


def test_rollback_uses_original_head_and_drops_db(tmp_path: Path) -> None:
    """L3 审核采纳：回滚必须用同步前 HEAD；不得把源库 --db 传给 rollback.sh。"""
    repo, short = _init_tree(tmp_path)
    old = _git(repo, "rev-parse", "HEAD").stdout.strip()
    r = _run(repo, tmp_path, "--apply", "--db", "aia", "--volume-prefix", "aia", START_FAIL="1")
    assert r.returncode != 0, r.stderr
    rb = [c for c in _calls(tmp_path) if c.startswith("rollback.sh")]
    assert rb, r.stderr
    args = rb[0].split("\t", 1)[1]
    assert "--rollback-head" in args and old in args
    assert "--db" not in args.split()
    assert "--volume-prefix" in args and "aia" in args
    start = [c for c in _calls(tmp_path) if c.startswith("start-stack.sh")][0]
    assert "--db" in start and "aia" in start
    assert (repo / ".worktrees" / short).is_dir()


def test_reuse_existing_same_head_worktree(tmp_path: Path) -> None:
    repo, short = _init_tree(tmp_path)
    r1 = _run(repo, tmp_path, "--apply")
    assert r1.returncode == 0, r1.stderr
    (tmp_path / "calls.log").write_text("", encoding="utf-8")
    r2 = _run(repo, tmp_path, "--apply")
    assert r2.returncode == 0, r2.stderr
    assert "复用" in r2.stderr
    assert (repo / ".worktrees" / short).is_dir()


def test_halt_failure_also_runs_rollback(tmp_path: Path) -> None:
    """L3 审核保留：后续步骤失败同样只回滚一次，且不跑 verify。"""
    repo, short = _init_tree(tmp_path)
    r = _run(repo, tmp_path, "--apply", HALT_FAIL="1")
    assert r.returncode != 0, r.stderr
    names = [c.split("\t", 1)[0] for c in _calls(tmp_path)]
    assert names[:2] == ["backup.sh", "start-stack.sh"]
    assert "halt-check.sh" in names
    assert "verify.sh" not in names
    assert "rollback.sh" in names
    assert (repo / ".worktrees" / short).is_dir()

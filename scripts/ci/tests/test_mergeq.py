"""T-O115 merge queue rule mirrors and offline self-tests."""

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
MERGEQ = REPO / "deploy/mergeq/mergeq.sh"
STALL = REPO / "deploy/mergeq/mergeq-stall.sh"


def require_tools() -> None:
    missing = [name for name in ("flock", "timeout", "jq") if shutil.which(name) is None]
    if missing:
        pytest.fail("CI 必需工具缺失: " + ", ".join(missing))


def make_gh(path: Path, mode: str = "empty") -> None:
    path.write_text(f'''#!/bin/bash
mode="${{FAKE_GH_MODE:-{mode}}}"
fail_on="${{FAKE_GH_FAIL_ON:-}}"
hang_on="${{FAKE_GH_HANG_ON:-}}"
if {{ [ "$mode" = fail ] || [ -n "$fail_on" ]; }} && {{ [ -z "$fail_on" ] || [[ "$*" == *"$fail_on"* ]]; }}; then echo boom >&2; exit 7; fi
if [ "$mode" = hang ] || {{ [ -n "$hang_on" ] && [[ "$*" == *"$hang_on"* ]]; }}; then sleep "${{FAKE_GH_SLEEP:-5}}"; exit 0; fi
case "$*" in
  *"api repos/"*) printf 'abcdef0123456789abcdef0123456789abcdef01\\n' ;;
  *"run list"*) printf 'abcdef0123456789abcdef0123456789abcdef01 completed success\\n' ;;
  *"pr list"*) printf '%s\\n' "${{FAKE_PR_LIST:-[]}}" ;;
  *"pr view 12"*) if [ "${{FAKE_FILES:-sensitive}}" = sensitive ]; then printf '%s\\n' '{{"baseRefName":"main","isDraft":false,"mergeable":"MERGEABLE","statusCheckRollup":[{{"name":"ci","conclusion":"SUCCESS"}}],"files":[{{"path":"deploy/env/.env"}}],"headRefName":"x"}}'; else printf '%s\\n' '{{"baseRefName":"main","isDraft":false,"mergeable":"MERGEABLE","statusCheckRollup":[{{"name":"ci","conclusion":"SUCCESS"}}],"files":[{{"path":"src/a.py"}}],"headRefName":"x"}}'; fi ;;
  *) printf '{{}}\\n' ;;
esac
''', encoding="utf-8")
    path.chmod(0o755)


def run(cmd, env, timeout=30):
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout, check=False)


def test_timeout_and_heartbeat_and_flock(tmp_path: Path) -> None:
    require_tools()
    bindir, rt = tmp_path / "bin", tmp_path / "runtime"
    bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_MODE": "hang", "FAKE_GH_SLEEP": "5"}
    first = subprocess.Popen(["bash", str(MERGEQ)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    time.sleep(0.2)
    second = run(["bash", str(MERGEQ)], env, 30)
    first.communicate(timeout=30)
    assert second.returncode == 0
    log = (rt / "mergeq.log").read_text()
    assert "已有实例，退出" in log and "GH-TIMEOUT" in log
    assert "阶段=sleep" in (rt / "mergeq.heartbeat").read_text()


def test_stall_process_info(tmp_path: Path) -> None:
    require_tools()
    bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "1", "MQ_ONCE": "1", "FAKE_GH_MODE": "hang", "FAKE_GH_SLEEP": "20"}
    stuck = subprocess.Popen(["bash", str(MERGEQ)], env=env)
    time.sleep(0.3)
    old = int(time.time()) - 660
    (rt / "mergeq.heartbeat").write_text(f"old pid={stuck.pid} 阶段=检查 PR #9 说明=测试 开始于={old}\n")
    os.utime(rt / "mergeq.heartbeat", (time.time() - 660, time.time() - 660))
    stall_env = {**env, "FAKE_GH_MODE": "empty"}
    result = run(["bash", str(STALL)], stall_env)
    stuck.kill(); stuck.wait(timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "MERGEQ-HEARTBEAT" in result.stdout and "MERGEQ-CHILD" in result.stdout


def test_flock_second_instance(tmp_path: Path) -> None:
    require_tools()
    bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_MODE": "hang", "FAKE_GH_SLEEP": "5"}
    first = subprocess.Popen(["bash", str(MERGEQ)], env=env)
    time.sleep(0.2)
    second = run(["bash", str(MERGEQ)], env)
    first.kill(); first.wait(timeout=30)
    assert second.returncode == 0
    assert "已有实例，退出" in (rt / "mergeq.log").read_text()


def test_sensitive_path(tmp_path: Path) -> None:
    require_tools(); app, bindir, rt = tmp_path / "app", tmp_path / "bin", tmp_path / "runtime"; app.mkdir(); bindir.mkdir(); rt.mkdir()
    shutil.copy2(MERGEQ, app / "mergeq.sh"); (app / "merge-approved.sh").write_text("#!/bin/bash\nexit 1\n"); (app / "merge-approved.sh").chmod(0o755); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_PR_LIST": "12", "FAKE_FILES": "sensitive"}
    result = run(["bash", str(app / "mergeq.sh")], env); assert result.returncode == 0
    assert "#12 敏感路径，跳过待人工" in (rt / "mergeq.log").read_text()


def test_non_sensitive_gate_reject(tmp_path: Path) -> None:
    require_tools(); app, bindir, rt = tmp_path / "app", tmp_path / "bin", tmp_path / "runtime"; app.mkdir(); bindir.mkdir(); rt.mkdir()
    shutil.copy2(MERGEQ, app / "mergeq.sh"); (app / "merge-approved.sh").write_text("#!/bin/bash\nexit 1\n"); (app / "merge-approved.sh").chmod(0o755); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_PR_LIST": "12", "FAKE_FILES": "normal"}
    result = run(["bash", str(app / "mergeq.sh")], env); assert result.returncode == 0
    log = (rt / "mergeq.log").read_text(); assert "敏感路径" not in log and "#12 合并门禁拒绝" in log and "GH-FAIL" not in log


def test_sensitive_regex_matches_rule(tmp_path: Path) -> None:
    line = next(line for line in MERGEQ.read_text().splitlines() if line.startswith("BAD="))
    assert "\\\\." not in line


def test_nonzero_main_failure_is_not_fake_wait(tmp_path: Path) -> None:
    require_tools(); bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_MODE": "fail"}
    result = run(["bash", str(MERGEQ)], env)
    assert result.returncode == 0
    log = (rt / "mergeq.log").read_text(); heartbeat = (rt / "mergeq.heartbeat").read_text()
    assert "GH-FAIL 取 main rc=7" in log and "等 main CI" not in log
    assert "GH-FAIL" in heartbeat


def test_pr_list_failure_is_logged(tmp_path: Path) -> None:
    require_tools(); bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_FAIL_ON": "pr list"}
    result = run(["bash", str(MERGEQ)], env)
    assert result.returncode == 0
    assert "GH-FAIL 列 PR rc=7" in (rt / "mergeq.log").read_text()


def test_pr_view_failure_aborts_before_gate(tmp_path: Path) -> None:
    require_tools(); app, bindir, rt = tmp_path / "app", tmp_path / "bin", tmp_path / "runtime"; app.mkdir(); bindir.mkdir(); rt.mkdir()
    shutil.copy2(MERGEQ, app / "mergeq.sh")
    marker = rt / "gate-called"
    (app / "merge-approved.sh").write_text(f"#!/bin/bash\nprintf x > {marker}\nexit 0\n"); (app / "merge-approved.sh").chmod(0o755); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_PR_LIST": "12", "FAKE_FILES": "normal", "FAKE_GH_FAIL_ON": "pr view 12"}
    result = run(["bash", str(app / "mergeq.sh")], env)
    assert result.returncode == 0
    assert "GH-FAIL 检查 PR #12" in (rt / "mergeq.log").read_text() and not marker.exists()


def test_gate_exit_two_aborts_without_rejection(tmp_path: Path) -> None:
    require_tools(); app, bindir, rt = tmp_path / "app", tmp_path / "bin", tmp_path / "runtime"; app.mkdir(); bindir.mkdir(); rt.mkdir()
    shutil.copy2(MERGEQ, app / "mergeq.sh"); (app / "merge-approved.sh").write_text("#!/bin/bash\nexit 2\n"); (app / "merge-approved.sh").chmod(0o755); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_PR_LIST": "12", "FAKE_FILES": "normal"}
    result = run(["bash", str(app / "mergeq.sh")], env)
    assert result.returncode == 0
    log = (rt / "mergeq.log").read_text(); assert "GH-FAIL" in log and "合并门禁拒绝" not in log


def test_run_list_timeout_is_logged(tmp_path: Path) -> None:
    require_tools(); bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_HANG_ON": "run list", "FAKE_GH_SLEEP": "5"}
    result = run(["bash", str(MERGEQ)], env)
    assert result.returncode == 0 and "GH-TIMEOUT 取 run" in (rt / "mergeq.log").read_text()


def test_pr_view_timeout_is_logged(tmp_path: Path) -> None:
    require_tools(); bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_PR_LIST": "12", "FAKE_FILES": "normal", "FAKE_GH_HANG_ON": "pr view 12", "FAKE_GH_SLEEP": "5"}
    result = run(["bash", str(MERGEQ)], env)
    assert result.returncode == 0 and "GH-TIMEOUT 检查 PR #12" in (rt / "mergeq.log").read_text()


def test_stall_failure_and_inode_warning(tmp_path: Path) -> None:
    require_tools(); bindir, rt = tmp_path / "bin", tmp_path / "runtime"; bindir.mkdir(); rt.mkdir(); make_gh(bindir / "gh")
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "GH_REPO": "test/example", "MQ_RT": str(rt), "MQ_GH_TIMEOUT": "1", "MQ_SLEEP": "0", "MQ_ONCE": "1", "FAKE_GH_MODE": "fail"}
    first = run(["bash", str(MERGEQ)], env); assert first.returncode == 0
    result = run(["bash", str(STALL)], {**env, "MQ_INODE_WARN": "-1"})
    assert result.returncode == 0
    assert "MERGEQ-GH-FAIL" in result.stdout and "BOX-INODE-HIGH" in result.stdout

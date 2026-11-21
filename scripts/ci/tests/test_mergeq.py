"""T-O115 merge queue rule mirrors and offline self-tests."""

import os
import re
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
if [ "${{FAKE_GH_MODE:-{mode}}}" = hang ]; then sleep "${{FAKE_GH_SLEEP:-5}}"; exit 0; fi
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
    return subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)


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
    log = (rt / "mergeq.log").read_text(); assert "敏感路径" not in log and "#12 合并门禁拒绝" in log


def test_sensitive_regex_matches_rule(tmp_path: Path) -> None:
    line = next(line for line in MERGEQ.read_text().splitlines() if line.startswith("BAD="))
    assert "\\\\." not in line

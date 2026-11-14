"""Offline restart guard checks; marker commands never operate a real stack."""

import os
from pathlib import Path
import re
import shutil
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[3]
PS_SCRIPT = REPO / "deploy/scripts/restart-guard.ps1"
POWERSHELL = shutil.which("pwsh") or shutil.which("powershell")


def test_restart_guard_bash() -> None:
    script = Path(__file__).with_suffix(".sh")
    result = subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "restart guard selftest: 9 passed" in result.stdout


def test_restart_guard_powershell_syntax() -> None:
    raw = PS_SCRIPT.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf"), "Windows PowerShell 5.1 needs BOM for Chinese source"
    source = raw.decode("utf-8-sig")
    assert source.startswith("#Requires -Version 5.1\n")
    if POWERSHELL:
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-Command",
             "$tokens=$null; $errors=$null; "
             "[void][System.Management.Automation.Language.Parser]::ParseFile("
             "$env:GUARD_PS_SOURCE,[ref]$tokens,[ref]$errors); "
             "if ($errors.Count) { $errors; exit 1 }"],
            env={**os.environ, "GUARD_PS_SOURCE": str(PS_SCRIPT)},
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return

    # Limited offline syntax check, not a substitute for the PowerShell parser:
    # tokenize comments/strings, then check delimiter balance and PS7-only tokens.
    tokens = re.findall(
        r"#[^\n]*|'(?:''|[^'])*'|\"(?:`[\s\S]|[^`\"])*\"|[()\[\]{}]|[^\s'\"()\[\]{}#]+|['\"]",
        source,
    )
    pairs = {"(": ")", "[": "]", "{": "}"}
    stack = []
    code = []
    for token in tokens:
        if token.startswith("#"):
            continue
        assert token not in ("'", '"'), "Unterminated PowerShell string"
        if token.startswith(("'", '"')):
            continue
        code.append(token)
        if token in pairs:
            stack.append(pairs[token])
        elif token in pairs.values():
            assert stack and stack.pop() == token, "Unbalanced PowerShell delimiter"
    assert not stack, "Unclosed PowerShell delimiter"
    assert not any(op in " ".join(code) for op in ("??", "?.", "&&", "||"))


@pytest.mark.skipif(not POWERSHELL, reason="No pwsh/powershell; static syntax check only")
def test_restart_guard_powershell_runtime(tmp_path: Path) -> None:
    lock_dir = tmp_path / "runtime with spaces"
    lock_dir.mkdir()
    marker = tmp_path / "marker"
    env = {**os.environ, "AIA_RUNTIME_LOCK_DIR": str(lock_dir), "GUARD_TEST_MARKER": str(marker)}
    then = "Set-Content -LiteralPath $env:GUARD_TEST_MARKER -Value executed"

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [POWERSHELL, "-NoProfile", "-NonInteractive", "-File", str(PS_SCRIPT), *args],
            capture_output=True, text=True, env=env, timeout=30,
        )

    result = run("-Then", then)
    assert result.returncode == 0 and marker.exists(), result.stdout + result.stderr
    assert "无回填锁，可以重启" in result.stdout
    marker.unlink()
    (lock_dir / "mairui-backfill.lock").write_text("T-B84\nDO_NOT_PRINT\n", encoding="utf-8")
    for name, metadata in (("owner.lock", "owner"), ("info.lock", "info"), ("empty.lock", None)):
        directory = lock_dir / name
        directory.mkdir()
        if metadata:
            (directory / metadata).write_text(f"T-{metadata}\nDO_NOT_PRINT\n", encoding="utf-8")
    (lock_dir / "unrelated.txt").write_text("DO_NOT_PRINT", encoding="utf-8")
    result = run("-Then", then)
    assert result.returncode == 3 and not marker.exists(), result.stdout + result.stderr
    for expected in ("mairui-backfill.lock | 持锁任务：T-B84", "owner.lock | 持锁任务：T-owner",
                     "info.lock | 持锁任务：T-info", "empty.lock | 持锁任务：未知", "修改时间："):
        assert expected in result.stdout
    assert "DO_NOT_PRINT" not in result.stdout + result.stderr
    clear = tmp_path / "clear"
    clear.mkdir()
    result = run("-LockDir", str(clear), "-Then", then)
    assert result.returncode == 0 and marker.exists(), result.stdout + result.stderr
    marker.unlink()
    result = run("-LockDir", str(tmp_path / "missing"), "-Then", then)
    assert result.returncode == 0 and marker.exists(), result.stdout + result.stderr
    assert "锁目录不存在" in result.stdout and "无回填锁，可以重启" in result.stdout
    result = run("-LockDir", str(clear), "-Then", "exit 17")
    assert result.returncode == 17, result.stdout + result.stderr

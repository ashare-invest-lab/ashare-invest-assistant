"""T-R31/T-R77：F21 阈值锁定、篡改/覆盖拒绝及无库 CLI（离线，无凭证）。"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def fail(msg: object = "") -> None:
    """Explicit failure that survives python -O (unlike assert)."""
    raise AssertionError(msg)


def require(cond: object, msg: object = "") -> None:
    if not cond:
        fail(msg)

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
import check_f21_ready as m  # noqa: E402


def test_load_ok():
    th = m.load_locked_thresholds()
    require(th["min_stocks"] == 5 and th["min_days"] == 15 and th["window_days"] == 20)
    require(th["factor_id"] == "main_20d_net")
    require(th["feature_key"] == "f.main_net_20d")


def test_hash_tamper_rejected():
    raw = json.loads(m.THRESHOLDS_PATH.read_text())
    raw["min_stocks"] = 1  # tamper
    # Point loader at temp copies
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        p = td / "f21_ready_thresholds.json"
        h = td / "f21_ready_thresholds.sha256"
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=2))
        # keep ORIGINAL hash → mismatch
        h.write_text(m.THRESHOLDS_HASH_PATH.read_text())
        old_p, old_h = m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH
        m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH = p, h
        try:
            try:
                m.load_locked_thresholds()
            except SystemExit as e:
                require("hash mismatch" in str(e))
            else:
                raise AssertionError("tampered thresholds accepted")
        finally:
            m.THRESHOLDS_PATH, m.THRESHOLDS_HASH_PATH = old_p, old_h


def test_cli_override_rejected():
    for flag in ("--min-stocks", "--min-days", "--window-days", "--factor-id", "--thresholds"):
        try:
            m.reject_override_attempts([flag, "1"])
        except SystemExit as e:
            require("rejected" in str(e), flag)
        else:
            raise AssertionError(flag)


def test_env_override_rejected():
    k = "F21_READY_MIN_STOCKS"
    old = os.environ.get(k)
    os.environ[k] = "1"
    try:
        try:
            m.reject_override_attempts([])
        except SystemExit as e:
            require(k in str(e))
        else:
            raise AssertionError("env override accepted")
    finally:
        if old is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = old


def test_decide_ready_boundary():
    th = m.load_locked_thresholds()
    require(m.decide_ready({"stocks_with_min_days": 5}, th) is True)
    require(m.decide_ready({"stocks_with_min_days": 4}, th) is False)


def run_no_db(*args, script=None, env_overrides=None):
    # Exclude the DB setting without reading its value; never connect in these cases.
    env = {
        key: os.environ[key] for key in os.environ
        if key != "DATABASE_URL" and key not in m.FORBIDDEN_ENV
    }
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env.update(env_overrides or {})
    return subprocess.run(
        [sys.executable, *(["-O"] if sys.flags.optimize else []),
         str(script or Path(m.__file__)), *args],
        env=env, capture_output=True, text=True, timeout=10,
    )


def test_no_db_cli():
    result = run_no_db()
    require(result.returncode == 0, result.stderr)
    report = json.loads(result.stdout)
    require(report["status"] == "skipped_no_db", report)
    require(report["f21_status"] == "declared", report)
    require("ready" in report and report["ready"] is None, report)
    require(report["message"] == "未做实库扫描，结论未验证", report)
    require("signal" not in report and "suggested_dispatch" not in report, report)

    result = run_no_db("--require-db")
    require(result.returncode == 1, result)
    require(result.stdout == "", result.stdout)
    require(result.stderr.strip() ==
            "DATABASE_URL 未设置；本脚本只读、不写，但需要目标库（通常是隔离库）。",
            result.stderr)


def test_no_db_overrides_rejected():
    for flag in ("--min-stocks", "--min-days", "--window-days", "--factor-id",
                 "--thresholds", "--thresholds-json"):
        result = run_no_db(flag + "=1")
        require(result.returncode != 0, flag)
        require("threshold override rejected" in result.stderr, result.stderr)
        require(result.stdout == "", result.stdout)
    for key in m.FORBIDDEN_ENV:
        result = run_no_db(env_overrides={key: "1"})
        require(result.returncode != 0, key)
        require("threshold override rejected via env: " + key in result.stderr,
                result.stderr)
        require(result.stdout == "", result.stdout)


def test_no_db_hash_tamper_rejected():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        script = root / "check_f21_ready.py"
        shutil.copyfile(m.__file__, script)
        thresholds = root / "T-R28"
        thresholds.mkdir()
        shutil.copyfile(m.THRESHOLDS_PATH, thresholds / m.THRESHOLDS_PATH.name)
        (thresholds / m.THRESHOLDS_HASH_PATH.name).write_text("0" * 64 + "\n")
        result = run_no_db(script=script)
        require(result.returncode != 0, result)
        require("thresholds hash mismatch" in result.stderr, result.stderr)
        require(result.stdout == "", result.stdout)


def main() -> int:
    test_load_ok()
    test_hash_tamper_rejected()
    test_cli_override_rejected()
    test_env_override_rejected()
    test_decide_ready_boundary()
    test_no_db_cli()
    test_no_db_overrides_rejected()
    test_no_db_hash_tamper_rejected()
    print(json.dumps({
        "normal_threshold_load": "pass",
        "mutation_hash_rejected": 1,
        "mutation_cli_override_rejected": 5,
        "mutation_env_override_rejected": 1,
        "decide_ready_boundary": "5_pass_4_fail",
        "no_db_cli": "skipped_no_db_ready_null",
        "require_db_missing_rc": 1,
        "no_db_cli_overrides_rejected": 6,
        "no_db_env_overrides_rejected": len(m.FORBIDDEN_ENV),
        "no_db_hash_tamper_rejected": 1,
        "f21_status": "declared",
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Exact frontend-audit exception tests; all advisories and versions are synthetic."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
import yaml

import frontend_audit as gate

TODAY = date(2026, 11, 17)


def advisory(*, advisory_id=gate.ADVISORY_ID, name=gate.PACKAGE, version=gate.VERSION,
             path=gate.DEPENDENCY_PATH, severity="high"):
    return {
        "github_advisory_id": advisory_id,
        "module_name": name,
        "severity": severity,
        "vulnerable_versions": gate.EXPECTED_VULNERABLE_RANGE,
        "patched_versions": gate.NO_PATCH,
        "findings": [{"version": version, "paths": [path]}],
    }


def report(*items):
    counts = {key: 0 for key in ("info", "low", "moderate", "high", "critical")}
    advisories = {}
    for index, item in enumerate(items):
        advisories[str(index)] = item
        counts[item["severity"]] += 1
    return {"advisories": advisories, "metadata": {"vulnerabilities": counts}}


def run(tmp_path, data, mode="gate", audit_exit=1, latest=gate.VERSION, today=TODAY):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    args = [mode, "--report", str(path), "--audit-exit", str(audit_exit)]
    if mode == "watch":
        args += ["--latest-version", latest]
    return gate.main(args, today=today)


def test_only_exact_advisory_version_and_path_is_temporarily_allowed(tmp_path):
    assert run(tmp_path, report(advisory())) == 0


def test_another_high_still_fails(tmp_path):
    other = advisory(advisory_id="GHSA-other-0000-0001", name="other-package")
    assert run(tmp_path, report(advisory(), other)) == 1


@pytest.mark.parametrize("change", [
    {"version": "4.0.6"},
    {"path": ".>another>picomatch"},
])
def test_same_advisory_with_different_version_or_path_fails(tmp_path, change):
    item = advisory()
    if "path" in change:
        item["findings"][0]["paths"] = [change["path"]]
    else:
        item["findings"][0].update(change)
    assert run(tmp_path, report(item)) == 1


def test_one_unapproved_path_in_same_finding_still_fails(tmp_path):
    item = advisory()
    item["findings"][0]["paths"].append(".>another>picomatch")
    assert run(tmp_path, report(item)) == 1


def test_unparseable_other_high_cannot_disappear(tmp_path):
    another = advisory(advisory_id="GHSA-other-0000-0002", name="other-package")
    del another["findings"]
    assert run(tmp_path, report(advisory(), another)) != 0


def test_inconsistent_high_count_cannot_disappear(tmp_path):
    data = report(advisory())
    data["metadata"]["vulnerabilities"]["high"] = 2
    assert run(tmp_path, data) != 0


def test_lower_severity_metadata_count_can_be_filtered_by_pnpm(tmp_path):
    data = report(advisory())
    data["metadata"]["vulnerabilities"]["moderate"] = 1
    assert run(tmp_path, data) == 0


def test_muted_advisory_cannot_hide_another_high(tmp_path):
    data = report(advisory())
    data["muted"] = [{"github_advisory_id": "GHSA-other-0000-0003"}]
    assert run(tmp_path, data) != 0


def test_expiry_is_fail_closed_for_gate_and_daily_watch(tmp_path):
    data = report(advisory())
    assert run(tmp_path, data, today=date(2026, 12, 1)) == 2
    assert run(tmp_path, data, mode="watch", today=date(2026, 12, 2)) == 2


def test_malformed_report_is_fail_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")
    assert gate.main(["gate", "--report", str(path), "--audit-exit", "1"], today=TODAY) == 2


def test_nonzero_audit_exit_without_exact_match_fails(tmp_path):
    assert run(tmp_path, report(), audit_exit=1) == 1
    assert run(tmp_path, report(advisory()), audit_exit=2) == 1


def test_clean_audit_does_not_need_exception(tmp_path):
    assert run(tmp_path, report(), audit_exit=0) == 0


def test_daily_watch_accepts_unchanged_unpatched_release(tmp_path):
    assert run(tmp_path, report(advisory()), mode="watch") == 0


def test_daily_watch_fails_when_advisory_publishes_patch(tmp_path):
    item = advisory()
    item["patched_versions"] = ">=4.0.8"
    assert run(tmp_path, report(item), mode="watch") == 1


def test_daily_watch_fails_when_npm_latest_changes(tmp_path):
    assert run(tmp_path, report(advisory()), mode="watch", latest="4.0.8") == 1


def test_daily_watch_fails_when_exception_can_be_removed(tmp_path):
    assert run(tmp_path, report(), mode="watch", audit_exit=0) == 1


def test_workflow_preserves_full_dev_audit_and_schedules_daily_watch():
    root = Path(__file__).resolve().parents[3]
    ci = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    frontend = "\n".join(step.get("run", "") for step in ci["jobs"]["frontend"]["steps"])
    assert "pnpm audit --audit-level high --json" in frontend
    assert "frontend_audit.py gate" in frontend
    assert "--prod" not in frontend
    secret = yaml.safe_load((root / ".github/workflows/secret-scan.yml").read_text(encoding="utf-8"))
    watch = secret["jobs"]["picomatch-fix-watch"]
    assert "schedule" in watch["if"]
    runs = "\n".join(step.get("run", "") for step in watch["steps"])
    assert "npm view picomatch version" in runs
    assert "frontend_audit.py watch" in runs
    assert "--prod" not in runs

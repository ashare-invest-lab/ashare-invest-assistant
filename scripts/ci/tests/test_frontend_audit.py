"""Exercise the full frontend audit gate using synthetic report envelopes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

import frontend_audit as gate


@pytest.fixture
def former_exception():
    """Use the retired identity in a synthetic report to prove it is now blocked."""
    return {
        "github_advisory_id": "GHSA-fc5q-39xc-vjpf",
        "module_name": "picomatch",
        "severity": "high",
        "findings": [{
            "version": "4.0.7",
            "paths": [".>typescript-eslint>@typescript-eslint/typescript-estree>tinyglobby>picomatch"],
        }],
    }


def report(*items):
    counts = dict.fromkeys(("info", "low", "moderate", "high", "critical"), 0)
    advisories = {}
    for index, item in enumerate(items):
        advisories[str(index)] = item
        counts[item["severity"]] += 1
    return {"advisories": advisories, "metadata": {"vulnerabilities": counts}}


def run(tmp_path, data, audit_exit=1):
    path = tmp_path / "audit.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return gate.main(["--report", str(path), "--audit-exit", str(audit_exit)])


@pytest.mark.parametrize("audit_exit", [0, 1])
def test_former_exact_exception_is_blocked(tmp_path, former_exception, audit_exit):
    assert run(tmp_path, report(former_exception), audit_exit) == 1


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_another_advisory_is_blocked_even_if_pnpm_reports_success(tmp_path, severity):
    item = {
        "github_advisory_id": "GHSA-synthetic-0001",
        "module_name": "synthetic-dependency",
        "severity": severity,
        "findings": [{"version": "1.0.0", "paths": [".>synthetic-dependency"]}],
    }
    assert run(tmp_path, report(item), audit_exit=0) == 1


@pytest.mark.parametrize("change", [
    {"version": "4.0.6"},
    {"paths": [".>another>picomatch"]},
])
def test_same_advisory_with_different_version_or_path_is_blocked(tmp_path, former_exception, change):
    former_exception["findings"][0].update(change)
    assert run(tmp_path, report(former_exception)) == 1


def test_additional_path_never_hides_a_high_advisory(tmp_path, former_exception):
    former_exception["findings"][0]["paths"].append(".>another>picomatch")
    assert run(tmp_path, report(former_exception), audit_exit=0) == 1


def test_malformed_advisory_details_fail_closed(tmp_path, former_exception):
    data = report(former_exception)
    del former_exception["findings"]
    assert run(tmp_path, data, audit_exit=0) == 2


@pytest.mark.parametrize("severity", ["high", "critical"])
def test_inconsistent_blocking_count_fails_closed(tmp_path, former_exception, severity):
    former_exception["severity"] = severity
    data = report(former_exception)
    data["metadata"]["vulnerabilities"][severity] = 0
    assert run(tmp_path, data, audit_exit=0) == 2


def test_lower_severity_metadata_count_can_be_filtered_by_pnpm(tmp_path):
    data = report()
    data["metadata"]["vulnerabilities"]["moderate"] = 1
    assert run(tmp_path, data, audit_exit=0) == 0


def test_muted_advisory_is_not_accepted(tmp_path):
    data = report()
    data["muted"] = [{"github_advisory_id": "GHSA-synthetic-0002"}]
    assert run(tmp_path, data, audit_exit=0) == 2


def test_malformed_report_is_fail_closed(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")
    assert gate.main(["--report", str(path), "--audit-exit", "0"]) == 2


@pytest.mark.parametrize("count", [None, -1, True])
def test_invalid_report_counts_fail_closed(tmp_path, count):
    data = report()
    data["metadata"]["vulnerabilities"]["high"] = count
    assert run(tmp_path, data, audit_exit=0) == 2


@pytest.mark.parametrize("audit_exit", [1, 2, 127])
def test_nonzero_audit_exit_cannot_pass_even_with_clean_report(tmp_path, audit_exit):
    assert run(tmp_path, report(), audit_exit=audit_exit) == 1


def test_clean_audit_passes(tmp_path):
    assert run(tmp_path, report(), audit_exit=0) == 0


def test_workflows_keep_full_dev_audit_and_scheduled_secret_scan():
    root = Path(__file__).resolve().parents[3]
    ci = yaml.load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    frontend = ci["jobs"]["frontend"]
    audit = next(step for step in frontend["steps"] if step.get("name") == "pnpm audit")
    assert "continue-on-error" not in frontend
    assert "continue-on-error" not in audit
    assert audit["working-directory"] == "src/frontend"
    assert audit["shell"] == "bash"
    assert audit["if"] == "${{ !cancelled() && steps.install.outcome == 'success' }}"
    assert audit["run"].splitlines() == [
        "set +e",
        'pnpm audit --audit-level high --json > "$RUNNER_TEMP/frontend-audit.json"',
        "audit_status=$?",
        "set -e",
        'python3 ../../scripts/ci/frontend_audit.py --report "$RUNNER_TEMP/frontend-audit.json" '
        '--audit-exit "$audit_status"',
    ]
    secret = yaml.load(
        (root / ".github/workflows/secret-scan.yml").read_text(encoding="utf-8"), Loader=yaml.BaseLoader,
    )
    assert set(secret["on"]) == {"pull_request", "merge_group", "push", "schedule", "workflow_dispatch"}
    assert secret["on"]["schedule"] == [{"cron": "17 19 * * *"}]
    assert set(secret["jobs"]) == {"scan", "selftest"}

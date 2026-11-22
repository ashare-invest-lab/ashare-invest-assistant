from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def baseline_bytes(path):
    return __import__("subprocess").check_output(
        ["git", "show", f"origin/main:{path}"], cwd=ROOT
    )


def baseline(path):
    return yaml.safe_load(baseline_bytes(path))


def test_secret_scan_concurrency_literals():
    _ci, secret = (
        load(p)
        for p in (".github/workflows/ci.yml", ".github/workflows/secret-scan.yml")
    )
    assert secret["concurrency"]["group"] == (
        "secret-scan-${{ github.event_name }}-"
        "${{ github.event_name == 'merge_group' && github.run_id || github.event_name == 'pull_request' && github.ref || github.run_id }}"
    )
    assert secret["concurrency"]["cancel-in-progress"] == (
        "${{ github.event_name == 'pull_request' }}"
    )


def test_workflow_job_identity_matches_origin():
    for path in (".github/workflows/ci.yml", ".github/workflows/secret-scan.yml"):
        current = load(path)
        origin = baseline(path)
        assert {
            (job_id, job.get("name", job_id)) for job_id, job in current["jobs"].items()
        } == {
            (job_id, job.get("name", job_id)) for job_id, job in origin["jobs"].items()
        }


def test_ci_matches_origin_byte_for_byte():
    assert (ROOT / ".github/workflows/ci.yml").read_bytes() == baseline_bytes(
        ".github/workflows/ci.yml"
    )

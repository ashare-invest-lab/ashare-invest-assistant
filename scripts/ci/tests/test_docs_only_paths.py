"""Docs-only PR classification and required check-name routing (T-O108)."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
import yaml

import docs_only_paths as classifier

REPO = Path(__file__).resolve().parents[3]
WORKFLOW = yaml.safe_load((REPO / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
CHECKS = {
    "coverage-base": "trusted main coverage readiness",
    "backend": "backend (ruff, mypy, pytest+coverage)",
    "frontend": "frontend (eslint, tsc, vitest, pnpm audit)",
    "contract": "contract (doc check, code namespaces, schemathesis)",
    "migrations": "migrations (alembic up/down/up)",
    "image": "image (backend.Dockerfile, no push)",
    "frontend-image": "frontend-image (frontend.Dockerfile, no push)",
    "pip-audit": "pip-audit",
    "licenses": "licenses (no ag-grid-enterprise, no GPL/AGPL/NC)",
    "fixtures": "fixtures (check_fixtures.py)",
    "gateway-limits": "gateway-limits (nginx client_max_body_size ↔ config/imports.yaml)",
    "secret-boundary": "secret-boundary (私钥只给 ingest，无全站证书变量)",
    "ignored-sources": "ignored-sources (源码不被 .gitignore 误伤)",
}


@pytest.mark.parametrize("paths,expected", [
    (["docs/foo.md"], True),
    (["README.md"], True),
    (["nested/README.md"], True),
    (["docs/assets/diagram.png"], True),
    (["docs/foo.md", "nested/README.md", "docs/data.json"], True),
    (["README.md", "src/backend/app.py"], False),
    ([], False),
    (["docs-other/foo.png"], False),
    (["README.MD"], False),
    (["docs"], False),
    (["docs/line\nbreak.png", "with space.md"], True),
])
def test_path_classification(paths, expected):
    assert classifier.is_docs_only(paths) is expected


def test_cli_uses_pr_three_dot_diff_and_detects_source_moved_into_docs(tmp_path):
    # All git writes/commits are isolated fixtures, never the working repository.
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid",
             "-c", "core.hooksPath=/dev/null", *args],
            cwd=tmp_path, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def classify(base, head):
        return subprocess.run(
            [sys.executable, classifier.__file__, base, head],
            cwd=tmp_path, capture_output=True, text=True,
        )

    git("init", "-b", "base")
    (tmp_path / "source.py").write_text("print('fixture')\n")
    git("add", ".")
    git("commit", "-m", "fixture base")
    git("checkout", "-b", "pr")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/space and\nnewline.png").write_bytes(b"fixture")
    (tmp_path / "README.md").write_text("fixture docs\n")
    git("add", ".")
    git("commit", "-m", "fixture docs")
    docs_head = git("rev-parse", "HEAD")
    git("checkout", "base")
    (tmp_path / "base-only.py").write_text("# unrelated base change\n")
    git("add", ".")
    git("commit", "-m", "fixture advancing base")
    base = git("rev-parse", "HEAD")
    result = classify(base, docs_head)
    assert result.returncode == 0, result.stderr
    assert result.stdout == "docs_only=true\n"
    # Empty diff runs full CI; missing objects fail instead of granting a bypass.
    assert classify(base, base).stdout == "docs_only=false\n"
    missing = classify("0" * 40, docs_head)
    assert missing.returncode != 0 and "docs_only=true" not in missing.stdout
    git("checkout", "pr")
    git("mv", "source.py", "docs/source.py")
    git("commit", "-m", "fixture source move")
    result = classify(base, git("rev-parse", "HEAD"))
    assert result.returncode == 0, result.stderr
    assert result.stdout == "docs_only=false\n"


def _condition(expression, event, docs_only):
    """Evaluate the workflow's small boolean expressions, rejecting other syntax."""
    expression = expression.removeprefix("${{").removesuffix("}}").strip()
    expression = expression.replace("github.event_name", repr(event))
    expression = expression.replace("needs.changes.outputs.docs_only", repr(docs_only))
    tree = ast.parse(expression.replace("&&", " and ").replace("||", " or "), mode="eval")
    assert all(isinstance(node, (ast.Expression, ast.BoolOp, ast.And, ast.Or,
                                ast.Compare, ast.Eq, ast.NotEq, ast.Constant))
               for node in ast.walk(tree))
    return eval(compile(tree, "<workflow condition>", "eval"), {"__builtins__": {}})


def test_each_required_check_has_one_full_and_one_empty_success_job():
    jobs = WORKFLOW["jobs"]
    assert set(jobs) == {"changes", *CHECKS, *(f"{key}-docs" for key in CHECKS)}
    for suffix in ("", "-docs"):
        assert Counter(jobs[key + suffix]["name"] for key in CHECKS) == Counter(CHECKS.values())
    for key, name in CHECKS.items():
        assert jobs[key]["name"] == jobs[key + "-docs"]["name"] == name
        assert jobs[key]["needs"] == jobs[key + "-docs"]["needs"] == "changes"
        assert jobs[key]["steps"]
        empty = jobs[key + "-docs"]
        assert set(empty) == {"name", "needs", "if", "runs-on", "steps"}
        assert empty["steps"] == [{"run": "exit 0"}]
        result = subprocess.run(["bash", "-c", empty["steps"][0]["run"]], capture_output=True)
        assert result.returncode == 0


@pytest.mark.parametrize("event", ["pull_request", "push", "merge_group", "workflow_dispatch"])
@pytest.mark.parametrize("docs_only", ["true", "false", ""])
def test_job_routing_and_concurrency(event, docs_only):
    bypass = event == "pull_request" and docs_only == "true"
    for key in CHECKS:
        assert _condition(WORKFLOW["jobs"][key]["if"], event, docs_only) is not bypass
        assert _condition(WORKFLOW["jobs"][key + "-docs"]["if"], event, docs_only) is bypass
    assert _condition(WORKFLOW["concurrency"]["cancel-in-progress"], event, docs_only) is (
        event == "pull_request"
    )


def test_classifier_only_checks_out_and_runs_stdlib_script_for_prs():
    changes = WORKFLOW["jobs"]["changes"]
    assert "services" not in changes and "needs" not in changes
    assert changes["outputs"] == {"docs_only": "${{ steps.classify.outputs.docs_only || 'false' }}"}
    checkout, classify = changes["steps"]
    assert checkout["uses"] == "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
    assert checkout["with"] == {"persist-credentials": False, "fetch-depth": 0}
    assert classify["id"] == "classify"
    assert classify["env"] == {
        "BASE_SHA": "${{ github.event.pull_request.base.sha }}",
        "HEAD_SHA": "${{ github.event.pull_request.head.sha }}",
    }
    assert classify["run"] == (
        'python3 scripts/ci/docs_only_paths.py "$BASE_SHA" "$HEAD_SHA" >> "$GITHUB_OUTPUT"'
    )
    for event in ("pull_request", "push", "merge_group", "workflow_dispatch"):
        for step in changes["steps"]:
            assert _condition(step["if"], event, "") is (event == "pull_request")


@pytest.mark.parametrize("key,commands", [
    ("backend", ["uv sync --frozen", "ruff check", "mypy", "-m pytest", "scripts/ci/check_coverage.py"]),
    ("frontend", ["pnpm install --frozen-lockfile", "pnpm exec eslint", "pnpm exec tsc",
                  "pnpm exec vitest run", "pnpm audit"]),
    ("contract", ["scripts/ci/check_contract.py", "schemathesis run"]),
    ("migrations", ["alembic upgrade head", "alembic downgrade base"]),
])
def test_full_jobs_retain_heavy_commands(key, commands):
    steps = WORKFLOW["jobs"][key]["steps"]
    runs = "\n".join(step.get("run", "") for step in steps)
    for command in commands:
        assert command in runs

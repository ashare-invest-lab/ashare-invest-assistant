"""Docs-only PR classification and required check-name routing (T-O108)."""

from __future__ import annotations

import ast
import os
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
    assert 'git show "$BASE_SHA:scripts/ci/docs_only_paths.py"' in classify["run"]
    assert "python3 -I" in classify["run"]
    assert "python3 scripts/ci/docs_only_paths.py" not in classify["run"]
    for event in ("pull_request", "push", "merge_group", "workflow_dispatch"):
        for step in changes["steps"]:
            assert _condition(step["if"], event, "") is (event == "pull_request")


@pytest.fixture
def workflow_repo(tmp_path):
    """Commit synthetic base/head trees; execute the actual workflow run verbatim."""
    repo = tmp_path / "repo"
    repo.mkdir()
    runner_temp = tmp_path / "runner temp"
    runner_temp.mkdir()

    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=CI test", "-c", "user.email=ci@example.invalid",
             "-c", "core.hooksPath=/dev/null", *args],
            cwd=repo, check=True, capture_output=True, text=True,
        ).stdout.strip()

    def write(path, content):
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    def commit():
        git("add", ".")
        git("commit", "-m", "fixture")
        return git("rev-parse", "HEAD")

    def prepare(base_script, changes):
        git("init", "-b", "base")
        write("src/x.py", "# base\n")
        if base_script is not None:
            write("scripts/ci/docs_only_paths.py", base_script)
        base = commit()
        git("checkout", "-b", "pr")
        for path, content in changes.items():
            write(path, content)
        return base, commit()

    def run(base, head, extra_env=None):
        output = tmp_path / "github-output"
        env = {**os.environ, "BASE_SHA": base, "HEAD_SHA": head,
               "GITHUB_OUTPUT": str(output), "RUNNER_TEMP": str(runner_temp),
               **(extra_env or {})}
        result = subprocess.run(
            ["bash", "-e", "-c", WORKFLOW["jobs"]["changes"]["steps"][1]["run"]],
            cwd=repo, env=env, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        return output.read_text(encoding="utf-8"), result

    return repo, prepare, run


def _current_classifier():
    return Path(classifier.__file__).read_text(encoding="utf-8")


def test_workflow_rejects_pr_classifier_tampering_with_source(workflow_repo):
    repo, prepare, run = workflow_repo
    base, head = prepare(_current_classifier(), {
        "src/x.py": "# changed source\n",
        "scripts/ci/docs_only_paths.py": "print('docs_only=true')\n",
    })
    # Control: the old workflow really would trust the malicious head script.
    control = subprocess.run(
        [sys.executable, "scripts/ci/docs_only_paths.py", base, head],
        cwd=repo, check=True, capture_output=True, text=True,
    )
    assert control.stdout == "docs_only=true\n"
    assert run(base, head)[0] == "docs_only=false\n"


@pytest.mark.parametrize("base_script", [
    None,
    "print('docs_only=true')\nraise SystemExit(1)\n",
    "print('docs_only=true\\ndocs_only=true')\n",
    "print('docs_only=true\\n')\n",
    "print('docs_only=maybe')\n",
    "print('docs_only=true', end='')\n",
    "import sys\nsys.stdout.buffer.write(b'docs_only=true\\x00\\n')\n",
    "print('')\n",
], ids=["missing-script", "nonzero-exit", "multiple-lines", "extra-blank-line",
        "invalid-value", "missing-newline", "nul-byte", "empty-line"])
def test_workflow_fails_closed_on_unavailable_or_invalid_classifier(workflow_repo, base_script):
    _, prepare, run = workflow_repo
    base, head = prepare(base_script, {"docs/guide.md": "# docs\n"})
    output, result = run(base, head)
    assert output == "docs_only=false\n"
    assert "::notice::" in result.stdout or "::warning::" in result.stdout


def test_workflow_fails_closed_when_base_object_is_missing(workflow_repo):
    _, prepare, run = workflow_repo
    _, head = prepare(_current_classifier(), {"docs/guide.md": "# docs\n"})
    output, result = run("0" * 40, head)
    assert output == "docs_only=false\n"
    assert "::notice::" in result.stdout


def test_workflow_fails_closed_when_diff_fails(workflow_repo):
    _, prepare, run = workflow_repo
    base, _ = prepare(_current_classifier(), {"docs/guide.md": "# docs\n"})
    output, result = run(base, "0" * 40)
    assert output == "docs_only=false\n"
    assert "::warning::" in result.stdout


@pytest.mark.parametrize("path,expected", [
    ("docs/guide.md", "true"),
    ("scripts/ci/docs_only_paths.py", "false"),
    (".github/workflows/ci.yml", "false"),
])
def test_workflow_classifies_trusted_paths(workflow_repo, path, expected):
    _, prepare, run = workflow_repo
    content = _current_classifier() + "\n# PR change\n" if path.endswith(".py") else "# change\n"
    base, head = prepare(_current_classifier(), {path: content})
    assert run(base, head)[0] == f"docs_only={expected}\n"


def test_workflow_ignores_pythonpath_injection(workflow_repo, tmp_path):
    _, prepare, run = workflow_repo
    base, head = prepare(_current_classifier(), {"src/x.py": "# source change\n"})
    injection = tmp_path / "python injection"
    injection.mkdir()
    (injection / "sitecustomize.py").write_text(
        "import os\nos.write(1, b'docs_only=true\\n')\nos._exit(0)\n", encoding="utf-8",
    )
    assert run(base, head, {"PYTHONPATH": str(injection)})[0] == "docs_only=false\n"


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

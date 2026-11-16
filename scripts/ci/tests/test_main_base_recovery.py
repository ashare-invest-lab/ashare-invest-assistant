"""User-A recovery uses disposable Git history and synthetic Actions artifacts only."""
import io
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import zipfile
from copy import deepcopy
from pathlib import Path

import coverage_ratchet as ratchet
import coverage_ratchet_base as loader
import pytest

REPO = "owner/repo"


def git(root, *args):
    return subprocess.check_output(
        ["git", "-c", "user.name=Synthetic CI", "-c", "user.email=ci@example.invalid",
         "-C", str(root), *args], text=True, encoding="utf-8").strip()


def commit(root, label):
    git(root, "commit", "--allow-empty", "-qm", label)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def history(tmp_path, monkeypatch):
    root = tmp_path / "synthetic-main"
    root.mkdir()
    git(root, "init", "-q", "--initial-branch=main")
    policy = root / loader.POLICY_PATH
    policy.parent.mkdir(parents=True)
    policy.write_text("{}\n", encoding="utf-8")
    git(root, "add", loader.POLICY_PATH)
    first = commit(root, "root with policy")
    second = commit(root, "unmeasured main")
    third = commit(root, "recovery main")
    monkeypatch.setattr(loader, "ROOT", root)
    return root, (first, second, third)


@pytest.fixture(autouse=True)
def reject_real_http(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Offline recovery tests must not open HTTP connections")
    monkeypatch.setattr(loader.urllib.request.OpenerDirector, "open", denied)


class Actions:
    def __init__(self):
        self.states = {}
        self.calls = []
        self.counts = {}

    def put(self, sha, mode="valid", *, counts=None):
        identifier = 100 + len(self.states)
        self.states[sha] = (identifier, mode)
        if counts is not None:
            self.counts[sha] = deepcopy(counts)

    def __call__(self, path, *, binary=False):
        self.calls.append(path)
        parsed = urllib.parse.urlsplit(path)
        if parsed.path.endswith("/ci.yml/runs"):
            query = urllib.parse.parse_qs(parsed.query)
            sha = query["head_sha"][0]
            if sha not in self.states:
                return {"workflow_runs": []}
            identifier, mode = self.states[sha]
            status = "in_progress" if mode == "pending" else "completed"
            if query.get("status") == ["completed"] and status != "completed":
                return {"workflow_runs": []}
            event = mode if mode in {"pull_request", "workflow_dispatch"} else "push"
            return {"workflow_runs": [{
                "id": identifier, "run_attempt": 1, "head_sha": sha,
                "head_branch": "topic" if mode == "topic" else "main",
                "event": event, "status": status,
                "repository": {"full_name": "foreign/repo" if mode == "foreign" else REPO},
            }]}
        identifier = int(parsed.path.split("/")[-2])
        sha, (_, mode) = next((sha, value) for sha, value in self.states.items()
                              if value[0] == identifier)
        if parsed.path.endswith("/artifacts"):
            artifacts = [] if mode == "no_artifact" else [{
                "id": identifier, "name": f"coverage-ratchet-{identifier}-1",
                "expired": mode == "expired",
            }]
            if mode == "ambiguous":
                artifacts *= 2
            return {"artifacts": artifacts}
        assert parsed.path == f"/actions/artifacts/{identifier}/zip" and binary
        if mode == "invalid_zip":
            return b"synthetic invalid archive"
        record = deepcopy(ratchet.bootstrap_record())
        record.update(commit=sha, run_id=str(identifier), attempt="1")
        if sha in self.counts:
            record["counts"] = deepcopy(self.counts[sha])
        if mode == "failed_ratchet":
            record["ratchet_passed"] = False
        elif mode == "wrong_identity":
            record["commit"] = "f" * 40
        archive = io.BytesIO()
        with zipfile.ZipFile(archive, "w") as stream:
            stream.writestr("coverage-ratchet-measurement.json", json.dumps(record))
        return archive.getvalue()


def assert_fallback(record, selected, requested, skipped):
    assert record["commit"] == selected
    assert record["ratchet_passed"] is True
    assert record["source"]["kind"] == "trusted-main-push-artifact"
    assert record["source"]["commit"] == selected
    assert record["source"]["fallback"] == {
        "requested_base_commit": requested, "skipped_heads": skipped,
        "ancestor_limit": loader.MAX_FALLBACK_ANCESTORS,
        "reason": record["source"]["fallback"]["reason"],
    }
    assert record["source"]["fallback"]["reason"]


def test_missing_exact_base_recovers_nearest_measured_first_parent(history):
    assert loader.MAX_FALLBACK_ANCESTORS == 50
    _, (first, second, third) = history
    actions = Actions()
    actions.put(first)
    actions.put(second)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert_fallback(record, second, third, 1)
    assert not any(first in call for call in actions.calls)


@pytest.mark.parametrize("mode", [
    "no_artifact", "expired", "ambiguous", "failed_ratchet", "wrong_identity", "invalid_zip",
    "pull_request", "workflow_dispatch", "foreign", "topic",
])
def test_unusable_or_untrusted_head_never_becomes_recovered_baseline(history, mode):
    _, (_, second, third) = history
    actions = Actions()
    actions.put(second)
    actions.put(third, mode)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert_fallback(record, second, third, 1)


def test_all_missing_history_still_errors_instead_of_bootstrap_reset(history):
    _, heads = history
    actions = Actions()
    with pytest.raises(ValueError, match="No usable trusted main push measurement"):
        loader.freeze(REPO, heads[-1], actions, allow_fallback=True)
    for head in heads:
        assert any(head in call for call in actions.calls)


@pytest.mark.parametrize("distance,success", [(2, True), (3, False)])
def test_ancestor_bound_includes_boundary_but_never_queries_beyond_it(
    history, monkeypatch, distance, success,
):
    root, (first, _, third) = history
    requested = third if distance == 2 else commit(root, "one beyond the bound")
    monkeypatch.setattr(loader, "MAX_FALLBACK_ANCESTORS", 2)
    actions = Actions()
    actions.put(first)
    if success:
        assert_fallback(loader.freeze(REPO, requested, actions, allow_fallback=True),
                        first, requested, 2)
    else:
        with pytest.raises(loader.MeasurementUnavailable, match="No usable trusted main push measurement"):
            loader.freeze(REPO, requested, actions, allow_fallback=True)
        assert not any(first in call for call in actions.calls)


def test_recovery_never_takes_a_merge_second_parent_measurement(history):
    root, (first, _, third) = history
    git(root, "checkout", "-qb", "side", first)
    side = commit(root, "side-only measurement")
    git(root, "checkout", "-q", "main")
    git(root, "merge", "--no-ff", "-qm", "main merge", "side")
    merged = git(root, "rev-parse", "HEAD")
    assert git(root, "rev-parse", merged + "^1") == third
    assert git(root, "rev-parse", merged + "^2") == side
    actions = Actions()
    actions.put(first)
    actions.put(side)
    record = loader.freeze(REPO, merged, actions, allow_fallback=True)
    assert_fallback(record, first, merged, 3)
    assert not any(side in call for call in actions.calls)


def test_exact_valid_base_keeps_existing_source_without_fallback(history):
    _, (_, _, third) = history
    actions = Actions()
    actions.put(third)
    record = loader.freeze(REPO, third, actions, allow_fallback=True)
    assert record["source"] == {
        "kind": "trusted-main-push-artifact", "commit": third,
        "run_id": 100, "attempt": 1,
    }


def test_existing_pending_exact_run_still_waits_without_ancestor_requests(history):
    _, (_, second, third) = history
    actions = Actions()
    actions.put(second)
    actions.put(third, "pending")
    with pytest.raises(loader.MeasurementPending):
        loader.freeze(REPO, third, actions, allow_fallback=True)
    assert not any(second in call for call in actions.calls)


@pytest.mark.parametrize("error", [
    urllib.error.HTTPError("https://example.invalid", 403, "synthetic denied", {}, None),
    urllib.error.URLError("synthetic transport failure"),
])
def test_authentication_or_transport_failure_is_not_hidden_by_ancestry(history, error):
    _, (_, _, third) = history
    calls = []
    def denied(path, **kwargs):
        calls.append(path)
        raise error
    with pytest.raises(type(error)):
        loader.freeze(REPO, third, denied, allow_fallback=True)
    assert len(calls) == 1


@pytest.fixture
def cli_recovery_case(history, tmp_path, monkeypatch):
    root, (_, second, third) = history

    def make(event_name="pull_request", mode="failed_ratchet", *, wait=0):
        if event_name == "workflow_dispatch":
            commit(root, "current dispatch main")  # HEAD^ is the requested third commit.
        actions = Actions()
        actions.put(second)
        if mode != "missing":
            actions.put(third, mode)
        event = {"before": third, "merge_group": {
            "base_ref": "refs/heads/main", "base_sha": third, "head_sha": "a" * 40,
        }, "pull_request": {
            "base": {"sha": third, "ref": "main", "repo": {"full_name": REPO}},
            "head": {"sha": "a" * 40},
        }}
        path = tmp_path / "synthetic-event.json"
        path.write_text(json.dumps(event), encoding="utf-8")
        output = tmp_path / "frozen.json"
        monkeypatch.setenv("GITHUB_EVENT_PATH", str(path))
        monkeypatch.setenv("GITHUB_EVENT_NAME", event_name)
        monkeypatch.setenv("GITHUB_REPOSITORY", REPO)
        refs = {"pull_request": "refs/pull/7/merge",
                "merge_group": "refs/heads/gh-readonly-queue/main/pr-7-synthetic"}
        monkeypatch.setenv("GITHUB_REF", refs.get(event_name, "refs/heads/main"))
        monkeypatch.setattr(loader, "api_reader", lambda repo: actions)
        monkeypatch.setattr(sys, "argv", ["loader", "--output", str(output),
                                         "--wait-for-main-seconds", str(wait)])
        return {"actions": actions, "output": output, "requested": third, "selected": second}

    return make


def assert_cli_recovers(main, case):
    assert main() == 0, "PR/main/merge_group must recover an unavailable exact main base"
    frozen = json.loads(case["output"].read_text(encoding="utf-8"))
    assert_fallback(frozen, case["selected"], case["requested"], 1)
    return frozen


@pytest.mark.parametrize("event_name", ["push", "workflow_dispatch", "pull_request", "merge_group"])
@pytest.mark.parametrize("mode", [
    "missing", "no_artifact", "expired", "ambiguous", "invalid_zip", "failed_ratchet",
    "wrong_identity", "pull_request", "workflow_dispatch", "foreign", "topic",
])
def test_cli_allows_main_pr_and_merge_group_to_recover_and_logs_reason(
    cli_recovery_case, capsys, event_name, mode,
):
    case = cli_recovery_case(event_name, mode)
    frozen = assert_cli_recovers(loader.main, case)
    stdout = capsys.readouterr().out
    assert "Frozen coverage baseline: " + case["selected"] in stdout
    assert "first-parent fallback commit=" + case["selected"] in stdout
    reason = frozen["source"]["fallback"]["reason"]
    assert "reason=" + reason in stdout
    if mode == "failed_ratchet":
        assert "ratchet_passed is not true" in reason
    elif mode in {"invalid_zip", "wrong_identity"}:
        assert "Invalid exact-base main push measurement" in reason
    elif mode in {"no_artifact", "expired", "ambiguous"}:
        assert "Missing, expired or ambiguous exact-base measurement" in reason
    else:
        assert "No completed exact-base main measurement run" in reason


@pytest.mark.parametrize("event_name", ["pull_request", "merge_group"])
@pytest.mark.parametrize("completed_mode", ["valid", "failed_ratchet", "no_artifact"])
def test_cli_waits_for_exact_main_push_before_deciding_to_recover(
    cli_recovery_case, monkeypatch, capsys, event_name, completed_mode,
):
    case = cli_recovery_case(event_name, "pending", wait=30)
    actions = case["actions"]
    identifier, _ = actions.states[case["requested"]]
    sleeps = []

    def complete(seconds):
        assert not any(case["selected"] in call for call in actions.calls)
        sleeps.append(seconds)
        actions.states[case["requested"]] = (identifier, completed_mode)

    monkeypatch.setattr(loader.time, "sleep", complete)
    monkeypatch.setattr(loader.time, "monotonic", lambda: 0)
    if completed_mode == "valid":
        assert loader.main() == 0
        frozen = json.loads(case["output"].read_text(encoding="utf-8"))
        assert frozen["commit"] == case["requested"]
        assert "fallback" not in frozen["source"]
        assert not any(case["selected"] in call for call in actions.calls)
    else:
        assert_cli_recovers(loader.main, case)
    assert sleeps == [15]
    assert f"Waiting for existing trusted main run {identifier}" in capsys.readouterr().out


@pytest.mark.parametrize("event_name", ["pull_request", "merge_group"])
def test_cli_pending_timeout_does_not_use_available_ancestor(
    cli_recovery_case, monkeypatch, event_name,
):
    case = cli_recovery_case(event_name, "pending", wait=30)
    ticks = iter([0, 30])
    monkeypatch.setattr(loader.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(loader.time, "sleep", lambda _: pytest.fail("Must time out"))
    assert loader.main() == 1
    assert not case["output"].exists()
    assert not any(case["selected"] in call for call in case["actions"].calls)


@pytest.mark.parametrize("mode", ["pull_request", "workflow_dispatch", "foreign", "topic"])
def test_untrusted_artifacts_throughout_history_cannot_supply_a_baseline(history, mode):
    _, heads = history
    actions = Actions()
    for head in heads:
        actions.put(head, mode)
    with pytest.raises(loader.MeasurementUnavailable):
        loader.freeze(REPO, heads[-1], actions, allow_fallback=True)
    assert not any("/artifacts" in call for call in actions.calls)


@pytest.mark.parametrize("distance", [50, 51])
def test_consecutive_failed_measurements_respect_actual_fifty_ancestor_limit(history, distance):
    root, (first, second, third) = history
    heads = [first, second, third]
    while len(heads) <= distance:
        heads.append(commit(root, f"failed main {len(heads)}"))
    actions = Actions()
    actions.put(first)
    for head in heads[1:]:
        actions.put(head, "failed_ratchet")
    if distance == 50:
        assert_fallback(loader.freeze(REPO, heads[-1], actions, allow_fallback=True),
                        first, heads[-1], 50)
    else:
        with pytest.raises(loader.MeasurementUnavailable, match="50 first-parent ancestors"):
            loader.freeze(REPO, heads[-1], actions, allow_fallback=True)
        assert not any(first in call for call in actions.calls)


@pytest.mark.parametrize("mutation", ["main_only", "disabled", "failed_ratchet", "non_main"])
def test_cli_recovery_and_trust_mutations_are_caught(
    cli_recovery_case, tmp_path, monkeypatch, mutation,
):
    case = cli_recovery_case(mode="pull_request" if mutation == "non_main" else "failed_ratchet")
    assert_cli_recovers(loader.main, case)
    case["output"].unlink()
    source = Path(loader.__file__).read_text(encoding="utf-8")
    if mutation in {"main_only", "disabled"}:
        needle = "                               allow_fallback=True)"
        replacement = ("                               allow_fallback="
                       '(os.environ["GITHUB_EVENT_NAME"] in {"push", "workflow_dispatch"}))'
                       if mutation == "main_only" else
                       "                               allow_fallback=False)")
    elif mutation == "failed_ratchet":
        needle = 'if record.get("ratchet_passed") is not True:'
        replacement = 'if False:  # mutated: accept failed ratchets'
    else:
        needle = 'and r["event"] == "push" and r["status"] == "completed"'
        replacement = 'and r["status"] == "completed"  # mutated: accept PR artifacts'
    assert source.count(needle) == 1
    mutant_path = tmp_path / "mutant_cli_recovery.py"
    mutant_path.write_text(source.replace(needle, replacement, 1), encoding="utf-8")
    namespace = {"__file__": loader.__file__, "__name__": "mutant_cli_recovery"}
    exec(compile(mutant_path.read_text(encoding="utf-8"), str(mutant_path), "exec"), namespace)
    namespace.update(ROOT=loader.ROOT, api_reader=loader.api_reader)
    with pytest.raises(AssertionError):
        assert_cli_recovers(namespace["main"], case)


def test_tag_dispatch_context_is_still_rejected_before_any_measurement():
    with pytest.raises(ValueError, match="Unsupported coverage baseline context"):
        loader.base_identity({}, {
            "GITHUB_REPOSITORY": REPO, "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/tags/synthetic-recovery",
        })


def test_bootstrap_exact_head_is_unchanged_even_when_recovery_is_enabled(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock
    monkeypatch.setattr(loader.subprocess, "run", Mock(side_effect=[
        SimpleNamespace(returncode=0), SimpleNamespace(returncode=128),
    ]))
    actions = Mock()
    record = loader.freeze(REPO, ratchet.BOOTSTRAP_BASE, actions, allow_fallback=True)
    assert record["source"]["kind"] == "approved-first-bootstrap"
    assert record["counts"]["total"] == [15571, 22926]
    actions.assert_not_called()


def test_no_new_fallback_can_reset_to_an_unmeasured_bootstrap_ancestor(history, monkeypatch):
    root, (first, _, third) = history
    monkeypatch.setattr(loader, "BOOTSTRAP_BASE", first)
    original = loader.subprocess.run
    def policy_absent_at_seed(argv, **kwargs):
        if argv[:3] == ["git", "show", first + ":" + loader.POLICY_PATH]:
            from types import SimpleNamespace
            return SimpleNamespace(returncode=128)
        return original(argv, **kwargs)
    monkeypatch.setattr(loader.subprocess, "run", policy_absent_at_seed)
    with pytest.raises(ValueError, match="No usable trusted main push measurement"):
        loader.freeze(REPO, third, Actions(), allow_fallback=True)
    assert root.exists()


def test_explicit_recovery_constants_match_the_approved_pair():
    assert loader.EXPLICIT_RECOVERY_BASE == "f6c939d6ed4af94144e7dd669f206c96d6aeaf6b"
    assert loader.EXPLICIT_RECOVERY_PARENT == "90ef8ff16abb7204b7c4ffd54174aeeb8f712455"


@pytest.fixture
def explicit_recovery_case(history, monkeypatch):
    root, (_, _, parent) = history

    def make(path="docs/recovery.md", *, approved=True):
        git(root, "checkout", "-q", "--detach", parent)
        changed = root / path
        changed.parent.mkdir(parents=True, exist_ok=True)
        changed.write_text("synthetic recovery change\n", encoding="utf-8")
        git(root, "add", path)
        child = commit(root, "explicit recovery: " + path)
        if approved:
            monkeypatch.setattr(loader, "EXPLICIT_RECOVERY_BASE", child)
            monkeypatch.setattr(loader, "EXPLICIT_RECOVERY_PARENT", parent)
        counts = deepcopy(ratchet.BOOTSTRAP["counts"])
        counts["total"] = [19263, 25198]
        actions = Actions()
        actions.put(parent, counts=counts)
        return {"root": root, "parent": parent, "child": child,
                "actions": actions, "counts": counts}

    return make


def assert_explicit_pair_recovers(freeze, case, *, allow_fallback=False):
    record = freeze(REPO, case["child"], case["actions"], allow_fallback=allow_fallback)
    assert record["commit"] == case["parent"]
    assert record["counts"] == case["counts"]
    assert record["ratchet_passed"] is True
    assert record["source"] == {
        "kind": "trusted-main-push-artifact", "commit": case["parent"],
        "run_id": 100, "attempt": 1, "requested_base": case["child"],
    }
    assert not any(case["child"] in call for call in case["actions"].calls)


def assert_other_base_rejected(freeze, case):
    with pytest.raises(ValueError, match="No completed exact-base main measurement run"):
        freeze(REPO, case["child"], case["actions"], allow_fallback=False)
    assert not any(case["parent"] in call for call in case["actions"].calls)


def assert_non_docs_rejected(freeze, case):
    with pytest.raises(ValueError, match="Explicit recovery requires a docs-only diff"):
        freeze(REPO, case["child"], case["actions"], allow_fallback=False)
    assert not case["actions"].calls


@pytest.mark.parametrize("allow_fallback", [False, True])
@pytest.mark.parametrize("child_mode", [None, "pending", "no_artifact", "failed_ratchet"])
def test_explicit_pair_uses_parent_measurement_before_any_child_run(
    explicit_recovery_case, allow_fallback, child_mode,
):
    case = explicit_recovery_case()
    if child_mode is not None:
        case["actions"].put(case["child"], child_mode)
    assert_explicit_pair_recovers(loader.freeze, case, allow_fallback=allow_fallback)


def test_other_docs_only_child_cannot_use_explicit_recovery(explicit_recovery_case):
    approved = explicit_recovery_case()
    other = explicit_recovery_case("docs/other.md", approved=False)
    assert other["child"] != approved["child"]
    assert_other_base_rejected(loader.freeze, other)


def test_explicit_recovery_rejects_non_docs_changes(explicit_recovery_case):
    assert_non_docs_rejected(loader.freeze, explicit_recovery_case("src/example.py"))


def test_explicit_recovery_requires_the_configured_first_parent(
    explicit_recovery_case, monkeypatch,
):
    case = explicit_recovery_case()
    wrong_parent = git(case["root"], "rev-parse", case["parent"] + "^1")
    monkeypatch.setattr(loader, "EXPLICIT_RECOVERY_PARENT", wrong_parent)
    case["actions"].put(wrong_parent)
    with pytest.raises(ValueError, match="Explicit recovery requires the approved first parent"):
        loader.freeze(REPO, case["child"], case["actions"])
    assert not case["actions"].calls


def test_main_fallback_accepts_the_explicit_recovery_artifact(explicit_recovery_case):
    case = explicit_recovery_case()
    requested = commit(case["root"], "later unmeasured main")
    record = loader.freeze(REPO, requested, case["actions"], allow_fallback=True)
    assert_fallback(record, case["parent"], requested, 1)
    assert record["counts"] == case["counts"]
    assert record["source"]["requested_base"] == case["child"]
    assert not any(case["child"] in call for call in case["actions"].calls)


@pytest.mark.parametrize("mutation", ["scope", "branch", "docs"])
def test_explicit_recovery_mutations_are_caught(explicit_recovery_case, tmp_path, mutation):
    case = explicit_recovery_case("src/example.py" if mutation == "docs" else "docs/recovery.md")
    if mutation == "scope":
        case = explicit_recovery_case("docs/other.md", approved=False)
        needle = "if sha == EXPLICIT_RECOVERY_BASE:"
        replacement = "if True:  # mutated: any base may recover"
        check = assert_other_base_rejected
    elif mutation == "branch":
        needle = "if sha == EXPLICIT_RECOVERY_BASE:"
        replacement = "if False:  # mutated: explicit recovery removed"
        check = assert_explicit_pair_recovers
    else:
        needle = 'if any(not path.startswith("docs/") for path in diff.stdout.split("\\0") if path):'
        replacement = "if False:  # mutated: docs-only check removed"
        check = assert_non_docs_rejected
    text = Path(loader.__file__).read_text(encoding="utf-8")
    assert text.count(needle) == 1
    mutant_path = tmp_path / "mutant_coverage_ratchet_base.py"
    mutant_path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    namespace = {"__file__": loader.__file__, "__name__": "mutant_coverage_ratchet_base"}
    exec(compile(mutant_path.read_text(encoding="utf-8"), str(mutant_path), "exec"), namespace)
    namespace.update(ROOT=loader.ROOT, EXPLICIT_RECOVERY_BASE=loader.EXPLICIT_RECOVERY_BASE,
                     EXPLICIT_RECOVERY_PARENT=loader.EXPLICIT_RECOVERY_PARENT)
    check(loader.freeze, case)
    case["actions"].calls.clear()
    if mutation == "branch":
        with pytest.raises(ValueError, match="No completed exact-base main measurement run"):
            check(namespace["freeze"], case)
    else:
        with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
            check(namespace["freeze"], case)
        # Without either guard the very same assertion sees an incorrect recovery.
        assert_explicit_pair_recovers(namespace["freeze"], case)

"""Nondeterministic statement exclusions: synthetic coverage only, no backend imports."""
import io
import json
import subprocess
import sys
import zipfile
from copy import deepcopy
from datetime import date, datetime, timezone
from pathlib import Path

import check_coverage as check
import coverage_ratchet as ratchet
import coverage_ratchet_base as loader
import pytest


CALENDAR = "src/backend/app/aggregates/calendar.py"
LINES = [78, 79, 80, 81, 82, 84, 85]
REPO = Path(__file__).resolve().parents[3]


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def coverage(session, *, lost_line=False, name=CALENDAR):
    executed = set(range(1, 78)) | set(session)
    if lost_line:
        executed.remove(77)  # A deterministic statement outside the whitelist.
    statements = set(range(1, 78)) | set(LINES)
    files = {name: {
        "executed_lines": sorted(executed), "missing_lines": sorted(statements - executed),
        "summary": {"covered_lines": len(executed), "num_statements": len(statements)},
    }}
    # Keep the real incident's exact overall counts and the existing scope floors.
    for scope, counts in {"domain": [113, 172], "importing": [1092, 1406],
                          "signals": [353, 436], "api": [17625, 23100]}.items():
        files[f"app/{scope}/stable.py"] = {"summary": {
            "covered_lines": counts[0], "num_statements": counts[1]}}
    return {"files": files, "totals": {
        "covered_lines": sum(info["summary"]["covered_lines"] for info in files.values()),
        "num_statements": sum(info["summary"]["num_statements"] for info in files.values()),
    }}


@pytest.fixture
def case(tmp_path):
    policy = json.loads(ratchet.NONDET_PATH.read_text(encoding="utf-8"))
    # Tests retain a fixed validity window independent of when this suite is run.
    policy["files"][0]["review_by"] = "2099-12-15"
    whitelist = write_json(tmp_path / "nondet.json", policy)
    before = write_json(tmp_path / "before.json", coverage([79, 80, 85]))
    current = write_json(tmp_path / "current.json", coverage([78]))
    trusted = deepcopy(ratchet.bootstrap_record())
    trusted["counts"] = ratchet.measured(before)
    frozen = write_json(tmp_path / "base.json", trusted)
    output = tmp_path / "measurement.json"
    argv = [str(current), "--base", str(frozen), "--base-coverage", str(before),
            "--base-source-root", str(REPO),
            "--nondet-lines", str(whitelist), "--output", str(output)]
    return {"policy": policy, "whitelist": whitelist, "before": before, "current": current,
            "trusted": trusted, "frozen": frozen, "output": output, "argv": argv}


def test_reviewed_repository_whitelist_has_exact_anchors_and_deadline():
    entries = ratchet.load_nondet_lines(ratchet.NONDET_PATH, today=date(2026, 11, 15))
    assert len(entries) == 1
    entry = entries[0]
    assert entry["path"] == CALENDAR and entry["lines"] == LINES
    assert entry["review_by"] == "2026-12-15" and entry["reason"]
    source = (REPO / CALENDAR).read_text(encoding="utf-8").splitlines()
    assert entry["anchors"] == {str(line): source[line - 1].strip() for line in LINES}


def test_preopen_vs_open_fails_raw_but_passes_with_exact_exclusions(case):
    before, current = ratchet.measured(case["before"]), ratchet.measured(case["current"])
    assert before["total"] == [19263, 25198]
    assert current["total"] == [19261, 25198]
    assert ratchet.compare(current, case["trusted"], case["trusted"]["minimums"])[0]
    original_files = {key: case[key].read_bytes() for key in ("before", "current", "frozen")}
    assert check.main(case["argv"]) == 0
    result = json.loads(case["output"].read_text())
    assert result["ratchet_passed"] is True
    assert result["counts"] == current  # Official counts MUST NOT be adjusted.
    comparison = result["comparison"]
    assert comparison["base_raw_counts"] == before
    assert comparison["counts"]["total"] == comparison["base_counts"]["total"] == [19260, 25191]
    for scope in ratchet.SCOPES[1:]:  # calendar.py only contributes to total.
        assert comparison["counts"][scope] == current[scope] == before[scope]
        assert comparison["base_counts"][scope] == before[scope]
    for label, executed, deduction in [("base", [79, 80, 85], [3, 7]), ("current", [78], [1, 7])]:
        audit = comparison["exclusions"][label]
        assert audit == [{**case["policy"]["files"][0], "covered_lines": executed,
                          "excluded_counts": deduction}]
    assert result["rows"][0]["covered"] == result["rows"][0]["base_covered"] == 19260
    assert result["minimums"] == ratchet.MINIMUMS
    assert original_files == {key: case[key].read_bytes() for key in original_files}


def test_losing_one_unregistered_line_still_fails_and_preserves_raw_counts(case):
    write_json(case["current"], coverage([78], lost_line=True))
    assert check.main(case["argv"]) == 1
    result = json.loads(case["output"].read_text())
    assert result["ratchet_passed"] is False
    assert result["counts"]["total"] == [19260, 25198]
    assert result["comparison"]["counts"]["total"] == [19259, 25191]
    assert result["rows"][0]["status"] == "fail"


@pytest.mark.parametrize("name", ["app/aggregates/calendar.py", "app\\aggregates\\calendar.py",
                                 "/home/runner/work/repo/src/backend/app/aggregates/calendar.py"])
def test_coverage_paths_are_normalized_on_both_sides(case, name):
    write_json(case["before"], coverage([79, 80, 85], name=name))
    write_json(case["current"], coverage([78], name=name))
    assert check.main(case["argv"]) == 0


def test_exclusions_keep_existing_package_scope_rules(case):
    policy = deepcopy(case["policy"]["files"])
    policy[0]["path"] = "src/backend/app/domain/calendar.py"
    write_json(case["current"], coverage([78], name="app\\domain\\calendar.py"))
    raw, adjusted, _ = ratchet.adjusted_measurement(case["current"], policy, label="current")
    for scope in ("total", "domain"):
        assert adjusted[scope] == [raw[scope][0] - 1, raw[scope][1] - 7]
    for scope in ("importing", "signals", "advice", "llm"):
        assert adjusted[scope] == raw[scope]


@pytest.mark.parametrize("change", ["anchor", "source", "shift", "truncated"])
def test_anchor_changes_or_source_line_drift_fail_with_location(case, tmp_path, monkeypatch, capsys, change):
    root = tmp_path / "source-copy"
    source = root / CALENDAR
    source.parent.mkdir(parents=True)
    text = (REPO / CALENDAR).read_text(encoding="utf-8").splitlines()
    if change == "anchor":
        case["policy"]["files"][0]["anchors"]["78"] += " changed"
        write_json(case["whitelist"], case["policy"])
    elif change == "source":
        text[77] += " # changed"
    elif change == "shift":
        text.insert(77, "# an inserted line")
    else:
        text = text[:77]
    source.write_text("\n".join(text) + "\n", encoding="utf-8")
    monkeypatch.setattr(ratchet, "ROOT", root)
    assert check.main(case["argv"]) == 1
    assert f"{CALENDAR}:78: anchor mismatch" in capsys.readouterr().err
    assert not case["output"].exists()


@pytest.fixture
def base_anchor_drift_case(case, tmp_path, monkeypatch):
    root = tmp_path / "repo"
    source = root / CALENDAR
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(f"value_{n} = {n}" if n != 83 else ""
                                for n in range(1, 86)) + "\n", encoding="utf-8")

    def git(*args):
        return subprocess.check_output([
            "git", "-C", str(root), "-c", "user.name=Synthetic Review",
            "-c", "user.email=review@example.invalid", "-c", "commit.gpgsign=false",
            *args], text=True).strip()

    git("init", "-q")
    git("add", CALENDAR)
    git("commit", "-qm", "deterministic base source")
    case["trusted"]["commit"] = git("rev-parse", "HEAD")
    source.write_text((REPO / CALENDAR).read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(ratchet, "ROOT", root)
    write_json(case["before"], coverage(LINES))
    case["trusted"]["counts"] = ratchet.measured(case["before"])
    write_json(case["frozen"], case["trusted"])
    index = case["argv"].index("--base-source-root")
    del case["argv"][index:index + 2]  # Exercise the production git-show path.
    assert case["trusted"]["counts"]["total"] == [19267, 25198]
    assert ratchet.measured(case["current"])["total"] == [19261, 25198]
    return case


def assert_base_anchor_drift_rejected(main, case, capsys):
    assert main(case["argv"]) == 1, "Base anchor drift must fail"
    assert f"{CALENDAR}:78: base anchor mismatch" in capsys.readouterr().err
    assert not case["output"].exists()


def test_base_anchor_drift_must_fail(base_anchor_drift_case, capsys):
    assert_base_anchor_drift_rejected(check.main, base_anchor_drift_case, capsys)


def test_mutation_removing_base_anchor_validation_is_caught(base_anchor_drift_case, tmp_path, capsys):
    text = Path(check.__file__).read_text(encoding="utf-8")
    needle = "        validate_base_anchors(exclusions, trusted.get(\"commit\"), source_root=args.base_source_root)\n"
    assert text.count(needle) == 1
    mutant_path = tmp_path / "mutant_check_coverage.py"
    mutant_path.write_text(text.replace(needle, "", 1), encoding="utf-8")
    namespace = {"__file__": check.__file__}  # Keep the real default policy paths.
    exec(compile(mutant_path.read_text(), str(mutant_path), "exec"), namespace)
    assert_base_anchor_drift_rejected(check.main, base_anchor_drift_case, capsys)
    with pytest.raises(AssertionError, match="Base anchor drift must fail"):
        assert_base_anchor_drift_rejected(namespace["main"], base_anchor_drift_case, capsys)
    result = json.loads(base_anchor_drift_case["output"].read_text())
    assert result["ratchet_passed"] is True
    assert result["comparison"]["counts"]["total"] == [19260, 25191]
    assert result["comparison"]["base_counts"]["total"] == [19260, 25191]


@pytest.mark.parametrize("change", ["anchor", "shift", "truncated", "missing"])
def test_injected_base_source_must_match_anchors(case, tmp_path, capsys, change):
    root = tmp_path / "base-source"
    source = root / CALENDAR
    source.parent.mkdir(parents=True)
    lines = (REPO / CALENDAR).read_text(encoding="utf-8").splitlines()
    if change == "anchor":
        lines[77] += " # changed"
    elif change == "shift":
        lines.insert(77, "# an inserted line")
    elif change == "truncated":
        lines = lines[:77]
    if change != "missing":
        source.write_text("\n".join(lines) + "\n", encoding="utf-8")
    case["argv"][case["argv"].index("--base-source-root") + 1] = str(root)
    assert check.main(case["argv"]) == 1
    message = "missing or unreadable base source" if change == "missing" else "base anchor mismatch"
    assert f"{CALENDAR}:78: {message}" in capsys.readouterr().err
    assert not case["output"].exists()


@pytest.mark.parametrize("change", ["missing_commit", "unknown_commit", "missing_file"])
def test_git_base_source_is_required(base_anchor_drift_case, monkeypatch, capsys, change):
    case = base_anchor_drift_case
    if change == "missing_commit":
        case["trusted"].pop("commit")
    elif change == "unknown_commit":
        case["trusted"]["commit"] = "f" * 40
    else:
        case["policy"]["files"][0]["path"] = "src/backend/app/aggregates/other.py"
        root = ratchet.ROOT
        (root / case["policy"]["files"][0]["path"]).write_text(
            (REPO / CALENDAR).read_text(encoding="utf-8"), encoding="utf-8")
        write_json(case["whitelist"], case["policy"])
    write_json(case["frozen"], case["trusted"])
    assert check.main(case["argv"]) == 1
    error = capsys.readouterr().err
    assert ("trusted base commit" if change == "missing_commit" else "base source") in error
    assert not case["output"].exists()


def test_git_base_allows_differences_outside_anchors(base_anchor_drift_case, capsys):
    case = base_anchor_drift_case
    # The parent is the deterministic base; this new commit has matching anchors
    # but differs from the working tree outside the registered lines.
    source = ratchet.ROOT / CALENDAR
    current = source.read_text(encoding="utf-8")
    source.write_text(current + "\n# unrelated base-only comment\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(ratchet.ROOT), "add", CALENDAR], check=True)
    subprocess.run(["git", "-C", str(ratchet.ROOT), "-c", "user.name=Synthetic Review",
                    "-c", "user.email=review@example.invalid", "-c", "commit.gpgsign=false",
                    "commit", "-qm", "matching base anchors"], check=True)
    case["trusted"]["commit"] = subprocess.check_output(
        ["git", "-C", str(ratchet.ROOT), "rev-parse", "HEAD"], text=True).strip()
    write_json(case["frozen"], case["trusted"])
    source.write_text(current, encoding="utf-8")
    assert check.main(case["argv"]) == 0
    assert not capsys.readouterr().err


@pytest.mark.parametrize("today", [date(2026, 12, 15), date(2026, 12, 16)])
def test_expiration_includes_review_day(today):
    with pytest.raises(ValueError, match=rf"{CALENDAR}:78: expired"):
        ratchet.load_nondet_lines(ratchet.NONDET_PATH, today=today)


def test_expiration_uses_utc_date(case, monkeypatch, capsys):
    class UTCClock:
        @staticmethod
        def now(tz):
            assert tz is timezone.utc
            return datetime(2099, 12, 15, 0, 1, tzinfo=timezone.utc)

    monkeypatch.setattr(ratchet, "datetime", UTCClock)
    assert check.main(case["argv"]) == 1
    assert f"{CALENDAR}:78: expired" in capsys.readouterr().err
    assert not case["output"].exists()


@pytest.mark.parametrize("missing", ["argument", "file"])
def test_nonempty_whitelist_requires_base_coverage(case, capsys, missing):
    argv = case["argv"].copy()
    if missing == "argument":
        index = argv.index("--base-coverage")
        del argv[index:index + 2]
    else:
        case["before"].unlink()
    assert check.main(argv) == 1
    error = capsys.readouterr().err
    assert "--base-coverage" in error if missing == "argument" else "before.json" in error
    assert not case["output"].exists()


def test_supplied_base_json_must_match_trusted_official_counts(case, capsys):
    write_json(case["before"], coverage([79, 80, 85], lost_line=True))
    assert check.main(case["argv"]) == 1
    assert "Base coverage.json counts disagree" in capsys.readouterr().err
    assert not case["output"].exists()


@pytest.mark.parametrize("side", ["current", "before"])
@pytest.mark.parametrize("line", [78, 81])
def test_registered_lines_must_be_statements_in_each_json(case, capsys, side, line):
    data = json.loads(case[side].read_text())
    info = data["files"][CALENDAR]
    for key in ("executed_lines", "missing_lines"):
        if line in info[key]:
            info[key].remove(line)
    write_json(case[side], data)
    assert check.main(case["argv"]) == 1
    assert f"{CALENDAR}:{line}: not a statement" in capsys.readouterr().err


@pytest.mark.parametrize("mutation", ["expiry", "anchor"])
def test_mutation_removing_validation_is_caught(case, tmp_path, mutation):
    text = Path(ratchet.__file__).read_text(encoding="utf-8")
    if mutation == "expiry":
        needle = "if review_by <= today:"
        replacement = "if False:  # mutated: expiry check removed"
        today = date(2100, 1, 1)
        message = "expired"
    else:
        needle = "if line > len(text) or text[line - 1].strip() != anchors[str(line)]:"
        replacement = "if False:  # mutated: anchor check removed"
        today = date(2026, 11, 15)
        message = "anchor mismatch"
        case["policy"]["files"][0]["anchors"]["78"] += " changed"
        write_json(case["whitelist"], case["policy"])
    assert text.count(needle) == 1
    mutant_path = tmp_path / "mutant_coverage_ratchet.py"
    mutant_path.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    namespace = {"__file__": str(mutant_path)}
    exec(compile(mutant_path.read_text(), str(mutant_path), "exec"), namespace)

    def rejects_invalid_policy(load):
        with pytest.raises(ValueError, match=message):
            load(case["whitelist"], root=REPO, today=today)

    rejects_invalid_policy(ratchet.load_nondet_lines)
    # The same critical assertion fails on a source copy without the guard.
    with pytest.raises(pytest.fail.Exception, match="DID NOT RAISE"):
        rejects_invalid_policy(namespace["load_nondet_lines"])


def archive(record, data=None):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as output:
        output.writestr("coverage-ratchet-measurement.json", json.dumps(record))
        if data is not None:
            output.writestr("coverage.json", json.dumps(data))
    return stream.getvalue()


@pytest.mark.parametrize("with_coverage", [True, False])
def test_freezer_exports_only_raw_json_from_the_validated_artifact(case, tmp_path, monkeypatch, with_coverage):
    trusted = deepcopy(case["trusted"])
    trusted.update(commit="b" * 40, run_id="123", attempt="1")
    data = json.loads(case["before"].read_text())
    # An embedded measurement field cannot substitute for the archive's file.
    trusted["_coverage_json"] = data
    frozen = loader.read_artifact(archive(trusted, data if with_coverage else None), "b" * 40, 123, 1)
    assert frozen["counts"] == trusted["counts"]
    monkeypatch.setattr(loader, "base_identity", lambda event, env: ("owner/repo", "b" * 40))
    monkeypatch.setattr(loader, "api_reader", lambda repo: None)
    monkeypatch.setattr(loader, "wait_for_base", lambda *args, **kwargs: frozen)
    event = write_json(tmp_path / "event.json", {})
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    monkeypatch.setenv("GITHUB_EVENT_NAME", "pull_request")
    output, coverage_output = tmp_path / "official.json", tmp_path / "raw.json"
    monkeypatch.setattr(sys, "argv", ["loader", "--output", str(output),
                                      "--coverage-output", str(coverage_output)])
    assert loader.main() == (0 if with_coverage else 1)
    if not with_coverage:
        assert not output.exists() and not coverage_output.exists()
        return
    result = json.loads(output.read_text())
    assert result["counts"] == trusted["counts"]
    assert "_coverage_json" not in result
    assert json.loads(coverage_output.read_text()) == data


def test_freezer_rejects_artifact_json_counts_inconsistent_with_record(case):
    trusted = deepcopy(case["trusted"])
    trusted.update(commit="b" * 40, run_id="123", attempt="1")
    with pytest.raises(ValueError, match="coverage.json counts disagree"):
        loader.read_artifact(archive(trusted, coverage([78])), "b" * 40, 123, 1)


def test_empty_whitelist_keeps_raw_comparison_and_needs_no_base_json(case):
    write_json(case["whitelist"], {"schema": "aia-coverage-nondet-lines-v1", "files": []})
    argv = case["argv"].copy()
    index = argv.index("--base-coverage")
    del argv[index:index + 2]
    assert check.main(argv) == 1  # The original two-line loss is still a regression.
    result = json.loads(case["output"].read_text())
    assert result["comparison"]["counts"] == result["counts"]
    assert result["comparison"]["base_counts"] == case["trusted"]["counts"]
    assert result["comparison"]["exclusions"] == {"current": [], "base": []}

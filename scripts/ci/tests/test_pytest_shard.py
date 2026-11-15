"""Small partition, report-validation and JUnit merge regressions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from scripts.ci import check_shard_union, merge_junit, pytest_shard


def test_plan_deterministic_union_overhead_and_unknown_files():
    config = {"shards": 3, "shard_overhead_seconds": {"1": 3},
              "weights": {"a.py": 4, "b.py": 3, "c.py": 7, "d.py": 2}}
    files = ["a.py", "b.py", "c.py", "d.py", "unknown.py"]
    plan = pytest_shard.plan(files, config)
    assert plan == pytest_shard.plan(reversed(files), config)
    assert plan == [(["b.py", "unknown.py"], 7), (["c.py"], 7), (["a.py", "d.py"], 6)]
    assigned = [path for members, _ in plan for path in members]
    assert sorted(assigned) == sorted(files)
    assert len(assigned) == len(set(assigned))


def test_plugin_reports_full_collection_and_deselects(tmp_path, monkeypatch):
    settings = tmp_path / "config.json"
    settings.write_text(json.dumps({"shards": 2, "weights": {}}))
    monkeypatch.setattr(pytest_shard, "CONFIG", settings)
    monkeypatch.setattr(pytest_shard, "ROOT", tmp_path)
    report = tmp_path / "report.json"
    monkeypatch.setenv("AIA_SHARD_INDEX", "1")
    monkeypatch.setenv("AIA_SHARD_TOTAL", "2")
    monkeypatch.setenv("AIA_SHARD_REPORT", str(report))
    items = [Mock(path=tmp_path / name, nodeid=f"{name}::test_ok") for name in ("a.py", "b.py")]
    original = items[:]
    config = SimpleNamespace(hook=SimpleNamespace(pytest_deselected=Mock()))
    pytest_shard.pytest_collection_modifyitems(config, items)
    assert items == original[:1]
    config.hook.pytest_deselected.assert_called_once_with(items=original[1:])
    assert json.loads(report.read_text()) == {
        "shard": 1, "total": 2, "collected": [i.nodeid for i in original],
        "selected": [original[0].nodeid], "files": ["a.py"], "workers": 1,
    }
    monkeypatch.setenv("AIA_SHARD_TOTAL", "3")
    with pytest.raises(pytest.UsageError):
        pytest_shard.pytest_collection_modifyitems(config, original)
    monkeypatch.delenv("AIA_SHARD_INDEX")
    pytest_shard.pytest_collection_modifyitems(config, original)
    assert len(original) == 2


def union_inputs(tmp_path):
    baseline = tmp_path / "baseline.txt"
    nodes = ["backend/a.py::test_a", "backend/b.py::test_b", "backend/c.py::test_c"]
    baseline.write_text("\n".join(nodes) + "\n\n3 tests collected in 0.1s\n")
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"shards": 2, "weights": {}}))
    groups = tmp_path / "ci-groups.yaml"
    groups.write_text("version: 1\ntests:\n" + "".join(
        f'  - {{"file": "tests/backend/{n}.py", "group": "serial_pg"}}\n' for n in "abc"))
    reports = [
        {"shard": 1, "total": 2, "collected": nodes, "selected": nodes[:2],
         "files": ["tests/backend/a.py", "tests/backend/b.py"], "workers": 1},
        {"shard": 2, "total": 2, "collected": nodes, "selected": nodes[2:],
         "files": ["tests/backend/c.py"], "workers": 1},
    ]
    return ["--baseline", str(baseline), "--config", str(config), "--groups", str(groups)], reports


def write_reports(tmp_path, reports):
    paths = []
    for i, report in enumerate(reports):
        path = tmp_path / f"report-{i}.json"
        path.write_text(json.dumps(report))
        paths.append(str(path))
    return paths


@pytest.mark.parametrize("invalid", ["empty", "missing", "duplicate", "omission", "file-twice", "overlap",
                                     "collection", "unlisted", "multi-worker"])
def test_union_rejects_invalid_reports(tmp_path, capsys, invalid):
    args, reports = union_inputs(tmp_path)
    if invalid == "empty":
        reports.clear()
    elif invalid == "missing":
        reports.pop()
    elif invalid == "duplicate":
        reports[1]["shard"] = 1
    elif invalid == "omission":
        reports[1]["selected"] = []
    elif invalid == "file-twice":
        reports[1]["files"].append(reports[0]["files"][0])
    elif invalid == "overlap":
        reports[1]["selected"].append(reports[0]["selected"][0])
    elif invalid == "collection":
        reports[1]["collected"] = []
    elif invalid == "unlisted":
        reports[1]["files"] = ["tests/backend/z.py"]
    elif invalid == "multi-worker":
        reports[0]["workers"] = 4
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1
    assert "::error" in capsys.readouterr().out


def test_union_tolerates_random_param_ids_but_not_count_change(tmp_path):
    args, reports = union_inputs(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(baseline.read_text().replace("test_c", "test_c[uuid-1]"))
    reports[0]["collected"] = reports[1]["collected"] = [n.replace("test_c", "test_c[uuid-2]") for n in reports[0]["collected"]]
    reports[1]["selected"] = ["backend/c.py::test_c[uuid-3]"]
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 0
    reports[1]["selected"].append("backend/c.py::test_c[uuid-4]")
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1


def test_union_summary_with_junit(tmp_path, monkeypatch, capsys):
    args, reports = union_inputs(tmp_path)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for i in (1, 2):
        (tmp_path / f"backend-pytest-shard-{i}.xml").write_text(
            '<testsuites><testsuite><testcase time="1.2"/><testcase time="2.3"/></testsuite></testsuites>')
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 0
    output = capsys.readouterr().out
    assert "| 1 | 2 | 3.5 |" in output
    assert "| 2 | 1 | 3.5 |" in output
    assert summary.read_text() == output


def test_merge_junit_preserves_suites_and_case_details(tmp_path):
    documents = [
        '<testsuite name="one" tests="1"><testcase name="a" time="1"><failure message="failed"/></testcase></testsuite>',
        '<testsuites><testsuite name="two"><properties><property name="x" value="y"/></properties>'
        '<testcase name="b"><skipped/></testcase></testsuite><testsuite name="three">'
        '<testcase name="c"><system-out>log</system-out></testcase></testsuite></testsuites>',
    ]
    paths = []
    for i, document in enumerate(documents):
        path = tmp_path / f"{i}.xml"
        path.write_text(document)
        paths.append(str(path))
    output = tmp_path / "merged.xml"
    assert merge_junit.main(["--output", str(output), *paths]) == 0
    root = ET.parse(output).getroot()
    assert root.tag == "testsuites"
    expected = [ET.fromstring(documents[0]), *ET.fromstring(documents[1])]
    assert [ET.tostring(s) for s in root] == [ET.tostring(s) for s in expected]


def test_serial_skips_guard(tmp_path, capsys):
    from scripts.ci import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "tests/backend/unit/test_x.py", "group": "parallel"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}}))

    def run(cases):
        junit = tmp_path / "j.xml"
        junit.write_text("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>")
        return check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)])

    ok = '<testcase classname="backend.api_app.test_pg.TestA" name="a"/>'
    skip = '<testcase classname="backend.api_app.test_pg" name="s"><skipped message="no pg"/></testcase>'
    other = '<testcase classname="backend.unit.test_x" name="x"><skipped/></testcase>'
    assert run([ok, skip, other, other]) == 0
    assert run([ok, skip, skip]) == 1
    assert run([skip]) == 1
    assert "::error" in capsys.readouterr().out

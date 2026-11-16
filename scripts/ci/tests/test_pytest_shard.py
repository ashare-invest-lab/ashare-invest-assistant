"""Small partition, report-validation and JUnit merge regressions."""
import json
from types import SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

import check_shard_union  # scripts/ci 由 conftest 加入 sys.path（与其他自测一致）
import merge_junit
import pytest_shard


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
    config["colocate"] = [["a.py", "d.py"]]
    plan = pytest_shard.plan(files, config)
    assert any({"a.py", "d.py"} <= set(members) for members, _ in plan)


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
                                     "collection", "unlisted", "multi-worker", "colocate-split"])
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
    elif invalid == "colocate-split":
        config = tmp_path / "config.json"
        config.write_text(json.dumps({"shards": 2, "weights": {},
                                      "colocate": [["tests/backend/a.py", "tests/backend/c.py"]]}))
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1
    assert "::error" in capsys.readouterr().out


def test_union_tolerates_random_param_ids_but_not_count_change(tmp_path):
    args, reports = union_inputs(tmp_path)
    baseline = tmp_path / "baseline.txt"
    baseline.write_text(baseline.read_text().replace("test_c", "test_c[550e8400-e29b-41d4-a716-446655440000]"))
    reports[0]["collected"] = reports[1]["collected"] = [
        n.replace("test_c", "test_c[32f78a26-1111-4444-8888-123456789abc]") for n in reports[0]["collected"]]
    reports[1]["selected"] = ["backend/c.py::test_c[32f78a26111144448888123456789abd]"]
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 0
    reports[1]["selected"].append("backend/c.py::test_c[32f78a26-1111-4444-8888-123456789abe]")
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1


def test_union_summary_with_junit(tmp_path, monkeypatch, capsys):
    args, reports = union_inputs(tmp_path)
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    for i, report in enumerate(reports, 1):
        (tmp_path / f"backend-pytest-shard-{i}.xml").write_text(
            '<testsuites><testsuite>' + ''.join(
                f'<testcase name="{node}" time="{time}"/>'
                for node, time in zip(report["selected"], (1.2, 2.3))) + '</testsuite></testsuites>')
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 0
    output = capsys.readouterr().out
    assert "| 1 | 2 | 3.5 |" in output
    assert "| 2 | 1 | 1.2 |" in output
    assert summary.read_text() == output


def test_merge_junit_preserves_suites_and_case_details(tmp_path):
    documents = [
        '<testsuite name="one" tests="1"><testcase name="a" time="1"><system-err>log</system-err></testcase></testsuite>',
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
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "tests/backend/unit/test_x.py", "group": "parallel"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": 1}}))

    def run(cases):
        junit = tmp_path / "j.xml"
        junit.write_text("<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>")
        return check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)])

    ok = '<testcase classname="backend.api_app.test_pg.TestA" name="a"/>'
    skip = '<testcase classname="backend.api_app.test_pg" name="s"><skipped message="no pg"/></testcase>'
    other = '<testcase classname="backend.unit.test_x" name="x"><skipped/></testcase>'
    assert run([ok, skip, other]) == 0
    assert run([ok, skip, skip]) == 1
    assert run([skip]) == 1
    assert "::error" in capsys.readouterr().out


def test_serial_skips_guard_counts_module_skip(tmp_path, capsys):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n'
                      '  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n'
                      '  - {"file": "tests/backend/api_app/test_other_pg.py", "group": "serial_pg"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": 3}}))
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuites><testsuite>'
                     '<testcase classname="" name="backend.api_app.test_pg">'
                     '<skipped message="collection skipped"/></testcase>'
                     '<testcase classname="backend.api_app.test_other_pg" name="a"/>'
                     '<testcase classname="backend.api_app.test_other_pg" name="b"/>'
                     '</testsuite></testsuites>')

    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == 1
    output = capsys.readouterr().out
    assert "passed=2 skipped=1" in output
    assert "min_passed=3" in output
    assert "::error" in output


@pytest.mark.parametrize("passed,min_passed,expected", [(1, 2, 1), (2, 2, 0), (0, 0, 1)])
def test_serial_skips_guard_min_passed(tmp_path, capsys, passed, min_passed, expected):
    import check_serial_skips

    groups = tmp_path / "g.yaml"
    groups.write_text('version: 1\ntests:\n'
                      '  - {"file": "tests/backend/api_app/test_pg.py", "group": "serial_pg"}\n')
    config = tmp_path / "c.json"
    config.write_text(json.dumps({"max_skipped": {"serial_pg": 1}, "min_passed": {"serial_pg": min_passed}}))
    junit = tmp_path / "j.xml"
    junit.write_text('<testsuites><testsuite>' + ''.join(
        f'<testcase classname="backend.api_app.test_pg" name="test_{i}"/>' for i in range(passed)) +
        '<testcase classname="backend.api_app.test_pg" name="s"><skipped/></testcase>'
        '</testsuite></testsuites>')

    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == expected
    output = capsys.readouterr().out
    assert f"passed={passed} skipped=1" in output
    assert f"min_passed={min_passed}" in output
    assert ("::error" in output) == bool(expected)


def test_union_rejects_duplicate_non_uuid_params(tmp_path):
    args, reports = union_inputs(tmp_path)
    nodes = ["backend/c.py::test_x[a]", "backend/c.py::test_x[b]"]
    baseline = tmp_path / "baseline.txt"
    baseline.write_text("\n".join(reports[0]["collected"][:2] + nodes))
    for report in reports:
        report["collected"] = reports[0]["selected"] + nodes
    reports[1]["selected"] = nodes
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 0
    reports[1]["selected"] = [nodes[0], nodes[0]]
    assert check_shard_union.main(args + write_reports(tmp_path, reports)) == 1


@pytest.mark.parametrize("params", [("a", "b"), ("uuid-1", "uuid-2"),
                                    ("550e8400-e29b-41d4-a716-446655440000-a",
                                     "32f78a26-1111-4444-8888-123456789abc-b")])
def test_stable_id_preserves_non_uuid_parameters(params):
    assert check_shard_union.stable_id(f"a.py::test_x[{params[0]}]") != check_shard_union.stable_id(
        f"a.py::test_x[{params[1]}]")


@pytest.mark.parametrize("invalid", ["failure", "error", "zero", "duplicate-file", "duplicate-node",
                                     "duplicate-across-inputs", "zero-input-among-valid"])
def test_merge_rejects_bad_junit(tmp_path, invalid):
    root = ET.fromstring('<testsuite><testcase classname="backend.a" name="test_a"/></testsuite>')
    if invalid in {"failure", "error"}:
        ET.SubElement(root[0], invalid, message="bad result")
    elif invalid == "zero":
        root.clear()
    elif invalid == "duplicate-node":
        ET.SubElement(root, "testcase", classname="backend.a", name="test_a")
    path = tmp_path / "one.xml"
    ET.ElementTree(root).write(path)
    inputs = [str(path)]
    if invalid == "duplicate-file":
        inputs.append(str(path))
    elif invalid in {"duplicate-across-inputs", "zero-input-among-valid"}:
        second = tmp_path / "two.xml"
        second.write_text(ET.tostring(root, encoding="unicode") if invalid == "duplicate-across-inputs"
                          else '<testsuite/>')
        inputs.append(str(second))
    output = tmp_path / "merged.xml"
    assert merge_junit.main(["--output", str(output), *inputs]) == 1
    merged = ET.parse(output).getroot()
    if invalid in {"failure", "error"}:
        assert merged.find(f".//testcase/{invalid}").get("message") == "bad result"


@pytest.mark.parametrize("invalid", ["failure", "error", "zero", "too-few", "too-many",
                                     "duplicate-node", "duplicate-across-shards"])
def test_union_rejects_bad_junit(tmp_path, invalid):
    args, reports = union_inputs(tmp_path)
    roots = []
    for report in reports:
        root = ET.Element("testsuite")
        for node in report["selected"]:
            ET.SubElement(root, "testcase", classname="backend", name=node, time="1.2")
        roots.append(root)
    if invalid in {"failure", "error"}:
        ET.SubElement(roots[1][0], invalid)
    elif invalid == "zero":
        roots[1].clear()
    elif invalid == "too-few":
        roots[0].remove(roots[0][1])
    elif invalid == "too-many":
        ET.SubElement(roots[1], "testcase", classname="backend", name="extra")
    elif invalid == "duplicate-node":
        roots[0][1].set("name", roots[0][0].get("name"))
    else:
        roots[1][0].set("name", roots[0][0].get("name"))
    for i, root in enumerate(roots, 1):
        ET.ElementTree(root).write(tmp_path / f"backend-pytest-shard-{i}.xml")
    assert check_shard_union.main(args + ["--junit", str(tmp_path)] + write_reports(tmp_path, reports)) == 1


@pytest.mark.parametrize("invalid", ["failure", "error", "duplicate", "zero", "foreign-failure", "foreign-error"])
def test_serial_rejects_bad_junit_at_minimum(tmp_path, invalid, capsys):
    import check_serial_skips

    groups = tmp_path / "groups.yaml"
    groups.write_text('tests:\n  - {file: tests/backend/test_pg.py, group: serial_pg}\n')
    config = tmp_path / "config.json"
    config.write_text(json.dumps({"min_passed": {"serial_pg": 1190}, "max_skipped": {"serial_pg": 0}}))
    root = ET.Element("testsuite")
    for i in range(1190):
        ET.SubElement(root, "testcase", classname="backend.test_pg", name=f"test_{i}")
    if invalid == "zero":
        root.clear()
    else:
        case = ET.SubElement(root, "testcase", classname="backend.test_pg", name="bad")
        if invalid == "duplicate":
            case.set("name", "test_0")
        else:
            if invalid.startswith("foreign-"):
                case.set("classname", "backend.test_other")
            ET.SubElement(case, invalid.removeprefix("foreign-"))
    junit = tmp_path / "junit.xml"
    ET.ElementTree(root).write(junit)
    assert check_serial_skips.main([str(junit), "--groups", str(groups), "--config", str(config)]) == 1
    output = capsys.readouterr().out
    if invalid in {"failure", "error"}:
        assert "passed=1190 skipped=0 failed=1" in output

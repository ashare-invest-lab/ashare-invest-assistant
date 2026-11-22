from __future__ import annotations

import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import merge_junit
import pytest
import shard_backend_tests as shards


def _fixture_root(tmp_path: Path, entries: list[str], files: list[str]) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "scripts/ci").mkdir(parents=True)
    (tmp_path / "tests/ci-groups.yaml").write_text(
        "version: 1\ntests:\n" + "".join(
            f'  - {json.dumps({"file": name, "group": "parallel"})}\n' for name in entries
        ),
        encoding="utf-8",
    )
    (tmp_path / "scripts/ci/backend-test-durations.json").write_text(
        json.dumps({"seconds": {name: 10 for name in entries}}), encoding="utf-8"
    )
    for name in files:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("def test_fixture(): pass\n", encoding="utf-8")
    return tmp_path


def test_lpt_is_deterministic_and_covers_without_overlap(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path, ["tests/backend/test_a.py", "tests/backend/test_b.py"],
                         ["tests/backend/test_a.py", "tests/backend/test_b.py",
                          "tests/backend/test_unregistered.py"])
    files, durations = shards.load_files(root)
    first = shards.plan_shards(files, durations, 2)
    second = shards.plan_shards(files, durations, 2)
    assert first == second
    assert set().union(*map(set, first)) == files
    assert set(first[0]).isdisjoint(first[1])


def test_missing_yaml_file_is_an_error(tmp_path: Path) -> None:
    root = _fixture_root(tmp_path, ["tests/backend/test_missing.py"], [])
    with pytest.raises(FileNotFoundError, match="missing"):
        shards.load_files(root)


def _write_xml(path: Path, root: str, names: list[str]) -> None:
    if root == "testsuite":
        body = "<testsuite>"
        tail = "</testsuite>"
    else:
        body = "<testsuites><testsuite>"
        tail = "</testsuite></testsuites>"
    cases = "".join(f'<testcase classname="c" name="{name}" time="1"/>' for name in names)
    path.write_text(body + cases + tail, encoding="utf-8")


@pytest.mark.parametrize("first_root,second_root", [("testsuites", "testsuite"), ("testsuite", "testsuites")])
def test_merge_junit_supports_both_roots_and_counts_cases(
    tmp_path: Path, first_root: str, second_root: str
) -> None:
    first = tmp_path / "one.xml"
    second = tmp_path / "two.xml"
    output = tmp_path / "merged.xml"
    _write_xml(first, first_root, ["one", "two"])
    _write_xml(second, second_root, ["three"])
    assert merge_junit.merge(output, [first, second]) == 0
    root = ET.parse(output).getroot()
    assert root.tag == "testsuites"
    assert root.attrib["tests"] == "3"
    assert [case.attrib["name"] for case in root.iter("testcase")] == ["one", "two", "three"]


def test_merge_junit_cli_rejects_empty_inputs(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, str(Path(merge_junit.__file__)), "--output", str(tmp_path / "out.xml")],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2  # argparse：至少一个输入

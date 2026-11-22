from __future__ import annotations

import json
from pathlib import Path

import check_serial_skips as check


def _inputs(tmp_path: Path, passed: int, skipped: int, failed: int = 0) -> list[str]:
    groups = tmp_path / "groups.yaml"
    groups.write_text(
        "tests:\n  - file: tests/backend/test_serial.py\n    group: serial_pg\n",
        encoding="utf-8",
    )
    config = tmp_path / "baseline.json"
    config.write_text(
        json.dumps({"serial_pg": {"max_skipped": 2, "min_passed": 3}}), encoding="utf-8"
    )
    cases = []
    for index in range(passed):
        cases.append(f'<testcase file="tests/backend/test_serial.py" name="p{index}"/>')
    for index in range(skipped):
        cases.append(
            f'<testcase file="tests/backend/test_serial.py" name="s{index}"><skipped/></testcase>'
        )
    for index in range(failed):
        cases.append(
            f'<testcase file="tests/backend/test_serial.py" name="f{index}"><failure/></testcase>'
        )
    junit = tmp_path / "junit.xml"
    junit.write_text(
        "<testsuites><testsuite>" + "".join(cases) + "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return [str(junit), "--groups", str(groups), "--config", str(config)]


def test_counts_are_reported_and_valid(tmp_path: Path, capsys) -> None:
    assert check.main(_inputs(tmp_path, 3, 2)) == 0
    assert "passed=3 skipped=2" in capsys.readouterr().out


def test_failed_zero_passed_and_thresholds_fail(tmp_path: Path) -> None:
    assert check.main(_inputs(tmp_path, 0, 0)) == 1
    assert check.main(_inputs(tmp_path, 3, 3)) == 1
    assert check.main(_inputs(tmp_path, 2, 0)) == 1
    assert check.main(_inputs(tmp_path, 3, 0, failed=1)) == 1


def test_reference_baseline_has_sources_and_requested_floors() -> None:
    baseline = json.loads(
        Path("scripts/ci/serial-skip-baseline.json").read_text(encoding="utf-8")
    )
    assert baseline["serial_pg"] == {"max_skipped": 99, "min_passed": 1290}
    assert "44965913926" in baseline["source"] and "44957367134" in baseline["source"]


def test_workflow_places_serial_check_after_a1s_check() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert text.index("确认 serial_pg 用例未悄悄变成跳过") > text.index(
        "确认 A1s–A32 与 t_t41 已执行"
    )
    assert 'uv run --no-project --with "pyyaml==${PYYAML_VERSION}"' in text

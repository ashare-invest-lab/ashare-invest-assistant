from __future__ import annotations

import shutil
from pathlib import Path

import check_shard_artifacts as check


def _make_tree(root: Path) -> None:
    for shard in range(6):
        (root / f"backend-shard-{shard}").mkdir(parents=True)
        (root / f"backend-shard-{shard}" / f".coverage.shard{shard}").write_bytes(
            b"coverage"
        )
        (
            root / f"backend-shard-{shard}" / f"backend-pytest-shard{shard}.xml"
        ).write_text(
            '<testsuite><testcase classname="tests.backend.test_demo" name="ok"/></testsuite>',
            encoding="utf-8",
        )
    (root / "backend-shard-0" / "selfcheck-a1s-a32.xml").write_text(
        "<testsuite><testcase name='selfcheck'/></testsuite>", encoding="utf-8"
    )


def test_realistic_nested_artifacts_pass(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    assert check.check(tmp_path, 6) == []


def test_flattened_artifacts_pass(tmp_path: Path) -> None:
    # download-artifact merge-multiple 会把各片文件平铺到同一目录。
    nested = tmp_path / "nested"
    flat = tmp_path / "flat"
    flat.mkdir()
    _make_tree(nested)
    for path in nested.rglob("*"):
        if path.is_file():
            shutil.copy2(path, flat / path.name)
    assert check.check(flat, 6) == []


def test_missing_duplicate_and_out_of_range_are_all_reported(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    (tmp_path / "backend-shard-1" / ".coverage.shard1").unlink()
    (tmp_path / "backend-shard-0" / ".coverage.shard9").write_bytes(b"x")
    (tmp_path / "duplicate").mkdir()
    (tmp_path / "duplicate" / ".coverage.shard0").write_bytes(b"x")
    issues = check.check(tmp_path, 6)
    assert any("coverage 文件应有 6 个" in issue for issue in issues)
    assert any("编号应为" in issue for issue in issues)


def test_empty_coverage_and_invalid_junit_fail(tmp_path: Path) -> None:
    _make_tree(tmp_path)
    (tmp_path / "backend-shard-2" / ".coverage.shard2").write_bytes(b"")
    (tmp_path / "backend-shard-3" / "backend-pytest-shard3.xml").write_text(
        "<bad", encoding="utf-8"
    )
    issues = check.check(tmp_path, 6)
    assert any("覆盖率文件为空" in issue for issue in issues)
    assert any("JUnit 无法解析" in issue for issue in issues)


def test_workflow_has_six_matrix_shards_and_integrity_step() -> None:
    text = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "shard: [0, 1, 2, 3, 4, 5]" in text
    assert "核对分片归档完整性" in text
    assert "--shards 6" in text

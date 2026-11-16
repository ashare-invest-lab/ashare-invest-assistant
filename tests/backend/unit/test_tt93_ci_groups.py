"""T-T93：只读清单守护；不导入测试模块、不请求资源 fixture、不嵌套收集。

独立 pytest 运行校验现存文件集合（包含因依赖缺失而未收集的文件）。
显式 backend+replay collect-only 后，可执行本文件传入日志，严格对账该子集；
日志含 src/backend/tests 模块时也严格对账其完整子集。
若 importorskip/收集错误等导致树与收集不一致，输出差集并失败，不能静默删清单项。
"""

from __future__ import annotations

import configparser
from collections import Counter
from pathlib import Path, PurePosixPath

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tests/ci-groups.yaml"
GROUPS = frozenset({"serial_pg", "serial_port", "serial_shared", "parallel"})


def _validated_files() -> set[str]:
    config = configparser.ConfigParser()
    config.read(ROOT / "tests/pytest.ini", encoding="utf-8")
    # 配置变化必须重新审查范围，防止守护与实际发现规则悄悄分叉。
    assert config["pytest"]["testpaths"].split() == ["backend", "replay"]
    assert config["pytest"]["python_files"].split() == ["test_*.py"]
    expected = {
        path.relative_to(ROOT).as_posix()
        for directory in ("tests/backend", "tests/replay", "src/backend/tests")
        for path in (ROOT / directory).rglob("test_*.py")
        if path.is_file()
    }
    document = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
    assert isinstance(document, dict) and document.get("version") == 1
    entries = document.get("tests")
    assert isinstance(entries, list) and entries, "tests 必须为非空列表"
    files = []
    for entry in entries:
        assert isinstance(entry, dict), f"非法条目：{entry!r}"
        filename = entry.get("file")
        assert isinstance(filename, str) and filename, "file 必须为非空字符串"
        path = PurePosixPath(filename)
        assert not path.is_absolute() and ".." not in path.parts and "\\" not in filename
        assert path.as_posix() == filename, f"路径必须为规范 POSIX 相对路径：{filename}"
        assert entry.get("group") in GROUPS, f"非法 group：{filename}"
        keywords = entry.get("keywords")
        assert isinstance(keywords, list) and keywords, f"缺少判定依据：{filename}"
        assert all(isinstance(word, str) and word.strip() for word in keywords), filename
        assert type(entry.get("unverified")) is bool, f"缺少未验证标记：{filename}"
        if entry["unverified"]:
            assert entry["group"] != "parallel", f"未验证文件不能并行：{filename}"
            assert isinstance(entry.get("reason"), str) and entry["reason"].strip(), filename
        assert (ROOT / filename).is_file(), f"路径不存在：{filename}"
        files.append(filename)
    duplicates = sorted(name for name, count in Counter(files).items() if count > 1)
    assert not duplicates, f"清单重复：{duplicates}"
    actual = set(files)
    assert actual == expected, (
        f"清单缺失：{sorted(expected - actual)}\n清单多余：{sorted(actual - expected)}"
    )
    return actual


def test_tt93_ci_groups_cover_backend_files() -> None:
    _validated_files()


def assert_tt93_collection_matches(log: Path) -> None:
    """消费显式 backend+replay 的 pytest --collect-only -q 输出，不触发收集。"""
    expected = _validated_files()
    expected_tests = {
        name for name in expected if name.startswith(("tests/backend/", "tests/replay/"))
    }
    expected_src = {name for name in expected if name.startswith("src/backend/tests/")}
    assert expected == expected_tests | expected_src, "清单有不支持的对账路径"
    collected_tests, collected_src = set(), set()
    lines = log.read_text(encoding="utf-8").splitlines()
    for line in lines:
        module, separator, _ = line.partition("::")
        if separator and module.startswith(("backend/", "replay/", "tests/backend/", "tests/replay/")):
            collected_tests.add(module if module.startswith("tests/") else "tests/" + module)
        elif separator and module.startswith("src/backend/tests/"):
            collected_src.add(module)
    # 显式 backend+replay 日志可不含 src；一旦含有，src 子集也必须完整对账。
    missing = sorted(
        (expected_tests - collected_tests)
        | (expected_src - collected_src if collected_src else set())
    )
    extra = sorted((collected_tests - expected_tests) | (collected_src - expected_src))
    print(f"清单有而 collect 无：{missing}\ncollect 有而清单无：{extra}")
    assert not any(line.startswith("ERROR ") for line in lines), "collect-only 有收集错误"
    assert not missing and not extra, "树/清单/collect 模块不一致，检查跳过依赖或发现规则"


@pytest.mark.parametrize(
    ("modules", "error", "fails"),
    [
        (["backend/a.py", "replay/b.py"], "", False),
        (["tests/backend/a.py", "tests/replay/b.py"], "", False),
        (
            ["backend/a.py", "replay/b.py", "src/backend/tests/c.py", "src/backend/tests/d.py"],
            "", False,
        ),
        (["backend/a.py"], "", True),
        (["backend/a.py", "replay/b.py", "backend/extra.py"], "", True),
        (["backend/a.py", "replay/b.py", "src/backend/tests/c.py"], "", True),
        (
            ["backend/a.py", "replay/b.py", "src/backend/tests/c.py",
             "src/backend/tests/d.py", "src/backend/tests/extra.py"],
            "", True,
        ),
        (["backend/a.py", "replay/b.py"], "ERROR collecting backend/a.py", True),
    ],
)
def test_tt93_collection_subsets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, modules: list[str], error: str, fails: bool
) -> None:
    expected = {
        "tests/backend/a.py", "tests/replay/b.py",
        "src/backend/tests/c.py", "src/backend/tests/d.py",
    }
    monkeypatch.setitem(assert_tt93_collection_matches.__globals__, "_validated_files", lambda: expected)
    log = tmp_path / "collect.log"
    log.write_text("\n".join([*(f"{module}::test_case" for module in modules), error]), encoding="utf-8")
    if fails:
        message = "collect-only 有收集错误" if error else "树/清单/collect 模块不一致"
        with pytest.raises(AssertionError, match=message):
            assert_tt93_collection_matches(log)
    else:
        assert_tt93_collection_matches(log)


if __name__ == "__main__":
    import sys

    assert len(sys.argv) == 2, "用法：python tests/backend/unit/test_tt93_ci_groups.py COLLECT_LOG"
    assert_tt93_collection_matches(Path(sys.argv[1]))

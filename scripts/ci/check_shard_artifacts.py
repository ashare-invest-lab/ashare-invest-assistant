#!/usr/bin/env python3
"""核对后端分片覆盖率、JUnit 与自检归档。"""

from __future__ import annotations

import argparse
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def _files(directory: Path, pattern: re.Pattern[str]) -> list[tuple[int, Path]]:
    found = []
    for path in directory.rglob("*"):
        if path.is_file():
            match = pattern.fullmatch(path.name)
            if match:
                found.append((int(match.group("shard")), path))
    return found


def check(directory: Path, shards: int) -> list[str]:
    issues: list[str] = []
    expected = set(range(shards))
    coverage = _files(directory, re.compile(r"\.coverage\.shard(?P<shard>\d+)"))
    junit = _files(directory, re.compile(r"backend-pytest-shard(?P<shard>\d+)\.xml"))
    for label, entries in (("coverage", coverage), ("JUnit", junit)):
        numbers = [number for number, _ in entries]
        if len(entries) != shards:
            issues.append(f"{label} 文件应有 {shards} 个，实际 {len(entries)} 个")
        if set(numbers) != expected:
            issues.append(
                f"{label} 编号应为 {sorted(expected)}，实际 {sorted(numbers)}"
            )
        if len(numbers) != len(set(numbers)):
            issues.append(f"{label} 存在重复分片编号")
    for _, path in coverage:
        if path.stat().st_size == 0:
            issues.append(f"覆盖率文件为空：{path.name}")
    selfchecks = [
        path
        for path in directory.rglob("*")
        if path.is_file() and path.name == "selfcheck-a1s-a32.xml"
    ]
    for path in [path for _, path in junit] + selfchecks:
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as error:
            issues.append(f"JUnit 无法解析 {path.name}：{error}")
            continue
        if not list(root.iter("testcase")):
            issues.append(f"JUnit 没有 testcase：{path.name}")
    if len(selfchecks) != 1:
        issues.append(f"selfcheck-a1s-a32.xml 应有 1 个，实际 {len(selfchecks)} 个")
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--shards", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        issues = check(args.dir, args.shards)
    except OSError as error:
        issues = [str(error)]
    if issues:
        print("::error title=backend artifacts::" + "；".join(issues))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

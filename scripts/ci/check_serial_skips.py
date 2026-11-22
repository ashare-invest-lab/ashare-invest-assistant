#!/usr/bin/env python3
"""确认 serial_pg 测试没有因分片或缺库而悄悄跳过。"""

from __future__ import annotations

import argparse
import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import yaml


def _read_policy(path: Path, group: str) -> dict[str, int]:
    config = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise TypeError(f"{path} 顶层必须是对象")
    policy = config.get(group)
    if not isinstance(policy, dict):
        raise TypeError(f"{path} 缺少 {group} 基线")
    values: dict[str, int] = {}
    for name in ("max_skipped", "min_passed"):
        value = policy.get(name)
        if type(value) is not int or value < 0:
            raise ValueError(f"{path} 的 {group}.{name} 无效")
        values[name] = value
    return values


def case_file(case: ET.Element, files: set[str]) -> str | None:
    """按 JUnit 的 file、完整类名和模块名匹配注册文件。"""
    if case.get("file"):
        path = case.get("file", "").replace("\\", "/").lstrip("./")
        for candidate in (path, "tests/" + path):
            if candidate in files:
                return candidate
    qualified = (case.get("classname") or case.get("name") or "").lstrip(".")
    parts = qualified.split(".")
    stem = parts[0] if parts else ""
    while parts:
        path = "/".join(parts) + ".py"
        for candidate in (path, "tests/" + path):
            if candidate in files:
                return candidate
        parts.pop()
    matches = [path for path in files if Path(path).stem == stem]
    return matches[0] if len(matches) == 1 else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--groups", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--trusted-config", type=Path)
    parser.add_argument("--group", default="serial_pg")
    args = parser.parse_args(argv)
    try:
        config_policy = _read_policy(args.config, args.group)
        policy = config_policy
        config_relaxes_trusted = False
        if args.trusted_config is not None:
            if args.trusted_config.exists():
                trusted_policy = _read_policy(args.trusted_config, args.group)
                config_relaxes_trusted = (
                    config_policy["max_skipped"] > trusted_policy["max_skipped"]
                    or config_policy["min_passed"] < trusted_policy["min_passed"]
                )
                policy = trusted_policy
            else:
                print(
                    f"trusted 基线文件不存在，退回使用 --config：{args.trusted_config}"
                )
        groups = yaml.safe_load(args.groups.read_text(encoding="utf-8"))
        files = {row["file"] for row in groups["tests"] if row["group"] == args.group}
        counts = {"passed": 0, "skipped": 0, "failed": 0}
        root = ET.parse(args.junit).getroot()
        for case in root.iter("testcase"):
            if case_file(case, files) is None:
                continue
            if case.find("failure") is not None or case.find("error") is not None:
                counts["failed"] += 1
            elif case.find("skipped") is not None:
                counts["skipped"] += 1
            else:
                counts["passed"] += 1
        print(
            f"{args.group}: passed={counts['passed']} skipped={counts['skipped']} "
            f"failed={counts['failed']} (max_skipped={policy['max_skipped']} "
            f"min_passed={policy['min_passed']})"
        )
        errors = []
        if counts["failed"] > 0:
            errors.append(f"failed {counts['failed']} > 0")
        if counts["passed"] == 0:
            errors.append("passed == 0")
        if counts["passed"] < policy["min_passed"]:
            errors.append(
                f"passed {counts['passed']} < min_passed {policy['min_passed']}"
            )
        if counts["skipped"] > policy["max_skipped"]:
            errors.append(
                f"skipped {counts['skipped']} > max_skipped {policy['max_skipped']}"
            )
        if config_relaxes_trusted:
            errors.append("基线放宽须先单独合入 main")
        if errors:
            raise ValueError("; ".join(errors))
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        ET.ParseError,
        yaml.YAMLError,
    ) as error:
        print(f"::error title=serial skips::{error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

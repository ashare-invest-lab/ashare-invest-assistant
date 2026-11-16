#!/usr/bin/env python3
"""T-O100: real-PG tests (tests/ci-groups.yaml serial_pg) must not silently turn into skips after sharding."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import yaml

from junit_validation import validate_junit


def case_file(case: ET.Element, files: set[str]) -> str | None:
    """Map a JUnit testcase to its tests/ file (classname may carry a class suffix)."""
    if case.get("file") and "tests/" + case.get("file", "") in files:
        return "tests/" + case.get("file", "")
    parts = (case.get("classname") or case.get("name") or "").split(".")
    while parts:
        path = "tests/" + "/".join(parts) + ".py"
        if path in files:
            return path
        parts.pop()
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("junit", type=Path)
    parser.add_argument("--groups", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--group", default="serial_pg")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        limit = config["max_skipped"][args.group]
        min_passed = config["min_passed"][args.group]
        files = {row["file"] for row in yaml.safe_load(args.groups.read_text(encoding="utf-8"))["tests"]
                 if row["group"] == args.group}
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
        print(f"{args.group}: passed={counts['passed']} skipped={counts['skipped']} "
              f"failed={counts['failed']} (max_skipped={limit} min_passed={min_passed})")
        if counts["failed"] > 0:
            raise ValueError(f"{args.group}: {counts['failed']} failed testcases")
        validate_junit(root)
        if counts["passed"] == 0:
            raise ValueError(f"{args.group}: no test ran")
        if counts["passed"] < min_passed:
            raise ValueError(f"{args.group}: passed {counts['passed']} < minimum {min_passed}")
        if counts["skipped"] > limit:
            raise ValueError(f"{args.group}: skipped {counts['skipped']} > baseline {limit}")
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError, yaml.YAMLError) as error:
        print(f"::error title=serial skips::{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

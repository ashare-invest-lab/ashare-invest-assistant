#!/usr/bin/env python3
"""T-O120：把各分片 JUnit（根为 testsuites 或 testsuite）合并成一个 <testsuites>，不丢任何 testcase。"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def merge(output: Path, inputs: list[Path]) -> int:
    merged = ET.Element("testsuites")
    for path in inputs:
        root = ET.parse(path).getroot()
        merged.extend([root] if root.tag == "testsuite" else root.findall("testsuite"))
    cases = list(merged.iter("testcase"))
    if not cases:
        print("merge_junit: no testcase in inputs", file=sys.stderr)
        return 1
    merged.set("tests", str(len(cases)))
    for tag, attr in (("failure", "failures"), ("error", "errors"), ("skipped", "skipped")):
        merged.set(attr, str(sum(case.find(tag) is not None for case in cases)))
    ET.ElementTree(merged).write(output, encoding="utf-8", xml_declaration=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", "-o", required=True, type=Path)
    parser.add_argument("inputs", nargs="+", type=Path)
    args = parser.parse_args(argv)
    return merge(args.output, args.inputs)


if __name__ == "__main__":
    sys.exit(main())

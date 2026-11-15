#!/usr/bin/env python3
"""T-O90 (G-STAGE6①): merge sharded JUnit XMLs into one backend-pytest.xml.

assert_a1s_a32_ran.py and readers consume one junit xml; shards produce several.
This unions <testsuite> children under one <testsuites> root without altering
case data; duplicates across shards would fail later identity checks, but we
also count and refuse exact duplicate (classname,name) pairs defensively.
"""
from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    root = ET.Element("testsuites", {"name": "backend-sharded"})
    seen: set[tuple[str, str]] = set()
    t = f = e = s = 0
    for path in args.inputs:
        tree = ET.parse(path)
        top = tree.getroot()
        suites = [top] if top.tag == "testsuite" else list(top.findall("testsuite"))
        if not suites and top.tag == "testsuites":
            suites = list(top)
        for suite in suites:
            for case in suite.findall("testcase"):
                key = (case.get("classname", ""), case.get("name", ""))
                if key in seen:
                    print(f"::error title=junit-merge::duplicate case {key}", file=sys.stderr)
                    return 1
                seen.add(key)
            root.append(suite)
            t += int(suite.get("tests", 0)); f += int(suite.get("failures", 0))
            e += int(suite.get("errors", 0)); s += int(suite.get("skipped", 0))
    root.set("tests", str(t)); root.set("failures", str(f))
    root.set("errors", str(e)); root.set("skipped", str(s))
    ET.ElementTree(root).write(args.output, encoding="utf-8", xml_declaration=True)
    print(f"merged {len(args.inputs)} junit shards -> {t} tests ({f}f/{e}e/{s}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Merge JUnit documents without discarding suites or testcase details."""
from __future__ import annotations

import argparse
from pathlib import Path
import xml.etree.ElementTree as ET


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("inputs", type=Path, nargs="+")
    args = parser.parse_args(argv)
    merged = ET.Element("testsuites")
    for path in args.inputs:
        root = ET.parse(path).getroot()
        if root.tag == "testsuite":
            merged.append(root)
        elif root.tag == "testsuites":
            merged.extend(root)
        else:
            raise ValueError(f"{path}: expected testsuite or testsuites")
    ET.ElementTree(merged).write(args.output, encoding="utf-8", xml_declaration=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Shared fail-closed checks for pytest JUnit artifacts."""
from __future__ import annotations

import xml.etree.ElementTree as ET


def validate_junit(root: ET.Element, seen: set[tuple[str, str]] | None = None) -> list[ET.Element]:
    if root.tag not in {"testsuite", "testsuites"}:
        raise ValueError("expected testsuite or testsuites")
    cases = list(root.iter("testcase"))
    if not cases:
        raise ValueError("JUnit has zero testcases")
    if next(root.iter("failure"), None) is not None or next(root.iter("error"), None) is not None:
        raise ValueError("JUnit contains failure or error")
    if seen is None:
        seen = set()
    for case in cases:
        node = (case.get("classname", ""), case.get("name", ""))
        if node in seen:
            raise ValueError(f"duplicate JUnit node: {node}")
        seen.add(node)
    return cases

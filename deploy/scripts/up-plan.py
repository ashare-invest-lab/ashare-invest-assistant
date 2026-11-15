#!/usr/bin/env python3
"""Plan up.sh's two phases from resolved Compose JSON; emit service names only."""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-deps", action="store_true")
    parser.add_argument("services", nargs="*")
    args = parser.parse_args()
    services = json.load(sys.stdin)["services"]
    ordered: list[str] = []
    visited: set[str] = set()
    visiting: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name not in services:
            parser.error(f"未知服务：{name}")
        if name in visiting:
            parser.error(f"服务依赖存在环：{name}")
        visiting.add(name)
        if not args.no_deps:
            for dependency in services[name].get("depends_on", {}):
                visit(dependency)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in args.services:
        visit(name)
    for name in ordered:
        kind = "job" if services[name].get("restart", "no") == "no" else "service"
        print(kind, name)


if __name__ == "__main__":
    main()

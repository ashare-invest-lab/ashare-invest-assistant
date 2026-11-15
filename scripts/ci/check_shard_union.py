"""Fail closed unless shard reports form an exact partition of collection."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import xml.etree.ElementTree as ET
from collections import Counter


def stable_id(nodeid: str) -> str:
    """Compare per test function: a few existing params use random ids (uuid4), so the
    bracketed part differs between processes. Counts per function must still match exactly."""
    return nodeid.split("[", 1)[0]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--junit", type=Path)
    parser.add_argument("--groups", type=Path, help="tests/ci-groups.yaml (T-T93); every shard file must be listed")
    parser.add_argument("reports", type=Path, nargs="*")
    args = parser.parse_args(argv)
    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        baseline_ids = [line.strip() for line in args.baseline.read_text(encoding="utf-8").splitlines()
                        if "::" in line]
        baseline = Counter(map(stable_id, baseline_ids))
        reports = [json.loads(path.read_text(encoding="utf-8")) for path in args.reports]
        total = config["shards"]
        if len(reports) != total or sorted(r["shard"] for r in reports) != list(range(1, total + 1)):
            raise ValueError("expected exactly one report for each shard 1..N")
        if not baseline:
            raise ValueError("baseline collection is empty")
        union = Counter()
        owners = {}
        for report in reports:
            if report["total"] != total or report.get("workers") != 1:
                raise ValueError(f"shard {report['shard']}: wrong total or not single-worker")
            if Counter(map(stable_id, report["collected"])) != baseline:
                raise ValueError(f"shard {report['shard']}: collection differs from baseline")
            for path in report["files"]:
                if path in owners:
                    raise ValueError(f"{path} selected by shards {owners[path]} and {report['shard']}")
                owners[path] = report["shard"]
            union.update(map(stable_id, report["selected"]))
        if union != baseline:
            diff = (union - baseline) + (baseline - union)
            raise ValueError(f"selected union differs from baseline: {sorted(diff)[:5]}")
        if args.groups:
            import yaml  # only the --groups check needs PyYAML

            listed = {row["file"] for row in yaml.safe_load(args.groups.read_text(encoding="utf-8"))["tests"]}
            unknown = sorted(set(owners) - listed)
            if unknown:
                raise ValueError(f"files missing from {args.groups}: {unknown[:5]}")
        lines = ["Shard union: OK", "", "| Shard | Tests | JUnit seconds |", "| --- | ---: | ---: |"]
        for report in sorted(reports, key=lambda r: r["shard"]):
            seconds = "—"
            if args.junit:
                paths = list(args.junit.rglob(f"backend-pytest-shard-{report['shard']}.xml"))
                if len(paths) != 1:
                    raise ValueError(f"shard {report['shard']}: expected exactly one JUnit")
                seconds = f"{sum(float(c.get('time', '0')) for c in ET.parse(paths[0]).iter('testcase')):.1f}"
            lines.append(f"| {report['shard']} | {len(report['selected'])} | {seconds} |")
        summary = "\n".join(lines) + "\n"
        print(summary, end="")
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
                output.write(summary)
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(f"::error title=shard union::{error}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

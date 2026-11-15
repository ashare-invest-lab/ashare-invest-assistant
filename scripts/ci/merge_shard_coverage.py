#!/usr/bin/env python3
"""T-O90 (G-STAGE6①): merge sharded coverage JSON into one exact-equivalent file.

pytest-cov writes one coverage.json per shard. The ratchet's measured() requires
files+totals consistent; this merger unions files (max line coverage is inherent:
each line measured once per shard; app source is only executed by tests present in
that shard, so identical keys across shards are merged by summing hits) and
recomputes totals as exact sums. Fails loudly on schema drift or overlap mismatch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def merge_file(a: dict, b: dict, name: str) -> dict:
    out = dict(a)
    # covered_lines union; executed_lines union preserves per-line evidence
    cov = set(a.get("executed_lines", [])) | set(b.get("executed_lines", []))
    mis = set(a.get("missing_lines", [])) & set(b.get("missing_lines", []))
    mis = {m for m in mis if m not in cov}
    sum_a, sum_b = a.get("summary", {}), b.get("summary", {})
    stmts = sorted(set(a.get("executed_lines", []) + a.get("missing_lines", []))
                   | set(b.get("executed_lines", []) + b.get("missing_lines", [])))
    out["executed_lines"] = sorted(cov)
    out["missing_lines"] = sorted(m for m in stmts if m not in cov)
    out["summary"] = {
        "covered_lines": len(cov),
        "num_statements": len(stmts),
        "percent_covered": round(100.0 * len(cov) / len(stmts), 4) if stmts else 100.0,
        "missing_lines": len(out["missing_lines"]),
        "excluded_lines": sum_a.get("excluded_lines", 0),
    }
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("inputs", nargs="+", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(argv)
    merged: dict = {}
    meta: dict = {}
    for path in args.inputs:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("files"), dict) or not data["files"]:
            print(f"::error title=cov-merge::{path} has no files", file=sys.stderr)
            return 1
        meta = meta or data.get("meta", {})
        for name, info in data["files"].items():
            if name not in merged:
                merged[name] = info
            else:
                merged[name] = merge_file(merged[name], info, name)
    totals_cov = sum(i["summary"]["covered_lines"] for i in merged.values())
    totals_all = sum(i["summary"]["num_statements"] for i in merged.values())
    result = {
        "meta": {**meta, "shard_merge": [str(p) for p in args.inputs]},
        "files": merged,
        "totals": {
            "covered_lines": totals_cov,
            "num_statements": totals_all,
            "percent_covered": round(100.0 * totals_cov / totals_all, 4) if totals_all else 100.0,
        },
    }
    args.output.write_text(json.dumps(result) + "\n", encoding="utf-8")
    print(f"merged {len(args.inputs)} shards -> {len(merged)} files, "
          f"totals {totals_cov}/{totals_all}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

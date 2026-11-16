#!/usr/bin/env python3
"""Gate exact coverage against the frozen trusted base; 80/90 remain goals only."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from coverage_ratchet import (NONDET_PATH, SELECTION, adjusted_measurement, compare,
                              load_nondet_lines, load_policy, validate_base_anchors, validate_record)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("coverage_json", type=Path)
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--base-coverage", type=Path)
    parser.add_argument("--base-source-root", type=Path,
                        help="Read base anchor source from this tree instead of the trusted commit")
    parser.add_argument("--nondet-lines", type=Path, default=NONDET_PATH)
    parser.add_argument("--policy", type=Path, default=Path(__file__).with_name("coverage-baseline.json"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        trusted = validate_record(json.loads(args.base.read_text(encoding="utf-8")))
        if trusted.get("ratchet_passed") is not True:
            raise ValueError("Trusted base did not pass its coverage ratchet")
        floors = load_policy(args.policy, trusted)
        exclusions = load_nondet_lines(args.nondet_lines)
        if exclusions and args.base_coverage is None:
            raise ValueError("Nonempty nondeterministic whitelist requires --base-coverage coverage.json")
        validate_base_anchors(exclusions, trusted.get("commit"), source_root=args.base_source_root)
        counts, adjusted, current_audit = adjusted_measurement(args.coverage_json, exclusions, label="current")
        base_adjusted, base_audit = trusted["counts"], []
        if args.base_coverage is not None:
            base_raw, base_adjusted, base_audit = adjusted_measurement(args.base_coverage, exclusions, label="base")
            if base_raw != trusted["counts"]:
                raise ValueError("Base coverage.json counts disagree with trusted measurement")
        errors, rows = compare(adjusted, {**trusted, "counts": base_adjusted}, floors)
        if current_audit or base_audit:
            print("nondet exclusions applied; "
                  f"raw={counts['total'][0]}/{counts['total'][1]} "
                  f"base_raw={trusted['counts']['total'][0]}/{trusted['counts']['total'][1]}; "
                  f"compared={adjusted['total'][0]}/{adjusted['total'][1]} "
                  f"vs {base_adjusted['total'][0]}/{base_adjusted['total'][1]}")
        for row in rows:
            value = (f"{100 * row['covered'] / row['statements']:.4f}%"
                     if row["statements"] else "N/A (zero statements)")
            print(f"{row['scope']}: {value} ({row['covered']}/{row['statements']}); "
                  f"base={row['base_covered']}/{row['base_statements']}; "
                  f"denominator_delta={row['denominator_delta']:+d}; "
                  f"minimum_ratio={row.get('effective_minimum', 'N/A')}; "
                  f"required_ratio={row.get('required_ratio', 'N/A')}; {row['status']}")
        result = {"schema": "aia-coverage-ratchet-v1", "selection": SELECTION,
                  "counts": counts, "minimums": floors, "commit": os.environ.get("GITHUB_SHA"),
                  "run_id": os.environ.get("GITHUB_RUN_ID"),
                  "attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
                  "base_commit": trusted.get("commit"), "base_source": trusted.get("source"),
                  "comparison": {"counts": adjusted, "base_counts": base_adjusted,
                                 "base_raw_counts": trusted["counts"],
                                 "exclusions": {"current": current_audit, "base": base_audit}},
                  "ratchet_passed": not errors, "rows": rows}
        args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        for error in errors:
            print("::error title=coverage-ratchet::" + error)
        return 1 if errors else 0
    except (OSError, ValueError, KeyError, TypeError, ZeroDivisionError) as exc:
        print("::error title=coverage-ratchet::Missing or invalid real measurement/trusted baseline: "
              + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

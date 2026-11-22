#!/usr/bin/env python3
"""T-O120：按文件把后端测试确定性地分到 N 片（LPT 贪心），每片在独立 runner/PG 上顺序跑。"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEST_ROOTS = ("src/backend/tests", "tests/backend", "tests/replay")
DEFAULT_SECONDS = 15.0


def load_files(root: Path = ROOT) -> tuple[set[str], dict[str, float]]:
    """ci-groups.yaml 登记的文件 ∪ 磁盘上的 test_*.py（不含 selfchecks）；登记但缺失则报错。"""
    listed = set()
    for line in (root / "tests/ci-groups.yaml").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("- {"):
            listed.add(json.loads(line.strip()[2:])["file"])
    missing = sorted(name for name in listed if not (root / name).is_file())
    if missing:
        raise FileNotFoundError("ci-groups.yaml lists missing test files: " + ", ".join(missing))
    disk = {p.relative_to(root).as_posix() for d in TEST_ROOTS if (root / d).is_dir()
            for p in (root / d).rglob("test_*.py") if "selfchecks" not in p.relative_to(root).parts}
    seconds = json.loads((root / "scripts/ci/backend-test-durations.json").read_text(encoding="utf-8"))["seconds"]
    return listed | disk, {k: float(v) for k, v in seconds.items()}


def plan_shards(files: set[str], durations: dict[str, float], count: int) -> list[list[str]]:
    shards: list[list[str]] = [[] for _ in range(count)]
    totals = [0.0] * count
    for name in sorted(files, key=lambda n: (-durations.get(n, DEFAULT_SECONDS), n)):
        i = min(range(count), key=lambda c: (totals[c], c))
        shards[i].append(name)
        totals[i] += durations.get(name, DEFAULT_SECONDS)
    return shards


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shards", type=int, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--index", type=int)
    group.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.shards <= 0 or (args.index is not None and not 0 <= args.index < args.shards):
        parser.error("--shards must be positive and --index must identify a shard")
    try:
        files, durations = load_files()
    except (OSError, ValueError, KeyError) as exc:
        print(f"shard plan error: {exc}", file=sys.stderr)
        return 2
    shards = plan_shards(files, durations, args.shards)
    if not args.check:
        print("\n".join(shards[args.index]))
        return 0
    for i, shard in enumerate(shards):
        print(f"shard {i}: {sum(durations.get(n, DEFAULT_SECONDS) for n in shard):.1f}s ({len(shard)} files)")
    flat = [n for shard in shards for n in shard]
    if len(flat) != len(set(flat)) or set(flat) != files:
        print("shard plan error: shards are not a disjoint cover", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

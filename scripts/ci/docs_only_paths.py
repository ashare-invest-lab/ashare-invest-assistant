"""Classify PR paths without dependencies; emit a GitHub Actions output line."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Sequence


# Runtime/test inputs: keep directory prefixes terminated by '/'.
CONSUMED_DOCS = (
    "docs/api-contract.md", "docs/plan.md", "docs/contracts/", "docs/strategies/",
    "docs/threat-model.md",
    "docs/handover/team/reports/T-B46-47-rulings.md",
    "docs/handover/team/tasks/T-R88.md",
)


def is_docs_only(paths: Sequence[str], modes: Sequence[str] | None = None) -> bool:
    """Empty diffs run full CI; paths are case sensitive repository-relative names."""
    return bool(paths) and (modes is None or (
        len(modes) == len(paths) and all(mode == "100644" for mode in modes)
    )) and all(
        path.endswith(".md") and (path.startswith("docs/") or "/" not in path)
        and not any(path.startswith(item) if item.endswith("/") else path == item
                    for item in CONSUMED_DOCS)
        for path in paths
    )


def changed_paths(base: str, head: str) -> tuple[list[str], list[str]]:
    for sha in (base, head):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise ValueError("base and head must be full commit SHAs")
    # -z preserves whitespace/newlines; --no-renames includes both sides of moves.
    result = subprocess.run(
        ["git", "diff", "--raw", "--no-abbrev", "--no-renames", "-z", f"{base}...{head}", "--"],
        check=True, capture_output=True,
    )
    fields = result.stdout.split(b"\0")
    paths, modes = [], []
    for index in range(0, len(fields) - 1, 2):
        old, new, _, _, status = fields[index].removeprefix(b":").split()
        paths.append(os.fsdecode(fields[index + 1]))
        # Deletions use the old mode; type changes must be ordinary on both sides.
        mode = old if status == b"D" else new
        if old not in (b"000000", b"100644"):
            mode = old
        modes.append(mode.decode("ascii"))
    return paths, modes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    print(f"docs_only={str(is_docs_only(*changed_paths(args.base, args.head))).lower()}")


if __name__ == "__main__":
    main()

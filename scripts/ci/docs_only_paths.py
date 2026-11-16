"""Classify PR paths without dependencies; emit a GitHub Actions output line."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections.abc import Sequence


def is_docs_only(paths: Sequence[str]) -> bool:
    """Empty diffs run full CI; paths are case sensitive repository-relative names."""
    return bool(paths) and all(path.startswith("docs/") or path.endswith(".md") for path in paths)


def changed_paths(base: str, head: str) -> list[str]:
    for sha in (base, head):
        if not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            raise ValueError("base and head must be full commit SHAs")
    # -z preserves whitespace/newlines; --no-renames includes both sides of moves.
    result = subprocess.run(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}...{head}", "--"],
        check=True, capture_output=True,
    )
    return [os.fsdecode(path) for path in result.stdout.split(b"\0") if path]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base")
    parser.add_argument("head")
    args = parser.parse_args()
    print(f"docs_only={str(is_docs_only(changed_paths(args.base, args.head))).lower()}")


if __name__ == "__main__":
    main()

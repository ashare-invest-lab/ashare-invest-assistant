"""T-B143 分钟线格式验证：离线把单个通达信 .lc1/.lc5 解析成 CSV（复用 app.ingest.tdx_local）。

只用于 1 只股票的回滚式入库验证（tb143_min_rollback.sql），不出网、不连库。
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.ingest.tdx_local import parse_lc_bytes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--code", required=True)
    parser.add_argument("--kind", required=True, choices=("lc1", "lc5"))
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    result = parse_lc_bytes(args.code, args.file.read_bytes(), args.kind)
    with args.out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(("code", "ts", "open", "high", "low", "close", "volume", "amount"))
        for bar in result.bars:
            assert bar.ts is not None
            writer.writerow((bar.code, bar.ts.isoformat(), bar.open, bar.high, bar.low,
                             bar.close, bar.volume, bar.amount))
    print(f"rows={len(result.bars)} rejected={dict(result.rejected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

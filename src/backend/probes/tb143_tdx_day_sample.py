"""T-B143 小样本：离线从 hsjday zip 导出指定 A 股的全部有效日线为 CSV。

解析与单位换算全部复用 app.ingest.tdx_local（T-B133，daily-bars-tdx.md §2/§3.3）。
口径常量集中在下方，T-A153 统一口径后只改这一处。不出网、不连库。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path
from typing import Any
from zipfile import ZipFile

from app.ingest.tdx_local import parse_day_bytes, unit_suspect

# ---- 口径常量（待 T-A153 映射表替换）----
# 编排者 T-B143 派单前缀白名单；920 为北交所（.BJ）。
PREFIX_SUFFIX = {
    **dict.fromkeys(("600", "601", "603", "605", "688", "689"), ".SH"),
    **dict.fromkeys(("000", "001", "002", "003", "300", "301", "302"), ".SZ"),
    **dict.fromkeys(("43", "83", "87", "920"), ".BJ"),
}
MARKET_DIR = {".SH": "sh", ".SZ": "sz", ".BJ": "bj"}  # daily-bars-tdx.md §3.2 sh/sz/bj 目录
SOURCE = "tdx_local"  # daily-bars-tdx.md §2；迁移 0033 CHECK 允许值
ADJ_TYPE = "none"  # daily-bars-tdx.md §2：只存不复权


def to_code(market: str, num: str) -> str | None:
    if len(num) != 6 or not num.isascii() or not num.isdigit():
        return None
    for prefix, suffix in PREFIX_SUFFIX.items():
        if num.startswith(prefix) and MARKET_DIR[suffix] == market:
            return num + suffix
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True, type=Path)
    parser.add_argument("--codes", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    codes = list(dict.fromkeys(code.strip() for code in args.codes.split(",")))
    for code in codes:
        num, _, suffix = code.partition(".")
        market = MARKET_DIR.get("." + suffix)
        if market is None or to_code(market, num) != code:
            parser.error(f"无效或非白名单股票代码：{code}")

    args.out.mkdir(parents=True, exist_ok=True)
    summary: dict[str, dict[str, Any]] = {}
    with ZipFile(args.zip) as archive, (args.out / "tdx_day_sample.csv").open(
        "w", encoding="utf-8", newline=""
    ) as stream:
        writer = csv.writer(stream)
        writer.writerow(("code", "trade_date", "open", "high", "low", "close", "volume", "amount"))
        for code in codes:
            num, suffix = code.split(".")
            market = MARKET_DIR["." + suffix]
            member = f"{market}\\lday\\{market}{num}.day"
            info: dict[str, Any] = {
                "rows": 0, "first": None, "last": None, "rejected": {},
                "unit_suspect": False, "sha256": None, "missing": True,
            }
            summary[code] = info
            try:
                data = archive.read(member)
            except KeyError:
                try:
                    data = archive.read(member.replace("\\", "/"))
                except KeyError:
                    continue
            result = parse_day_bytes(code, data)
            dates = [bar.trade_date for bar in result.bars]
            info.update(
                rows=len(result.bars),
                first=min(dates).isoformat() if dates else None,
                last=max(dates).isoformat() if dates else None,
                rejected=dict(result.rejected),
                unit_suspect=unit_suspect(result.bars),
                sha256=hashlib.sha256(data).hexdigest(), missing=False,
            )
            for bar in result.bars:
                writer.writerow((bar.code, bar.trade_date.isoformat(), *(
                    str(getattr(bar, field))
                    for field in ("open", "high", "low", "close", "volume", "amount")
                )))
    (args.out / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""T-B143 一次性离线导出，CSV 为 UTF-8 且带表头，不访问行情接口或数据库。

三个子命令的 --out 都是输出目录，可使用同一目录；分别生成 daily_bars.csv、
ex_rights_events.csv、minute_file_catalog.csv，summary.json 按子命令保留审计信息。
--generator 由调用方传入本脚本的 git blob SHA。day 出现文件拒绝时返回 1，
summary 状态为 partial，其他文件继续；整包拒绝返回 2，不生成该包 CSV。
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from dataclasses import asdict
from datetime import date
from pathlib import Path
from zipfile import ZipFile

from app.ingest.gbbq import GbbqRefused, load_pytdx_keys, read_gbbq_zip
from app.ingest.minute_catalog import hf_entries_from_manifest
from app.ingest.tdx_history import DayRefusal, iter_day_zip
from app.ingest.tdx_local import file_sha256

DAY_COLUMNS = ("code", "trade_date", "adj_type", "open", "high", "low", "close", "volume", "amount")
GBBQ_COLUMNS = (
    "code",
    "ex_date",
    "cash_per_share",
    "rights_price",
    "bonus_ratio",
    "rights_ratio",
    "source",
    "snapshot_sha256",
)
CATALOG_COLUMNS = (
    "source",
    "code",
    "kind",
    "date_from",
    "date_to",
    "rel_path",
    "sha256",
    "row_count",
    "splice_segment",
    "generator",
)


def main(argv: list[str] | None = None) -> int:
    """运行一个离线子命令，输出 CSV 与可追溯的输入哈希、生成器版本、计数。"""
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    day = sub.add_parser("day", help="导出资格集内的 .day 日线")
    day.add_argument("--zip", type=Path, required=True)
    day.add_argument("--eligible-codes", type=Path, required=True)
    day.add_argument("--before", type=date.fromisoformat)
    gbbq = sub.add_parser("gbbq", help="校验并导出权息快照")
    gbbq.add_argument("--zip", type=Path, required=True)
    gbbq.add_argument("--expected-sha256", required=True)
    hf = sub.add_parser("hf-catalog", help="登记 HF 2022plus 文件清单")
    hf.add_argument("--manifest-files-csv", type=Path, required=True)
    for command in (day, gbbq, hf):
        command.add_argument("--generator", required=True, help="调用方提供的本脚本 git blob SHA")
        command.add_argument("--out", type=Path, required=True, help="输出目录")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)
    counts: Counter[str] = Counter()
    inputs: dict[str, str] = {}
    status = "ok"
    error: str | None = None
    output = {
        "day": "daily_bars.csv",
        "gbbq": "ex_rights_events.csv",
        "hf-catalog": "minute_file_catalog.csv",
    }[args.command]
    target = args.out / output
    temporary = target.with_suffix(".csv.part")
    exit_code = 0
    try:
        if args.command == "gbbq":
            # 先解码成功再打开输出文件，避免拒绝包留下部分事件。
            inputs["zip"] = file_sha256(args.zip)
            if inputs["zip"] != args.expected_sha256:
                raise GbbqRefused("sha256_mismatch")
            snapshot, events = read_gbbq_zip(args.zip, args.expected_sha256, load_pytdx_keys())
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=GBBQ_COLUMNS)
                writer.writeheader()
                for event in events:
                    writer.writerow({**asdict(event), "snapshot_sha256": snapshot})
            counts["rows_exported"] = len(events)
        elif args.command == "hf-catalog":
            inputs["manifest_files_csv"] = file_sha256(args.manifest_files_csv)
            with args.manifest_files_csv.open(encoding="utf-8-sig", newline="") as stream:
                entries, counts = hf_entries_from_manifest(csv.DictReader(stream), args.generator)
            with temporary.open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=CATALOG_COLUMNS)
                writer.writeheader()
                writer.writerows(asdict(entry) for entry in entries)
            counts["rows_exported"] = len(entries)
            if any(value for key, value in counts.items() if key.startswith("reject_")):
                status, exit_code = "partial", 1
        else:
            inputs["zip"] = file_sha256(args.zip)
            inputs["eligible_codes"] = file_sha256(args.eligible_codes)
            eligible = set(args.eligible_codes.read_text(encoding="utf-8").splitlines())
            eligible = {code.strip() for code in eligible if code.strip()}
            with (
                ZipFile(args.zip) as archive,
                temporary.open("w", encoding="utf-8", newline="") as stream,
            ):
                writer = csv.writer(stream)
                writer.writerow(DAY_COLUMNS)
                for _code, result in iter_day_zip(archive, eligible, args.before):
                    if isinstance(result, DayRefusal):
                        prefix = "file_refused" if result.file_refused else "skipped"
                        counts[f"{prefix}:{result.reason}"] += 1
                        if result.file_refused:
                            status, exit_code = "partial", 1
                        continue
                    counts["files_parsed"] += 1
                    counts.update({f"record:{key}": n for key, n in result.rejected.items()})
                    for bar in result.bars:
                        writer.writerow(
                            (
                                bar.code,
                                bar.trade_date,
                                "none",
                                bar.open,
                                bar.high,
                                bar.low,
                                bar.close,
                                bar.volume,
                                f"{bar.amount:.4f}",
                            )
                        )
                        counts["rows_exported"] += 1
        temporary.replace(target)
    except GbbqRefused as exc:
        status, error, exit_code = "refused", str(exc), 2
        counts[f"refused:{error}"] += 1
    finally:
        temporary.unlink(missing_ok=True)
    summary_path = args.out / "summary.json"
    summaries = (
        json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.exists() else {}
    )
    summaries[args.command] = {
        "status": status,
        "counts": dict(counts),
        "input_sha256": inputs,
        "generator": args.generator,
        "csv": output,
        "error": error,
        "before": args.before.isoformat() if args.command == "day" and args.before else None,
    }
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

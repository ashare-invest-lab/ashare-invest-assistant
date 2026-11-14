"""T-B143 一次性离线导出，CSV 为 UTF-8 且带表头，不访问行情接口或数据库。

各子命令的 --out 都是输出目录，可使用同一目录；生成 CSV，summary.json
按子命令保留审计信息。day --split-by-year 生成每年独立的 day_YYYY.csv。
--generator 由调用方传入本脚本的 git blob SHA。day 出现文件拒绝时返回 1，
summary 状态为 partial，其他文件继续；整包拒绝返回 2，不生成该包 CSV。
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from collections import Counter
from contextlib import ExitStack
from dataclasses import asdict
from datetime import date
from pathlib import Path
from zipfile import ZipFile

from app.ingest.gbbq import GbbqRefused, load_pytdx_keys, read_gbbq_zip
from app.ingest.minute_catalog import (
    check_overlap,
    hf_entries_from_manifest,
    lc_entry,
    resolve,
    validate_rel_path,
)
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
    day.add_argument("--split-by-year", action="store_true")
    gbbq = sub.add_parser("gbbq", help="校验并导出权息快照")
    gbbq.add_argument("--zip", type=Path, required=True)
    gbbq.add_argument("--expected-sha256", required=True)
    hf = sub.add_parser("hf-catalog", help="登记 HF 2022plus 文件清单")
    hf.add_argument("--manifest-files-csv", type=Path, required=True)
    lc = sub.add_parser("lc-catalog", help="校验原始 .lc 快照并导出目录")
    lc.add_argument("--root", type=Path, required=True, help="包含 tdx-min 的快照根目录")
    lc.add_argument("--sha-manifest", type=Path, required=True)
    for command in (day, gbbq, hf, lc):
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
        "lc-catalog": "minute_file_catalog.csv",
    }[args.command]
    target = args.out / output
    temporary = target.with_suffix(".csv.part")
    pending = {target: temporary}
    file_rows: Counter[str] = Counter()
    files: dict[str, dict[str, int | str]] = {}
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
        elif args.command in ("hf-catalog", "lc-catalog"):
            if args.command == "hf-catalog":
                inputs["manifest_files_csv"] = file_sha256(args.manifest_files_csv)
                with args.manifest_files_csv.open(encoding="utf-8-sig", newline="") as stream:
                    entries, counts = hf_entries_from_manifest(
                        csv.DictReader(stream), args.generator
                    )
            else:
                inputs["sha_manifest"] = file_sha256(args.sha_manifest)
                entries = []
                with args.sha_manifest.open(encoding="utf-8-sig", newline="") as stream:
                    for row in csv.DictReader(stream):
                        rel = validate_rel_path(row["rel_path"])
                        data = resolve(str(args.root), rel).read_bytes()
                        if hashlib.sha256(data).hexdigest() != row["sha256"]:
                            raise ValueError(f"sha256_mismatch: {rel}")
                        if len(data) != int(row["bytes"]):
                            raise ValueError(f"bytes_mismatch: {rel}")
                        entry = lc_entry(
                            rel, data, row["sha256"], Path(rel).suffix[1:], args.generator
                        )
                        check_overlap(entries, entry)
                        entries.append(entry)
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
            if args.split_by_year:
                pending.clear()
                output = "day_YYYY.csv"
            with ZipFile(args.zip) as archive, ExitStack() as stack:
                writers = {}
                if not args.split_by_year:
                    writer = csv.writer(
                        stack.enter_context(temporary.open("w", encoding="utf-8", newline=""))
                    )
                    writer.writerow(DAY_COLUMNS)
                    writers[target.name] = writer
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
                        name = (
                            f"day_{bar.trade_date.year}.csv" if args.split_by_year else target.name
                        )
                        if name not in writers:
                            path = args.out / name
                            pending[path] = path.with_suffix(".csv.part")
                            writer = csv.writer(
                                stack.enter_context(
                                    pending[path].open("w", encoding="utf-8", newline="")
                                )
                            )
                            writer.writerow(DAY_COLUMNS)
                            writers[name] = writer
                        writer = writers[name]
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
                        file_rows[name] += 1
        for destination, part in pending.items():
            files[destination.name] = {
                "rows": file_rows[destination.name]
                if args.command == "day"
                else counts["rows_exported"],
                "sha256": file_sha256(part),
            }
            part.replace(destination)
    except (GbbqRefused, ValueError, OSError) as exc:
        status, error, exit_code = "refused", str(exc), 2
        counts[f"refused:{error}"] += 1
    finally:
        for part in pending.values():
            part.unlink(missing_ok=True)
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
        "files": files,
        "error": error,
        "before": args.before.isoformat() if args.command == "day" and args.before else None,
    }
    summary_path.write_text(
        json.dumps(summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())

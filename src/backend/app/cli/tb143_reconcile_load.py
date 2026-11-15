"""两段式日线对账/追加：默认只读；--apply 才写 market.daily_bars。

不加载 Settings/.env；连接只来自显式 --dsn 或 DATABASE_URL，不输出连接信息。
每个 CSV（zip 则每年）独立事务；异常行跳过，文件/写库异常回滚该批。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
from collections import Counter
from collections.abc import Callable, Iterator, Sequence
from contextlib import AbstractContextManager, contextmanager, suppress
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol, TextIO, cast
from zipfile import BadZipFile, ZipFile

import psycopg

from app.bj_offline_volume import CodeReject, _bj_write_unconfirmed, qualified_code
from app.cli.tb143_export import DAY_COLUMNS
from app.cli.tb143_inputs import InputKeys, Inputs, prepare
from app.ingest.tdx_history import DayRefusal, iter_day_zip
from app.ingest.tdx_local import (
    ExistingBar,
    TdxBar,
    file_sha256,
    is_a_share,
    reconcile,
)

Key = tuple[str, date, str]
FIELDS = DAY_COLUMNS[3:]
CHUNK = 2000
INSERT_SQL = """
INSERT INTO market.daily_bars
(code, trade_date, adj_type, open, high, low, close, volume, amount,
 source, pre_close, is_suspended, source_licence_id, fetched_at)
VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,'tdx_local',NULL,NULL,NULL,now())
ON CONFLICT (code, trade_date, adj_type) DO NOTHING
"""
KEY_SQL = """
SELECT d.code, d.trade_date, d.adj_type, d.source,
       d.open, d.high, d.low, d.close, d.volume, d.amount
FROM market.daily_bars d
JOIN unnest(%s::text[], %s::date[]) AS k(code, trade_date)
 ON d.code=k.code AND d.trade_date=k.trade_date AND d.adj_type='none'
"""


def key(bar: TdxBar) -> Key:
    return bar.code, bar.trade_date, "none"


def values(bar: TdxBar) -> tuple[object, ...]:
    return (*key(bar), *(getattr(bar, name) for name in FIELDS))


class Repository(Protocol):
    """可用纯内存事务替身离线验证；生产路径实际 SELECT 已有行。"""

    def transaction(self, apply: bool) -> AbstractContextManager[None]: ...
    def securities(self) -> dict[str, tuple[str, str | None]]: ...
    def existing(self, keys: Sequence[Key]) -> dict[Key, ExistingBar]: ...
    def counts(self, keys: Sequence[Key]) -> dict[str, int]: ...
    def insert(self, rows: Sequence[tuple[object, ...]]) -> int: ...
    def close(self) -> None: ...


class PgRepository:
    """仅连接调用方指定实例；apply 锁住写入者，保证候选主键可作回滚依据。"""

    def __init__(self, dsn: str) -> None:
        self.conn: psycopg.Connection[tuple[Any, ...]] = psycopg.connect(dsn, autocommit=True)

    @contextmanager
    def transaction(self, apply: bool) -> Iterator[None]:
        with self.conn.transaction():
            self.conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            if apply:
                self.conn.execute("SET LOCAL lock_timeout = '5s'")
                # 在首次读快照前取锁；其他日线写入者不能干扰候选键和 mairui 计数。
                self.conn.execute("LOCK TABLE market.daily_bars IN SHARE ROW EXCLUSIVE MODE")
            else:
                self.conn.execute("SET TRANSACTION READ ONLY")
            yield

    def securities(self) -> dict[str, tuple[str, str | None]]:
        return {
            row[0]: (row[1], row[2])
            for row in self.conn.execute("SELECT code, type, listing_status FROM market.securities")
        }

    def existing(self, keys: Sequence[Key]) -> dict[Key, ExistingBar]:
        if not keys:
            return {}
        return {
            (row[0], row[1], row[2]): ExistingBar(*row[3:])
            for row in self.conn.execute(KEY_SQL, ([k[0] for k in keys], [k[1] for k in keys]))
        }

    def counts(self, keys: Sequence[Key]) -> dict[str, int]:
        row = self.conn.execute("""
            SELECT count(*), count(*) FILTER (WHERE source='mairui'),
                   count(*) FILTER (WHERE source='tdx_local') FROM market.daily_bars
        """).fetchone()
        if row is None:
            raise ValueError("counts_missing")
        result = dict(zip(("total", "mairui", "tdx_local"), row, strict=True))
        result["batch_keys"] = sum(
            len(self.existing(keys[start : start + CHUNK])) for start in range(0, len(keys), CHUNK)
        )
        return result

    def insert(self, rows: Sequence[tuple[object, ...]]) -> int:
        with self.conn.cursor() as cursor:
            cursor.executemany(INSERT_SQL, rows)
            return cursor.rowcount

    def close(self) -> None:
        self.conn.close()


def parse_row(row: dict[str, str | None]) -> TdxBar:
    """导出 CSV 已为股/元；不推断停牌，不二次换算或容忍非法数值。"""
    if any(row.get(name) is None or row.get(name) == "" for name in DAY_COLUMNS):
        raise ValueError("missing_column")
    code = str(row["code"])
    if re.fullmatch(r"[0-9]{6}\.(SH|SZ|BJ)", code) is None:
        raise ValueError("invalid_code")
    if row["adj_type"] != "none":
        raise ValueError("adj_type_not_none")
    raw_day = str(row["trade_date"])
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_day) is None:
        raise ValueError("invalid_date")
    try:
        day = date.fromisoformat(raw_day)
    except ValueError as exc:
        raise ValueError("invalid_date") from exc
    numbers = [Decimal(str(row[name])) for name in FIELDS]
    if any(not n.is_finite() for n in numbers):
        raise ValueError("non_finite")
    if any(abs(n) >= Decimal("1e16") or n != n.quantize(Decimal("0.0001")) for n in numbers):
        raise ValueError("out_of_range_or_precision")
    o, h, low, c, volume, amount = numbers
    if min(o, h, low, c) <= 0 or not low <= min(o, c) <= max(o, c) <= h:
        raise ValueError("invalid_ohlc")
    if volume < 0 or volume != volume.to_integral_value() or amount < 0:
        raise ValueError("invalid_volume_or_amount")
    return TdxBar(code, day, None, o, h, low, c, volume, amount)


def detail(stream: TextIO, kind: str, **fields: object) -> None:
    payload = dict.fromkeys(
        ("code", "trade_date", "field", "existing_source", "existing_value", "tdx_value")
    )
    payload.update(fields)
    payload["kind"] = kind
    payload.setdefault("adj_type", "none")
    stream.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _zip_csv(
    path: Path, out: Path, eligible: set[str], log: TextIO, counts: Counter[str]
) -> Inputs:
    """复用完整 zip 解析，不给 before，故 920 历史窗口不截断。"""
    result = Inputs(hashes={str(path): file_sha256(path)})
    out.mkdir(parents=True)
    # 每次只打开一个代码的年度文件，避免长窗口耗尽文件描述符。
    with ZipFile(path) as archive:
        for code, parsed in iter_day_zip(archive, eligible, None):
            if isinstance(parsed, DayRefusal):
                category = "abnormal" if parsed.file_refused else "zip_skipped"
                counts[category] += 1
                detail(log, category, code=code, reason=parsed.reason)
                if parsed.file_refused:
                    result.errors.append(f"zip:{code}:{parsed.reason}")
                continue
            for reason, number in parsed.rejected.items():
                counts["abnormal"] += number
                detail(log, "abnormal", code=code, reason=reason, rows=number)
            years: dict[int, list[TdxBar]] = {}
            for bar in parsed.bars:
                years.setdefault(bar.trade_date.year, []).append(bar)
            for year, bars in years.items():
                target = out / f"day_{year}.csv"
                exists = target.exists()
                with target.open("a", encoding="utf-8", newline="") as stream:
                    writer = csv.writer(stream)
                    if not exists:
                        writer.writerow(DAY_COLUMNS)
                    writer.writerows(values(bar) for bar in bars)
    result.files = sorted(out.glob("*.csv"))
    if not result.files:
        result.errors.append("bj:no_daily_csv")
    result.hashes.update({str(p): file_sha256(p) for p in result.files})
    return result


def _batch(
    repo: Repository,
    path: Path,
    route: str,
    before: date,
    bj_codes: set[str],
    out: Path,
    index: int,
    apply: bool,
    log: TextIO,
    seen: InputKeys,
    expected_hash: str,
) -> dict[str, object]:
    counts: Counter[str] = Counter(
        dict.fromkeys(
            (
                "new",
                "identical",
                "mismatch",
                "non_a_share",
                "abnormal",
                "out_of_scope",
                "blocked_bj_unconfirmed",
            ),
            0,
        )
    )
    report: dict[str, object] = {"file": str(path), "route": route, "counts": counts, "inserted": 0}
    new_keys = out / f"{index:04d}_new_keys.csv"
    candidates = out / f"{index:04d}_candidates.csv"
    report.update(new_keys=str(new_keys), candidates=str(candidates))
    batch_keys: list[Key] = []
    coverage: dict[str, dict[str, str | int]] = {}
    report["coverage"] = coverage
    try:
        with repo.transaction(apply):
            if file_sha256(path) != expected_hash:
                raise ValueError("input_changed_after_preflight")
            securities = repo.securities()
            with (
                path.open(encoding="utf-8-sig", newline="") as source,
                new_keys.open("x", encoding="utf-8", newline="") as keys_stream,
                candidates.open("x", encoding="utf-8", newline="") as candidate_stream,
            ):
                reader = csv.DictReader(source, strict=True)
                if reader.fieldnames != list(DAY_COLUMNS):
                    raise ValueError("missing_or_wrong_columns")
                keys_writer, rows_writer = csv.writer(keys_stream), csv.writer(candidate_stream)
                keys_writer.writerow(DAY_COLUMNS[:3])
                rows_writer.writerow(DAY_COLUMNS)
                pending: list[TdxBar] = []

                def flush() -> None:
                    existing = repo.existing([key(bar) for bar in pending])
                    for bar in pending:
                        current = existing.get(key(bar))
                        if current is None:
                            counts["new"] += 1
                            keys_writer.writerow(key(bar))
                            rows_writer.writerow(values(bar))
                        else:
                            differences = reconcile(bar, current, compare_amount=True)
                            counts["mismatch" if differences else "identical"] += 1
                            for item in differences:
                                detail(
                                    log,
                                    "mismatch",
                                    **{k: v for k, v in item.items() if k != "kind"},
                                )
                    pending.clear()

                for line, row in enumerate(reader, 2):
                    try:
                        if None in row or any(value is None for value in row.values()):
                            raise ValueError("missing_or_extra_columns")
                        bar = parse_row(row)
                    except (ValueError, InvalidOperation) as exc:
                        counts["abnormal"] += 1
                        detail(
                            log,
                            "abnormal",
                            file=str(path),
                            line=line,
                            reason=str(exc),
                            code=row.get("code"),
                            trade_date=row.get("trade_date"),
                        )
                        continue
                    if not is_a_share(securities.get(bar.code)):
                        counts["non_a_share"] += 1
                        detail(log, "non_a_share", code=bar.code, trade_date=bar.trade_date)
                        continue
                    if (route == "history" and bar.trade_date >= before) or (
                        route == "bj" and bar.code not in bj_codes
                    ):
                        counts["out_of_scope"] += 1
                        continue
                    if key(bar) in seen:
                        counts["abnormal"] += 1
                        detail(
                            log,
                            "abnormal",
                            code=bar.code,
                            trade_date=bar.trade_date,
                            reason="duplicate_input_key",
                        )
                        continue
                    seen.add(key(bar))
                    batch_keys.append(key(bar))
                    day = bar.trade_date.isoformat()
                    entry = coverage.setdefault(bar.code, {"from": day, "to": day, "rows": 0})
                    entry["from"] = min(str(entry["from"]), day)
                    entry["to"] = max(str(entry["to"]), day)
                    entry["rows"] = int(entry["rows"]) + 1
                    pending.append(bar)
                    if len(pending) >= CHUNK:
                        flush()
                flush()
                for stream in (keys_stream, candidate_stream):
                    stream.flush()
                    os.fsync(stream.fileno())
            # 两份文件已关闭（落盘）才允许首次 INSERT；失败时文件保留。
            if file_sha256(path) != expected_hash:
                raise ValueError("input_changed_during_reconcile")
            report["before"] = before_counts = repo.counts(batch_keys)
            detail(
                log,
                "batch_prepared",
                batch=index,
                file=str(path),
                before=before_counts,
                new_keys=str(new_keys),
                candidates=str(candidates),
            )
            log.flush()
            os.fsync(log.fileno())
            inserted = 0
            if apply:
                with candidates.open(encoding="utf-8", newline="") as stream:
                    rows: list[tuple[object, ...]] = []
                    for row in csv.DictReader(stream):
                        bar = parse_row(row)
                        # 共用确认状态；前缀复用同模块的归属规则，防止 BJ 错标后缀绕过。
                        code = bar.code
                        if not code.endswith(".BJ"):
                            with suppress(CodeReject):
                                code = qualified_code(code[:6])
                        if _bj_write_unconfirmed({"code": code}):
                            counts["blocked_bj_unconfirmed"] += 1
                            detail(
                                log,
                                "blocked_bj_unconfirmed",
                                code=bar.code,
                                trade_date=bar.trade_date,
                            )
                            continue
                        rows.append(values(bar))
                        if len(rows) >= CHUNK:
                            inserted += repo.insert(rows)
                            rows.clear()
                    if rows:
                        inserted += repo.insert(rows)
            report["after"] = after_counts = repo.counts(batch_keys)
            if before_counts["mairui"] != after_counts["mairui"]:
                raise ValueError("mairui_count_changed")
            if apply and (
                inserted != counts["new"] - counts["blocked_bj_unconfirmed"]
                or after_counts["total"] - before_counts["total"] != inserted
                or after_counts["tdx_local"] - before_counts["tdx_local"] != inserted
                or after_counts["batch_keys"] - before_counts["batch_keys"] != inserted
            ):
                raise ValueError("insert_count_mismatch")
        report.update(status="committed" if apply else "dry_run", inserted=inserted)
    except (psycopg.Error, OSError, ValueError, csv.Error) as exc:
        # 连接异常文本可能含 DSN；仅输出异常类型/自定义原因，不输出数据库消息。
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        report.update(status="failed", error=reason, inserted=0)
        counts["abnormal"] += 1
        detail(log, "abnormal", file=str(path), reason=reason)
        seen.difference_update(batch_keys)
    return report


def run(args: argparse.Namespace, factory: Callable[[str], Repository]) -> int:
    args.out.mkdir(parents=True, exist_ok=False)
    counts: Counter[str] = Counter(
        dict.fromkeys(
            ("new", "identical", "mismatch", "non_a_share", "abnormal", "blocked_bj_unconfirmed"),
            0,
        )
    )
    summary: dict[str, Any] = {
        "mode": "apply" if args.apply else "dry_run",
        "counts": counts,
        "batches": [],
        "integrity": {},
        "bj_codes_requested": 0,
    }
    repo: Repository | None = None
    seen: InputKeys | None = None
    exit_code = 0
    with (args.out / "reconcile.jsonl").open("x", encoding="utf-8") as log:
        try:
            if any(
                args.out.resolve().is_relative_to(path.resolve())
                for path in (args.shards_dir, args.bj_data)
            ):
                raise ValueError("out_must_be_outside_inputs")
            bj_codes = {
                line.strip()
                for line in args.bj_codes.read_text(encoding="utf-8-sig").splitlines()
                if line.strip()
            }
            if not bj_codes or any(
                re.fullmatch(r"920[0-9]{3}\.BJ", code) is None for code in bj_codes
            ):
                raise ValueError("bj_codes:expected_920xxx.BJ")
            summary["bj_codes_requested"] = len(bj_codes)
            inputs = {
                "history": prepare(
                    args.shards_dir, args.out / "prepared_history", args.bundle_sizes
                )
            }
            if args.bj_data.is_file() and args.bj_data.suffix.lower() == ".zip":
                inputs["bj"] = _zip_csv(
                    args.bj_data, args.out / "prepared_bj", bj_codes, log, counts
                )
            else:
                inputs["bj"] = prepare(args.bj_data, args.out / "prepared_bj")
            summary["integrity"] = {
                name: {
                    "complete": not entry.errors,
                    "errors": entry.errors,
                    "input_sha256": entry.hashes,
                }
                for name, entry in inputs.items()
            }
            incomplete = any(entry.errors for entry in inputs.values())
            summary["incomplete"] = incomplete
            if incomplete and args.apply:
                summary["status"] = "refused_integrity"
                return 2
            if not args.dsn:
                raise ValueError("dsn_required:use_DATABASE_URL_or_--dsn")
            repo = factory(args.dsn)
            seen = InputKeys(args.out / "input_keys")
            index = 0
            for route, entry in inputs.items():
                for path in entry.files:
                    index += 1
                    report = _batch(
                        repo,
                        path,
                        route,
                        args.before,
                        bj_codes,
                        args.out,
                        index,
                        args.apply,
                        log,
                        seen,
                        entry.hashes[str(path)],
                    )
                    summary["batches"].append(report)
                    detail(log, "batch_result", batch=index, result=report)
                    log.flush()
                    os.fsync(log.fileno())
                    counts.update(cast(Counter[str], report["counts"]))
                    if report["status"] == "failed":
                        exit_code = 1
            if incomplete:
                exit_code = 1
            observed = {
                code
                for batch in summary["batches"]
                if batch["route"] == "bj"
                for code in batch["coverage"]
            }
            summary["bj_codes_observed"] = len(observed)
            summary["bj_codes_missing"] = sorted(bj_codes - observed)
            summary["status"] = "partial" if exit_code else "ok"
        except (psycopg.Error, OSError, ValueError, BadZipFile) as exc:
            summary.update(
                status="failed",
                error=(str(exc) if isinstance(exc, ValueError) else type(exc).__name__),
            )
            counts["abnormal"] += 1
            detail(log, "abnormal", reason=summary["error"])
            exit_code = 2
        finally:
            if seen is not None:
                seen.close()
            if repo is not None:
                repo.close()
            (args.out / "summary.json").write_text(
                json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
    return exit_code


def main(
    argv: list[str] | None = None, *, factory: Callable[[str], Repository] = PgRepository
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shards-dir", type=Path, required=True)
    parser.add_argument("--bj-codes", type=Path, required=True)
    parser.add_argument("--bj-data", type=Path, required=True)
    parser.add_argument(
        "--out", type=Path, required=True, help="全新审计目录；失败保留，重跑另选目录"
    )
    parser.add_argument("--lock-dir", type=Path)
    parser.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--before", type=date.fromisoformat, default=date(2023, 11, 13))
    parser.add_argument("--bundle-sizes", help="旧 p?? 传输恢复时的五个 tgz 字节数，逗号分隔")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    locked = False
    try:
        if args.lock_dir:
            try:
                args.lock_dir.mkdir()
                locked = True
            except FileExistsError:
                print("LOCKED: skipped")
                return 0
        return run(args, factory)
    except OSError as exc:
        print(f"filesystem_error:{type(exc).__name__}")
        return 2
    finally:
        if locked:
            args.lock_dir.rmdir()


if __name__ == "__main__":
    raise SystemExit(main())

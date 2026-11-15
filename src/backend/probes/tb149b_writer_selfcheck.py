#!/usr/bin/env python3
"""T-B149b 离线写入口自检：虚构数据、内存 DBAPI，禁止网络和凭据读取。"""

from __future__ import annotations

import builtins
import csv
import io
import os
import socket
import unittest
from contextlib import ExitStack, contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

import psycopg

from app import bj_offline_volume as gate
from app.cli import tb143_reconcile_load as loader
from app.marketdata import daily_bars as writer

DAY = date(2026, 8, 7)
STAMP = datetime(2026, 8, 7, tzinfo=UTC)


def bar(code):
    return writer.DailyBar(
        code,
        DAY,
        "none",
        *(Decimal("10") for _ in range(4)),
        None,
        Decimal("700"),
        Decimal("7000"),
        None,
    )


def row(code):
    return (
        code,
        DAY,
        "none",
        *(Decimal("10") for _ in range(4)),
        Decimal("700"),
        Decimal("7000"),
    )


def confirm():
    gate.confirm_bj_offline_volume_units(
        [
            {
                "mairui": {"code": f"920{i:03d}.BJ", "t": DAY.isoformat(), "v": "7"},
                "tdx_local": {
                    "code": f"920{i:03d}.BJ",
                    "trade_date": DAY.isoformat(),
                    "volume": "700",
                    "source": "tdx_local",
                },
            }
            for i in range(800, 820)
        ]
    )


class MemoryCursor:
    """让真实 SQLAlchemy 编译/执行路径落到内存游标，而非替换 upsert。"""

    def __init__(self, conn):
        self.conn = conn
        self.description = None
        self.rows = []
        self.rowcount = 0

    def execute(self, sql, params):
        if not self.conn.active:
            raise AssertionError("write escaped outer transaction")
        self.conn.calls.append((sql, params))
        if self.conn.fail:
            raise psycopg.DataError("synthetic failure")
        if sql.startswith("INSERT"):
            self.description = [
                (name, 25, None, None, None, None, None)
                for name in ("code", "trade_date", "adj_type")
            ]
            for name in params:
                if not name.startswith("code_m"):
                    continue
                suffix = name.removeprefix("code")
                row = {
                    field: params[field + suffix]
                    for field in (
                        "code",
                        "trade_date",
                        "adj_type",
                        "open",
                        "high",
                        "low",
                        "close",
                        "pre_close",
                        "volume",
                        "amount",
                        "is_suspended",
                        "source",
                        "source_licence_id",
                        "fetched_at",
                    )
                }
                key = tuple(row[field] for field in ("code", "trade_date", "adj_type"))
                if key not in self.conn.table:
                    self.conn.table[key] = row
                    self.rows.append(key)
        elif sql.startswith("SELECT"):
            names = list(writer.daily_bars.c.keys())
            numeric = {"open", "high", "low", "close", "pre_close", "volume", "amount"}
            self.description = [
                (name, 1700 if name in numeric else 25, None, None, None, None, None)
                for name in names
            ]
            self.rows = [tuple(row.get(name) for name in names) for row in self.conn.table.values()]
        else:
            raise AssertionError(f"unexpected statement: {sql}")
        self.rowcount = len(self.rows)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def __iter__(self):
        return iter(self.rows)

    def close(self):
        pass


class MemoryPg:
    def __init__(self):
        self.active = False
        self.closed = self.broken = self.fail = False
        self.info = SimpleNamespace(transaction_status=psycopg.pq.TransactionStatus.IDLE)
        self.table = {}
        self.calls = []
        self.committed = self.rolled_back = 0

    @contextmanager
    def transaction(self):
        if self.active:
            raise AssertionError("nested transaction")
        saved = dict(self.table)
        self.active = True
        self.info.transaction_status = psycopg.pq.TransactionStatus.INTRANS
        try:
            yield
        except BaseException:
            self.table = saved
            self.rolled_back += 1
            raise
        else:
            self.committed += 1
        finally:
            self.active = False
            self.info.transaction_status = psycopg.pq.TransactionStatus.IDLE

    def execute(self, sql):
        self.calls.append((sql, None))

    def cursor(self, *args, **kwargs):
        return MemoryCursor(self)

    def close(self):
        self.closed = True

    def commit(self):
        raise AssertionError("adapter committed outer connection")

    def rollback(self):
        raise AssertionError("adapter rolled back outer connection")


class BatchRepository(loader.PgRepository):
    """仅替换批处理读接口，保留真实 insert、upsert 和事务适配器。"""

    def __init__(self, codes):
        self.conn = MemoryPg()
        self.codes = codes
        self.last_blocked_bj_unconfirmed = 0

    def securities(self):
        return dict.fromkeys(self.codes, ("stock", "listed"))

    def existing(self, keys):
        return {
            key: loader.ExistingBar(
                stored["source"], *(stored[field] for field in loader.FIELDS)
            )
            for key in keys
            if (stored := self.conn.table.get(key)) is not None
        }

    def counts(self, keys):
        rows = list(self.conn.table.values())
        return {
            "total": len(rows),
            "mairui": sum(row["source"] == "mairui" for row in rows),
            "tdx_local": sum(row["source"] == "tdx_local" for row in rows),
            "batch_keys": sum(key in self.conn.table for key in keys),
        }


class WriterChecks(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(gate, "_bj_offline_volume_codes", frozenset()))

        def forbidden(*args, **kwargs):
            raise AssertionError("network/extra connection forbidden")

        self.stack.enter_context(patch.object(socket.socket, "connect", forbidden))
        self.stack.enter_context(patch.object(socket, "getaddrinfo", forbidden))
        self.stack.enter_context(patch.object(psycopg, "connect", forbidden))

        def guarded(original):
            def guard(file, *args, **kwargs):
                if isinstance(file, (str, bytes, os.PathLike)):
                    path = Path(os.fsdecode(file))
                    if (
                        path.name.startswith(".env")
                        or path.suffix in {".key", ".pem"}
                        or {"secrets", ".aws", ".ssh"}.intersection(path.parts)
                    ):
                        raise AssertionError("credential read forbidden")
                return original(file, *args, **kwargs)

            return guard

        for module in (builtins, io, os):
            self.stack.enter_context(patch.object(module, "open", guarded(module.open)))

    def connection(self):
        raw = MemoryPg()
        repo = object.__new__(loader.PgRepository)
        repo.conn = raw
        return repo, raw

    def upsert(self, repo, bars, source):
        engine = loader.create_engine("postgresql+psycopg://", poolclass=loader.NullPool)
        with loader.Connection(
            engine,
            connection=loader._BorrowedConnection(repo.conn),
            _allow_autobegin=False,
            _allow_revalidate=False,
        ) as conn:
            return writer.upsert_daily_bars(
                conn,
                writer.DailyBarsResult(bars=bars),
                source=source,
                licence_id=None,
                fetched_at=STAMP,
            )

    def test_mixed_sources_block_bj_before_statement(self):
        for source in ("mairui", "tdx_local", "fake", "future_source"):
            with self.subTest(source=source):
                repo, raw = self.connection()
                with (
                    repo.transaction(True),
                    patch.object(
                        writer,
                        "pg_insert",
                        wraps=writer.pg_insert,
                    ) as insert,
                ):
                    stats = self.upsert(
                        repo,
                        [
                            bar(code)
                            for code in (
                                "920999.BJ",
                                "430999.SH",
                                "831999",
                                "873999.SZ",
                                "689999.SH",
                                "302999.SZ",
                            )
                        ],
                        source,
                    )
                    self.assertEqual(insert.call_count, 1)
                    self.assertEqual(stats.blocked_bj_unconfirmed, 4)
                    self.assertEqual(stats.inserted, 2)
                    self.assertEqual((stats.conflicts, stats.issues), (0, ()))
                    self.assertEqual({key[0] for key in raw.table}, {"689999.SH", "302999.SZ"})
                    self.assertEqual(raw.committed, 0)
                    self.assertFalse(raw.closed)

    def test_all_bj_never_constructs_insert(self):
        repo, raw = self.connection()
        with repo.transaction(True), patch.object(writer, "pg_insert") as insert:
            stats = self.upsert(repo, [bar("920999.BJ")], "mairui")
            insert.assert_not_called()
            self.assertEqual((stats.inserted, stats.blocked_bj_unconfirmed), (0, 1))
            self.assertEqual(len(raw.calls), 3)  # 只有隔离级别、超时、锁。

    def test_confirmed_bj_outside_samples_writes_for_every_source(self):
        confirm()
        for source in ("mairui", "tdx_local", "fake", "future_source"):
            with self.subTest(source=source):
                repo, raw = self.connection()
                with repo.transaction(True):
                    stats = self.upsert(repo, [bar("920999.BJ"), bar("430999.SH")], source)
                    self.assertEqual((stats.inserted, stats.blocked_bj_unconfirmed), (2, 0))
                self.assertEqual(raw.committed, 1)

    def test_failed_confirmation_revokes_gate(self):
        confirm()
        with self.assertRaises(gate.RowReject):
            gate.confirm_bj_offline_volume_units([])
        self.assertTrue(gate._bj_write_unconfirmed({"code": "920999.SH"}))

    def test_repository_borrows_locked_transaction_and_preserves_conflicts(self):
        repo, raw = self.connection()
        row = (
            "689999.SH",
            DAY,
            "none",
            *(Decimal("10") for _ in range(4)),
            Decimal("700"),
            Decimal("7000"),
        )
        with repo.transaction(True):
            self.assertEqual(repo.insert([row]), 1)
            self.assertEqual(repo.insert([row]), 0)
            # 用不同成交量测试同一主键的冲突。
            changed = (*row[:7], Decimal("701"), Decimal("7010"))
            self.assertEqual(repo.insert([changed]), 0)
            self.assertEqual((raw.committed, raw.rolled_back, raw.closed), (0, 0, False))
            stored = next(iter(raw.table.values()))
            self.assertEqual(stored["source"], "tdx_local")
            self.assertEqual(stored["volume"], Decimal("700"))
            for name in ("pre_close", "is_suspended", "source_licence_id"):
                self.assertIsNone(stored[name])
            self.assertIsNotNone(stored["fetched_at"].utcoffset())
        self.assertEqual(raw.committed, 1)
        self.assertIn("REPEATABLE READ", raw.calls[0][0])
        self.assertIn("SHARE ROW EXCLUSIVE", raw.calls[2][0])
        self.assertFalse(any(sql.startswith("UPDATE") for sql, _ in raw.calls))
        self.assertFalse(raw.closed)
        repo.close()
        self.assertTrue(raw.closed)

    def test_repository_also_blocks_direct_bj(self):
        repo, raw = self.connection()
        row = (
            "920999.BJ",
            DAY,
            "none",
            *(Decimal("10") for _ in range(4)),
            Decimal("700"),
            Decimal("7000"),
        )
        with repo.transaction(True):
            self.assertEqual(repo.insert([row]), 0)
            self.assertEqual(raw.table, {})
            confirm()
            self.assertEqual(repo.insert([row]), 1)

    def test_repository_reports_blocked_and_resets_each_insert(self):
        repo, raw = self.connection()
        blocked = ("920999.BJ", "430999.SH", "831999.SZ", "873999.SZ")
        with repo.transaction(True):
            inserted = repo.insert([row(code) for code in (*blocked, "689999.SH", "302999.SZ")])
            self.assertIs(type(inserted), int)
            self.assertEqual((inserted, repo.last_blocked_bj_unconfirmed), (2, 4))
            self.assertEqual(repo.insert([row("920999.BJ")]), 0)
            self.assertEqual(repo.last_blocked_bj_unconfirmed, 1)
            self.assertEqual(repo.insert([]), 0)
            self.assertEqual(repo.last_blocked_bj_unconfirmed, 0)
            self.assertEqual(repo.insert([row("430999.SH")]), 0)
            self.assertEqual(repo.last_blocked_bj_unconfirmed, 1)
            self.assertEqual(repo.insert([row("689999.SH")]), 0)
            self.assertEqual(repo.last_blocked_bj_unconfirmed, 0)
        self.assertEqual((raw.committed, raw.rolled_back), (1, 0))
        self.assertEqual({key[0] for key in raw.table}, {"689999.SH", "302999.SZ"})

    def batch(self, codes, *, chunk, apply=True, prefilter=None, expose_stats=True):
        repo = BatchRepository(codes)
        # dry-run 不应读取上一次 insert 的计数。
        repo.last_blocked_bj_unconfirmed = 99
        with TemporaryDirectory(prefix="tb149b-writer-") as directory, ExitStack() as stack:
            root = Path(directory)
            source = root / "day.csv"
            with source.open("w", encoding="utf-8", newline="") as stream:
                csv.writer(stream).writerows([loader.DAY_COLUMNS, *(row(code) for code in codes)])
            seen = loader.InputKeys(root / "seen")
            stack.callback(seen.close)
            stack.enter_context(patch.object(loader, "CHUNK", chunk))
            if prefilter is not None:
                stack.enter_context(patch.object(loader, "_bj_write_unconfirmed", prefilter))
            insert = stack.enter_context(patch.object(repo, "insert", wraps=repo.insert))
            target = repo if expose_stats else SimpleNamespace(
                **{name: getattr(repo, name) for name in (
                    "transaction", "securities", "existing", "counts", "insert", "close"
                )}
            )
            with (root / "log.jsonl").open("w", encoding="utf-8") as log:
                report = loader._batch(
                    target, source, "history", date(2027, 1, 1), set(), root,
                    1, apply, log, seen, loader.file_sha256(source),
                )
            return report, repo.conn, insert.call_count

    def test_batch_commits_sh_sz_when_upstream_misses_bj(self):
        codes = ("920999.BJ", "689999.SH", "430999.SH", "302999.SZ", "873999.SZ")
        # 完全漏过滤、仅识别后缀、正常预过滤；两种分块均覆盖尾块调用。
        for prefilter in (lambda row: False, lambda row: row["code"].endswith(".BJ"), None):
            for chunk in (2, 10):
                with self.subTest(prefilter=prefilter, chunk=chunk):
                    report, raw, calls = self.batch(codes, chunk=chunk, prefilter=prefilter)
                    self.assertEqual(report["status"], "committed", report)
                    self.assertNotIn("error", report)
                    self.assertEqual(report["inserted"], 2)
                    self.assertEqual(report["counts"]["new"], 5)
                    self.assertEqual(report["counts"]["blocked_bj_unconfirmed"], 3)
                    self.assertEqual(report["counts"]["abnormal"], 0)
                    self.assertEqual(report["after"]["total"] - report["before"]["total"], 2)
                    self.assertEqual((raw.committed, raw.rolled_back), (1, 0))
                    self.assertEqual({key[0] for key in raw.table}, {"689999.SH", "302999.SZ"})
                    self.assertGreater(calls, 0)

    def test_batch_dry_run_ignores_stale_blocked_stats(self):
        report, raw, calls = self.batch(("920999.BJ", "689999.SH"), chunk=2, apply=False)
        self.assertEqual(report["status"], "dry_run", report)
        self.assertEqual(report["counts"]["blocked_bj_unconfirmed"], 0)
        self.assertEqual((report["inserted"], calls), (0, 0))
        self.assertEqual((raw.committed, raw.rolled_back, raw.table), (1, 0, {}))

    def test_batch_int_repository_without_blocked_attribute(self):
        for apply in (False, True):
            with self.subTest(apply=apply):
                report, raw, calls = self.batch(
                    ("689999.SH", "302999.SZ"), chunk=1, apply=apply, expose_stats=False,
                )
                self.assertEqual(report["status"], "committed" if apply else "dry_run", report)
                self.assertEqual(report["counts"]["blocked_bj_unconfirmed"], 0)
                self.assertEqual((report["inserted"], calls), (2, 2) if apply else (0, 0))
                self.assertEqual((raw.committed, raw.rolled_back), (1, 0))

    def test_repository_requires_outer_transaction(self):
        repo, raw = self.connection()
        with self.assertRaisesRegex(ValueError, "insert_requires_active_transaction"):
            repo.insert([("unused",)])
        self.assertEqual(raw.calls, [])
        self.assertEqual(repo.insert([]), 0)

    def test_outer_rollback_retains_control(self):
        repo, raw = self.connection()
        with self.assertRaisesRegex(RuntimeError, "synthetic rollback"):
            with repo.transaction(True):
                self.upsert(repo, [bar("689999.SH")], "tdx_local")
                raise RuntimeError("synthetic rollback")
        self.assertEqual((raw.committed, raw.rolled_back), (0, 1))
        self.assertEqual(raw.table, {})
        self.assertFalse(raw.closed)

    def test_write_error_leaves_rollback_to_outer_owner(self):
        repo, raw = self.connection()
        raw.fail = True
        with self.assertRaises(loader.SQLAlchemyError) as raised:
            with repo.transaction(True):
                self.upsert(repo, [bar("689999.SH")], "tdx_local")
        self.assertIsInstance(raised.exception.orig, psycopg.DataError)
        self.assertEqual((raw.committed, raw.rolled_back), (0, 1))
        self.assertFalse(raw.closed)

    def test_no_local_statement_and_single_app_writer(self):
        source = Path(loader.__file__).read_text(encoding="utf-8")
        self.assertNotIn("INSERT_SQL", source)
        self.assertNotIn("INSERT INTO market.daily_bars".lower(), source.lower())
        patterns = (
            "insert(daily_bars",
            "update(daily_bars",
            "delete(daily_bars",
            "daily_bars.insert",
            "INSERT INTO market.daily_bars",
            "pg_insert(daily_bars",
        )
        app = Path(writer.__file__).resolve().parents[1]
        writers = [
            path.relative_to(app).as_posix()
            for path in app.rglob("*")
            if path.is_file()
            and path.suffix in {".py", ".md", ".ps1"}
            and any(p.lower() in path.read_text(encoding="utf-8").lower() for p in patterns)
        ]
        self.assertEqual(writers, ["marketdata/daily_bars.py"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

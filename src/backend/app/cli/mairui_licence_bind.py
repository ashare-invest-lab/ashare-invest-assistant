"""T-B141（架构师 T-A152 风险①）：把回填写入的 mairui NULL 行绑定到唯一 active 证书。

幂等可重跑：回填结束后再跑一次补齐，每次用新的清单路径；回滚按清单置回 NULL。
调用方负责事务，清单 fsync 成功后才更新数据库；不读取证书值。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import column, create_engine, func, select, update, values
from sqlalchemy.engine import Connection

from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars

Key = tuple[str, dt.date, str]
HEADER = ["code", "trade_date", "adj_type"]
BATCH_SIZE = 5000


@dataclass
class BindReport:
    licence_id: uuid.UUID | None
    rows: int
    applied: bool
    refused: str | None = None


def _process(
    conn: Connection, keys: list[Key], licence_id: uuid.UUID, *, apply: bool, undo: bool
) -> int:
    count = 0
    bars = daily_bars.c
    for offset in range(0, len(keys), BATCH_SIZE):
        batch = values(
            *(column(name, daily_bars.c[name].type) for name in HEADER), name="manifest_keys"
        ).data(keys[offset : offset + BATCH_SIZE])
        conditions = (
            bars.code == batch.c.code,
            bars.trade_date == batch.c.trade_date,
            bars.adj_type == batch.c.adj_type,
            bars.source == "mairui",
            bars.source_licence_id == licence_id if undo else bars.source_licence_id.is_(None),
        )
        if apply:
            result = conn.execute(
                update(daily_bars)
                .where(*conditions)
                .values(source_licence_id=None if undo else licence_id)
            )
            count += result.rowcount
        else:
            count += conn.execute(
                select(func.count()).select_from(daily_bars, batch).where(*conditions)
            ).scalar_one()
    return count


def bind(conn: Connection, manifest: Path, *, apply: bool) -> BindReport:
    ids = conn.execute(
        select(user_data_licences.c.id).where(
            user_data_licences.c.status == "active", user_data_licences.c.deleted_at.is_(None)
        )
    ).scalars().all()
    if len(ids) != 1:
        return BindReport(None, 0, False, f"active_licence_count:{len(ids)}")
    licence_id = ids[0]
    stmt = (
        select(*(daily_bars.c[name] for name in HEADER))
        .where(daily_bars.c.source == "mairui", daily_bars.c.source_licence_id.is_(None))
        .order_by(*(daily_bars.c[name] for name in HEADER))
    )
    if apply:
        stmt = stmt.with_for_update()
    keys: list[Key] = [(r.code, r.trade_date, r.adj_type) for r in conn.execute(stmt)]
    if not apply or not keys:
        return BindReport(licence_id, len(keys), apply)
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        stream.write(f"# licence_id={licence_id}\n")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows((code, date.isoformat(), adj) for code, date, adj in keys)
        stream.flush()
        os.fsync(stream.fileno())
    count = _process(conn, keys, licence_id, apply=True, undo=False)
    if count != len(keys):
        raise RuntimeError(f"bind rowcount mismatch: expected {len(keys)}, got {count}")
    return BindReport(licence_id, count, True)


def rollback(conn: Connection, manifest: Path, *, apply: bool) -> BindReport:
    with manifest.open(encoding="utf-8", newline="") as stream:
        first = stream.readline().rstrip("\n")
        if not first.startswith("# licence_id="):
            raise ValueError("invalid manifest licence header")
        licence_id = uuid.UUID(first.removeprefix("# licence_id="))
        if first != f"# licence_id={licence_id}":
            raise ValueError("invalid manifest licence header")
        reader = csv.reader(stream, strict=True)
        if next(reader, None) != HEADER:
            raise ValueError("invalid manifest columns")
        keys: list[Key] = []
        for row in reader:
            if len(row) != 3 or not row[0] or not row[2]:
                raise ValueError("invalid manifest key")
            date = dt.date.fromisoformat(row[1])
            if date.isoformat() != row[1]:
                raise ValueError("invalid manifest date")
            keys.append((row[0], date, row[2]))
        if len(set(keys)) != len(keys):
            raise ValueError("duplicate manifest key")
    count = _process(conn, keys, licence_id, apply=apply, undo=True)
    return BindReport(licence_id, count, apply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-B141 mairui licence binding")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rollback", action="store_true")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report row count only (default)")
    mode.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args(argv)
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required in the environment")
    engine = create_engine(dsn)
    try:
        with engine.begin() as conn:
            report = (rollback if args.rollback else bind)(conn, args.manifest, apply=args.apply)
        if report.refused:
            print(report.refused)
            return 3
        print(f"licence_id={report.licence_id} rows={report.rows}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

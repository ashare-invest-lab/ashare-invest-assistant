"""T-B141（架构师 T-A152 风险①）：把回填写入的 mairui NULL 行绑定到唯一 active 证书。

幂等可重跑：回填结束后再跑一次补齐，每次用新的清单路径；回滚按清单置回 NULL。
换证用 --from-licence 直接改绑，不产生 unbound。
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

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Connection

from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars
from app.marketdata.daily_bars import update_mairui_source_licence_id

Key = tuple[str, dt.date, str]
HEADER = ["code", "trade_date", "adj_type"]


@dataclass
class BindReport:
    licence_id: uuid.UUID | None
    rows: int
    applied: bool
    refused: str | None = None


def _process(
    conn: Connection, keys: list[Key], licence_id: uuid.UUID, *, apply: bool, undo: bool,
    source_licence: uuid.UUID | None = None, restore_to: uuid.UUID | None = None,
) -> int:
    match = licence_id if undo else source_licence
    value = restore_to if undo else licence_id
    return update_mairui_source_licence_id(conn, keys, match=match, value=value, apply=apply)


def bind(
    conn: Connection, manifest: Path, *, apply: bool, from_licence: uuid.UUID | None = None
) -> BindReport:
    """绑定 NULL 行；换证用 from_licence 直接改绑，不产生 unbound。"""
    ids = conn.execute(
        select(user_data_licences.c.id).where(
            user_data_licences.c.status == "active", user_data_licences.c.deleted_at.is_(None)
        )
    ).scalars().all()
    if len(ids) != 1:
        return BindReport(None, 0, False, f"active_licence_count:{len(ids)}")
    licence_id = ids[0]
    if from_licence is not None:
        owner = conn.execute(
            select(user_data_licences.c.user_id).where(user_data_licences.c.id == from_licence)
        ).scalar_one_or_none()
        active_owner = conn.execute(
            select(user_data_licences.c.user_id).where(user_data_licences.c.id == licence_id)
        ).scalar_one()
        if owner is None:
            return BindReport(licence_id, 0, False, "from_licence_missing")
        if owner != active_owner:
            return BindReport(licence_id, 0, False, "from_licence_not_owner")
        if from_licence == licence_id:
            return BindReport(licence_id, 0, False, "from_licence_is_active")
    stmt = (
        select(*(daily_bars.c[name] for name in HEADER))
        .where(
            daily_bars.c.source == "mairui",
            daily_bars.c.source_licence_id == from_licence
            if from_licence is not None else daily_bars.c.source_licence_id.is_(None),
        )
        .order_by(*(daily_bars.c[name] for name in HEADER))
    )
    if apply:
        stmt = stmt.with_for_update()
    keys: list[Key] = [(r.code, r.trade_date, r.adj_type) for r in conn.execute(stmt)]
    if not apply or not keys:
        return BindReport(licence_id, len(keys), apply)
    fd = os.open(manifest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        suffix = f" from_licence={from_licence}" if from_licence is not None else ""
        stream.write(f"# licence_id={licence_id}{suffix}\n")
        writer = csv.writer(stream, lineterminator="\n")
        writer.writerow(HEADER)
        writer.writerows((code, date.isoformat(), adj) for code, date, adj in keys)
        stream.flush()
        os.fsync(stream.fileno())
    count = _process(
        conn, keys, licence_id, apply=True, undo=False, source_licence=from_licence
    )
    if count != len(keys):
        raise RuntimeError(f"bind rowcount mismatch: expected {len(keys)}, got {count}")
    return BindReport(licence_id, count, True)


def rollback(conn: Connection, manifest: Path, *, apply: bool) -> BindReport:
    with manifest.open(encoding="utf-8", newline="") as stream:
        first = stream.readline().rstrip("\n")
        if not first.startswith("# licence_id="):
            raise ValueError("invalid manifest licence header")
        header, separator, source = first.partition(" from_licence=")
        licence_id = uuid.UUID(header.removeprefix("# licence_id="))
        restore_to = uuid.UUID(source) if separator else None
        expected = f"# licence_id={licence_id}"
        if restore_to is not None:
            expected += f" from_licence={restore_to}"
        if first != expected:
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
    count = _process(conn, keys, licence_id, apply=apply, undo=True, restore_to=restore_to)
    return BindReport(licence_id, count, apply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-B141 mairui licence binding")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--rollback", action="store_true")
    parser.add_argument("--from-licence", type=uuid.UUID)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="report row count only (default)")
    mode.add_argument("--apply", action="store_true", help="write changes")
    args = parser.parse_args(argv)
    if args.rollback and args.from_licence is not None:
        parser.error("--from-licence cannot be used with --rollback")
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        parser.error("DATABASE_URL is required in the environment")
    engine = create_engine(dsn)
    try:
        with engine.begin() as conn:
            if args.rollback:
                report = rollback(conn, args.manifest, apply=args.apply)
            else:
                report = bind(conn, args.manifest, apply=args.apply, from_licence=args.from_licence)
        if report.refused:
            print(report.refused)
            return 3
        suffix = f" from_licence={args.from_licence}" if args.from_licence is not None else ""
        print(f"licence_id={report.licence_id} rows={report.rows}{suffix}")
        return 0
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())

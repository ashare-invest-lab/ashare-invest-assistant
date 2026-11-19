"""年度 CSV staging → 公共 writer；只读调用环境 DATABASE_URL，不加载 .env。"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import psycopg
from sqlalchemy.dialects.postgresql import dialect
from sqlalchemy.engine import Connection
from sqlalchemy.sql import ClauseElement

from app.bj_offline_volume import RowReject
from app.marketdata.daily_bars import (
    UPSERT_BATCH_ROWS,
    DailyBar,
    DailyBarsResult,
    upsert_daily_bars,
)

_BEFORE = "INSERT INTO load_params VALUES (:'before'::date);"
_COPY = "COPY day_stage FROM :'csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');"
_MAIRUI = """SELECT count(*), count(*) FILTER (WHERE trade_date < %s)
             FROM market.daily_bars WHERE source = 'mairui'"""


def to_psycopg_dsn(url: str) -> str:
    """把 SQLAlchemy 风格 ``postgresql+psycopg://`` 转成 psycopg 可用的 ``postgresql://``。

    算法出处：``src/backend/app/api/v1/health.py`` 的 ``_psycopg_dsn``。
    不打印、不记录传入值。
    """
    if not isinstance(url, str) or not url.strip():
        raise RowReject("db_url_invalid")
    scheme, sep, rest = url.partition("://")
    if sep and "+" in scheme:
        scheme = scheme.split("+", 1)[0]
    return f"{scheme}{sep}{rest}"


class _WriterConnection:
    """在调用方的 psycopg 事务上执行公共 writer 的 SQLAlchemy 语句；不拥有连接。"""

    def __init__(self, conn: psycopg.Connection[tuple[Any, ...]]) -> None:
        self.conn = conn

    def execute(self, statement: ClauseElement) -> SimpleNamespace:
        pg_dialect = dialect()  # type: ignore[no-untyped-call]  # 第三方构造器未标注类型。
        compiled = statement.compile(
            dialect=pg_dialect, compile_kwargs={"render_postcompile": True},
        )
        with self.conn.cursor() as cursor:
            cursor.execute(str(compiled), compiled.params)
            names = [column.name for column in cursor.description] if cursor.description else []
            rows = [
                dict(zip(names, row, strict=False)) if not isinstance(row, Mapping) else dict(row)
                for row in cursor.fetchall()
            ] if names else []
        return SimpleNamespace(all=lambda: [SimpleNamespace(**row) for row in rows],
                               mappings=lambda: rows)


def load_day(
    conn: psycopg.Connection[tuple[Any, ...]], csv_path: Path, before: date,
) -> dict[str, int]:
    """拥有整年事务；已有行不覆盖，未确认 BJ 跳过，其他合法行仍提交。"""
    if int(conn.info.transaction_status) != 0:
        raise ValueError("connection_transaction_already_active")
    # 只分割受版本控制的固定语句；路径从不进入 SQL，日期使用绑定参数。
    sql = (Path(__file__).resolve().parents[2] / "probes" / "tb143_load_day.sql").read_text(
        encoding="utf-8",
    )
    setup, rest = sql.split(_BEFORE)
    stage, validate = rest.split(_COPY)
    counts = {"candidates": 0, "inserted": 0, "skipped": 0, "blocked_bj_unconfirmed": 0}
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(setup)
            cur.execute("INSERT INTO load_params VALUES (%s)", (before,))
            cur.execute(stage)
            with csv_path.open("rb") as stream, cur.copy(
                "COPY day_stage FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"
            ) as copy:
                while chunk := stream.read(1024 * 1024):
                    copy.write(chunk)
            cur.execute(validate)
            cur.execute(_MAIRUI, (before,))
            mairui_before, historical = cast(tuple[int, int], cur.fetchone())
            if historical:
                raise ValueError("before 之前已有麦蕊行，拒绝加载")
        stamp = datetime.now(UTC)
        # 服务端游标避免年度 CSV 一次性载入内存；writer 使用同一连接的独立游标。
        with conn.cursor(name="tb143_stage") as rows:
            rows.execute("SELECT code, trade_date, adj_type, open, high, low, close, "
                         "volume, amount FROM day_stage")
            while batch := rows.fetchmany(UPSERT_BATCH_ROWS):
                bars = [DailyBar(
                    code=r[0], trade_date=r[1], adj_type=r[2], open=r[3], high=r[4],
                    low=r[5], close=r[6], volume=r[7], amount=r[8],
                    pre_close=None, is_suspended=None,
                ) for r in batch]
                stats = upsert_daily_bars(
                    cast(Connection, _WriterConnection(conn)), DailyBarsResult(bars=bars),
                    source="tdx_local", licence_id=None, fetched_at=stamp,
                )
                counts["candidates"] += len(bars)
                counts["inserted"] += stats.inserted
                counts["blocked_bj_unconfirmed"] += stats.blocked_bj_unconfirmed
        with conn.cursor() as cur:
            cur.execute(_MAIRUI, (before,))
            if cur.fetchone() != (mairui_before, historical):
                raise ValueError("麦蕊行数变化，回滚本年加载")
        counts["skipped"] = counts["candidates"] - counts["inserted"]
    return counts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--before", type=date.fromisoformat, required=True)
    args = parser.parse_args(argv)
    try:
        dsn = to_psycopg_dsn(os.environ.get("DATABASE_URL", ""))
        with psycopg.connect(dsn) as conn:
            counts = load_day(conn, args.csv, args.before)
    except Exception as exc:  # noqa: BLE001 -- CLI 边界统一脱敏，失败不能输出驱动原文。
        # 驱动异常可能含连接串或输入数据；只报告类型，不输出敏感原文。
        print(f"REFUSED: {type(exc).__name__}; keep input artifacts; "
              "修复输入或运行环境后重试 "
              "python -m app.cli.tb143_day_load --csv <CSV> --before <DATE>",
              file=sys.stderr)
        return 1
    print("candidates|inserted|skipped")
    print(f"{counts['candidates']}|{counts['inserted']}|{counts['skipped']}")
    print(f"blocked_bj_unconfirmed|{counts['blocked_bj_unconfirmed']}")
    if counts["blocked_bj_unconfirmed"] > 0:
        print("INCOMPLETE: keep input artifacts; BJ 仍须通过公共 writer 确认门闩；"
              "满足条件后重试 python -m app.cli.tb143_day_load --csv <CSV> --before <DATE>")
        return 1
    print("COMPLETED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

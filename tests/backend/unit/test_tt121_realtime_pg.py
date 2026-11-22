"""T-T121 ③: realtime quote writes use an isolated PostgreSQL transaction."""

from __future__ import annotations

import datetime as dt
import os
import uuid
from collections.abc import Iterator
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

import pytest
from sqlalchemy import create_engine, select, text

from app.marketdata import realtime_collect
from app.db.tables.market import quotes_snapshot


CODE = "999121.SH"
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)


@pytest.fixture
def pg_conn() -> Iterator[Any]:
    url = os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip("TT41_DATABASE_URL 未设置：T-T121 需要隔离 PostgreSQL")
    parsed = urlsplit(url)
    assert parsed.hostname == "127.0.0.1" and parsed.port == 55432, (
        "T-T121 PG 例只允许连接 127.0.0.1:55432 隔离库"
    )
    engine = create_engine(url, hide_parameters=True)
    try:
        with engine.connect() as conn:
            transaction = conn.begin()
            try:
                # 仅在 127.0.0.1:55432 的隔离 TT41 测试库创建合成最小表。
                conn.execute(text("CREATE SCHEMA IF NOT EXISTS market"))
                conn.execute(
                    text(
                        """
                        CREATE TABLE IF NOT EXISTS market.quotes_snapshot (
                            code text NOT NULL,
                            ts timestamptz NOT NULL,
                            price numeric,
                            pct_change numeric,
                            payload jsonb,
                            source text,
                            source_licence_id uuid,
                            revision bigint NOT NULL DEFAULT 0,
                            content_fingerprint text,
                            volume numeric,
                            amount numeric,
                            is_suspended boolean,
                            limit_up boolean,
                            limit_down boolean,
                            batch_id uuid,
                            fetched_at timestamptz
                        )
                        """
                    )
                )
                conn.execute(
                    text(
                        """
                        CREATE UNIQUE INDEX IF NOT EXISTS
                            tt121_quotes_snapshot_owner_revision
                        ON market.quotes_snapshot
                            (code, ts, source, source_licence_id, revision)
                        WHERE source_licence_id IS NOT NULL
                          AND source IN ('mairui')
                        """
                    )
                )
                yield conn
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def _row(licence: uuid.UUID, *, price: str = "10.00") -> dict[str, object]:
    return {
        "code": CODE,
        "ts": NOW - dt.timedelta(minutes=1),
        "price": Decimal(price),
        "pct_change": Decimal("1.25"),
        "payload": {"fixture": "synthetic", "price": price},
        "source": "mairui",
        "source_licence_id": licence,
        "volume": Decimal("100"),
        "amount": Decimal("1000"),
        "is_suspended": False,
        "limit_up": None,
        "limit_down": None,
        "fetched_at": NOW,
    }


def test_realtime_write_and_conflict_are_queryable_and_duplicate_is_ignored(pg_conn: Any) -> None:
    licence = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
    row = _row(licence)

    realtime_collect._write_rows(pg_conn, [row], uuid.uuid4())
    assert realtime_collect._write_rows(pg_conn, [row], uuid.uuid4()) == 0
    saved = pg_conn.execute(
        select(quotes_snapshot.c.price, quotes_snapshot.c.source_licence_id).where(
            quotes_snapshot.c.code == CODE,
            quotes_snapshot.c.source_licence_id == licence,
        )
    ).all()
    assert [(price, lid) for price, lid in saved] == [(Decimal("10.0000"), licence)]


def test_realtime_read_isolated_by_source_licence_on_real_pg(pg_conn: Any) -> None:
    owner_licence = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
    other_licence = uuid.UUID("cccccccc-cccc-cccc-cccc-ccccccccccc1")
    realtime_collect._write_rows(pg_conn, [_row(owner_licence, price="10.00")], uuid.uuid4())
    realtime_collect._write_rows(pg_conn, [_row(other_licence, price="99.00")], uuid.uuid4())

    def visible_price(licence: uuid.UUID) -> Decimal:
        return pg_conn.execute(
            select(quotes_snapshot.c.price)
            .where(
                quotes_snapshot.c.code == CODE,
                quotes_snapshot.c.source == "mairui",
                quotes_snapshot.c.source_licence_id == licence,
            )
        ).scalar_one()

    assert visible_price(owner_licence) == Decimal("10.0000")
    assert visible_price(other_licence) == Decimal("99.0000")
    assert visible_price(owner_licence) != visible_price(other_licence)

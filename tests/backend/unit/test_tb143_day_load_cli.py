"""年度 CSV CLI 纯单测：合成数据、假 psycopg 事务，无真实 PG/网络。"""

from __future__ import annotations

import csv
import socket
from contextlib import contextmanager
from datetime import UTC, date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import psycopg
import pytest
from sqlalchemy import literal, select

from app.bj_offline_volume import RowReject
from app.cli import tb143_day_load as cli
from app.marketdata.daily_bars import UpsertStats

BEFORE = date(2025, 1, 1)
URL = "postgresql+psycopg://example.invalid/db"
RETRY = "python -m app.cli.tb143_day_load --csv <CSV> --before <DATE>"


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    def denied(*args, **kwargs):
        pytest.fail("纯单测禁止网络或真实 PG 连接")

    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(cli.psycopg, "connect", Mock(side_effect=denied))


class FakeCursor:
    def __init__(self, conn, name):
        self.conn, self.name = conn, name
        self.rows = list(conn.rows) if name else []

    def execute(self, sql, params=None):
        assert self.conn.info.transaction_status == 2
        self.conn.queries.append((self.name, sql, params))
        if sql.lstrip().startswith("DO $$"):
            self.conn.events.append("validate")
            if self.conn.validation_error:
                assert self.conn.validation_error in sql
                raise psycopg.errors.RaiseException(self.conn.validation_error)
        if sql == cli._MAIRUI:
            self.counts = next(self.conn.mairui_counts)

    @contextmanager
    def copy(self, sql):
        assert self.conn.info.transaction_status == 2
        self.conn.events.append("copy")
        self.conn.copy_sql = sql
        yield SimpleNamespace(write=self.conn.payload.extend)

    def fetchone(self):
        return self.counts

    def fetchmany(self, size):
        assert self.name == "tb143_stage"
        batch, self.rows = self.rows[:size], self.rows[size:]
        return batch


class FakeConnection:
    def __init__(self, rows=(), *, counts=((4, 0), (4, 0)), validation_error=None):
        self.info = SimpleNamespace(transaction_status=0)
        self.rows, self.mairui_counts = rows, iter(counts)
        self.validation_error = validation_error
        self.events, self.queries, self.payload = [], [], bytearray()
        self.stored, self.pending = ["existing-mairui"], []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True

    @contextmanager
    def transaction(self):
        assert self.info.transaction_status == 0
        self.info.transaction_status = 2
        self.events.append("begin")
        try:
            yield
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()

    @contextmanager
    def cursor(self, name=None):
        yield FakeCursor(self, name)

    def commit(self):
        self.events.append("commit")
        self.stored.extend(self.pending)
        self.pending.clear()
        self.info.transaction_status = 0

    def rollback(self):
        self.events.append("rollback")
        self.pending.clear()
        self.info.transaction_status = 0


@pytest.fixture
def batch(tmp_path):
    row = ("600999.SH", date(2024, 1, 2), "none", *(Decimal("12.34"),) * 4,
           Decimal("700"), Decimal("8638"))
    rows = [row, row, ("920999.BJ", *row[1:])]
    path = tmp_path / "synthetic.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows([
            ("code", "trade_date", "adj_type", "open", "high", "low", "close", "volume", "amount"),
            *rows,
        ])
    return path, rows


@pytest.fixture
def writer(monkeypatch):
    def upsert(adapter, result, **kwargs):
        conn = adapter.conn
        assert isinstance(adapter, cli._WriterConnection)
        assert conn.info.transaction_status == 2
        assert conn.events[-1] in ("validate", "writer")
        assert kwargs["source"] == "tdx_local" and kwargs["licence_id"] is None
        assert kwargs["fetched_at"].tzinfo == UTC
        conn.events.append("writer")
        inserted = blocked = 0
        for bar in result.bars:
            assert bar.volume == Decimal("700")
            assert bar.pre_close is None and bar.is_suspended is None
            if bar.code.endswith(".BJ"):
                blocked += 1
            elif bar not in conn.pending:
                conn.pending.append(bar)
                inserted += 1
        return UpsertStats(inserted, len(result.bars) - inserted - blocked, 0, (),
                           blocked_bj_unconfirmed=blocked)

    observed = Mock(side_effect=upsert)
    monkeypatch.setattr(cli, "upsert_daily_bars", observed)
    monkeypatch.setattr(cli, "UPSERT_BATCH_ROWS", 1)
    return observed


@pytest.mark.parametrize("url,expected", [
    (URL, "postgresql://example.invalid/db"),
    ("postgresql://example.invalid/db", "postgresql://example.invalid/db"),
])
def test_to_psycopg_dsn(url, expected):
    assert cli.to_psycopg_dsn(url) == expected


@pytest.mark.parametrize("url", ["", " \t", None, 123, b"postgresql://example.invalid/db"])
def test_to_psycopg_dsn_rejects_invalid(url):
    with pytest.raises(RowReject, match="^db_url_invalid$"):
        cli.to_psycopg_dsn(url)


@pytest.mark.parametrize("rows,description,expected", [
    ([(7,)], [SimpleNamespace(name="value")], [{"value": 7}]),
    ([{"value": 7}], [SimpleNamespace(name="value")], [{"value": 7}]),
    ([], None, []),
])
def test_writer_connection_compiles_and_wraps(rows, description, expected):
    conn = MagicMock()
    cursor = conn.cursor.return_value.__enter__.return_value
    cursor.description, cursor.fetchall.return_value = description, rows
    result = cli._WriterConnection(conn).execute(select(literal(7).label("value")))
    sql, params = cursor.execute.call_args.args
    assert sql == "SELECT %(param_1)s::INTEGER AS value" and params == {"param_1": 7}
    assert result.mappings() == expected
    assert [vars(row) for row in result.all()] == expected
    assert cursor.fetchall.call_count == bool(description)
    conn.commit.assert_not_called()
    conn.rollback.assert_not_called()


def test_load_day_rejects_active_transaction(batch, writer):
    path, rows = batch
    conn = FakeConnection(rows)
    conn.info.transaction_status = 2
    with pytest.raises(ValueError, match="^connection_transaction_already_active$"):
        cli.load_day(conn, path, BEFORE)
    assert conn.info.transaction_status == 2
    assert not conn.events and not conn.queries
    writer.assert_not_called()


def test_load_day_copies_validates_calls_writer_and_commits(batch, writer):
    path, rows = batch
    original = path.read_bytes()
    conn = FakeConnection(rows)
    assert cli.load_day(conn, path, BEFORE) == {
        "candidates": 3, "inserted": 1, "skipped": 2, "blocked_bj_unconfirmed": 1,
    }
    assert conn.events == ["begin", "copy", "validate", "writer", "writer", "writer", "commit"]
    assert writer.call_count == 3
    assert all(call.args[0].conn is conn for call in writer.call_args_list)
    bars = [call.args[1].bars[0] for call in writer.call_args_list]
    assert [(b.code, b.trade_date, b.adj_type, b.open, b.high, b.low, b.close, b.volume, b.amount)
            for b in bars] == rows
    assert conn.stored == ["existing-mairui", bars[0]] and not conn.pending
    assert conn.info.transaction_status == 0
    assert bytes(conn.payload) == original == path.read_bytes()
    assert conn.copy_sql == "COPY day_stage FROM STDIN WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')"
    assert "CREATE TEMP TABLE load_params" in conn.queries[0][1]
    assert conn.queries[1] == (None, "INSERT INTO load_params VALUES (%s)", (BEFORE,))
    assert "CREATE TEMP TABLE day_stage" in conn.queries[2][1]
    assert [(sql, params) for _, sql, params in conn.queries if sql == cli._MAIRUI] == [
        (cli._MAIRUI, (BEFORE,)), (cli._MAIRUI, (BEFORE,)),
    ]
    assert [name for name, _, _ in conn.queries if name] == ["tb143_stage"]


@pytest.mark.parametrize("counts,validation_error,reason,writer_calls", [
    (((4, 1),), None, "before 之前已有麦蕊行，拒绝加载", 0),
    (((4, 0), (5, 0)), None, "麦蕊行数变化，回滚本年加载", 3),
    (((4, 0),), "日线日期必须全部小于 before，拒绝加载",
     "日线日期必须全部小于 before，拒绝加载", 0),
    (((4, 0),), "每次只能加载一年的日线 CSV", "每次只能加载一年的日线 CSV", 0),
])
def test_load_day_batch_guards_roll_back(batch, writer, counts, validation_error, reason, writer_calls):
    path, rows = batch
    original = path.read_bytes()
    conn = FakeConnection(rows, counts=counts, validation_error=validation_error)
    error = psycopg.errors.RaiseException if validation_error else ValueError
    with pytest.raises(error, match=f"^{reason}$"):
        cli.load_day(conn, path, BEFORE)
    assert conn.events[-1] == "rollback" and "commit" not in conn.events
    assert conn.info.transaction_status == 0
    assert conn.stored == ["existing-mairui"] and not conn.pending
    assert writer.call_count == writer_calls
    assert path.read_bytes() == original


@pytest.mark.parametrize("failure", ["missing_url", "connect", "load"])
def test_main_refuses_without_leaking_driver_details(batch, monkeypatch, capsys, failure, writer):
    path, rows = batch
    conn = FakeConnection(rows, counts=((4, 1),))
    if failure != "missing_url":
        monkeypatch.setenv("DATABASE_URL", URL)
    connect = Mock(return_value=conn)
    if failure == "connect":
        connect.side_effect = psycopg.OperationalError(f"{URL} password=synthetic-redacted")
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    assert cli.main(["--csv", str(path), "--before", BEFORE.isoformat()]) == 1
    out, err = capsys.readouterr()
    assert not out
    assert "REFUSED:" in err and RETRY in err and "keep input artifacts" in err
    assert URL not in err and "example.invalid" not in err and "synthetic-redacted" not in err
    assert "password" not in err
    if failure == "missing_url":
        connect.assert_not_called()
    else:
        connect.assert_called_once_with("postgresql://example.invalid/db")
    writer.assert_not_called()
    assert path.is_file()


@pytest.mark.parametrize("blocked", [False, True])
def test_main_reports_success_or_bj_incomplete(batch, writer, monkeypatch, capsys, blocked):
    path, rows = batch
    conn = FakeConnection(rows if blocked else rows[:1])
    monkeypatch.setenv("DATABASE_URL", URL)
    connect = Mock(return_value=conn)
    monkeypatch.setattr(cli.psycopg, "connect", connect)
    original = path.read_bytes()
    assert cli.main(["--csv", str(path), "--before", BEFORE.isoformat()]) == int(blocked)
    out, err = capsys.readouterr()
    assert not err
    assert "candidates|inserted|skipped\n" + ("3|1|2" if blocked else "1|1|0") in out
    assert f"blocked_bj_unconfirmed|{int(blocked)}\n" in out
    assert ("INCOMPLETE" in out) == blocked
    assert ("COMPLETED" in out) == (not blocked)
    if blocked:
        assert RETRY in out and "keep input artifacts" in out
    assert writer.call_count == (3 if blocked else 1)
    assert conn.events[-1] == "commit" and conn.closed
    assert path.read_bytes() == original
    connect.assert_called_once_with("postgresql://example.invalid/db")

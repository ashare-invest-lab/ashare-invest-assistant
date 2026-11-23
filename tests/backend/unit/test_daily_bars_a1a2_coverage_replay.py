"""Offline/replay coverage for the A1+A2 daily-bar wiring."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from app.db.tables.daily_bars import outbox
from app.db.tables.licences import user_data_licence_holds as holds
from app.db.tables.market import daily_bars, trading_calendar
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.ingest import daily_bars as fetcher
from app.ingest.daily_bars_consumer import (
    MairuiDailyBarsTransport,
    _decode_daily_bars,
    process,
)
from app.ingest.daily_lists import DailyHaltError
from app.marketdata.daily_bars import DailyBar
from app.marketdata.daily_bars_outbox import enqueue
from psycopg import sql
from sqlalchemy import create_engine, insert, select, text
from sqlalchemy.engine import make_url

DAY = dt.date(2026, 11, 12)
NOW = dt.datetime(2026, 11, 12, 10, tzinfo=dt.UTC)
OWNER, LID, RID = (uuid.UUID(int=n) for n in (921, 922, 923))
CODES = ["000001.SH", "000002.SH"]
GRANT = fetcher.DailyBarsGrant(
    OWNER,
    LID,
    RID,
    NOW - dt.timedelta(hours=1),
    NOW + dt.timedelta(hours=1),
    "synthetic-a1-a2-replay",
)


@pytest.fixture
def consumer_world(pg_url, monkeypatch: pytest.MonkeyPatch, tmp_path):
    url = make_url(pg_url)
    assert url.host in {"127.0.0.1", "localhost", "::1", "postgres"}
    name = "a1a2_replay_" + uuid.uuid4().hex
    admin = psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    )
    engine = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(url.set(drivername="postgresql+psycopg", database=name))
        with engine.begin() as conn:
            conn.execute(text("CREATE SCHEMA app"))
            conn.execute(text("CREATE SCHEMA market"))
            for table in (users, pipeline_runs, outbox, holds, trading_calendar, daily_bars):
                table.create(conn)
            conn.execute(
                text(
                    "CREATE TABLE app.user_data_licence_status "
                    "(id uuid, user_id uuid, status text, paused_until timestamptz, "
                    "expires_on date, deleted_at timestamptz)"
                )
            )
            conn.execute(
                insert(users).values(
                    id=OWNER,
                    username="synthetic_a1a2",
                    display_name="synthetic",
                    role="user",
                    status="approved",
                    password_hash="unusable",
                )
            )
            conn.execute(
                text(
                    "INSERT INTO app.user_data_licence_status(id,user_id,status) "
                    "VALUES (:id,:owner,'active')"
                ),
                {"id": LID, "owner": OWNER},
            )
            conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
        monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 5)
        monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 5)
        monkeypatch.setattr(fetcher, "daily_universe", lambda *_: CODES)
        yield SimpleNamespace(engine=engine, root=tmp_path)
    finally:
        if engine is not None:
            engine.dispose()
        admin.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(name)))
        admin.close()


def _queue(world: Any) -> uuid.UUID:
    with world.engine.begin() as conn:
        enqueue(
            conn,
            trade_date=DAY,
            user_id=OWNER,
            batch_seq=0,
            batch_kind="daily",
            window_trading_days=None,
            grant_reader=lambda _: GRANT,
            now=NOW,
        )
        return conn.execute(select(outbox.c.id)).scalar_one()


def test_decoder_replays_valid_rows_and_rejects_invalid_payload() -> None:
    result = _decode_daily_bars(
        "000001.SH",
        {
            "data": [
                {
                    "t": "2026-11-12 00:00:00",
                    "o": "10.1",
                    "h": "10.8",
                    "l": "9.9",
                    "c": "10.5",
                    "pc": "10.0",
                    "v": "100",
                    "a": "1050",
                    "sf": None,
                }
            ]
        },
    )
    assert result is not None and len(result.bars) == 1
    assert result.bars[0].close == 10.5
    assert result.bars[0].is_suspended is None
    assert _decode_daily_bars("000001.SH", {"status": 200}) is None
    with pytest.raises(DailyHaltError, match="daily_bars_payload_invalid"):
        _decode_daily_bars("000001.SH", {"data": [{"t": "bad-date"}]})


def test_mairui_transport_replays_sh_and_bj_routes(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []
    from app.ingest import daily_lists, egress, runtime

    monkeypatch.setattr(daily_lists, "credential", lambda *_: "synthetic-secret")
    monkeypatch.setattr(runtime, "get_ingest_core", lambda: "synthetic-core")

    def replay_get(**kwargs: object) -> SimpleNamespace:
        calls.append(kwargs)
        return SimpleNamespace(
            status=200,
            body=[
                {
                    "t": "20261112",
                    "o": "1",
                    "h": "2",
                    "l": "1",
                    "c": "2",
                    "pc": "1",
                    "v": "10",
                    "a": "20",
                    "sf": False,
                }
            ],
        )

    monkeypatch.setattr(egress, "mairui_get", replay_get)
    transport = MairuiDailyBarsTransport(object())
    common = {
        "lease": object(),
        "item": {"user_id": OWNER},
        "grant": GRANT,
        "start": DAY,
        "end": DAY,
        "clock": lambda: NOW,
        "stop": fetcher.HALT.parent / "synthetic-stop",
        "halt": fetcher.HALT.parent / "synthetic-halt",
    }
    sh_status, sh_result = transport(code="000001.SH", **common)
    bj_status, bj_result = transport(code="430001.BJ", **common)
    assert sh_status == bj_status == 200
    assert sh_result is not None and bj_result is not None
    assert calls[0]["path"] == "/hsstock/history/000001.SH/d/n/?st=20261112&et=20261112"
    assert calls[1]["path"] == "/bj/history/430001.BJ/d/n/?st=20261112&et=20261112"
    assert all(call["core"] == "synthetic-core" for call in calls)


def test_process_uses_egress_bound_transport_replay(
    consumer_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import daily_lists, egress, runtime

    monkeypatch.setattr(daily_lists, "credential", lambda *_: "synthetic-secret")
    monkeypatch.setattr(runtime, "get_ingest_core", lambda: "synthetic-core")
    calls: list[str] = []

    def replay_get(**kwargs: object) -> SimpleNamespace:
        calls.append(str(kwargs["path"]))
        return SimpleNamespace(
            status=200,
            body=[
                {
                    "t": "20261112",
                    "o": "1",
                    "h": "2",
                    "l": "1",
                    "c": "2",
                    "pc": "1",
                    "v": "10",
                    "a": "20",
                    "sf": False,
                }
            ],
        )

    monkeypatch.setattr(egress, "mairui_get", replay_get)
    bid = _queue(consumer_world)
    result = process(
        consumer_world.engine,
        bid,
        transport=MairuiDailyBarsTransport(consumer_world.engine),
        grant_reader=lambda _: GRANT,
        clock=lambda: NOW,
        stop=consumer_world.root / "STOP",
        halt=consumer_world.root / "HALTED",
    )
    assert result == "done"
    assert calls == [
        "/hsstock/history/000001.SH/d/n/?st=20261112&et=20261112",
        "/hsstock/history/000002.SH/d/n/?st=20261112&et=20261112",
    ]


def test_process_rejects_missing_grant_before_transport(
    consumer_world: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.ingest import daily_lists, egress, runtime

    monkeypatch.setattr(daily_lists, "credential", lambda *_: "synthetic-secret")
    monkeypatch.setattr(runtime, "get_ingest_core", lambda: "synthetic-core")
    monkeypatch.setattr(egress, "mairui_get", lambda **_: pytest.fail("transport must not run"))
    bid = _queue(consumer_world)
    result = process(
        consumer_world.engine,
        bid,
        transport=MairuiDailyBarsTransport(consumer_world.engine),
        grant_reader=lambda _: None,
        clock=lambda: NOW,
        stop=consumer_world.root / "STOP",
        halt=consumer_world.root / "HALTED",
    )
    assert result == "failed"


def test_https_get_inserts_encoded_secret_before_query(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest import egress

    requested: list[str] = []

    class RawSocket:
        def settimeout(self, _timeout: int) -> None:
            pass

        def connect(self, _address: tuple[str, int]) -> None:
            pass

    class TLS:
        def close(self) -> None:
            pass

    class Context:
        def wrap_socket(self, _raw: RawSocket, server_hostname: str) -> TLS:
            assert server_hostname == egress.HOST
            return TLS()

    class Response:
        status = 200

        def read(self, _limit: int) -> bytes:
            return b'{"ok": true}'

    class Connection:
        def __init__(self, _host: str, timeout: int) -> None:
            assert timeout == 20
            self.sock = None

        def request(self, method: str, path: str) -> None:
            assert method == "GET"
            requested.append(path)

        def getresponse(self) -> Response:
            return Response()

    monkeypatch.setattr(
        egress.socket,
        "getaddrinfo",
        lambda *_args, **_kwargs: [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))
        ],
    )
    monkeypatch.setattr(egress.socket, "socket", lambda *_args: RawSocket())
    monkeypatch.setattr(egress.ssl, "create_default_context", lambda: Context())
    monkeypatch.setattr(egress.http.client, "HTTPSConnection", Connection)
    monkeypatch.setattr(egress.ng, "register_resolved_ip", lambda _ip: None)
    status, body = egress._https_get("/history/?st=20261112", "secret/value")
    assert status == 200 and body == {"ok": True}
    assert requested == ["/history/secret%2Fvalue?st=20261112"]


def test_bootstrap_applies_budget_before_database_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest import daily_bars
    from app.workers import ingest as worker

    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(
        daily_bars,
        "configure_batch_limits",
        lambda *, daily, backfill: seen.append((daily, backfill)),
    )
    settings = SimpleNamespace(
        database_url=None,
        business=SimpleNamespace(
            ingest=SimpleNamespace(
                budget=SimpleNamespace(daily_bars_batch_limit=500, daily_bars_backfill_batch_limit=2000)
            )
        ),
    )
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        worker.bootstrap_ingest_core(settings)
    assert seen == [(500, 2000)]


def test_daily_bars_task_applies_budget_before_off_source(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest import daily_bars as ingest_daily_bars
    from app.marketdata import daily_bars as module
    from app.workers import jobs

    seen: list[tuple[int, int]] = []
    monkeypatch.setattr(
        ingest_daily_bars,
        "configure_batch_limits",
        lambda *, daily, backfill: seen.append((daily, backfill)),
    )
    monkeypatch.setattr(module, "_record_run", lambda *args, **kwargs: None)

    class Engine:
        def begin(self):
            class Transaction:
                def __enter__(self):
                    return object()

                def __exit__(self, *_args):
                    return False

            return Transaction()

    monkeypatch.setattr(jobs, "_engine", lambda _settings: Engine())
    settings = SimpleNamespace(
        daily_bars_source="off",
        business=SimpleNamespace(
            ingest=SimpleNamespace(
                budget=SimpleNamespace(daily_bars_batch_limit=500, daily_bars_backfill_batch_limit=2000)
            )
        ),
    )
    assert module.daily_bars_fetch_task(settings, DAY.isoformat()) == 0
    assert seen == [(500, 2000)]


def test_daily_bar_type_used_by_replay() -> None:
    assert isinstance(DailyBar("000001.SH", DAY, "none", None, None, None, None, None, None, None, None), DailyBar)

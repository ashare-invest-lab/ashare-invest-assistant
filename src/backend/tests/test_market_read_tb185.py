"""T-B185 read regressions; all database and Redis facts are synthetic."""

# ruff: noqa: S101
from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
import redis
from starlette.requests import Request

from app.api.v1 import health, securities
from app.licences import ingest_status
from app.marketdata import bars_read, daily_snapshot, owned_daily_read, quotes_read
from app.schemas.enums import DataStatus, GapReason

DAY = dt.date(2026, 11, 13)
OWNER = uuid.UUID(int=185)
CODE = "999991.SH"


@pytest.mark.parametrize(
    ("now", "is_open", "expected_day", "fetched", "status"),
    [
        ("2026-11-13T15:00:00+08:00", True, DAY, "2026-11-13T15:00:00+08:00", "fresh"),
        ("2026-11-13T20:00:00+08:00", True, DAY, "2026-11-13T17:00:00+08:00", "fresh"),
        ("2026-11-15T12:00:00+08:00", False, DAY, "2026-11-13T17:00:00+08:00", "fresh"),
        ("2026-11-16T10:00:00+08:00", True, DAY, "2026-11-13T17:00:00+08:00", "stale"),
        ("2026-11-16T14:59:59+08:00", True, DAY, "2026-11-13T17:00:00+08:00", "stale"),
        (
            "2026-11-16T16:00:00+08:00",
            True,
            dt.date(2026, 11, 16),
            "2026-11-13T17:00:00+08:00",
            "stale",
        ),
        ("2026-11-15T12:00:00+08:00", None, DAY, "2026-11-13T17:00:00+08:00", "stale"),
        ("2026-11-15T12:00:00+08:00", False, None, "2026-11-13T17:00:00+08:00", "stale"),
        ("2026-11-15T12:00:00+08:00", False, DAY, "2026-11-14T10:00:00+08:00", "stale"),
    ],
)
def test_quote_close_freshness(
    monkeypatch: pytest.MonkeyPatch,
    now: str,
    is_open: bool | None,
    expected_day: dt.date | None,
    fetched: str,
    status: str,
) -> None:
    instant = dt.datetime.fromisoformat(now)

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return instant.astimezone(tz)

    monkeypatch.setattr(
        quotes_read,
        "dt",
        SimpleNamespace(datetime=Clock, time=dt.time, timedelta=dt.timedelta, UTC=dt.UTC),
    )
    conn = MagicMock()
    identity = SimpleNamespace(code=CODE, name="合成", type="stock")
    calendar = MagicMock()
    calendar.scalar_one_or_none.return_value = is_open
    latest = MagicMock()
    latest.scalar_one_or_none.return_value = expected_day
    conn.execute.side_effect = [MagicMock(all=Mock(return_value=[identity])), calendar, latest]
    monkeypatch.setattr(daily_snapshot, "active_licence_id", Mock(return_value=OWNER))
    monkeypatch.setattr(
        quotes_read,
        "_daily_closes",
        Mock(
            return_value={
                CODE: SimpleNamespace(
                    close=Decimal("8.25"),
                    pre_close=Decimal("8"),
                    trade_date=DAY,
                    fetched_at=dt.datetime.fromisoformat(fetched),
                    volume=Decimal("12300"),
                    amount=Decimal("101475.00"),
                )
            }
        ),
    )
    item = quotes_read.read_quotes(conn, OWNER, (CODE,)).items[0]
    assert item.data_status == status
    assert item.volume == "12300"
    assert item.amount == "101475.00"
    assert item.data_as_of == dt.datetime.fromisoformat(fetched).isoformat()


def test_quote_query_selects_raw_volume_and_amount() -> None:
    conn = MagicMock()
    quotes_read._daily_closes(conn, (CODE,), OWNER, dt.datetime.now(dt.UTC))
    columns = conn.execute.call_args.args[0].selected_columns.keys()
    assert "volume" in columns
    assert "amount" in columns


@pytest.mark.parametrize(
    ("raw", "paused", "unavailable", "expected"),
    [
        ('{"ts":1000}', False, False, "ok"),
        ('{"ts":880}', False, False, "ok"),
        ('{"ts":879}', False, False, "stale"),
        (None, False, False, "stale"),
        ('{"ts":true}', False, False, "stale"),
        ('{"ts":"1000"}', False, False, "stale"),
        ('{"ts":1000.0}', False, False, "stale"),
        ("[]", False, False, "stale"),
        ("broken", False, False, "stale"),
        (b"\xff", False, False, "stale"),
        (None, True, False, "paused"),
        ('{"ts":1000}', True, True, "unknown"),
    ],
)
def test_ingest_heartbeat_reuses_ready_state(
    monkeypatch: pytest.MonkeyPatch,
    raw: bytes | str | None,
    paused: bool,
    unavailable: bool,
    expected: str,
) -> None:
    settings = SimpleNamespace(
        ingest_heartbeat_key="synthetic:heartbeat",
        ingest_paused_key="synthetic:paused",
        ingest_stale_after_s=120,
        business=SimpleNamespace(securities=SimpleNamespace(master=SimpleNamespace())),
    )
    rds = MagicMock()
    rds.get.return_value = raw
    rds.exists.return_value = paused
    if unavailable:
        rds.get.side_effect = redis.ConnectionError("synthetic outage")
    monkeypatch.setattr(ingest_status, "now_utc", lambda: dt.datetime.fromtimestamp(1000, dt.UTC))
    monkeypatch.setattr(ingest_status.service, "ingest_licences", lambda *a: ([], False))
    for name, value in [
        ("_leader", None),
        ("_oldest_queued", {}),
        ("_errors_24h", []),
        ("_used_last_minute", 0),
        ("_ip_alerts_24h", 0),
        ("master_alerts", []),
    ]:
        monkeypatch.setattr(ingest_status, name, Mock(return_value=value))
    shared = Mock(wraps=health.ingest_state)
    monkeypatch.setattr(health, "ingest_state", shared)
    body = ingest_status.build(MagicMock(), rds, settings)
    assert body["heartbeat"] == expected
    if not unavailable:
        shared.assert_called_once()
        assert body["heartbeat"] == health.ingest_state(
            paused=paused, heartbeat=raw, stale_after_s=120, now=1000
        )
    assert not {"ts", "heartbeat_at", "heartbeat_time"} & body.keys()


@pytest.mark.parametrize("reason", ["suspended", "future_reason", "", None, 42, []])
def test_bars_unknown_gap_reason_returns_200(reason: object) -> None:
    query = bars_read.BarsQuery("d", "none", None, None, None, 500)
    body = bars_read.empty_bars(CODE, "合成", query)
    body["gaps"] = [{"key": "bars", "reason": reason, "message": "当日停牌"}]
    request = Request({"type": "http", "query_string": b"freq=d&adjust=none"})
    response = securities.security_bars(
        CODE, request, SimpleNamespace(user_id=OWNER), Mock(read=Mock(return_value=body)), None
    )
    assert response.status_code == 200
    gap = json.loads(response.body)["gaps"][0]
    assert gap["reason"] == GapReason.NO_SOURCE
    assert gap["message"] == "当日停牌"


def test_owned_suspension_uses_contract_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = MagicMock()
    conn.execute.return_value.all.return_value = [
        SimpleNamespace(trade_date=DAY, is_suspended=True)
    ]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    monkeypatch.setattr(
        bars_read.PlaceholderBarsReader,
        "read",
        lambda *a: bars_read.empty_bars(
            CODE, "合成", bars_read.BarsQuery("d", "none", None, None, None, 500)
        ),
    )
    monkeypatch.setattr(owned_daily_read, "active_licence_id", lambda *a: OWNER)
    monkeypatch.setattr(owned_daily_read, "_expected_day", lambda *a: DAY)
    body = owned_daily_read.OwnedDailyBarsReader(engine).read(
        OWNER, CODE, bars_read.BarsQuery("d", "none", None, None, None, 500)
    )
    assert body["gaps"][0]["reason"] == GapReason.NO_SOURCE
    assert body["gaps"][0]["message"] == "当日停牌"
    assert bars_read.BarsResponse.model_validate(body).data_status is DataStatus.UNAVAILABLE


@pytest.mark.parametrize("reason", list(GapReason))
def test_bars_preserves_known_gap_reason(reason: GapReason) -> None:
    gap = bars_read.BarsGap(key="bars", reason=reason, message="合成缺口")
    assert gap.reason is reason

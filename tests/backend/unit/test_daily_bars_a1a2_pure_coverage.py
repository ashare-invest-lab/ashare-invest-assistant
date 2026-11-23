"""Pure synthetic coverage for the configurable daily-bar ingest wiring."""

from __future__ import annotations

import socket
from types import SimpleNamespace
from typing import Any

import pytest
from app.config_files import IngestBudget
from app.ingest import daily_bars as fetcher
from app.ingest import egress
from app.ingest.daily_bars_consumer import _decode_daily_bars
from app.ingest.daily_lists import DailyHaltError
from app.workers import ingest as ingest_worker


def _budget(**overrides: Any) -> IngestBudget:
    values: dict[str, Any] = {
        "per_minute_budget": 10,
        "max_concurrency": 1,
        "shares": {"snapshot": 3, "minute_bars": 3, "other": 3},
        "priority_min_share": {"p0_intraday": 0.7, "p2_backfill_intraday": 0.0},
        "daily_bars_batch_limit": 500,
        "daily_bars_backfill_batch_limit": 2000,
    }
    values.update(overrides)
    return IngestBudget.model_validate(values)


def test_ingest_budget_accepts_limits_and_rejects_out_of_range() -> None:
    budget = _budget()
    assert budget.daily_bars_batch_limit == 500
    assert budget.daily_bars_backfill_batch_limit == 2000
    with pytest.raises(ValueError):
        _budget(daily_bars_batch_limit=501)
    with pytest.raises(ValueError):
        _budget(daily_bars_backfill_batch_limit=2001)
    with pytest.raises(ValueError):
        _budget(shares={"snapshot": 4, "minute_bars": 4, "other": 4})


def test_ingest_budget_defaults_limits_for_legacy_config() -> None:
    values = _budget().model_dump()
    values.pop("daily_bars_batch_limit")
    values.pop("daily_bars_backfill_batch_limit")
    budget = IngestBudget.model_validate(values)
    assert (budget.daily_bars_batch_limit, budget.daily_bars_backfill_batch_limit) == (500, 2000)


def test_configure_batch_limits_is_fail_closed_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher.configure_batch_limits(daily=5, backfill=7)
    assert fetcher.DAILY_BARS_BATCH_LIMIT == 5
    assert fetcher.DAILY_BARS_BACKFILL_BATCH_LIMIT == 7
    with pytest.raises(ValueError):
        fetcher.configure_batch_limits(daily=0, backfill=7)
    with pytest.raises(ValueError):
        fetcher.configure_batch_limits(daily=5, backfill=2001)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BATCH_LIMIT", 0)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 0)


def test_decoder_accepts_trade_date_alias_and_decimal_failure() -> None:
    result = _decode_daily_bars(
        "000001.SH",
        [{"trade_date": "20261112", "c": "10.25", "v": "7", "sf": True}],
    )
    assert result is not None
    assert result.bars[0].close == 10.25
    assert result.bars[0].volume == 700
    assert result.bars[0].is_suspended is True
    with pytest.raises(DailyHaltError, match="daily_bars_payload_invalid"):
        _decode_daily_bars("000001.SH", [{"t": "20261112", "c": "bad"}])


def test_https_get_handles_empty_dns_and_status_without_real_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(egress.socket, "getaddrinfo", lambda *_args, **_kwargs: [])
    with pytest.raises(DailyHaltError, match="transport_or_response_failed_no_retry"):
        egress._https_get("/history/", "synthetic")

    requested: list[str] = []

    class RawSocket:
        def settimeout(self, value: int) -> None:
            assert value == 20

        def connect(self, address: tuple[str, int]) -> None:
            assert address == ("127.0.0.1", 443)

    class Tls:
        def close(self) -> None:
            pass

    class Context:
        def wrap_socket(self, raw: RawSocket, *, server_hostname: str) -> Tls:
            assert server_hostname == egress.HOST
            return Tls()

    class Response:
        status = 429

        def read(self, _limit: int) -> bytes:
            pytest.fail("rate-limited response must not read a body")

    class Connection:
        def __init__(self, host: str, *, timeout: int) -> None:
            assert host == egress.HOST and timeout == 20
            self.sock: Tls | None = None

        def request(self, method: str, path: str) -> None:
            requested.append(f"{method} {path}")

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
    status, body = egress._https_get("/history/?st=20261112", "synthetic/value")
    assert status == 429 and body is None
    assert requested == ["GET /history/synthetic%2Fvalue?st=20261112"]


def test_worker_heartbeat_temp_engine_passes_transport_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import engine as engine_module
    from app.ingest import daily_bars_consumer, daily_lists, runtime, verify_licence

    events: list[str] = []

    class Client:
        def set(self, *_args: object, **_kwargs: object) -> None:
            events.append("heartbeat")

        def exists(self, _key: str) -> bool:
            return False

        def close(self) -> None:
            events.append("closed")

    class Engine:
        def dispose(self) -> None:
            events.append("disposed")

    engine = Engine()
    monkeypatch.setattr(ingest_worker.redis.Redis, "from_url", lambda *a, **k: Client())
    monkeypatch.setattr(engine_module, "engine_for", lambda *a, **k: engine)
    monkeypatch.setattr(runtime, "get_ingest_core", lambda: None)
    monkeypatch.setattr(runtime, "tick_ingest_core", lambda: events.append("core"))
    monkeypatch.setattr(daily_lists, "tick", lambda *a, **k: events.append("lists"))
    monkeypatch.setattr(verify_licence, "tick", lambda *a, **k: events.append("verify"))
    monkeypatch.setattr(ingest_worker, "tick_realtime_quotes", lambda *a, **k: events.append("quotes"))
    monkeypatch.setattr(daily_bars_consumer, "wake_delayed", lambda *a, **k: events.append("wake"))

    def observed_tick(_engine: object, **kwargs: object) -> int:
        assert kwargs["transport"].__class__.__name__ == "MairuiDailyBarsTransport"
        events.append("bars")
        return 0

    monkeypatch.setattr(daily_bars_consumer, "tick", observed_tick)
    settings = SimpleNamespace(
        redis_url="redis://synthetic",
        health_check_timeout_s=1,
        ingest_heartbeat_key="synthetic:heartbeat",
        ingest_paused_key="synthetic:paused",
        daily_bars_source="mairui",
        database_url=SimpleNamespace(get_secret_value=lambda: "synthetic-dsn"),
        business=SimpleNamespace(ingest=SimpleNamespace(heartbeat=SimpleNamespace(ttl_s=30))),
    )
    ingest_worker.write_heartbeat(settings)
    assert events == ["heartbeat", "lists", "verify", "bars", "wake", "quotes", "disposed", "core", "closed"]

"""T-B224 realtime breaker tests with synthetic clocks and upstream errors."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.marketdata.realtime_collect import RealtimeCollectionStoppedError
from app.workers import ingest


def _settings(cooldown: int = 300) -> SimpleNamespace:
    return SimpleNamespace(
        realtime_quotes_source="mairui",
        business=SimpleNamespace(
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(quote_interval_s=0),
                adaptive=SimpleNamespace(breaker_cooldown_s=cooldown),
            )
        ),
    )


@pytest.mark.parametrize("status", [429, 503])
def test_status_breaker_skips_during_cooldown_and_recovers(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    task = Mock(side_effect=RealtimeCollectionStoppedError("upstream", status=status))
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr(ingest, "_realtime_breaker_until", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    settings = _settings()
    ingest.tick_realtime_quotes(settings, now_monotonic=100.0)
    ingest.tick_realtime_quotes(settings, now_monotonic=399.9)
    assert task.call_count == 1
    ingest.tick_realtime_quotes(settings, now_monotonic=400.0)
    assert task.call_count == 2


def test_cooldown_reads_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock(side_effect=RealtimeCollectionStoppedError("upstream", status=503))
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr(ingest, "_realtime_breaker_until", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(10), now_monotonic=100.0)
    ingest.tick_realtime_quotes(_settings(10), now_monotonic=109.9)
    assert task.call_count == 1
    ingest.tick_realtime_quotes(_settings(10), now_monotonic=110.0)
    assert task.call_count == 2


@pytest.mark.parametrize("error", [RealtimeCollectionStoppedError("upstream", status=500), RealtimeCollectionStoppedError("local")])
def test_other_stopped_errors_do_not_break(monkeypatch: pytest.MonkeyPatch, error: RealtimeCollectionStoppedError) -> None:
    task = Mock(side_effect=error)
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr(ingest, "_realtime_breaker_until", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(), now_monotonic=100.0)
    ingest.tick_realtime_quotes(_settings(), now_monotonic=100.1)
    assert task.call_count == 2


def test_zero_cooldown_does_not_break(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock(side_effect=RealtimeCollectionStoppedError("upstream", status=429))
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr(ingest, "_realtime_breaker_until", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    settings = _settings(0)
    ingest.tick_realtime_quotes(settings, now_monotonic=100.0)
    ingest.tick_realtime_quotes(settings, now_monotonic=100.1)
    assert task.call_count == 2

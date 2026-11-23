"""Ingest heartbeat realtime quote scheduling stays inside the ingest boundary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from app.workers import ingest


def _settings(source: str = "mairui", interval: int = 15) -> SimpleNamespace:
    return SimpleNamespace(
        realtime_quotes_source=source,
        business=SimpleNamespace(
            realtime=SimpleNamespace(intervals=SimpleNamespace(quote_interval_s=interval))
        ),
    )


def test_realtime_tick_calls_when_gate_is_due(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock()
    engine = Mock()
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(), engine=engine, now_monotonic=100.0)

    task.assert_called_once_with(_settings(), engine=engine)


def test_realtime_tick_skips_before_interval(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock()
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", 100.0)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(), engine=Mock(), now_monotonic=114.9)

    task.assert_not_called()


def test_realtime_tick_skips_when_source_is_not_mairui(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock()
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(source="off"), engine=Mock(), now_monotonic=100.0)

    task.assert_not_called()


def test_realtime_tick_logs_task_error_without_raising(monkeypatch: pytest.MonkeyPatch) -> None:
    task = Mock(side_effect=RuntimeError("synthetic failure"))
    monkeypatch.setattr(ingest, "_last_realtime_quotes_tick", None)
    monkeypatch.setattr("app.marketdata.realtime_collect.realtime_quotes_task", task)

    ingest.tick_realtime_quotes(_settings(), engine=Mock(), now_monotonic=100.0)

    task.assert_called_once()

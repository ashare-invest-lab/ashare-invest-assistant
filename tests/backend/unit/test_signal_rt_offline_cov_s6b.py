"""Test worker activation and cleanup only; no intraday rules, adapters, or services."""

from __future__ import annotations

import datetime as dt
import runpy
import socket
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from app.intraday import consumer
from app.notify import transport
from app.workers import jobs, runner, signal_rt


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("signal worker unit tests must not connect to services")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(signal_rt, "_consumer", None)


@pytest.mark.parametrize("mode", ["local", "staging", "production"])
def test_non_test_environment_stays_paused_before_resource_creation(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    def denied(*args: object) -> None:
        raise AssertionError("paused worker must not construct or flush resources")

    for name in ("Consumer", "_redis", "_engine", "flush"):
        monkeypatch.setattr(signal_rt, name, denied)
    signal_rt.tick(SimpleNamespace(app_env=mode))
    assert signal_rt._consumer is None


def test_test_environment_reuses_consumer_and_flushes_the_same_utc_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(app_env="test")
    client, engine = object(), object()
    events: list[object] = []
    times: list[dt.datetime] = []
    instance = SimpleNamespace(client=client)

    def redis(config: object) -> object:
        assert config is settings
        events.append("redis")
        return client

    def make_consumer(config: object, connection: object) -> Any:
        assert config is settings and connection is client
        events.append("consumer")
        return instance

    def pump(at: dt.datetime) -> None:
        assert at.tzinfo is dt.UTC
        times.append(at)
        events.append("pump")

    def make_engine(config: object) -> object:
        assert config is settings
        events.append("engine")
        return engine

    def flush(actual_engine: object, actual_client: object, at: dt.datetime) -> None:
        assert actual_engine is engine and actual_client is client
        assert at is times[-1]
        events.append("flush")

    instance.pump = pump
    monkeypatch.setattr(signal_rt, "Consumer", make_consumer)
    monkeypatch.setattr(signal_rt, "_redis", redis)
    monkeypatch.setattr(signal_rt, "_engine", make_engine)
    monkeypatch.setattr(signal_rt, "flush", flush)
    signal_rt.tick(settings)
    signal_rt.tick(settings)
    assert signal_rt._consumer is instance
    assert events == [
        "redis",
        "consumer",
        "pump",
        "engine",
        "flush",
        "pump",
        "engine",
        "flush",
    ]
    assert len(times) == 2


def test_failed_pump_does_not_flush_or_create_an_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(at: dt.datetime) -> None:
        raise RuntimeError("synthetic pump failure")

    def denied(*args: object) -> None:
        raise AssertionError("failed pump must not flush notifications")

    cached = SimpleNamespace(pump=broken)
    monkeypatch.setattr(signal_rt, "_consumer", cached)
    monkeypatch.setattr(signal_rt, "_engine", denied)
    monkeypatch.setattr(signal_rt, "flush", denied)
    with pytest.raises(RuntimeError, match="synthetic pump failure"):
        signal_rt.tick(SimpleNamespace(app_env="test"))
    assert signal_rt._consumer is cached


@pytest.mark.parametrize("outcome", ["idle", "normal", "error"])
def test_entry_disposes_only_its_created_consumer_even_when_runner_fails(
    monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    events: list[str] = []
    settings = SimpleNamespace(app_env="test")
    client = SimpleNamespace(close=lambda: events.append("client.close"))
    instance = SimpleNamespace(
        client=client,
        pump=lambda at: events.append("pump"),
        close=lambda: events.append("consumer.close"),
    )

    def make_consumer(config: object, connection: object) -> Any:
        assert config is settings and connection is client
        events.append("consumer")
        return instance

    def run(name: str, tick: Any, *, interval_s: int) -> int:
        assert name == "signal-rt" and interval_s == 1
        if outcome != "idle":
            tick(settings)
        if outcome == "error":
            raise RuntimeError("synthetic runner failure")
        return 7

    monkeypatch.setattr(consumer, "Consumer", make_consumer)
    monkeypatch.setattr(jobs, "_redis", lambda config: client)
    monkeypatch.setattr(jobs, "_engine", lambda config: object())
    monkeypatch.setattr(transport, "flush", lambda *args: events.append("flush"))
    monkeypatch.setattr(runner, "run", run)
    if outcome == "error":
        with pytest.raises(RuntimeError, match="synthetic runner failure"):
            runpy.run_path(str(Path(signal_rt.__file__)), run_name="__main__")
    else:
        with pytest.raises(SystemExit) as stopped:
            runpy.run_path(str(Path(signal_rt.__file__)), run_name="__main__")
        assert stopped.value.code == 7
    assert events == (
        []
        if outcome == "idle"
        else ["consumer", "pump", "flush", "consumer.close", "client.close"]
    )

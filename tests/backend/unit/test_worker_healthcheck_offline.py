"""Synthetic worker healthcheck decisions; no processes or external services."""

from __future__ import annotations

import runpy
import socket
import sys
from types import SimpleNamespace

import pytest
from app.workers import healthcheck, runner

NOW = 1_800_000_000.0


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("worker healthcheck attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def alive_at(monkeypatch: pytest.MonkeyPatch, mtime: float) -> None:
    monkeypatch.setattr(healthcheck.time, "time", lambda: NOW)
    monkeypatch.setattr(
        healthcheck,
        "alive_file",
        lambda name: SimpleNamespace(stat=lambda: SimpleNamespace(st_mtime=mtime)),
    )


@pytest.mark.parametrize("argv", [[], ["unknown"], ["worker", "beat"]])
def test_main_rejects_missing_unknown_or_extra_arguments(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    argv: list[str],
) -> None:
    def must_not_read(name: str) -> None:
        pytest.fail(f"invalid argv reached alive_file: {name}")

    monkeypatch.setattr(healthcheck, "alive_file", must_not_read)
    assert healthcheck.main(argv) == 2
    assert capsys.readouterr().err == (
        "用法：python -m app.workers.healthcheck {worker|beat|ingest|signal-rt}\n"
    )


@pytest.mark.parametrize("name", healthcheck.NAMES)
def test_main_accepts_each_fresh_worker(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    alive_at(monkeypatch, NOW)
    assert healthcheck.main([name]) == 0


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (3 * healthcheck.ALIVE_INTERVAL_S, 0),
        (3 * healthcheck.ALIVE_INTERVAL_S + 0.001, 1),
    ],
)
def test_main_enforces_alive_age_boundary(
    monkeypatch: pytest.MonkeyPatch, age: float, expected: int
) -> None:
    alive_at(monkeypatch, NOW - age)
    assert healthcheck.main(["worker"]) == expected


def test_main_treats_missing_alive_file_as_unhealthy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing(name: str) -> None:
        raise FileNotFoundError(name)

    monkeypatch.setattr(healthcheck, "alive_file", missing)
    assert healthcheck.main(["beat"]) == 1


def test_module_entrypoint_exits_with_main_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(healthcheck.time, "time", lambda: NOW)
    monkeypatch.setattr(
        runner,
        "alive_file",
        lambda name: SimpleNamespace(stat=lambda: SimpleNamespace(st_mtime=NOW)),
    )
    monkeypatch.setattr(sys, "argv", ["python -m app.workers.healthcheck", "beat"])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(healthcheck.__file__, run_name="__main__")
    assert exit_info.value.code == 0

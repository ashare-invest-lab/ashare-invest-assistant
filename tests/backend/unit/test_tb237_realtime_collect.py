"""T-B237 verifies the registered realtime transport seam."""

from __future__ import annotations

import ast
import datetime as dt
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.marketdata import realtime_collect
from tests.backend.unit.test_ta91_a1s_static_t_t55 import (
    _realtime_quotes_seam_lines,
    _s5_transport_inject,
)

OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)


class _Context:
    def __init__(self, value: object) -> None:
        self.value = value

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, *_args: object) -> bool:
        return False


class _Engine:
    def __init__(self) -> None:
        self.connection = Mock()

    def begin(self) -> _Context:
        return _Context(self.connection)


@pytest.fixture(autouse=True)
def _live_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")


def test_realtime_collect_has_only_registered_transport_seam() -> None:
    path = Path(__file__).parents[3] / "src/backend/app/marketdata/realtime_collect.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    allowed = {f"kw:transport:{line}" for line in _realtime_quotes_seam_lines(tree)}
    assert set(_s5_transport_inject(tree)) == allowed


def test_collect_entry_accepts_synthetic_upstream_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = _Engine()
    clock = SimpleNamespace(trade_date=NOW.date(), session=SimpleNamespace(value="morning"))
    calls: list[tuple[str, str]] = []

    def upstream(path: str, secret: str) -> tuple[int, object]:
        calls.append((path, secret))
        return 200, [{"code": "600000.SH", "ts": NOW}]

    def fetch(*_args: object, **kwargs: object) -> tuple[int, object]:
        injected = kwargs["upstream"]
        assert injected is upstream
        return injected("synthetic-path", "synthetic-secret")  # type: ignore[operator]

    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", fetch)
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: 1)

    written = realtime_collect.collect_realtime_quotes(
        engine.connection,
        settings,
        owner=OWNER,
        now=NOW,
        upstream=upstream,
        engine=engine,
    )

    assert written == 1
    assert calls == [("synthetic-path", "synthetic-secret")]


def test_fetch_maps_synthetic_upstream_to_egress(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engine = Mock()
    core = object()
    upstream = Mock(return_value=(200, [{"synthetic": True}]))
    seen: dict[str, object] = {}

    def fake_mairui_get(**kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        status, body = kwargs["transport"]("synthetic-path", "synthetic-secret")  # type: ignore[operator]
        return SimpleNamespace(status=status, body=body)

    monkeypatch.setattr(realtime_collect, "get_ingest_core", lambda: core)
    monkeypatch.setattr(realtime_collect, "single_egress", lambda _engine: _Context("lease"))
    monkeypatch.setattr(realtime_collect, "mairui_get", fake_mairui_get)

    status, body = realtime_collect._fetch_with_egress(
        engine,
        SimpleNamespace(),
        owner=OWNER,
        licence_id=LICENCE,
        now=NOW,
        path="synthetic-path",
        upstream=upstream,
        secret_loader=lambda *_args: "synthetic-secret",
        stop=tmp_path / "stop",
        halt=tmp_path / "halt",
    )

    assert (status, body) == (200, [{"synthetic": True}])
    assert seen["transport"] is upstream
    assert "upstream" not in seen
    upstream.assert_called_once_with("synthetic-path", "synthetic-secret")

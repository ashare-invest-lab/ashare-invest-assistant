"""S14 M3：合成实时快照通过写入边界且全程禁止网络。"""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock

from app.marketdata import realtime_collect

OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)
CODES = ["990000.SH", "990001.SZ"]


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
        self.begin_calls = 0

    def begin(self) -> _Context:
        self.begin_calls += 1
        return _Context(self.connection)


def test_replay_snapshot_batch_reaches_writer_without_network(
    monkeypatch, tmp_path
) -> None:
    socket_calls: list[object] = []

    def reject_socket(*args: object, **kwargs: object) -> None:
        socket_calls.append((args, kwargs))
        raise AssertionError("M3 replay must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", reject_socket)
    monkeypatch.setattr(socket, "create_connection", reject_socket)
    monkeypatch.setattr(realtime_collect, "verification_is_offline", lambda: False)
    monkeypatch.setattr(
        realtime_collect,
        "_open_clock",
        lambda *_args: SimpleNamespace(
            trade_date=NOW.date(), session=SimpleNamespace(value="morning")
        ),
    )
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: CODES)
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (
            200,
            [
                {
                    "dm": "990000",
                    "ts": "2030-06-11T10:00:00+08:00",
                    "price": "12.34",
                },
                {
                    "dm": "990001",
                    "ts": "2030-06-11T10:00:00+08:00",
                    "price": "23.45",
                },
            ],
        ),
    )

    writes: list[tuple[list[dict[str, object]], uuid.UUID]] = []

    def capture_write(_conn: object, rows: list[dict[str, object]], batch_id: uuid.UUID) -> int:
        writes.append((rows, batch_id))
        return len(rows)

    monkeypatch.setattr(realtime_collect, "_write_rows", capture_write)
    engine = _Engine()
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    stop = tmp_path / "STOP"
    halt = tmp_path / "HALT"

    result = realtime_collect.collect_realtime_quotes(
        engine.connection,
        settings,
        owner=OWNER,
        now=NOW,
        upstream=Mock(),
        engine=engine,
        stop=stop,
        halt=halt,
    )

    assert result == 2
    assert engine.begin_calls == 1
    assert len(writes) == 1
    rows, batch_id = writes[0]
    assert batch_id.int
    assert [row["code"] for row in rows] == CODES
    assert all(row["source"] == "mairui" for row in rows)
    assert all(row["source_licence_id"] == LICENCE for row in rows)
    assert all(row["ts"] == NOW for row in rows)
    assert socket_calls == []
    assert not stop.exists()
    assert not halt.exists()

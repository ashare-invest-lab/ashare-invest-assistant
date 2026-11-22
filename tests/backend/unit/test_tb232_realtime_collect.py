"""T-B232 verifies post-commit realtime publication reads from a fresh connection."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest

from app.marketdata import quotes_read, realtime_collect, realtime_publish


OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
LICENCE = uuid.UUID("bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1")
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)


class _Context:
    def __init__(self, value: object, on_exit: object | None = None) -> None:
        self.value = value
        self.on_exit = on_exit

    def __enter__(self) -> object:
        return self.value

    def __exit__(self, *_args: object) -> bool:
        if callable(self.on_exit):
            self.on_exit()
        return False


class _Connection:
    def __init__(self, visible_rows: list[str]) -> None:
        self.visible_rows = visible_rows
        self.pending_rows: list[str] = []


class _Engine:
    def __init__(self) -> None:
        self.committed_rows = ["old-row"]
        self.write_conn = _Connection(self.committed_rows)
        self.read_conn = _Connection(self.committed_rows)

    def begin(self) -> _Context:
        def commit() -> None:
            self.committed_rows.extend(self.write_conn.pending_rows)
            self.write_conn.pending_rows.clear()
            self.read_conn.visible_rows = self.committed_rows

        return _Context(self.write_conn, commit)

    def connect(self) -> _Context:
        return _Context(self.read_conn)


@pytest.fixture(autouse=True)
def _live_mode_for_collection_tests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAIRUI_MODE", "live")


def test_realtime_publish_reads_committed_rows_on_fresh_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = SimpleNamespace(realtime_quotes_source="mairui")
    engine = _Engine()
    caller_conn = _Connection(["old-row"])
    clock = SimpleNamespace(
        trade_date=NOW.date(),
        session=SimpleNamespace(value="morning"),
    )
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: clock)
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: LICENCE)
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: ["600000.SH"])
    monkeypatch.setattr(
        realtime_collect,
        "_fetch_with_egress",
        lambda *_args, **_kwargs: (200, [{"code": "600000.SH", "ts": NOW}]),
    )

    def write_rows(write_conn: _Connection, rows: list[dict[str, object]], _batch_id: uuid.UUID) -> int:
        assert rows
        write_conn.pending_rows.append("new-row")
        return 1

    monkeypatch.setattr(realtime_collect, "_write_rows", write_rows)
    read_connections: list[object] = []
    published: list[object] = []

    def read_rows(read_conn: _Connection, *_args: object) -> object:
        read_connections.append(read_conn)
        item = read_conn.visible_rows[-1]
        return SimpleNamespace(items=[SimpleNamespace(security_code=item, t="2030-06-11T10:00:00+08:00")])

    def publish(_redis: object, _owner: uuid.UUID, response: object, _stamp: dt.datetime) -> bool:
        published.append(response)
        return True

    monkeypatch.setattr(quotes_read, "read_quotes", read_rows)
    monkeypatch.setattr(realtime_publish, "publish_quote", publish)

    assert (
        realtime_collect.collect_realtime_quotes(
            caller_conn,
            settings,
            owner=OWNER,
            now=NOW,
            engine=engine,
            redis_client=object(),
        )
        == 1
    )
    assert caller_conn.visible_rows == ["old-row"]
    assert engine.committed_rows == ["old-row", "new-row"]
    assert read_connections == [engine.read_conn]
    assert published[0].items[0].security_code == "new-row"

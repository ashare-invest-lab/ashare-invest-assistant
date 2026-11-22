"""T-T121 ②: a published quote reaches the real /stream route once."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Callable
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app.api.v1 import notifications
from app.auth import deps
from app.auth.sessions import Session
from app.config import Settings
from app.main import create_app
from app.marketdata.realtime_publish import publish_quote


OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
OTHER_OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2")
SID = "synthetic-session"
AT = dt.datetime.now(dt.UTC)


class _FakeRedis:
    """Small in-memory Redis surface used by transport.publish/replay."""

    def __init__(self) -> None:
        self.strings: dict[str, bytes] = {}
        self.sorted_sets: dict[str, dict[str, float]] = {}
        self.hashes: dict[str, dict[str, str]] = {}
        self.poll_hook: Callable[[], None] | None = None
        self.polled = False
        self.disconnected = False

    def get(self, key: str) -> bytes:
        self._assert_sse_key(key, "seq")
        return self.strings.get(key, b"0")

    def eval(self, script: str, numkeys: int, *args: object) -> bytes | list[bytes]:
        if numkeys == 1:
            assert args[0] == "p2n06:notify:pending"
            return []
        assert numkeys == 4
        keys = [str(value) for value in args[:numkeys]]
        owner = self._assert_sse_keys(keys)
        token = str(args[numkeys + 4])
        dedup_key = keys[3]
        if "SET" in script and token and dedup_key in self.strings:
            return b""
        sequence_key, order_key, body_key, _ = keys
        sequence = int(self.strings.get(sequence_key, b"0")) + 1
        identifier = str(sequence)
        self.strings[sequence_key] = identifier.encode()
        self.sorted_sets.setdefault(order_key, {})[identifier] = float(args[numkeys])
        self.hashes.setdefault(body_key, {})[identifier] = str(args[numkeys + 1])
        if token:
            self.strings[dedup_key] = b"1"
        assert owner
        return identifier.encode()

    def zscore(self, key: str, member: str) -> float | None:
        self._assert_sse_key(key, "order")
        return self.sorted_sets.get(key, {}).get(str(member))

    def zrangebyscore(
        self,
        key: str,
        minimum: object,
        maximum: object,
        start: int | None = None,
        num: int | None = None,
        withscores: bool = False,
        score_cast_func: Callable[[float], object] = float,
    ) -> list[bytes] | list[tuple[bytes, object]]:
        self._assert_sse_key(key, "order")
        if self.poll_hook is not None and not self.polled:
            self.polled = True
            self.poll_hook()
        low = float(str(minimum).lstrip("("))
        high = float(str(maximum))
        result = [
            (identifier, score)
            for identifier, score in sorted(
                self.sorted_sets.get(key, {}).items(), key=lambda item: int(item[0])
            )
            if low <= score <= high
        ]
        if start is not None:
            result = result[start : None if num is None else start + num]
        if withscores:
            return [(identifier.encode(), score_cast_func(score)) for identifier, score in result]
        identifiers = [identifier.encode() for identifier, _score in result]
        self.disconnected = True
        return identifiers

    def hget(self, key: str, member: str) -> bytes | None:
        self._assert_sse_key(key, "body")
        body = self.hashes.get(key, {}).get(str(member))
        return None if body is None else body.encode()

    @staticmethod
    def _assert_sse_key(key: str, suffix: str) -> str:
        parts = key.split(":")
        assert len(parts) == 4
        assert parts[:2] == ["p2n06", "sse"]
        assert parts[3] == suffix
        uuid.UUID(parts[2])
        return parts[2]

    @classmethod
    def _assert_sse_keys(cls, keys: list[str]) -> str:
        assert len(keys) == 4
        owner = cls._assert_sse_key(keys[0], "seq")
        assert keys == [
            f"p2n06:sse:{owner}:seq",
            f"p2n06:sse:{owner}:order",
            f"p2n06:sse:{owner}:body",
            f"p2n06:sse:{owner}:dedup:{keys[3].rsplit(':', 1)[-1]}",
        ]
        return owner


def _response() -> SimpleNamespace:
    return SimpleNamespace(
        items=[
            SimpleNamespace(
                security_code="999991.SH",
                name="虚构证券",
                price="10.00",
                change_pct="1.00",
                amount="1000",
                t="2030-06-11T09:31:00+08:00",
            )
        ]
    )


def test_stream_receives_one_quote_after_write_and_deduplicates_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        app_env="test",
        database_url="postgresql://127.0.0.1:1/aia_test",
        redis_url="redis://127.0.0.1:1/0",
        app_master_key="test-only-master-key-xxxxxxxxxxxxxxxx",
    )
    monkeypatch.setattr("app.main.check_startup", lambda _settings: None)
    monkeypatch.setattr("app.main.private_keys_present", lambda: False)
    rds = _FakeRedis()
    store = SimpleNamespace(get=lambda sid: Session("digest", str(OWNER), "csrf", AT.isoformat()))
    engine = object()
    auth = SimpleNamespace(user_id=OWNER)
    monkeypatch.setattr(notifications, "load_user", lambda _engine, _uid: SimpleNamespace(status="approved"))
    monkeypatch.setattr(
        Request,
        "is_disconnected",
        lambda request: _is_disconnected(request, rds),
    )
    app = create_app(settings)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_redis] = lambda: rds
    app.dependency_overrides[deps.get_session_store] = lambda: store
    app.dependency_overrides[deps.current_auth] = lambda: auth
    response = _response()
    rds.poll_hook = lambda: publish_quote(rds, OWNER, response, AT)

    with TestClient(app) as client:
        client.cookies.set("sid", SID)
        with client.stream("GET", "/api/v1/stream") as stream:
            body = "".join(stream.iter_text())

    assert body.count("event: quote") == 1
    quote_start = body.index("event: quote")
    event_id = body[:quote_start].rsplit("id: ", 1)[1].splitlines()[0].strip()
    assert event_id
    frame = body.split("event: quote\ndata: ", 1)[1].split("\n\n", 1)[0]
    payload = json.loads(frame)
    assert isinstance(payload["data_as_of"], str) and payload["data_as_of"]
    item = payload["items"][0]
    assert item["security_code"] == "999991.SH"
    assert isinstance(item["t"], str) and item["t"]
    assert not publish_quote(rds, OWNER, response, AT)
    owner_order_key = f"p2n06:sse:{OWNER}:order"
    owner_body_key = f"p2n06:sse:{OWNER}:body"
    assert rds.sorted_sets[owner_order_key] == {"1": AT.timestamp()}
    assert rds.hashes[owner_body_key][event_id]

    assert publish_quote(rds, OTHER_OWNER, response, AT)
    other_order_key = f"p2n06:sse:{OTHER_OWNER}:order"
    other_body_key = f"p2n06:sse:{OTHER_OWNER}:body"
    assert rds.sorted_sets[other_order_key] == {"1": AT.timestamp()}
    assert rds.hashes[other_body_key]["1"]
    assert owner_order_key != other_order_key
    assert owner_body_key != other_body_key
    assert rds.sorted_sets[owner_order_key] == {"1": AT.timestamp()}
    assert set(rds.hashes[owner_body_key]) == {event_id}


async def _is_disconnected(_request: Request, rds: _FakeRedis) -> bool:
    return rds.disconnected

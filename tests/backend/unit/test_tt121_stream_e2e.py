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
SID = "synthetic-session"
AT = dt.datetime.now(dt.UTC)


class _FakeRedis:
    """Small in-memory Redis surface used by transport.publish/replay."""

    def __init__(self) -> None:
        self.sequence = 0
        self.events: dict[str, tuple[float, str]] = {}
        self.dedup: set[str] = set()
        self.poll_hook: Callable[[], None] | None = None
        self.polled = False
        self.disconnected = False

    def get(self, key: str) -> bytes:
        assert key.endswith(":seq")
        return str(self.sequence).encode()

    def eval(self, script: str, numkeys: int, *args: object) -> bytes | list[bytes]:
        if numkeys == 1:
            return []
        assert numkeys == 4
        token = str(args[-1])
        if "SET" in script and token and token in self.dedup:
            return b""
        self.sequence += 1
        identifier = str(self.sequence)
        self.events[identifier] = (float(args[4]), str(args[5]))
        if token:
            self.dedup.add(token)
        return identifier.encode()

    def zscore(self, key: str, member: str) -> float | None:
        assert key.endswith(":order")
        event = self.events.get(str(member))
        return None if event is None else event[0]

    def zrangebyscore(self, key: str, minimum: object, maximum: object) -> list[bytes]:
        assert key.endswith(":order")
        if self.poll_hook is not None and not self.polled:
            self.polled = True
            self.poll_hook()
        low = float(str(minimum).lstrip("("))
        high = float(str(maximum))
        result = [
            identifier.encode()
            for identifier, (score, _body) in sorted(
                self.events.items(), key=lambda item: int(item[0])
            )
            if low <= score <= high
        ]
        if result:
            self.disconnected = True
        return result

    def hget(self, key: str, member: str) -> bytes | None:
        assert key.endswith(":body")
        event = self.events.get(str(member))
        return None if event is None else event[1].encode()


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
    frame = body.split("event: quote\ndata: ", 1)[1].split("\n\n", 1)[0]
    payload = json.loads(frame)
    assert payload["items"][0]["security_code"] == "999991.SH"
    assert len(rds.events) == 1
    assert not publish_quote(rds, OWNER, response, AT)
    assert len(rds.events) == 1


async def _is_disconnected(_request: Request, rds: _FakeRedis) -> bool:
    return rds.disconnected

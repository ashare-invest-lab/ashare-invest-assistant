"""T-T117：T-B222 /stream quote 发布验收，虚构夹具、禁网。"""
from __future__ import annotations
import asyncio
import datetime as dt
import json
import re
import uuid
from pathlib import Path
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.api.v1 import notifications
from app.auth import deps
from app.auth.sessions import SESSION_COOKIE
from app.config import Settings, get_settings
from app.main import create_app
from app.marketdata import quotes_read, realtime_collect
from app.schemas.enums import DataStatus
OWNER = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1")
CODE, CODE_2 = "999991.SH", "999992.SZ"
NOW = dt.datetime(2030, 6, 11, 2, 0, tzinfo=dt.UTC)
EARLY, LATE = "2030-06-11T09:31:00+08:00", "2030-06-11T09:32:00+08:00"
class FakeRedis:
    def __init__(self) -> None:
        self.seq = 0
        self.order: list[tuple[float, str]] = []
        self.body: dict[str, dict[str, object]] = {}
        self.dedup: set[str] = set()
    def get(self, key: str) -> bytes:
        return str(self.seq).encode() if key.endswith(":seq") else b"0"
    def eval(self, _script: str, numkeys: int, *_args: object) -> list[bytes] | bytes:
        if numkeys == 1:
            return []
        if numkeys != 4:
            raise AssertionError(f"unexpected Redis script shape: {numkeys}")
        at, raw_body, _cutoff, _ttl, token = _args
        token_text = str(token)
        if token_text and token_text in self.dedup:
            return b""
        if token_text:
            self.dedup.add(token_text)
        self.seq += 1
        identifier = str(self.seq)
        self.order.append((float(at), identifier))
        self.body[identifier] = json.loads(str(raw_body))
        return identifier.encode()
    def zscore(self, _key: str, identifier: str) -> float | None:
        return next((score for score, item in self.order if item == identifier), None)
    def zrangebyscore(self, _key: str, lower: float, upper: float) -> list[bytes]:
        return [item.encode() for score, item in self.order if lower <= score <= upper]
    def hget(self, _key: str, identifier: str) -> bytes:
        return json.dumps(self.body[identifier], ensure_ascii=False).encode()
class Clock(dt.datetime):
    @classmethod
    def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
        return NOW if tz is None else NOW.astimezone(tz)
def _settings(source: str) -> Settings:
    return Settings(app_env="test", database_url=None, redis_url=None,
                    realtime_quotes_source=source, session_cookie_secure=False,
                    business=get_settings().business)
def _wired() -> bool:
    """确认 marketdata 生产代码已把 quote 接到发布路径（不含通用 transport）。"""
    pat = re.compile(r"\bpublish\s*\([\s\S]{0,500}['\"]quote['\"]")
    root = Path(realtime_collect.__file__).resolve().parent
    return any(pat.search(item.read_text()) for item in root.glob("*.py"))
def _require_wired() -> None:
    if not _wired():
        pytest.xfail("待 T-B222：生产入口尚未接入 /stream quote 发布（R376 裁定 /stream；T-B222）")
def _quote(code: str, price: str, stamp: str) -> dict[str, str]:
    return {"code": code, "price": price, "pct_change": "1.00", "amount": "1000", "ts": stamp}
def _quote_response(rows: list[dict[str, str]]) -> quotes_read.QuotesResponse:
    return quotes_read.QuotesResponse(items=[quotes_read.QuoteItem(
        security_code=row["code"], name="虚构证券", price=row["price"],
        change_pct=row["pct_change"], amount=row["amount"], t=row["ts"],
        data_status=DataStatus.FRESH, data_as_of=row["ts"], gaps=[])
        for row in rows])
def _events(text: str) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for block in text.split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines and "data" in lines:
            result.append({"event": lines["event"], "data": json.loads(lines["data"])})
    return result
async def _read_stream(app: object, last_id: str | None) -> str:
    messages: list[bytes] = []
    disconnected = asyncio.Event()
    done = asyncio.Event()
    first = True
    async def receive() -> dict[str, object]:
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}
    async def send(message: dict[str, object]) -> None:
        if message["type"] == "http.response.body":
            messages.append(message.get("body", b""))
            disconnected.set()
            if not message.get("more_body", False):
                done.set()
    headers = [(b"cookie", f"{SESSION_COOKIE}=synthetic-session".encode())]
    if last_id is not None:
        headers.append((b"last-event-id", last_id.encode()))
    scope = {"type": "http", "http_version": "1.1", "method": "GET", "scheme": "http",
             "path": "/api/v1/stream", "raw_path": b"/api/v1/stream", "query_string": b"",
             "headers": headers, "client": ("127.0.0.1", 1234), "server": ("testserver", 80)}
    task = asyncio.create_task(app(scope, receive, send))  # type: ignore[operator]
    try:
        await asyncio.wait_for(done.wait(), timeout=1)
        await asyncio.wait_for(task, timeout=1)
    finally:
        if not task.done():
            task.cancel()
    return b"".join(messages).decode()
@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    rds = FakeRedis()
    state = SimpleNamespace(rows=[_quote(CODE, "10.00", EARLY)])
    settings = _settings("mairui")
    conn = MagicMock()
    engine = SimpleNamespace(connect=lambda: nullcontext(conn), begin=lambda: nullcontext(conn))
    store = SimpleNamespace(get=lambda _sid: SimpleNamespace(user_id=str(OWNER)))
    app = create_app(settings)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_redis] = lambda: rds
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.get_session_store] = lambda: store
    monkeypatch.setattr(notifications, "load_user", lambda *_args: SimpleNamespace(status="approved"))
    monkeypatch.setattr(notifications, "dt", SimpleNamespace(datetime=Clock, UTC=dt.UTC, timedelta=dt.timedelta))
    monkeypatch.setattr("app.workers.jobs._engine", lambda _settings: engine)
    monkeypatch.setattr(realtime_collect, "_open_clock", lambda *_args: SimpleNamespace(
        trade_date=NOW.date(), session=SimpleNamespace(value="morning")))
    monkeypatch.setattr(realtime_collect, "active_licence_id", lambda *_args: uuid.UUID(int=2))
    monkeypatch.setattr(realtime_collect, "_owned_codes", lambda *_args: [row["code"] for row in state.rows])
    monkeypatch.setattr(realtime_collect, "_fetch_with_egress", lambda *_args, **_kwargs: (200, state.rows))
    monkeypatch.setattr(realtime_collect, "_write_rows", lambda *_args: len(state.rows))
    monkeypatch.setattr(quotes_read, "read_quotes", lambda *_args, **_kwargs: _quote_response(state.rows))
    monkeypatch.setattr(realtime_collect, "mairui_get", lambda *_args, **_kwargs: pytest.fail("不得调用麦蕊"))
    return SimpleNamespace(app=app, rds=rds, state=state, settings=settings)
def _run(world: SimpleNamespace, source: str | None = None) -> int:
    settings = world.settings if source is None else _settings(source)
    return realtime_collect.realtime_quotes_task(settings, owner=OWNER, now=NOW)
def _quote_events(world: SimpleNamespace, last_id: str) -> list[dict[str, object]]:
    return [event for event in _events(asyncio.run(_read_stream(world.app, last_id)))
            if event["event"] == "quote"]
def _assert_quote_shape(event: dict[str, object]) -> None:
    data = event["data"]
    assert isinstance(data, dict)
    assert set(data) == {"items", "data_as_of"}
    assert isinstance(data["data_as_of"], str) and data["data_as_of"]
    assert isinstance(data["items"], list) and data["items"]
    for item in data["items"]:
        assert set(item) == {"security_code", "name", "price", "change_pct", "amount", "t"}
        assert isinstance(item["t"], str) and item["t"]
    assert "source" not in data and "basis" not in data

def test_no_quote_change_does_not_publish(world: SimpleNamespace) -> None:
    _require_wired()
    _run(world)
    baseline = str(world.rds.seq)
    assert any(payload["event"] == "quote" for payload in world.rds.body.values())
    _run(world)
    assert _quote_events(world, baseline) == []

def test_realtime_quotes_source_off_does_not_publish(world: SimpleNamespace) -> None:
    _require_wired()
    _run(world)
    assert any(payload["event"] == "quote" for payload in world.rds.body.values())
    baseline = str(world.rds.seq)
    world.state.rows = [_quote(CODE, "10.01", LATE)]
    _run(world, "off")
    assert _quote_events(world, baseline) == []

def test_changed_cached_quote_publishes_once_with_contract_shape(world: SimpleNamespace) -> None:
    _require_wired()
    _run(world)
    baseline = str(world.rds.seq)
    world.state.rows = [_quote(CODE, "10.01", LATE)]
    _run(world)
    events = _quote_events(world, baseline)
    assert len(events) == 1
    _assert_quote_shape(events[0])

def test_quote_data_as_of_is_earliest_actual_item_time(world: SimpleNamespace) -> None:
    _require_wired()
    _run(world)
    baseline = str(world.rds.seq)
    world.state.rows = [_quote(CODE, "10.01", EARLY), _quote(CODE_2, "20.01", LATE)]
    _run(world)
    events = _quote_events(world, baseline)
    assert len(events) == 1
    _assert_quote_shape(events[0])
    data = events[0]["data"]
    assert data["data_as_of"] == EARLY
    assert data["data_as_of"] != Clock.now(dt.timezone(dt.timedelta(hours=8))).isoformat()

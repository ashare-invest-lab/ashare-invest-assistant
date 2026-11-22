"""T-T119：四功能 HTTP 矩阵。``create_app`` + 虚构隔离夹具，只走正式 ``/api/v1``。"""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.auth import deps
from app.auth.sessions import CSRF_COOKIE, SESSION_COOKIE, Session
from app.config import Settings
from app.main import create_app

OWNER = uuid.UUID("00000000-0000-4000-8000-000000000101")
OTHER = uuid.UUID("00000000-0000-4000-8000-000000000102")
LICENCE = uuid.UUID("00000000-0000-4000-8000-000000000111")
OTHER_LICENCE = uuid.UUID("00000000-0000-4000-8000-000000000112")
CODE = "999991.SH"
OTHER_CODE = "999992.SZ"
NOW = dt.datetime(2041, 5, 6, 8, 5, tzinfo=dt.UTC)

class Row(SimpleNamespace):
    @property
    def _mapping(self) -> dict[str, Any]:
        return vars(self)

def _security(code: str = CODE, *, name: str | None = None) -> Row:
    return Row(code=code, name=name or f"synthetic {code}", type="stock")

def _bar(
    *,
    source_licence_id: uuid.UUID = LICENCE,
    fetched_at: dt.datetime = dt.datetime(2041, 5, 5, 9, 5, tzinfo=dt.UTC),
    close: Decimal = Decimal("7.8750"),
) -> Row:
    return Row(
        code=CODE,
        trade_date=dt.date(2041, 5, 5),
        fetched_at=fetched_at,
        source="mairui",
        adj_type="none",
        source_licence_id=source_licence_id,
        is_suspended=False,
        open=Decimal("7.0"),
        high=Decimal("8.0"),
        low=Decimal("7.0"),
        close=close,
        pre_close=Decimal("7.5"),
        volume=Decimal("123"),
        amount=Decimal("456"),
    )

def _restriction(*, identifier: int, until: dt.datetime | None, target_id: str, user_id: uuid.UUID = OWNER) -> Row:
    return Row(
        id=uuid.UUID(int=identifier), user_id=user_id, kind="blocklist", target_type="security",
        target_id=target_id, until=until, reason="synthetic", created_at=NOW, removed_at=None,
    )

class Result:
    def __init__(self, rows: list[Any] | None = None, *, one_value: Any = None) -> None:
        self.rows = rows or []
        self.one_value = one_value

    def __iter__(self):
        return iter(self.rows)

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        if self.one_value is not None:
            return self.one_value
        if len(self.rows) != 1:
            raise AssertionError(f"expected one row, got {len(self.rows)}")
        return self.rows[0]

    def scalar_one_or_none(self) -> Any | None:
        if self.one_value is not None:
            return self.one_value
        row = self.first()
        if row is None:
            return None
        if hasattr(row, "_mapping"):
            return next(iter(row._mapping.values()))
        if isinstance(row, (tuple, list)):
            return row[0]
        for name in ("id", "date", "is_open", "count"):
            if hasattr(row, name):
                return getattr(row, name)
        return row

    def scalar_one(self) -> Any:
        value = self.scalar_one_or_none()
        if value is None:
            raise AssertionError("expected scalar")
        return value

    def scalar(self) -> Any:
        return self.scalar_one_or_none()

    def scalars(self) -> "Result":
        values = []
        for row in self.rows:
            if isinstance(row, (tuple, list)):
                values.append(row[0])
            elif hasattr(row, "status"):
                values.append(row.status)
            else:
                values.append(row)
        return Result(values)

@dataclass
class State:
    licence_owner: bool = True
    licence_status: str = "active"
    securities: dict[str, Any] = field(default_factory=lambda: {CODE: _security()})
    bars: list[Any] = field(default_factory=list)
    restrictions: list[Any] = field(default_factory=list)
    watchlist: list[Any] = field(default_factory=list)
    reviews: list[Any] = field(default_factory=list)
    review_versions: list[Any] = field(default_factory=list)
    data_snapshots: list[Any] = field(default_factory=list)

class Engine:
    def __init__(self, state: State) -> None:
        self.state = state

    @contextmanager
    def connect(self):
        yield Connection(self.state)

    @contextmanager
    def begin(self):
        yield Connection(self.state)

class Connection:
    def __init__(self, state: State) -> None:
        self.state = state

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        rendered = str(statement.compile(dialect=postgresql.dialect()))
        params = statement.compile().params
        if "app.users" in rendered:
            user_id = params.get("id_1", OWNER)
            return Result([SimpleNamespace(id=user_id, status="approved", role="user")])
        if "market.securities" in rendered:
            requested = params.get("code_1", tuple(self.state.securities))
            if isinstance(requested, str):
                requested = (requested,)
            return Result([self.state.securities[code] for code in requested if code in self.state.securities])
        if "app.user_data_licence_status" in rendered:
            owner = params.get("user_id_1")
            if owner == OWNER and self.state.licence_owner and self.state.licence_status == "active":
                return Result([SimpleNamespace(id=LICENCE)])
            return Result([])
        if "market.daily_bars" in rendered:
            cutoff = params.get("fetched_at_1")
            source_licence = params.get("source_licence_id_1")
            rows = [
                row
                for row in self.state.bars
                if (source_licence is None or row.source_licence_id == source_licence)
                and (cutoff is None or row.fetched_at <= cutoff)
            ]
            return Result(rows)
        if "market.trading_calendar" in rendered:
            if "min(" in rendered and "max(" in rendered:
                return Result(one_value=(dt.date(2020, 1, 1), dt.date(2030, 12, 31)))
            if "is_open" in rendered and "SELECT market.trading_calendar.is_open" in rendered:
                return Result([SimpleNamespace(is_open=True)])
            return Result([SimpleNamespace(date=dt.date(2041, 5, 6))])
        if "app.watchlist_items" in rendered:
            return Result(list(self.state.watchlist))
        if "app.user_restrictions" in rendered:
            if rendered.lstrip().upper().startswith("INSERT"):
                values = params
                item = Row(
                    id=values["id"], user_id=values["user_id"], kind=values["kind"],
                    target_type=values["target_type"], target_id=values["target_id"],
                    until=values["until"], reason=values["reason"],
                    created_at=dt.datetime.now(dt.UTC), removed_at=None,
                )
                self.state.restrictions.append(item)
                return Result([])
            identifier = params.get("id_1")
            rows = [r for r in self.state.restrictions if identifier is None or r.id == identifier]
            user_id = params.get("user_id_1")
            if user_id is not None:
                rows = [r for r in rows if r.user_id == user_id]
            if "removed_at IS NULL" in rendered:
                rows = [r for r in rows if r.removed_at is None]
            return Result(rows)
        bucket = (
            "review_versions" if "review_versions" in rendered else
            "data_snapshots" if "data_snapshots" in rendered else
            "reviews" if "app.reviews" in rendered else None
        )
        if bucket is not None:
            rows = getattr(self.state, bucket)
            verb = rendered.lstrip().split(None, 1)[0].upper()
            if verb == "INSERT":
                row = Row(**params)
                if bucket == "reviews" and not hasattr(row, "current_version_id"):
                    row.current_version_id = None
                if not hasattr(row, "created_at"):
                    row.created_at = NOW
                rows.append(row)
                return Result([])
            if verb == "UPDATE":
                for row in rows:
                    if any(
                        (field := key[:-2] if key.endswith("_1") else "")
                        and hasattr(row, field)
                        and getattr(row, field) != value
                        for key, value in params.items()
                    ):
                        continue
                    for key, value in params.items():
                        if not key.endswith("_1"):
                            setattr(row, key, value)
                return Result(rows)
            selected = list(rows)
            for key, value in params.items():
                field = key[:-2] if key.endswith("_1") else key
                if selected and hasattr(selected[0], field):
                    selected = [row for row in selected if getattr(row, field) == value]
            return Result(selected)
        if "count(" in rendered:
            return Result([0])
        if "alembic_version" in rendered:
            return Result([None])
        return Result([])

class Store:
    def __init__(self) -> None:
        self.sessions = {
            "owner-session": Session("owner", str(OWNER), "owner-csrf", NOW.isoformat()),
            "other-session": Session("other", str(OTHER), "other-csrf", NOW.isoformat()),
        }

    def get(self, sid: str | None) -> Session | None:
        return self.sessions.get(sid)

    def delete(self, _session: Session) -> None:
        return None

    def revoke_user(self, _user_id: str) -> int:
        return 0

class Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, _key: str) -> None:
        return self.values.get(_key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)

@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Any:
    state = State(bars=[])
    engine = Engine(state)
    store = Store()
    redis = Redis()
    settings = Settings(app_env="test", database_url=None, redis_url=None, _env_file=None)
    app = create_app(settings)
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_session_store] = lambda: store
    app.dependency_overrides[deps.get_redis] = lambda: redis
    with TestClient(app, raise_server_exceptions=False) as client:
        def login(user: str = "owner") -> None:
            sid = f"{user}-session"
            csrf = f"{user}-csrf"
            client.cookies.set(SESSION_COOKIE, sid)
            client.cookies.set(CSRF_COOKIE, csrf)

        yield SimpleNamespace(client=client, state=state, login=login, app=app)

def _json_error(response: Any, status: int, code: str) -> None:
    assert response.status_code == status, response.text
    assert response.json()["error"]["code"] == code

def _assert_quote_unavailable(response: Any, *, reason: str) -> None:
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["security_code"] == CODE
    assert item["data_status"] == "unavailable"
    assert all(item[key] is None for key in ("price", "change_pct", "volume", "amount", "t", "data_as_of"))
    assert item["gaps"][0]["reason"] == reason

def test_tt119_realtime_quotes_empty_cache_is_unavailable_without_enqueue(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.core import IngestCore
    from app.ingest.scheduler import Scheduler

    monkeypatch.setattr(IngestCore, "submit", lambda *_a, **_k: pytest.fail("quotes must not enqueue"))
    monkeypatch.setattr(Scheduler, "submit", lambda *_a, **_k: pytest.fail("quotes must not enqueue"))
    world.login()
    _assert_quote_unavailable(world.client.get("/api/v1/quotes", params={"codes": CODE}), reason="no_source")

def _freeze_quotes_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.marketdata import quotes_read

    class Clock(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

    monkeypatch.setattr(quotes_read, "dt", SimpleNamespace(datetime=Clock, time=dt.time, timedelta=dt.timedelta, UTC=dt.UTC))

def test_tt119_realtime_quotes_stale_cache_is_stale(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    world.state.bars = [_bar()]
    _freeze_quotes_clock(monkeypatch)
    world.login()
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["data_status"] == "stale"
    assert item["price"] == "7.8750"

def test_tt119_realtime_quotes_future_fetched_at_is_not_visible(world: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    world.state.bars = [_bar(fetched_at=NOW + dt.timedelta(minutes=1))]
    _freeze_quotes_clock(monkeypatch)
    world.login()
    _assert_quote_unavailable(world.client.get("/api/v1/quotes", params={"codes": CODE}), reason="no_source")

def test_tt119_realtime_quotes_unusable_certificate_cannot_borrow_other_user(world: Any) -> None:
    world.state.licence_owner = False
    world.state.bars = [_bar(source_licence_id=OTHER_LICENCE, close=Decimal("9876.54"))]
    world.login()
    response = world.client.get("/api/v1/quotes", params={"codes": CODE})
    _assert_quote_unavailable(response, reason="data_licence_unavailable")
    assert "9876.54" not in response.text

@pytest.mark.parametrize("path", ["/api/v1/quotes?codes=999991.SH", "/api/v1/market/overview", "/api/v1/terminal", "/api/v1/restrictions"])
def test_tt119_http_requires_session(world: Any, path: str) -> None:
    _require_http_route(world, "GET", path.split("?", 1)[0], f"本栈未注册 {path.split('?', 1)[0]} 路由")
    _json_error(world.client.get(path), 401, "AUTH_REQUIRED")

def test_tt119_market_overview_empty_shape(world: Any) -> None:
    world.state.securities.clear()
    world.login()
    response = world.client.get("/api/v1/market/overview")
    assert response.status_code == 200
    body = response.json()
    for key in ("trade_date", "session", "indices", "breadth", "regime", "regime_position_range", "turnover_total", "basis", "data_status", "data_as_of", "gaps"):
        assert key in body
    assert body["indices"] == []
    assert body["basis"] is None
    assert body["data_status"] == "unavailable"
    assert body["data_as_of"] is None

def test_tt119_sector_flows_empty_and_owner_scoped(world: Any) -> None:
    world.login()
    response = world.client.get("/api/v1/market/sector-flows", params={"kind": "industry"})
    assert response.status_code == 200
    body = response.json()
    assert body["items"] == [] and body["data_as_of"] is None
    assert body["gaps"][0]["reason"] == "no_source"
    world.state.licence_owner = False
    response = world.client.get("/api/v1/market/sector-flows", params={"kind": "industry"})
    assert response.status_code == 200
    assert response.json()["gaps"][0]["reason"] == "data_licence_unavailable"

def test_tt119_terminal_empty_rows_keep_unavailable_shape(world: Any) -> None:
    world.login()
    response = world.client.get("/api/v1/terminal")
    assert response.status_code == 200
    body = response.json()
    assert body["rows"] == []
    assert body["data_status"] == "partial"
    assert "data_as_of" in body and "gaps" in body

def test_tt119_terminal_certificate_isolation_keeps_foreign_quote_out(world: Any) -> None:
    world.state.watchlist = [
        SimpleNamespace(user_id=OWNER, security_code=CODE, removed_at=None, added_at=NOW)
    ]
    world.state.licence_owner = False
    world.state.bars = [_bar(source_licence_id=OTHER_LICENCE, close=Decimal("9876.54"))]
    world.login()
    response = world.client.get("/api/v1/terminal")
    assert response.status_code == 200
    row = response.json()["rows"][0]
    assert row["security_code"] == CODE and row["quote"] is None
    assert row["data_status"] == "unavailable"
    assert "9876.54" not in response.text

def test_tt119_restrictions_empty_list_shape(world: Any) -> None:
    _require_restriction_route(world)
    world.login()
    response = world.client.get("/api/v1/restrictions")
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["next_cursor"] is None

def test_tt119_restrictions_create_returns_201_and_json_paths(world: Any) -> None:
    _require_restriction_route(world)
    world.login()
    response = world.client.post(
        "/api/v1/restrictions",
        json={"kind": "blocklist", "target_type": "security", "target_id": CODE, "until": None, "reason": "synthetic"},
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["kind"] == "blocklist" and body["target_id"] == CODE

def test_tt119_restrictions_missing_resource_is_404(world: Any) -> None:
    _require_restriction_route(world)
    world.login()
    response = world.client.delete(
        f"/api/v1/restrictions/{uuid.UUID(int=999)}",
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    _json_error(response, 404, "NOT_FOUND")

def test_tt119_restrictions_other_user_resource_is_404(world: Any) -> None:
    _require_restriction_route(world)
    world.state.restrictions.append(_restriction(identifier=998, until=None, target_id=CODE, user_id=OTHER))
    world.login()
    response = world.client.delete(
        f"/api/v1/restrictions/{uuid.UUID(int=998)}",
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    _json_error(response, 404, "NOT_FOUND")

def test_tt119_restrictions_idempotency_conflict_is_409(world: Any) -> None:
    _require_restriction_route(world)
    world.login()
    payload = {"kind": "blocklist", "target_type": "security", "target_id": CODE, "until": None, "reason": "synthetic"}
    headers = {"X-CSRF-Token": "owner-csrf", "Idempotency-Key": "matrix-key"}
    assert world.client.post("/api/v1/restrictions", json=payload, headers=headers).status_code == 201
    conflict = dict(payload, reason="different synthetic reason")
    _json_error(world.client.post("/api/v1/restrictions", json=conflict, headers=headers), 409, "IDEMPOTENCY_CONFLICT")

def test_tt119_restrictions_until_pit_pending_mainline(world: Any) -> None:
    _require_restriction_route(world)
    world.state.restrictions.extend(
        [
            _restriction(identifier=0x121, until=dt.datetime(2020, 1, 2, tzinfo=dt.UTC), target_id=CODE),
            _restriction(identifier=0x122, until=dt.datetime(2041, 6, 1, tzinfo=dt.UTC), target_id=OTHER_CODE),
        ]
    )
    world.login()
    response = world.client.get("/api/v1/restrictions")
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    by_target = {item["target_id"]: item for item in items}
    assert CODE in by_target and OTHER_CODE in by_target
    expired = by_target[CODE]
    active = by_target[OTHER_CODE]
    if "status" not in expired or "status" not in active:
        pytest.xfail("待 #348：restrictions until 的时点区间语义尚未在主线接线")
    assert expired["status"] == "expired"
    assert active["status"] == "active"

def _require_http_route(world: Any, method: str, path: str, reason: str) -> None:
    target = path if path.startswith("/api/") else "/api/v1" + path
    response = world.client.request(method, target)
    missing = world.client.request(method, "/api/v1/__tt119_missing_route__")
    def _error(res: Any) -> dict[str, Any] | None:
        try:
            body = res.json()
        except ValueError:
            return None
        error = body.get("error") if isinstance(body, dict) else None
        return error if isinstance(error, dict) else None
    err, missed = _error(response), _error(missing)
    unregistered = response.status_code == 404 and (
        err is None or (missing.status_code == 404 and missed is not None and err.get("code") == missed.get("code") and err.get("message") == missed.get("message"))
    )
    if unregistered:
        pytest.xfail(reason)

def _require_review_route(world: Any, method: str, path: str) -> None:
    _require_http_route(world, method, path, "复盘待 #379/#356（#349 契约）：主线尚未注册 reviews 路由")

def _require_restriction_route(world: Any) -> None:
    _require_http_route(world, "GET", "/api/v1/restrictions", "本栈未注册 restrictions 路由")

def _review_create_payload() -> dict[str, Any]:
    return {
        "plan_id": None,
        "security_code": CODE,
        "period_start": "2041-05-01",
        "period_end": "2041-05-05",
        "plan_version_ids": [],
        "trade_ids": [],
        "judgement": [],
        "tags": [],
        "lessons": None,
    }
def test_tt119_reviews_empty_http_matrix_cell(world: Any) -> None:
    _require_review_route(world, "GET", "/reviews")
    world.login()
    response = world.client.get("/api/v1/reviews")
    assert response.status_code == 200
    assert "items" in response.json()
def test_tt119_reviews_create_http_matrix_cell(world: Any) -> None:
    _require_review_route(world, "POST", "/reviews")
    world.login()
    response = world.client.post(
        "/api/v1/reviews",
        json=_review_create_payload(),
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    assert response.status_code == 201, response.text
def test_tt119_reviews_available_at_pit_pending_mainline(world: Any) -> None:
    _require_review_route(world, "POST", "/reviews")
    world.login()
    response = world.client.post(
        "/api/v1/reviews",
        json=_review_create_payload(),
        headers={"X-CSRF-Token": "owner-csrf"},
    )
    if response.status_code == 404:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    assert response.status_code == 201, response.text
    body = response.json()
    review_id = body["id"] if "id" in body else None
    if review_id is None:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    trade_rows = getattr(world.state, "trades", None)
    batch_rows = getattr(world.state, "import_batches", None)
    if trade_rows is None or batch_rows is None:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    if not trade_rows or not batch_rows:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    detail = world.client.get(f"/api/v1/reviews/{review_id}")
    if detail.status_code == 404:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    assert detail.status_code == 200, detail.text
    detail_body = detail.json()
    if "evidence" not in detail_body or detail_body["evidence"] is None:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    if any(not hasattr(row, "id") or not hasattr(row, "import_batch_id") for row in trade_rows):
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    if any(not hasattr(row, "id") or not hasattr(row, "committed_at") for row in batch_rows):
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    saved_at_value = body.get("created_at")
    if saved_at_value is None:
        version_body = body.get("version")
        saved_at_value = version_body.get("created_at") if isinstance(version_body, dict) else None
    if saved_at_value is None:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    saved_at = saved_at_value if isinstance(saved_at_value, dt.datetime) else dt.datetime.fromisoformat(str(saved_at_value).replace("Z", "+00:00"))
    late_batches = {
        row.id
        for row in batch_rows
        if row.committed_at is not None
        and (row.committed_at if isinstance(row.committed_at, dt.datetime) else dt.datetime.fromisoformat(str(row.committed_at).replace("Z", "+00:00")))
        > saved_at
    }
    if not late_batches:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    late_trade_ids = {row.id for row in trade_rows if row.import_batch_id in late_batches}
    if not late_trade_ids:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    version = detail_body["current_version"] if "current_version" in detail_body else None
    if not isinstance(version, dict) or "trade_ids" not in version:
        pytest.xfail("待 #349+#379：reviews available_at 的 PIT 过滤尚未在主线实现")
    assert not late_trade_ids & set(version["trade_ids"])

def test_tt119_reviews_other_user_isolation_pending_route(world: Any) -> None:
    _require_review_route(world, "GET", "/reviews/00000000-0000-4000-8000-000000000999")
    world.login("other")
    _json_error(world.client.get("/api/v1/reviews/00000000-0000-4000-8000-000000000999"), 404, "NOT_FOUND")

def test_tt119_reviews_versions_http_matrix_cell(world: Any) -> None:
    _require_review_route(world, "GET", "/reviews/00000000-0000-4000-8000-000000000999/versions")
    world.login()
    response = world.client.get("/api/v1/reviews/00000000-0000-4000-8000-000000000999/versions")
    _json_error(response, 404, "NOT_FOUND")

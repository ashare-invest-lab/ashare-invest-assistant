from __future__ import annotations

import datetime as dt
import uuid
from contextlib import nullcontext
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.api.v1 import reviews as api
from app.api.v1.reviews import ReviewCreate, ReviewVersionCreate
from app.auth import deps
from app.common.errors import AppError, ErrorCode, install_exception_handlers
from app.common.pagination import PageParams, build_page, decode_cursor, encode_cursor
from app.config import get_settings
from app.reviews import service
from app.reviews.metrics import _stat, empty_metrics
from fastapi import FastAPI
from fastapi.testclient import TestClient

# fmt: off
U = uuid.UUID(int=201)
RID = uuid.UUID(int=203)
PID = uuid.UUID(int=204)
VID = uuid.UUID(int=205)
TID = uuid.UUID(int=206)
CODE = "600000.SH"
def body(**extra: Any) -> dict[str, Any]:
    value = {
        "security_code": CODE,
        "period_start": "2026-01-01",
        "period_end": "2026-01-05",
    }
    value.update(extra)
    return value
def test_metrics_thresholds_and_missing_window() -> None:
    assert _stat("w", value=Decimal(1), n=4)["value"] is None
    assert _stat("w", value=Decimal("1.0000"), n=5)["value"] == "1.0000"
    assert _stat("w", value=Decimal(1), n=29)["small_sample"]
    assert not _stat("w", value=Decimal(1), n=30)["small_sample"]
    assert empty_metrics(dt.date(2026, 1, 1), dt.date(2026, 1, 5))["holding_return"]["n"] == 0
def test_validation_and_security_code() -> None:
    assert service._code("600000.sh") == CODE
    with pytest.raises(AppError) as invalid:
        service._code("bad")
    assert invalid.value.code == ErrorCode.VALIDATION_ERROR
    with pytest.raises(AppError):
        service.create(
            cast(Any, SimpleNamespace()),
            U,
            ReviewCreate.model_validate(body(security_code=None)),
        )
    with pytest.raises(AppError):
        service.create(
            cast(Any, SimpleNamespace()),
            U,
            ReviewCreate.model_validate(body(period_end="2025-12-31")),
        )
    with pytest.raises(ValueError):
        ReviewCreate.model_validate({**body(), "outcome_metrics": {}})
class Engine:
    def __init__(self, conn: Any) -> None:
        self.conn = conn
    def connect(self) -> Any:
        return nullcontext(self.conn)
    def begin(self) -> Any:
        return nullcontext(self.conn)
class ValidationConnection:
    def __init__(self, plan: Any = None) -> None:
        self.plan = plan
        self.versions: list[Any] = []
        self.trade: Any = None
    def execute(self, statement: Any) -> Any:
        text = str(statement)
        if "app.action_plans" in text and "app.plan_versions" not in text:
            return SimpleNamespace(first=lambda: self.plan)
        if "app.plan_versions" in text:
            return SimpleNamespace(all=lambda: self.versions)
        if "app.trades" in text:
            return SimpleNamespace(all=lambda: [] if self.trade is None else [self.trade])
        raise AssertionError(text)
class Redis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.data:
            return False
        self.data[key] = value
        return True
    def get(self, key: str) -> str | None:
        return self.data.get(key)
    def delete(self, key: str) -> None:
        self.data.pop(key, None)
@pytest.fixture
def http() -> Any:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(api.router, prefix="/api/v1")
    conn, rds = ValidationConnection(), Redis()
    app.dependency_overrides.update(
        {
            deps.current_auth: lambda: SimpleNamespace(user_id=U),
            deps.get_engine: lambda: Engine(conn),
            deps.get_redis: lambda: rds,
            get_settings: lambda: SimpleNamespace(
                app_env="test",
                app_master_key=None,
                page_limit_default=2,
                page_limit_max=200,
                cursor_ttl_s=3600,
            ),
        }
    )
    with TestClient(app) as client:
        yield client, conn, rds
def test_listing_cursor_and_owner(http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    client, _, _ = http
    rows = [
        SimpleNamespace(
            id=uuid.UUID(int=210 + i),
            created_at=dt.datetime(2026, 1, 5 - i, tzinfo=dt.UTC),
        )
        for i in range(3)
    ]
    def page(_c: Any, owner: uuid.UUID, cfg: Any, pp: PageParams, *_: Any) -> Any:
        assert owner == U
        rows2 = rows
        if pp.cursor:
            stamp, ident = decode_cursor(pp.cursor, scope=f"reviews:{U}:None:None", settings=cfg)
            rows2 = [r for r in rows if (r.created_at.isoformat(), str(r.id)) < (stamp, ident)]
        return build_page(
            rows2,
            limit=pp.limit,
            key=lambda r: [r.created_at.isoformat(), str(r.id)],
            scope=f"reviews:{U}:None:None",
            settings=cfg,
        )
    monkeypatch.setattr(api, "_page_reviews", page)
    monkeypatch.setattr(api.service, "summary", lambda _c, r: {"id": str(r.id)})
    first = client.get("/api/v1/reviews?limit=1")
    second = client.get("/api/v1/reviews", params={"limit": 1, "cursor": first.json()["next_cursor"]})
    assert first.status_code == second.status_code == 200
    assert first.json()["items"][0] != second.json()["items"][0]
@pytest.mark.parametrize(
    "path",
    [f"/api/v1/reviews/{uuid.UUID(int=220)}", f"/api/v1/reviews/{uuid.UUID(int=221)}"],
)
def test_detail_not_found(http: Any, monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr(
        api.service,
        "full",
        lambda *_: (_ for _ in ()).throw(AppError(ErrorCode.NOT_FOUND)),
    )
    response = http[0].get(path)
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"
@pytest.mark.parametrize(
    "payload",
    [
        body(security_code=None),
        body(period_end="2025-12-31"),
        body(plan_version_ids=[str(VID)]),
        body(trade_ids=[str(TID)]),
        body(plan_id=str(PID), security_code="000001.SZ"),
        body(plan_id=str(PID), plan_version_ids=[str(VID)]),
        body(trade_ids=[str(TID)], security_code=CODE),
    ],
)
def test_post_rejects_all_invalid_links(http: Any, payload: dict[str, Any]) -> None:
    if payload.get("plan_id"):
        http[1].plan = SimpleNamespace(id=PID, security_code=CODE, user_id=U)
    if payload.get("plan_id") and payload.get("plan_version_ids"):
        http[1].versions = [SimpleNamespace(id=VID, plan_id=uuid.UUID(int=999), security_code=CODE)]
    if payload.get("trade_ids") and payload.get("security_code") == CODE:
        http[1].trade = SimpleNamespace(id=TID, security_code="000001.SZ", plan_version_id=None)
    response = http[0].post("/api/v1/reviews", json=payload)
    assert response.status_code == 400 and response.json()["error"]["code"] == "VALIDATION_ERROR"
def test_post_idempotency_complete_result(http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    metrics = empty_metrics(dt.date(2026, 1, 1), dt.date(2026, 1, 5))
    metrics["holding_return"] = _stat("2026-01-01/2026-01-05", value=Decimal("0.1234"), n=5)
    result = {
        "id": str(RID),
        "current_version": {"outcome_metrics": metrics},
        "gaps": [{"key": "outcome_metrics"}],
    }
    calls = 0
    def create(*_: Any) -> uuid.UUID:
        nonlocal calls
        calls += 1
        return RID
    monkeypatch.setattr(api.service, "create", create)
    monkeypatch.setattr(api.service, "full", lambda *_: result)
    c = http[0]
    a = c.post("/api/v1/reviews", json=body(), headers={"Idempotency-Key": "k"})
    b = c.post("/api/v1/reviews", json=body(), headers={"Idempotency-Key": "k"})
    d = c.post("/api/v1/reviews", json=body(lessons="other"), headers={"Idempotency-Key": "k"})
    assert a.status_code == b.status_code == 201 and a.json() == b.json() == result and calls == 1
    payload = a.json()
    assert isinstance(payload["current_version"]["outcome_metrics"]["holding_return"]["value"], str)
    assert payload["current_version"]["outcome_metrics"]["benchmark_return"]["value"] is None
    assert payload["gaps"]
    assert d.status_code == 409
def test_versions_conflict_success_history_and_methods(http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    history = {1: {"version_no": 1, "lessons": "old"}}
    def revise(_c: Any, _u: Any, _i: Any, value: Any) -> uuid.UUID:
        if value.base_version_no != 1:
            raise AppError(ErrorCode.VERSION_CONFLICT)
        history[2] = {"version_no": 2, "lessons": value.lessons, "plan_version_ids": value.plan_version_ids, "trade_ids": value.trade_ids}
        return RID
    monkeypatch.setattr(api.service, "revise", revise)
    monkeypatch.setattr(api.service, "full", lambda *_: {"id": str(RID), "current_version_no": 2})
    c = http[0]
    assert c.post(f"/api/v1/reviews/{RID}/versions", json={**body(), "base_version_no": 2}).status_code == 409
    assert (
        c.post(
            f"/api/v1/reviews/{RID}/versions",
            json={**body(lessons="new"), "base_version_no": 1, "plan_version_ids": [], "trade_ids": []},
        ).status_code
        == 201
    )
    assert history[2]["plan_version_ids"] == history[2]["trade_ids"] == []
    class Row:
        version_no = 1
    http[1].execute = lambda _s: SimpleNamespace(first=lambda: Row())
    monkeypatch.setattr(api.service, "_owned", lambda *_: SimpleNamespace(id=RID))
    monkeypatch.setattr(api.service, "version_body", lambda *_: history[1])
    first = c.get(f"/api/v1/reviews/{RID}/versions/1")
    second = c.get(f"/api/v1/reviews/{RID}/versions/1")
    assert first.json() == second.json() == history[1]
    assert c.request("PATCH", f"/api/v1/reviews/{RID}", json={}).status_code == 405
    assert c.request("DELETE", f"/api/v1/reviews/{RID}", json={}).status_code == 405

def test_missing_current_version_projection() -> None:
    row = SimpleNamespace(id=RID, user_id=U, plan_id=None, security_code=CODE, period_start=dt.date(2026, 1, 1), period_end=dt.date(2026, 1, 5), current_version_id=None, created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    class Conn:
        def execute(self, statement: Any) -> Any:
            return SimpleNamespace(first=lambda: row, scalar=lambda: None, all=list)
    detail = service.full(Conn(), U, RID)
    summary = service.summary(Conn(), row)
    assert detail["current_version"] is None and detail["data_status"] == "unavailable"
    assert "current_version" not in summary and summary["data_status"] == "unavailable"
    assert detail["gaps"][0]["reason"] == "no_source"
    for result in (detail, summary):
        assert result["gaps"][0]["reason"] == "no_source"


def test_service_link_validation_owner_and_empty_links() -> None:
    plan = SimpleNamespace(id=PID, user_id=U, security_code=CODE)
    pv = SimpleNamespace(id=VID, plan_id=PID, security_code=CODE)
    trade = SimpleNamespace(id=TID, security_code=CODE, plan_version_id=VID)

    class Conn:
        def __init__(self, *, plan_row: Any = plan, pv_rows: list[Any] | None = None, trade_rows: list[Any] | None = None, valid: list[Any] | None = None) -> None:
            self.plan_row, self.pv_rows, self.trade_rows, self.valid = plan_row, pv_rows or [], trade_rows or [], valid or []

        def execute(self, statement: Any) -> Any:
            text = str(statement)
            if "app.action_plans" in text and "app.plan_versions" not in text:
                return SimpleNamespace(first=lambda: self.plan_row)
            if "app.trades" in text:
                return SimpleNamespace(all=lambda: self.trade_rows)
            if "app.plan_versions" in text:
                return SimpleNamespace(all=lambda: self.pv_rows or self.valid)
            raise AssertionError(text)

    assert service._validate_links(Conn(pv_rows=[pv]), U, plan_id=PID, security_code=CODE, plan_version_ids=[VID], trade_ids=[]) == (CODE, plan)
    assert service._validate_links(Conn(pv_rows=[pv], trade_rows=[trade]), U, plan_id=PID, security_code=CODE, plan_version_ids=[], trade_ids=[TID]) == (CODE, plan)
    assert service._validate_links(Conn(pv_rows=[pv]), U, plan_id=None, security_code=CODE, plan_version_ids=[VID], trade_ids=[]) == (CODE, None)
    for kwargs in (
        {"plan_id": PID, "security_code": "000001.SZ", "plan_version_ids": [], "trade_ids": []},
        {"plan_id": PID, "security_code": CODE, "plan_version_ids": [VID], "trade_ids": []},
        {"plan_id": PID, "security_code": CODE, "plan_version_ids": [], "trade_ids": [TID]},
    ):
        with pytest.raises(AppError) as exc:
            service._validate_links(Conn(pv_rows=[SimpleNamespace(id=VID, plan_id=uuid.UUID(int=999), security_code=CODE)], trade_rows=[SimpleNamespace(id=TID, security_code="000001.SZ", plan_version_id=None)]), U, **kwargs)
        assert exc.value.code == ErrorCode.VALIDATION_ERROR


def test_service_create_snapshot_and_revise_guards(monkeypatch: pytest.MonkeyPatch) -> None:
    body_value = ReviewCreate.model_validate(body(lessons="lesson", tags=["tag"], judgement=[{"condition_text": "ok", "fulfilled": True}]))
    inserted: list[str] = []

    class Conn:
        def execute(self, statement: Any) -> Any:
            text = str(statement)
            inserted.append(text)
            if "review_versions" in text and "SELECT" in text.upper():
                return SimpleNamespace(one=lambda: SimpleNamespace(id=VID))
            return SimpleNamespace(first=lambda: None, one=lambda: SimpleNamespace(id=VID), scalar=lambda: None, all=list)

    monkeypatch.setattr(service, "_validate_links", lambda *_args, **_kwargs: (CODE, None))
    monkeypatch.setattr(service.uuid, "uuid4", lambda: RID)
    assert service.create(Conn(), U, body_value) == RID
    assert any("data_snapshots" in sql for sql in inserted)
    assert any("review_versions" in sql for sql in inserted)
    assert service._snapshot_items(dt.date(2026, 1, 1), dt.date(2026, 1, 5), None, [], [], True)["data_status"] == "unavailable"

    missing = SimpleNamespace(current_version_id=None)
    monkeypatch.setattr(service, "_owned", lambda *_args, **_kwargs: missing)
    with pytest.raises(AppError) as exc:
        service.revise(Conn(), U, RID, ReviewVersionCreate.model_validate({**body(), "base_version_no": 1}))
    assert exc.value.code == ErrorCode.NOT_FOUND

    stale = SimpleNamespace(current_version_id=VID)
    monkeypatch.setattr(service, "_owned", lambda *_args, **_kwargs: stale)
    class StaleConn(Conn):
        def execute(self, statement: Any) -> Any:
            if "review_versions" in str(statement):
                return SimpleNamespace(first=lambda: None)
            return super().execute(statement)
    with pytest.raises(AppError) as exc:
        service.revise(StaleConn(), U, RID, ReviewVersionCreate.model_validate({**body(), "base_version_no": 1}))
    assert exc.value.code == ErrorCode.NOT_FOUND


def test_snapshot_projection_and_timeline_sources() -> None:
    snap_items = {"data_status": "partial", "data_as_of": None, "gaps": [], "outcome_metrics": {"holding_return": {"value": "1", "n": 5}}, "attribution": {"judgement": []}}
    pv_row = SimpleNamespace(id=VID, created_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC), version_no=3)
    trade_row = SimpleNamespace(id=TID, created_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC), traded_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC))
    version = SimpleNamespace(id=RID, version_no=2, plan_version_ids=[VID], trade_ids=[TID], snapshot_id=VID, lessons=None, tags=None, attribution=None, outcome_metrics=None, created_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC))
    class Conn:
        def execute(self, statement: Any) -> Any:
            text = str(statement)
            if "data_snapshots" in text:
                return SimpleNamespace(first=lambda: SimpleNamespace(_mapping={"items": snap_items}))
            if "plan_versions" in text:
                return SimpleNamespace(all=lambda: [pv_row])
            if "trades" in text:
                return SimpleNamespace(all=lambda: [trade_row])
            return SimpleNamespace(all=lambda: [version], first=lambda: version, scalar=lambda: None)
    projected = service.version_body(Conn(), U, version)
    assert projected["data_status"] == "partial" and projected["outcome_metrics"]["holding_return"]["value"] is None and projected["tags"] == []
    timeline = service._timeline(Conn(), U, RID, version)
    assert [item["kind"] for item in timeline] == ["plan_version", "trade", "review_version"]


def test_route_invalid_cursors_and_version_not_found(http: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings()
    scope = f"reviews:{U}:{RID}:versions"
    bad = encode_cursor(["wrong"], scope=scope, settings=cfg)
    monkeypatch.setattr(api.service, "_owned", lambda *_: SimpleNamespace(id=RID))
    response = http[0].get(f"/api/v1/reviews/{RID}/versions", params={"cursor": bad})
    assert response.status_code == 400 and response.json()["error"]["code"] == "INVALID_CURSOR"
    monkeypatch.setattr(api.service, "version_body", lambda *_: {"version_no": 1})
    http[1].execute = lambda _s: SimpleNamespace(first=lambda: None)
    response = http[0].get(f"/api/v1/reviews/{RID}/versions/99")
    assert response.status_code == 404 and response.json()["error"]["code"] == "NOT_FOUND"


def test_paging_helpers_and_revise_replacement(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = get_settings()
    current = SimpleNamespace(version_no=1, id=VID)
    rows = [SimpleNamespace(id=RID, created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))]
    class Conn:
        def execute(self, statement: Any) -> Any:
            text = str(statement)
            if "review_versions" in text:
                return SimpleNamespace(all=lambda: [SimpleNamespace(version_no=1)], first=lambda: current)
            return SimpleNamespace(all=lambda: rows, first=lambda: current, one=lambda: SimpleNamespace(id=VID))
    page = api._page_reviews(Conn(), U, cfg, PageParams(limit=1, cursor=None), CODE, None)
    assert len(page.items) == 1
    cursor = encode_cursor([rows[0].created_at.isoformat(), str(RID)], scope=f"reviews:{U}:{CODE}:None", settings=cfg)
    assert api._page_reviews(Conn(), U, cfg, PageParams(limit=1, cursor=cursor), CODE, None).items == rows
    bad_cursor = encode_cursor(["not-a-date", str(RID)], scope=f"reviews:{U}:{CODE}:None", settings=cfg)
    with pytest.raises(AppError) as exc:
        api._page_reviews(Conn(), U, cfg, PageParams(limit=1, cursor=bad_cursor), CODE, None)
    assert exc.value.code == ErrorCode.INVALID_CURSOR

    monkeypatch.setattr(api.service, "_owned", lambda *_: SimpleNamespace(id=RID))
    monkeypatch.setattr(api.service, "version_body", lambda *_: {"version_no": 1})
    assert api._version_page(Conn(), U, RID, cfg, PageParams(limit=1, cursor=encode_cursor([1], scope=f"reviews:{U}:{RID}:versions", settings=cfg))).items == [{"version_no": 1}]

    review = SimpleNamespace(current_version_id=VID)
    monkeypatch.setattr(service, "_owned", lambda *_args, **_kwargs: review)
    monkeypatch.setattr(service, "_validate_links", lambda *_args, **_kwargs: (CODE, None))
    monkeypatch.setattr(service, "_new_version", lambda *_args, **_kwargs: SimpleNamespace(id=uuid.UUID(int=207)))
    assert service.revise(Conn(), U, RID, ReviewVersionCreate.model_validate({**body(lessons="replacement"), "base_version_no": 1})) == RID

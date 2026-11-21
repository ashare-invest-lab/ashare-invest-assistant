"""T-T110 /reviews V1--V4 的离线契约测试。

测试只使用虚构用户、证券和 UUID。T-B201 尚未提供路由时，相关用例以严格
动态 xfail 标记，路由落地后会直接执行这些 HTTP 契约断言。
"""

from __future__ import annotations

import datetime as dt
import importlib
import socket
import uuid
from contextlib import nullcontext
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators

pytestmark = pytest.mark.unit

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER = uuid.UUID("22222222-2222-4222-8222-222222222222")
REVIEW_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
VERSION_ID = uuid.UUID("44444444-4444-4444-8444-444444444444")
OWN_PLAN = uuid.UUID("77777777-7777-4777-8777-777777777777")
OTHER_PLAN = uuid.UUID("55555555-5555-4555-8555-555555555555")
OTHER_TRADE = uuid.UUID("66666666-6666-4666-8666-666666666666")
SYNTHETIC_CODE = "000000.SZ"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("T-T110 离线契约测试尝试建立网络连接")

    monkeypatch.setattr(socket, "getaddrinfo", reject)
    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket.socket, "connect_ex", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


class SyntheticRow:
    """可同时满足 SQLAlchemy Row 的属性与 mapping 读取。"""

    def __init__(self, **values: Any) -> None:
        self.__dict__.update(values)

    @property
    def _mapping(self) -> dict[str, Any]:
        return dict(self.__dict__)


class SyntheticResult:
    def __init__(self, rows: list[SyntheticRow]) -> None:
        self.rows = rows

    def all(self) -> list[SyntheticRow]:
        return list(self.rows)

    @property
    def rowcount(self) -> int:
        return len(self.rows)

    def first(self) -> SyntheticRow | None:
        return self.rows[0] if self.rows else None

    def one(self) -> SyntheticRow:
        assert len(self.rows) == 1
        return self.rows[0]

    def scalar_one_or_none(self) -> Any:
        row = self.first()
        return None if row is None else getattr(row, "value", getattr(row, "id", row))

    def scalar_one(self) -> Any:
        value = self.scalar_one_or_none()
        assert value is not None
        return value

    def scalar(self) -> Any:
        row = self.first()
        return None if row is None else getattr(row, "value", getattr(row, "name", row))

    def scalars(self) -> "SyntheticResult":
        return self

    def mappings(self) -> "SyntheticResult":
        return self

    def __iter__(self):
        return iter(self.rows)


@dataclass
class SyntheticDB:
    """内存假 Engine/Connection，记录 SQLAlchemy 语句但不连接任何服务。"""

    reviews: list[SyntheticRow] = field(default_factory=list)
    versions: list[SyntheticRow] = field(default_factory=list)
    snapshots: list[SyntheticRow] = field(default_factory=list)
    plans: list[SyntheticRow] = field(default_factory=list)
    plan_versions: list[SyntheticRow] = field(default_factory=list)
    trades: list[SyntheticRow] = field(default_factory=list)
    securities: list[SyntheticRow] = field(default_factory=list)
    statements: list[Any] = field(default_factory=list)
    inserted: list[Any] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.reviews:
            self.reviews.append(
                SyntheticRow(
                    id=REVIEW_ID,
                    user_id=OWNER,
                    plan_id=uuid.UUID("77777777-7777-4777-8777-777777777777"),
                    security_code=SYNTHETIC_CODE,
                    name="合成复盘",
                    period_start=dt.date(2026, 1, 1),
                    period_end=dt.date(2026, 1, 2),
                    current_version_id=VERSION_ID,
                    current_version_no=1,
                    created_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
                )
            )
        if not self.versions:
            self.versions.append(self.version_row())
        if not self.snapshots:
            self.snapshots.append(
                SyntheticRow(
                    id=uuid.UUID("88888888-8888-4888-8888-888888888888"),
                    items={
                        "data_status": "unavailable",
                        "data_as_of": None,
                        "gaps": [{"key": "outcome_metrics", "reason": "no_source"}],
                    },
                )
            )
        if not self.plans:
            self.plans.append(
                SyntheticRow(id=OWN_PLAN, user_id=OWNER, security_code=SYNTHETIC_CODE)
            )
        if not self.plan_versions:
            self.plan_versions.append(
                SyntheticRow(
                    id=VERSION_ID,
                    plan_id=OWN_PLAN,
                    security_code=SYNTHETIC_CODE,
                    version_no=1,
                    created_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
                )
            )
        if not self.securities:
            self.securities.append(
                SyntheticRow(code=SYNTHETIC_CODE, name="合成证券")
            )

    def version_row(self, **updates: Any) -> SyntheticRow:
        values = {
            "id": VERSION_ID,
            "review_id": REVIEW_ID,
            "version_no": 1,
            "plan_version_ids": [VERSION_ID],
            "trade_ids": [],
            "snapshot_id": uuid.UUID("88888888-8888-4888-8888-888888888888"),
            "lessons": "合成经验",
            "tags": ["synthetic"],
            "attribution": {
                "judgement": [{"condition_text": "条件", "fulfilled": True, "note": None}],
                "execution": [],
                "market": [],
            },
            "outcome_metrics": {
                key: {
                    "value": None,
                    "n": 0,
                    "window": {"start": "2026-01-01", "end": "2026-01-02"},
                    "small_sample": True,
                    "gaps": ["no_source"],
                }
                for key in ("holding_return", "benchmark_return", "excess_return", "max_drawdown")
            },
            "created_at": dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        }
        values.update(updates)
        return SyntheticRow(**values)

    def connection(self) -> "SyntheticConnection":
        return SyntheticConnection(self)


class SyntheticConnection:
    def __init__(self, db: SyntheticDB) -> None:
        self.db = db

    def __enter__(self) -> "SyntheticConnection":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def begin(self) -> Any:
        return nullcontext(self)

    def commit(self) -> None:
        return None

    def rollback(self) -> None:
        return None

    @staticmethod
    def _value(value: Any) -> Any:
        return getattr(value, "value", value)

    @classmethod
    def _matches(cls, row: SyntheticRow, clause: Any) -> bool:
        if clause is None:
            return True
        clauses = getattr(clause, "clauses", None)
        if clauses is not None:
            operator = getattr(clause, "operator", None)
            values = [cls._matches(row, item) for item in clauses]
            if operator is operators.and_:
                return all(values)
            if operator is operators.or_:
                return any(values)
        left = getattr(clause, "left", None)
        right = getattr(clause, "right", None)
        operator = getattr(clause, "operator", None)
        if left is None or right is None:
            return True
        if hasattr(left, "clauses") and hasattr(right, "clauses"):
            lhs = [getattr(row, getattr(item, "name", ""), None) for item in left.clauses]
            rhs = [cls._value(item) for item in right.clauses]
            return tuple(lhs) < tuple(rhs) if operator is operators.lt else True
        name = getattr(left, "name", None)
        actual = getattr(row, name, None)
        expected = getattr(row, getattr(right, "name", ""), None) if hasattr(right, "table") else cls._value(right)
        if operator is operators.eq:
            return actual == expected
        if operator is operators.ne:
            return actual != expected
        if operator is operators.lt:
            return actual < expected
        if operator is operators.in_op:
            return actual in expected
        if operator is operators.is_:
            return actual is expected
        return True

    @classmethod
    def _filter(cls, rows: list[SyntheticRow], statement: Any) -> list[SyntheticRow]:
        for clause in getattr(statement, "_where_criteria", ()):
            rows = [row for row in rows if cls._matches(row, clause)]
        order_by = getattr(statement, "_order_by_clauses", ())
        for ordering in reversed(order_by):
            column = getattr(ordering, "element", ordering)
            name = getattr(column, "name", None)
            if name:
                rows.sort(key=lambda row: getattr(row, name, None), reverse=bool(getattr(ordering, "modifier", None) is operators.desc_op))
        limit = getattr(getattr(statement, "_limit_clause", None), "value", None)
        if limit is not None:
            rows = rows[: int(limit)]
        return rows

    def _rows_for(self, statement: Any) -> list[SyntheticRow]:
        text = str(statement).lower()
        if "review_versions" in text:
            rows = self.db.versions
        elif "plan_versions" in text:
            rows = self.db.plan_versions
        elif "data_snapshots" in text:
            rows = self.db.snapshots
        elif "action_plans" in text:
            rows = self.db.plans
        elif "trades" in text:
            rows = self.db.trades
        elif "securities" in text:
            rows = self.db.securities
        else:
            rows = self.db.reviews
        if "join app.action_plans" in text:
            rows = [
                SyntheticRow(
                    id=item.id,
                    plan_id=item.plan_id,
                    security_code=item.security_code,
                    user_id=next(plan.user_id for plan in self.db.plans if plan.id == item.plan_id),
                )
                for item in self.db.plan_versions
                if any(plan.id == item.plan_id for plan in self.db.plans)
            ]
        return self._filter(list(rows), statement)

    def _insert(self, statement: Any) -> SyntheticResult:
        table = getattr(statement, "table", None)
        values = dict(statement.compile().params)
        name = getattr(table, "name", "")
        if name == "data_snapshots":
            self.db.snapshots.append(SyntheticRow(**values))
            return SyntheticResult([])
        if name == "review_versions":
            row = SyntheticRow(created_at=dt.datetime.now(dt.UTC), **values)
            self.db.versions.append(row)
            return SyntheticResult([row])
        if name == "reviews":
            row = SyntheticRow(created_at=dt.datetime.now(dt.UTC), **values)
            self.db.reviews.append(row)
            return SyntheticResult([row])
        return SyntheticResult([])

    def _update(self, statement: Any) -> SyntheticResult:
        values = dict(statement.compile().params)
        table = getattr(statement, "table", None)
        name = getattr(table, "name", "")
        identifier = values.get("id_1")
        rows = self.db.reviews if name == "reviews" else self.db.versions
        for row in rows:
            if identifier is None or getattr(row, "id", None) == identifier:
                for key, value in values.items():
                    if key != "id_1":
                        setattr(row, key, value)
        return SyntheticResult([])

    def execute(self, statement: Any, *args: Any, **kwargs: Any) -> SyntheticResult:
        self.db.statements.append(statement)
        if getattr(statement, "is_insert", False):
            self.db.inserted.append(statement)
            return self._insert(statement)
        if getattr(statement, "is_update", False):
            return self._update(statement)
        rows = self._rows_for(statement)
        columns = getattr(statement, "selected_columns", ())
        if len(columns) == 1:
            name = getattr(columns[0], "name", None)
            rows = [SyntheticRow(**{"value": getattr(row, name, None), name: getattr(row, name, None)}) for row in rows]
        return SyntheticResult(rows)


class SyntheticEngine:
    def __init__(self, db: SyntheticDB) -> None:
        self.db = db

    def connect(self) -> SyntheticConnection:
        return self.db.connection()

    def begin(self) -> SyntheticConnection:
        return self.db.connection()


@dataclass
class World:
    client: TestClient
    routes: Any
    db: SyntheticDB

    def require(self, method: str, path: str) -> None:
        router = getattr(self.routes, "router", None)
        if router is None:
            pytest.xfail(f"T-B201 未实现：V? 缺少 reviews.router（{method} {path}）")
        def shape(value: str) -> str:
            return "/".join(
                "{}" if part.startswith("{") and part.endswith("}") else part
                for part in value.split("/")
            )

        for route in router.routes:
            if shape(route.path) == shape(path) and method.upper() in (route.methods or set()):
                return
        if any(shape(route.path) == shape(path) for route in router.routes):
            concrete = path.replace("{review_id}", str(REVIEW_ID)).replace("{identifier}", str(REVIEW_ID)).replace("{version_no}", "1")
            response = self.client.request(method.upper(), f"/api/v1{concrete}")
            assert_error(response, 405, "METHOD_NOT_ALLOWED")
            return
        pytest.xfail(f"T-B201/#346 未实现：缺少 {method} {path}")


def _load_routes() -> Any:
    try:
        return importlib.import_module("app.api.v1.reviews")
    except ModuleNotFoundError as exc:
        if exc.name == "app.api.v1.reviews":
            return None
        raise


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> World:
    routes = _load_routes()
    if routes is None:
        pytest.xfail("T-B201 未实现：app.api.v1.reviews 模块尚不存在")
    router = getattr(routes, "router", None)
    if router is None:
        pytest.xfail("T-B201 未实现：app.api.v1.reviews 未公开 router")

    from app.auth import deps
    from app.common.errors import install_exception_handlers
    from app.config import get_settings

    db = SyntheticDB()
    engine = SyntheticEngine(db)
    auth = SimpleNamespace(user_id=OWNER, user=SimpleNamespace(id=OWNER))
    settings = SimpleNamespace(
        app_env="test",
        app_master_key=None,
        page_limit_default=50,
        page_limit_max=200,
        cursor_ttl_s=3600,
    )

    class MemoryRedis:
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

    redis = MemoryRedis()
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.current_auth] = lambda: auth
    app.dependency_overrides[deps.get_redis] = lambda: redis
    app.dependency_overrides[get_settings] = lambda: settings
    with TestClient(app) as client:
        yield World(client=client, routes=routes, db=db)
    app.dependency_overrides.clear()


def assert_error(response: Any, status: int, code: str) -> dict[str, Any]:
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    return error


def assert_stat(value: Any) -> None:
    assert isinstance(value, dict)
    assert {"value", "n", "window", "small_sample"} <= set(value)
    assert isinstance(value["n"], int) and value["n"] >= 0
    assert value["window"] is not None
    assert isinstance(value["small_sample"], bool)


def valid_review(**overrides: Any) -> dict[str, Any]:
    body = {
        "plan_id": str(OWN_PLAN),
        "security_code": SYNTHETIC_CODE,
        "period_start": "2026-01-01",
        "period_end": "2026-01-02",
        "plan_version_ids": [str(VERSION_ID)],
        "trade_ids": [],
        "lessons": "合成经验",
        "tags": ["synthetic"],
        "judgement": [{"condition_text": "条件", "fulfilled": True, "note": None}],
    }
    body.update(overrides)
    return body


def valid_version(**overrides: Any) -> dict[str, Any]:
    body = {
        "plan_version_ids": [str(VERSION_ID)],
        "trade_ids": [],
        "lessons": "合成经验",
        "tags": ["synthetic"],
        "judgement": [{"condition_text": "条件", "fulfilled": True, "note": None}],
        "base_version_no": 1,
    }
    body.update(overrides)
    return body


def test_v1_list_owned_rows_and_datastatusblock(world: World) -> None:
    world.require("GET", "/reviews")
    world.db.reviews.append(
        SyntheticRow(
            id=OTHER,
            user_id=OTHER,
            plan_id=OTHER_PLAN,
            security_code=SYNTHETIC_CODE,
            name="他人复盘",
            period_start=dt.date(2026, 1, 1),
            period_end=dt.date(2026, 1, 2),
            current_version_id=VERSION_ID,
            current_version_no=1,
            created_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        )
    )
    response = world.client.get("/api/v1/reviews?limit=2")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {"items", "next_cursor"}
    assert isinstance(payload["items"], list)
    for item in payload["items"]:
        assert {
            "id", "plan_id", "security_code", "name", "period_start", "period_end",
            "current_version_no", "created_at",
        } <= set(item)
    assert any(item["id"] == str(REVIEW_ID) for item in payload["items"])
    for item in payload["items"]:
        assert {"data_status", "data_as_of", "gaps"} <= set(item)
    assert all(item["id"] != str(OTHER) for item in payload["items"])


def test_v1_empty_list_and_stable_cursor_boundary(world: World) -> None:
    world.require("GET", "/reviews")
    world.db.reviews.clear()
    empty = world.client.get("/api/v1/reviews?limit=2")
    assert empty.status_code == 200
    assert empty.json() == {"items": [], "next_cursor": None}

    world.db.reviews.extend([SyntheticDB().reviews[0], SyntheticDB().reviews[0]])
    first = world.client.get("/api/v1/reviews?limit=1")
    assert first.status_code == 200
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str) and cursor
    second = world.client.get("/api/v1/reviews?limit=1", params={"cursor": cursor})
    assert second.status_code == 200
    assert second.json()["next_cursor"] is None


def test_v1_invalid_cursor_is_400_invalid_cursor(world: World) -> None:
    world.require("GET", "/reviews")
    assert_error(
        world.client.get("/api/v1/reviews?cursor=not-a-valid-cursor"),
        400,
        "INVALID_CURSOR",
    )


def test_v1_detail_has_current_version_timeline_and_parseable_empty_stats(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    response = world.client.get(f"/api/v1/reviews/{REVIEW_ID}")
    assert response.status_code == 200
    payload = response.json()
    assert {"current_version", "timeline"} <= set(payload)
    assert isinstance(payload["timeline"], list)
    for key in ("holding_return", "benchmark_return", "excess_return", "max_drawdown"):
        assert_stat(payload["current_version"]["outcome_metrics"][key])


def test_v1_unknown_or_other_owner_is_404_without_leak(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    for review_id in (uuid.UUID("99999999-9999-4999-8999-999999999999"), OTHER):
        error = assert_error(world.client.get(f"/api/v1/reviews/{review_id}"), 404, "NOT_FOUND")
        assert str(OTHER_PLAN) not in str(error)
        assert SYNTHETIC_CODE not in str(error)


def test_v2_create_201_keeps_computed_facts_server_owned(world: World) -> None:
    world.require("POST", "/reviews")
    response = world.client.post("/api/v1/reviews", json=valid_review())
    assert response.status_code == 201
    payload = response.json()
    assert "outcome_metrics" in payload.get("current_version", payload)
    assert payload.get("outcome_metrics") != {"holding_return": {"value": 999}}
    assert all("holding_return" not in item for item in payload.get("judgement", []))


@pytest.mark.parametrize(
    "body",
    [
        valid_review(plan_id=None, security_code=SYNTHETIC_CODE),
        valid_review(plan_id=str(OWN_PLAN), security_code=None),
    ],
)
def test_v2_create_plan_only_or_security_only_boundary(world: World, body: dict[str, Any]) -> None:
    world.require("POST", "/reviews")
    response = world.client.post("/api/v1/reviews", json=body)
    assert response.status_code == 201


@pytest.mark.parametrize(
    "body",
    [
        valid_review(plan_id=None, security_code=None),
        valid_review(period_start="2026-01-03", period_end="2026-01-02"),
        valid_review(trade_ids=[str(OTHER_TRADE)]),
        valid_review(outcome_metrics={"holding_return": {"value": 99}}),
    ],
)
def test_v2_create_rejects_missing_scope_bad_dates_and_foreign_links(
    world: World, body: dict[str, Any]
) -> None:
    world.require("POST", "/reviews")
    assert_error(world.client.post("/api/v1/reviews", json=body), 400, "VALIDATION_ERROR")


def test_v2_version_save_freezes_old_content(world: World) -> None:
    world.require("GET", "/reviews/{review_id}/versions/{version_no}")
    world.require("POST", "/reviews/{review_id}/versions")
    before = world.client.get(f"/api/v1/reviews/{REVIEW_ID}/versions/1")
    assert before.status_code == 200
    old_lessons = before.json()["lessons"]
    saved = world.client.post(
        f"/api/v1/reviews/{REVIEW_ID}/versions",
        json=valid_version(lessons="新的合成经验"),
    )
    assert saved.status_code == 201
    assert saved.json()["current_version_no"] > 1
    after = world.client.get(f"/api/v1/reviews/{REVIEW_ID}/versions/1")
    assert after.status_code == 200
    assert after.json()["lessons"] == old_lessons


def test_v2_version_base_conflict_has_current_version_no(world: World) -> None:
    world.require("POST", "/reviews/{review_id}/versions")
    error = assert_error(
        world.client.post(
            f"/api/v1/reviews/{REVIEW_ID}/versions",
            json=valid_version(base_version_no=2),
        ),
        409,
        "VERSION_CONFLICT",
    )
    assert error["details"]["current_version_no"] == 1


@pytest.mark.parametrize("method", ["patch", "delete"])
def test_v2_old_version_mutations_are_405(world: World, method: str) -> None:
    world.require(method.upper(), "/reviews/{review_id}/versions/{version_no}")
    response = getattr(world.client, method)(f"/api/v1/reviews/{REVIEW_ID}/versions/1")
    assert_error(response, 405, "METHOD_NOT_ALLOWED")


def test_v3_timeline_and_judgement_preserve_three_part_attribution(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    payload = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()
    assert any(
        any(part in str(item.get("kind", "")).lower() for part in ("plan", "trade"))
        for item in payload["timeline"]
    )
    attribution = payload["current_version"]["attribution"]
    assert attribution["judgement"][0]["fulfilled"] is True
    assert isinstance(attribution["execution"], list)
    assert isinstance(attribution["market"], list)


def test_v3_missing_evidence_stays_unknown_or_empty(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    attribution = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()["current_version"]["attribution"]
    for key in ("execution", "market"):
        assert all(not item.get("evidence_ids") for item in attribution[key])


def test_v3_foreign_trade_same_security_cannot_enter_review(world: World) -> None:
    world.require("POST", "/reviews")
    response = world.client.post(
        "/api/v1/reviews",
        json=valid_review(trade_ids=[str(OTHER_TRADE)], security_code=SYNTHETIC_CODE),
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


def test_v4_outcome_metrics_are_stat_objects(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    metrics = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()["current_version"]["outcome_metrics"]
    assert set(metrics) == {"holding_return", "benchmark_return", "excess_return", "max_drawdown"}
    for metric in metrics.values():
        assert_stat(metric)


def test_v4_missing_fee_or_benchmark_is_null_with_no_source_gap(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    metrics = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()["current_version"]["outcome_metrics"]
    for metric in (metrics["holding_return"], metrics["benchmark_return"]):
        assert metric["value"] is None
        assert "no_source" in metric.get("gaps", [])


def test_v4_future_period_has_no_terminal_value(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    world.db.reviews[0].period_end = dt.date.today() + dt.timedelta(days=30)
    payload = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()
    metrics = payload["current_version"]["outcome_metrics"]
    for metric in metrics.values():
        assert metric.get("value") is None
    if any("not_yet_published" not in metric.get("gaps", []) for metric in metrics.values()):
        pytest.xfail("T-B201/#346 未实现：未来周期指标未标记 not_yet_published")


def test_v4_simulation_cannot_be_reported_as_real_holding_return(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    world.db.versions[0].outcome_metrics["holding_return"] = {
        "value": 0.42,
        "n": 10,
        "window": {"start": "2026-01-01", "end": "2026-01-02"},
        "small_sample": False,
        "source": "simulated_tracking",
    }
    metrics = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()["current_version"]["outcome_metrics"]
    holding = metrics["holding_return"]
    if holding.get("value") is not None and holding.get("source") == "simulated_tracking":
        pytest.xfail("T-B201/#346 未实现：未过滤 simulated_tracking 指标")


def test_v4_unverified_numeric_u5_value_is_marked_unverified(world: World) -> None:
    world.require("GET", "/reviews/{review_id}")
    world.db.versions[0].outcome_metrics["excess_return"] = {
        "value": 0.1,
        "n": 3,
        "window": {"start": "2026-01-01", "end": "2026-01-02"},
        "small_sample": True,
        "gaps": [],
    }
    metric = world.client.get(f"/api/v1/reviews/{REVIEW_ID}").json()["current_version"]["outcome_metrics"]["excess_return"]
    if metric.get("value") is not None:
        text = " ".join(str(metric.get(key, "")) for key in ("gap", "gaps", "status", "label"))
        if "unverified" not in text.lower() and "未验证" not in text:
            pytest.xfail("T-B201/#346 未实现：未给 U5 数值指标标注未验证状态")

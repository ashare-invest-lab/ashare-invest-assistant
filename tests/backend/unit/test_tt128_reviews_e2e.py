"""T-T128：#362 复盘页六条清单的真实 HTTP + 隔离 PostgreSQL 验收。"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import SecretStr
from psycopg import sql
from sqlalchemy import create_engine, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, make_url

from app.auth import deps
from app.config import Settings, load_yaml_dir
from app.db.migration_check import MigrationLineageError
from app.db.tables.accounts import accounts, import_batches, trades
from app.db.tables.market import securities, trading_calendar
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.reviews import data_snapshots, review_versions, reviews
from app.db.tables.users import users
from app.main import create_app

OWNER = uuid.uuid4()
CODE = "600128.SH"
BENCHMARK = "000300.SH"
DAY = dt.date(2025, 1, 8)
UTC = dt.timezone.utc
PLAN_ID = uuid.uuid4()
PLAN_VERSION_ID = uuid.uuid4()


class RedisStub:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del ex
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> int:
        return int(self.values.pop(key, None) is not None)


class RouteUnavailable(RuntimeError):
    """运行时路由未注册，供严格 xfail 精确匹配。"""


def _database_url() -> str:
    raw = os.environ.get("AIA_TEST_DATABASE_URL") or os.environ.get("TT41_DATABASE_URL")
    if not raw:
        pytest.skip("未设置 AIA_TEST_DATABASE_URL 或 TT41_DATABASE_URL，跳过 PostgreSQL 验收")
    return raw


def _upgrade(database_url: str) -> Engine:
    backend = Path(__file__).resolve().parents[3] / "src" / "backend"
    cfg = Config(str(backend / "alembic.ini"))
    cfg.cmd_opts = SimpleNamespace(x=[f"url={database_url}"])
    try:
        command.upgrade(cfg, "head")
    except MigrationLineageError as exc:
        if "DATABASE_REVISION_NOT_MAINLINE" not in str(exc):
            raise
    return create_engine(
        make_url(database_url).set(drivername="postgresql+psycopg"),
        hide_parameters=True,
        pool_pre_ping=True,
    )


def _settings(monkeypatch: pytest.MonkeyPatch, database_url: str) -> Settings:
    config_dir = Path(__file__).resolve().parents[3] / "config"
    monkeypatch.setattr(
        Settings,
        "settings_customise_sources",
        classmethod(lambda cls, settings_cls, init_settings, **kwargs: (init_settings,)),
    )
    return Settings(
        _env_file=None,
        app_env="test",
        service_name="api",
        database_url=SecretStr(database_url),
        redis_url="redis://127.0.0.1:63999/0",
        app_master_key=None,
        api_prefix="/api/v1",
        session_cookie_secure=False,
        config_dir=config_dir,
        business=load_yaml_dir(config_dir),
    )


def _require_route(client: TestClient, path: str) -> None:
    if not any(route.path == path for route in client.app.routes):
        raise RouteUnavailable(f"HTTP 路由未注册 {path}")


@pytest.fixture(scope="module")
def pg() -> Any:
    base_url = make_url(_database_url())
    database_name = "tt128_" + uuid.uuid4().hex
    if not base_url.database:
        raise RuntimeError("T-T128 数据库 DSN 缺少数据库名")
    admin = psycopg.connect(
        base_url.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False),
        autocommit=True,
    )
    created = False
    engine: Engine | None = None
    try:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))
        created = True
        isolated_url = base_url.set(database=database_name).set(drivername="postgresql+psycopg")
        engine = _upgrade(isolated_url.render_as_string(hide_password=False))
        with engine.begin() as conn:
            conn.execute(
                insert(users).values(
                    id=OWNER,
                    username=f"tt128_{OWNER.hex[:8]}",
                    password_hash="synthetic-password-hash",
                    role="user",
                    status="approved",
                )
            )
            conn.execute(
                pg_insert(securities),
                [
                    {"code": CODE, "type": "stock", "name": "虚构复盘证券", "exchange": "SH", "listing_status": "listed"},
                    {"code": BENCHMARK, "type": "index", "name": "虚构基准", "exchange": "SH", "listing_status": "listed"},
                ],
            )
            conn.execute(
                insert(action_plans).values(
                    id=PLAN_ID,
                    user_id=OWNER,
                    security_code=CODE,
                    status="draft",
                    origin="manual",
                    candidate_signal_ids=[],
                )
            )
            conn.execute(
                insert(plan_versions).values(
                    id=PLAN_VERSION_ID,
                    plan_id=PLAN_ID,
                    version_no=1,
                    action="buy",
                    rationale="虚构复盘计划",
                    snapshot_id=None,
                )
            )
            conn.execute(update(action_plans).where(action_plans.c.id == PLAN_ID).values(current_version_id=PLAN_VERSION_ID))
            conn.execute(insert(trading_calendar).values(date=DAY, is_open=True))
        yield engine
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            admin.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name)))
        admin.close()


@pytest.fixture
def http(pg: Engine, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest) -> TestClient:
    cfg = _settings(monkeypatch, pg.url.render_as_string(hide_password=False))
    app = create_app(cfg)
    required = {
        "test_post_reviews_freezes_four_empty_outcome_metrics_and_gaps": ["/api/v1/reviews"],
        "test_get_reviews_projects_summary_status_and_metric_gaps": ["/api/v1/reviews"],
        "test_get_review_detail_without_version_has_empty_state_and_status": ["/api/v1/reviews/{identifier}"],
        "test_versions_keep_old_snapshot_metrics_and_evidence_frozen": [
            "/api/v1/reviews",
            "/api/v1/reviews/{identifier}/versions",
            "/api/v1/reviews/{identifier}/versions/{version_no}",
        ],
        "test_timeline_separates_simulated_tracking_from_actual_trade_evidence": ["/api/v1/reviews/{identifier}"],
        "test_import_commit_visibility_and_pit_do_not_make_zero_samples": ["/api/v1/reviews"],
    }[request.node.name]
    missing = next((path for path in required if not any(route.path == path for route in app.routes)), None)
    if missing:
        request.node.add_marker(
            pytest.mark.xfail(
                strict=True,
                raises=RouteUnavailable,
                reason=f"T-T128 缺路由 {missing}，等 T-B242/#362",
            )
        )
    redis = RedisStub()
    app.dependency_overrides.update(
        {
            deps.current_auth: lambda: SimpleNamespace(user_id=OWNER),
            deps.get_engine: lambda: pg,
            deps.get_redis: lambda: redis,
            deps.get_settings: lambda: cfg,
        }
    )
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    client.close()


def _body(**extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "security_code": CODE,
        "period_start": "2025-01-02",
        "period_end": DAY.isoformat(),
        "plan_version_ids": [],
        "trade_ids": [],
        "lessons": None,
        "tags": [],
        "judgement": [],
    }
    body.update(extra)
    return body


def _metrics(payload: dict[str, Any]) -> dict[str, Any]:
    return payload["current_version"]["outcome_metrics"]


def _assert_empty_metrics(metrics: dict[str, Any]) -> None:
    assert set(metrics) == {"holding_return", "benchmark_return", "excess_return", "max_drawdown"}
    for metric in metrics.values():
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["small_sample"] is True


def _metric_gap_keys(payload: dict[str, Any]) -> set[str]:
    return {item["key"] for item in payload["gaps"]}


def _insert_account(conn: Any, account_id: uuid.UUID) -> None:
    conn.execute(
        insert(accounts).values(
            id=account_id,
            user_id=OWNER,
            name="虚构账户",
            broker_label="synthetic",
            base_currency="CNY",
        )
    )


def _insert_trade(
    conn: Any,
    trade_id: uuid.UUID,
    account_id: uuid.UUID,
    *,
    batch_id: uuid.UUID | None = None,
    traded_at: dt.datetime | None = None,
) -> None:
    conn.execute(
        insert(trades).values(
            id=trade_id,
            account_id=account_id,
            user_id=OWNER,
            security_code=CODE,
            side="buy",
            quantity=Decimal("10"),
            price=Decimal("10"),
            amount=Decimal("100"),
            commission=Decimal("0"),
            stamp_tax=Decimal("0"),
            transfer_fee=Decimal("0"),
            other_fee=Decimal("0"),
            net_amount=Decimal("100"),
            traded_at=traded_at or dt.datetime(2025, 1, 3, 7, tzinfo=UTC),
            trade_date=DAY,
            source="import" if batch_id else "manual",
            import_batch_id=batch_id,
            epistemic_type="execution",
            dedup_key=str(trade_id),
        )
    )


def test_post_reviews_freezes_four_empty_outcome_metrics_and_gaps(http: TestClient, pg: Engine) -> None:
    """清单 1：POST 创建的四项指标均为空，缺口逐项归因。"""
    _require_route(http, "/api/v1/reviews")
    response = http.post("/api/v1/reviews", json=_body())
    assert response.status_code == 201, response.text
    payload = response.json()
    _assert_empty_metrics(_metrics(payload))
    snapshot_id = payload["current_version"]["snapshot_id"]
    with pg.connect() as conn:
        snapshot = conn.execute(
            select(data_snapshots.c["items"]).where(data_snapshots.c.id == snapshot_id)
        ).scalar_one()
    persisted_metrics = snapshot["outcome_metrics"]
    for metric in persisted_metrics.values():
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["small_sample"] is True
    assert _metric_gap_keys(payload) >= {
        "outcome_metrics.holding_return",
        "outcome_metrics.benchmark_return",
        "outcome_metrics.excess_return",
        "outcome_metrics.max_drawdown",
    }
    assert all(item["reason"] == "no_source" for item in payload["gaps"] if item["key"].startswith("outcome_metrics."))


def test_get_reviews_projects_summary_status_and_metric_gaps(http: TestClient) -> None:
    """清单 2：GET 列表投影四项指标缺口与顶层数据状态块。"""
    _require_route(http, "/api/v1/reviews")
    created = http.post("/api/v1/reviews", json=_body(plan_id=str(PLAN_ID))).json()
    listed = http.get("/api/v1/reviews")
    assert listed.status_code == 200, listed.text
    item = next(row for row in listed.json()["items"] if row["id"] == created["id"])
    assert item["data_status"] == "unavailable"
    assert item["data_as_of"] is None
    assert set(item) >= {"data_status", "data_as_of", "gaps"}
    assert _metric_gap_keys(item) >= {
        "outcome_metrics.holding_return",
        "outcome_metrics.benchmark_return",
        "outcome_metrics.excess_return",
        "outcome_metrics.max_drawdown",
    }


def test_get_review_detail_without_version_has_empty_state_and_status(http: TestClient, pg: Engine) -> None:
    """清单 3：无版本、无证据时详情顶层状态和空态保持可解释。"""
    _require_route(http, "/api/v1/reviews/{identifier}")
    review_id = uuid.uuid4()
    with pg.begin() as conn:
        conn.execute(
            insert(reviews).values(
                id=review_id,
                user_id=OWNER,
                security_code=CODE,
                period_start=dt.date(2025, 1, 2),
                period_end=DAY,
            )
        )
    response = http.get(f"/api/v1/reviews/{review_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["current_version"] is None
    assert payload["current_version_no"] is None
    assert payload["timeline"] == []
    assert payload["evidence"] == []
    assert payload["data_status"] == "unavailable"
    assert payload["data_as_of"] is None
    assert {item["key"] for item in payload["gaps"]} >= {"outcome_metrics"}


def test_versions_keep_old_snapshot_metrics_and_evidence_frozen(http: TestClient, pg: Engine) -> None:
    """清单 4：新增后续成交只进入新版本，旧版本仍冻结为空态。"""
    for path in ("/api/v1/reviews", "/api/v1/reviews/{identifier}/versions", "/api/v1/reviews/{identifier}/versions/{version_no}"):
        _require_route(http, path)
    first = http.post("/api/v1/reviews", json=_body()).json()
    review_id = first["id"]
    account_id, trade_id = uuid.uuid4(), uuid.uuid4()
    with pg.begin() as conn:
        _insert_account(conn, account_id)
        _insert_trade(conn, trade_id, account_id)
    revised = http.post(
        f"/api/v1/reviews/{review_id}/versions",
        json=_body(trade_ids=[str(trade_id)], base_version_no=1),
    )
    assert revised.status_code == 201, revised.text
    old = http.get(f"/api/v1/reviews/{review_id}/versions/1")
    current = http.get(f"/api/v1/reviews/{review_id}/versions/2")
    assert old.status_code == current.status_code == 200
    old_payload, current_payload = old.json(), current.json()
    assert old_payload["trade_ids"] == []
    assert old_payload["evidence"] == []
    _assert_empty_metrics(old_payload["outcome_metrics"])
    assert current_payload["trade_ids"] == [str(trade_id)]
    assert old_payload["snapshot_id"] != current_payload["snapshot_id"]
    versions = http.get(f"/api/v1/reviews/{review_id}/versions")
    assert [item["version_no"] for item in versions.json()["items"]] == [2, 1]


def test_timeline_separates_simulated_tracking_from_actual_trade_evidence(http: TestClient, pg: Engine) -> None:
    """清单 5：模拟 tracking 不能进入实际成交指标或成交时间线。"""
    _require_route(http, "/api/v1/reviews/{identifier}")
    review_id, version_id, snapshot_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    window = "2025-01-02/2025-01-08"
    simulated = {
        name: {"value": "12.00", "n": 10, "window": window, "small_sample": True}
        for name in ("holding_return", "benchmark_return", "excess_return", "max_drawdown")
    }
    items = {
        "period_start": "2025-01-02",
        "period_end": "2025-01-08",
        "outcome_metrics": simulated,
        "attribution": {"judgement": [], "execution": [], "market": []},
        "evidence": [],
        "data_status": "partial",
        "data_as_of": None,
        "gaps": [],
    }
    with pg.begin() as conn:
        conn.execute(insert(reviews).values(id=review_id, user_id=OWNER, security_code=CODE, period_start=dt.date(2025, 1, 2), period_end=DAY, current_version_id=None))
        raw = hashlib.sha256(str(snapshot_id).encode()).hexdigest()
        conn.execute(insert(data_snapshots).values(id=snapshot_id, user_id=OWNER, purpose="review", items=items, hash=raw))
        conn.execute(insert(review_versions).values(id=version_id, review_id=review_id, version_no=1, plan_version_ids=[], trade_ids=[], outcome_metrics=simulated, attribution=items["attribution"], tags=[], snapshot_id=snapshot_id))
        conn.execute(update(reviews).where(reviews.c.id == review_id).values(current_version_id=version_id))
    response = http.get(f"/api/v1/reviews/{review_id}")
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["evidence"] == []
    assert [item["kind"] for item in payload["timeline"]] == ["review_version"]
    assert payload["current_version"]["attribution"]["execution"] == []
    for metric in payload["current_version"]["outcome_metrics"].values():
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["small_sample"] is True
        assert "source" not in metric


def test_import_commit_visibility_and_pit_do_not_make_zero_samples(http: TestClient, pg: Engine) -> None:
    """清单 6：未提交与未来提交批次均不可见，PIT 缺口不转零值。"""
    _require_route(http, "/api/v1/reviews")
    account_id = uuid.uuid4()
    unproven_batch, future_batch = uuid.uuid4(), uuid.uuid4()
    unproven_trade, future_trade = uuid.uuid4(), uuid.uuid4()
    with pg.begin() as conn:
        _insert_account(conn, account_id)
        conn.execute(insert(import_batches).values(id=unproven_batch, user_id=OWNER, account_id=account_id, status="parsing", kind="trades"))
        conn.execute(insert(import_batches).values(id=future_batch, user_id=OWNER, account_id=account_id, status="committed", kind="trades", committed_at=dt.datetime.now(UTC) + dt.timedelta(days=1)))
        _insert_trade(conn, unproven_trade, account_id, batch_id=unproven_batch)
        _insert_trade(conn, future_trade, account_id, batch_id=future_batch)
    response = http.post("/api/v1/reviews", json=_body(trade_ids=[str(unproven_trade), str(future_trade)]))
    assert response.status_code == 201, response.text
    payload = response.json()
    _assert_empty_metrics(_metrics(payload))
    assert payload["data_status"] == "unavailable"
    assert payload["data_as_of"] is None
    assert payload["evidence"] == []
    assert not any(item["kind"] == "trade" for item in payload["timeline"])
    assert any(item["key"] == "trades.import_commit_unproven" and item["reason"] == "no_source" for item in payload["gaps"])

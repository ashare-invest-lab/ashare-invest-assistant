"""T-T127：禁投冷静期页的真实 HTTP / 隔离 PostgreSQL 验收。

数据库只播种虚构用户和证券。认证依赖在应用边界注入虚构的已批准用户，
限制项、证券名称、删除重查均经真实 SQLAlchemy PostgreSQL 连接和 HTTP 路由。
"""

from __future__ import annotations

import datetime as dt
import threading
import uuid
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Iterator

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import create_engine, delete, insert, text

from app.auth.deps import AuthContext, current_auth, get_redis
from app.config import Settings
from app.db.tables.market import securities
from app.db.tables.signals import user_restrictions
from app.db.tables.users import users
from app.main import create_app


UTC = dt.UTC
API = "/api/v1/restrictions"


class MemoryRedis:
    """只替代本测试的 Redis 资源，限制记录仍走隔离 PostgreSQL。"""

    def __init__(self) -> None:
        self._values: dict[str, str] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        del ex
        with self._lock:
            if nx and key in self._values:
                return False
            self._values[key] = value
            return True

    def get(self, key: str) -> str | None:
        with self._lock:
            return self._values.get(key)

    def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)


@dataclass
class World:
    engine: Any
    client: TestClient
    user_id: uuid.UUID
    named_code: str
    missing_code: str


def _settings(pg_url: str) -> Settings:
    return Settings(
        _env_file=None,
        database_url=SecretStr(pg_url),
        redis_url="redis://127.0.0.1:1/0",
        app_env="test",
        app_master_key=SecretStr("T-T127 synthetic test master key only 0001"),
        session_cookie_secure=False,
    )


@pytest.fixture()
def world(pg_url: str) -> Iterator[World]:
    engine = create_engine(pg_url, hide_parameters=True)
    user_id = uuid.uuid4()
    named_code = f"600{uuid.uuid4().hex[:3]}.SH"
    missing_code = f"600{uuid.uuid4().hex[:3]}.SH"
    with engine.begin() as conn:
        conn.execute(
            insert(users).values(
                id=user_id,
                username=f"tt127_{user_id.hex[:12]}",
                password_hash="synthetic-password-hash",
                display_name="T-T127 虚构用户",
                role="user",
                status="approved",
            )
        )
        conn.execute(
            insert(securities).values(
                code=named_code,
                type="stock",
                name="T-T127 虚构证券",
                exchange="SH",
                board="main",
                listing_status="listed",
            )
        )

    settings = _settings(pg_url)
    app = create_app(settings)
    app.dependency_overrides[current_auth] = lambda: AuthContext(
        user=SimpleNamespace(id=user_id, status="approved", role="user"),
        session=SimpleNamespace(),
    )
    redis = MemoryRedis()
    app.dependency_overrides[get_redis] = lambda: redis
    client = TestClient(app, raise_server_exceptions=False)
    try:
        yield World(engine, client, user_id, named_code, missing_code)
    finally:
        client.close()
        app.dependency_overrides.clear()
    with engine.begin() as conn:
        conn.execute(delete(user_restrictions).where(user_restrictions.c.user_id == user_id))
        conn.execute(delete(securities).where(securities.c.code == named_code))
        conn.execute(delete(users).where(users.c.id == user_id))
    engine.dispose()


def _seed_restriction(
    world: World,
    *,
    kind: str = "blocklist",
    target_id: str | None = None,
    until: dt.datetime | None = None,
    created_at: dt.datetime | None = None,
) -> uuid.UUID:
    identifier = uuid.uuid4()
    values: dict[str, Any] = {
        "id": identifier,
        "user_id": world.user_id,
        "kind": kind,
        "target_type": "security",
        "target_id": target_id or world.named_code,
        "until": until,
    }
    if created_at is not None:
        values["created_at"] = created_at
    with world.engine.begin() as conn:
        conn.execute(insert(user_restrictions).values(**values))
    return identifier


def _error(response: Any) -> dict[str, Any]:
    assert response.headers.get("content-type", "").startswith("application/json")
    body = response.json()
    assert "error" in body
    return body["error"]


def test_cooling_off_requires_timezone_and_future_until(world: World) -> None:
    missing = world.client.post(
        API,
        json={"kind": "cooling_off", "target_type": "security", "target_id": world.named_code},
    )
    assert missing.status_code == 400
    assert _error(missing)["code"] == "VALIDATION_ERROR"
    assert {item["issue"] for item in _error(missing)["details"]["fields"]} == {
        "required_for_kind"
    }

    past = world.client.post(
        API,
        json={
            "kind": "cooling_off",
            "target_type": "security",
            "target_id": world.named_code,
            "until": (dt.datetime.now(UTC) - dt.timedelta(seconds=2)).isoformat(),
        },
    )
    assert past.status_code == 400
    assert _error(past)["code"] == "VALIDATION_ERROR"
    assert {item["issue"] for item in _error(past)["details"]["fields"]} == {"must_be_future"}


def test_cooling_off_future_value_is_visible_over_http(world: World) -> None:
    until = dt.datetime.now(UTC) + dt.timedelta(days=1)
    response = world.client.post(
        API,
        json={
            "kind": "cooling_off",
            "target_type": "security",
            "target_id": world.named_code,
            "until": until.isoformat(),
            "reason": "synthetic runtime default check",
        },
    )
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["kind"] == "cooling_off"
    assert item["status"] == "active"
    assert item["name"] == "T-T127 虚构证券"
    assert item["gaps"] == []


def test_list_projects_active_expired_missing_name_and_top_level_gaps(world: World) -> None:
    now = dt.datetime.now(UTC)
    _seed_restriction(world, created_at=now - dt.timedelta(minutes=2))
    _seed_restriction(
        world,
        target_id=world.missing_code,
        until=now - dt.timedelta(seconds=2),
        created_at=now - dt.timedelta(minutes=1),
    )
    response = world.client.get(API)
    assert response.status_code == 200, response.text
    body = response.json()
    assert {item["status"] for item in body["items"]} == {"active", "expired"}
    missing = next(item for item in body["items"] if item["target_id"] == world.missing_code)
    assert missing["name"] is None
    assert any(gap["reason"] == "no_source" for gap in body["gaps"])
    named = next(item for item in body["items"] if item["target_id"] == world.named_code)
    assert named["name"] == "T-T127 虚构证券"


def test_post_idempotency_is_http_visible(world: World) -> None:
    payload = {
        "kind": "blocklist",
        "target_type": "security",
        "target_id": world.named_code,
        "reason": "synthetic idempotency",
    }
    first = world.client.post(API, json=payload, headers={"Idempotency-Key": "tt127-key"})
    replay = world.client.post(API, json=payload, headers={"Idempotency-Key": "tt127-key"})
    assert first.status_code == replay.status_code == 201
    assert replay.json() == first.json()
    changed = world.client.post(
        API,
        json={**payload, "reason": "synthetic conflict"},
        headers={"Idempotency-Key": "tt127-key"},
    )
    assert changed.status_code == 409
    assert _error(changed)["code"] == "IDEMPOTENCY_CONFLICT"


def test_concurrent_delete_rechecks_and_empty_state_are_http_visible(world: World) -> None:
    created = world.client.post(
        API,
        json={
            "kind": "blocklist",
            "target_type": "security",
            "target_id": world.named_code,
        },
    )
    assert created.status_code == 201, created.text
    restriction_id = created.json()["id"]

    responses: list[Any] = []
    lock = threading.Lock()

    def delete_once() -> None:
        result = world.client.delete(f"{API}/{restriction_id}")
        with lock:
            responses.append(result)

    threads = [threading.Thread(target=delete_once) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(responses) == 2
    assert all(response.status_code == 200 for response in responses)
    bodies = [response.json() for response in responses]
    assert {body["status"] for body in bodies} == {"removed"}
    assert len({body["removed_at"] for body in bodies}) == 1
    assert all(body["recheck"] == {"released_reason_ids": [], "remaining_reason_ids": []} for body in bodies)
    assert all("tradable" not in body for body in bodies)
    listed = world.client.get(API)
    assert listed.status_code == 200
    assert listed.json()["items"] == []


@pytest.mark.xfail(
    strict=True,
    reason="T-T127 / §7.5 recheck gaps must return 200 with explicit no_source gap",
)
def test_delete_recheck_gap_is_not_reported_as_release(world: World) -> None:
    """Unknown target values model a future enum and must surface a gap, not success."""
    definition: str
    with world.engine.begin() as conn:
        definition = str(
            conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='app.user_restrictions'::regclass "
                    "AND conname='ck_user_restrictions_target_type'"
                )
            ).scalar_one()
        )
        conn.execute(
            text("ALTER TABLE app.user_restrictions DROP CONSTRAINT ck_user_restrictions_target_type")
        )
        identifier = uuid.uuid4()
        conn.execute(
            insert(user_restrictions).values(
                id=identifier,
                user_id=world.user_id,
                kind="blocklist",
                target_type="future_target",
                target_id=world.named_code,
            )
        )
    try:
        response = world.client.delete(f"{API}/{identifier}")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["recheck"]["released_reason_ids"] == []
        assert body["gaps"]
        assert body["gaps"][0]["reason"] == "no_source"
    finally:
        with world.engine.begin() as conn:
            conn.execute(delete(user_restrictions).where(user_restrictions.c.id == identifier))
            conn.execute(
                text(
                    "ALTER TABLE app.user_restrictions ADD CONSTRAINT "
                    f"ck_user_restrictions_target_type {definition}"
                )
            )


@pytest.mark.xfail(
    strict=True,
    reason="T-T127 / §7.5 future kind/status must render 未知 without HTTP response failure",
)
def test_unknown_kind_is_preserved_by_http_projection(world: World) -> None:
    definition: str
    identifier = uuid.uuid4()
    with world.engine.begin() as conn:
        definition = str(
            conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid='app.user_restrictions'::regclass "
                    "AND conname='ck_user_restrictions_kind'"
                )
            ).scalar_one()
        )
        conn.execute(
            text("ALTER TABLE app.user_restrictions DROP CONSTRAINT ck_user_restrictions_kind")
        )
        conn.execute(
            insert(user_restrictions).values(
                id=identifier,
                user_id=world.user_id,
                kind="future_kind",
                target_type="security",
                target_id=world.named_code,
            )
        )
    try:
        response = world.client.get(API)
        assert response.status_code == 200, response.text
        item = response.json()["items"][0]
        assert item["kind"] == "future_kind"
        assert item["status"] == "unknown"
    finally:
        with world.engine.begin() as conn:
            conn.execute(delete(user_restrictions).where(user_restrictions.c.id == identifier))
            conn.execute(
                text(
                    "ALTER TABLE app.user_restrictions ADD CONSTRAINT "
                    f"ck_user_restrictions_kind {definition}"
                )
            )

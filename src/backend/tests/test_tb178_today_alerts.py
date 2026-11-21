"""T-B178: fictional alerts through the real Today route and isolated PostgreSQL."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import json
import os
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Engine, create_engine, insert, text
from sqlalchemy.engine import make_url

from app.aggregates.models import Today
from app.api.v1.aggregates import router
from app.auth.deps import current_auth, get_engine
from app.config import get_settings
from app.config_files import MarketRulesConfig, RealtimeConfig
from app.db.base import SCHEMAS, metadata
from app.db.tables.market import securities, trading_calendar
from app.db.tables.research import alert_rules, alerts
from app.db.tables.users import users

ROOT = Path(__file__).resolve().parents[3]
AT = dt.datetime(2020, 1, 2, 8, tzinfo=dt.UTC)
CODE = "999991.SH"


@pytest.fixture(scope="module")
def database() -> Iterator[Engine]:
    preset = os.environ.get("AIA_TEST_DATABASE_URL")
    if not preset:
        pytest.skip("AIA_TEST_DATABASE_URL is required; no database fallback")
    base = make_url(preset).set(drivername="postgresql+psycopg")
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    name = "tb178_" + uuid.uuid4().hex
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    engine = create_engine(base.set(database=name))
    try:
        with engine.begin() as conn:
            conn.execute(text("CREATE EXTENSION btree_gist"))
            conn.execute(text("CREATE EXTENSION pg_trgm"))
            for schema in SCHEMAS:
                conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            metadata.create_all(conn)
            conn.execute(
                insert(securities).values(
                    code=CODE,
                    name="虚构证券",
                    type="stock",
                    exchange="SH",
                    board="star",
                    listing_status="listed",
                )
            )
            day = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date()
            conn.execute(insert(trading_calendar).values(date=day, is_open=True))
        yield engine
    finally:
        engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        admin.dispose()


@pytest.fixture
def world(database: Engine) -> Iterator[SimpleNamespace]:
    owner, other = uuid.uuid4(), uuid.uuid4()
    with database.begin() as conn:
        for uid in (owner, other):
            conn.execute(
                insert(users).values(
                    id=uid,
                    username="tb178_" + uid.hex[:12],
                    password_hash=uuid.uuid4().hex,
                    role="user",
                    status="approved",
                )
            )
    business = SimpleNamespace(
        **{
            key: model.model_validate(yaml.safe_load((ROOT / f"config/{key}.yaml").read_text()))
            for key, model in (("market_rules", MarketRulesConfig), ("realtime", RealtimeConfig))
        }
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_engine] = lambda: database
    app.dependency_overrides[current_auth] = lambda: SimpleNamespace(user_id=owner)
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(business=business)
    with TestClient(app) as client:
        yield SimpleNamespace(engine=database, client=client, owner=owner, other=other)


def add(world: SimpleNamespace, number: int, **overrides: Any) -> str:
    identifier, rule = uuid.UUID(int=number), uuid.uuid4()
    happened = {
        "origin": "holding_event",
        "name": "虚构证券",
        "title": "合成事件已记录",
        "evidence_ids": ["same"],
        "evidence": [
            {
                "id": "same",
                "key": "synthetic.event",
                "value": number,
                "unit": None,
                "provider": "system",
                "endpoint": None,
                "data_as_of": AT.isoformat(),
                "fetched_at": AT.isoformat(),
                "epistemic_type": "fact",
            }
        ],
    }
    happened.update(overrides.pop("happened", {}))
    values = {
        "id": identifier,
        "user_id": world.owner,
        "rule_id": rule,
        "security_code": CODE,
        "severity": "info",
        "status": "new",
        "triggered_at": AT,
        "data_as_of": AT,
        "what_happened": happened,
        "affected": [
            {"plan_id": str(uuid.UUID(int=178)), "plan_version_no": 1, "condition_id": None}
        ],
        **overrides,
    }
    with world.engine.begin() as conn:
        conn.execute(
            insert(alert_rules).values(
                id=rule,
                user_id=values["user_id"],
                origin="holding_event",
                type="custom",
            )
        )
        conn.execute(insert(alerts).values(**values))
    return str(identifier)


def read(world: SimpleNamespace) -> dict[str, Any]:
    response = world.client.get("/api/v1/today")
    assert response.status_code == 200, response.text
    return dict(response.json())


def test_severity_order_fields_and_evidence(world: SimpleNamespace) -> None:
    ids = [
        add(world, 10, severity="important"),
        add(world, 11, severity="attention", status="read", happened={"origin": "user_custom"}),
        add(world, 12),
    ]
    body = read(world)
    items = body["alerts"]["items"]
    assert len(items) == 3
    assert [item["id"] for item in items] == ids
    assert {item["severity"] for item in items} == {"important", "attention", "info"}
    assert body["alerts"]["more"] is False
    assert body["plan_triggers"] == {"items": [], "more": False}
    evidence = {item["id"]: item for item in body["evidence"]}
    assert len(evidence) == 3  # Identical local IDs must not collide across alerts.
    for index, item in enumerate(items, 10):
        assert set(item) == {
            "id",
            "rule_id",
            "origin",
            "severity",
            "status",
            "security_code",
            "name",
            "title",
            "triggered_at",
            "data_as_of",
            "affected_plans",
            "evidence_ids",
        }
        assert item["evidence_ids"]
        assert set(item["evidence_ids"]) <= evidence.keys()
        assert evidence[item["evidence_ids"][0]]["value"] == index
        assert item["affected_plans"] == [
            {
                "plan_id": str(uuid.UUID(int=178)),
                "plan_version_no": 1,
                "condition_id": None,
            }
        ]
        assert item["name"] == "虚构证券"
        assert item["title"] == "合成事件已记录"
    assert "alerts" not in {gap["key"] for gap in body["gaps"]}


def test_sort_limit_and_more(world: SimpleNamespace) -> None:
    expected = []
    for number in range(100, 151):
        severity = ("important", "attention", "info")[number % 3]
        at = AT + dt.timedelta(hours=number % 2)
        identifier = add(world, number, severity=severity, triggered_at=at)
        expected.append(((number % 3, -at.timestamp(), identifier), identifier))
    body = read(world)
    assert body["alerts"]["more"] is True
    assert len(body["alerts"]["items"]) == 50
    assert [item["id"] for item in body["alerts"]["items"]] == [
        identifier for _, identifier in sorted(expected)[:50]
    ]


def test_filters_and_account_name(world: SimpleNamespace) -> None:
    kept = add(world, 200, security_code=None, happened={"name": "应被清空"})
    for number, status in enumerate(("checked", "acted", "dismissed"), 201):
        add(world, number, status=status)
    add(world, 204, happened={"origin": "plan_condition"})
    add(world, 205, what_happened={"title": "缺省为计划条件"})
    add(world, 206, user_id=world.other)
    body = read(world)
    assert [item["id"] for item in body["alerts"]["items"]] == [kept]
    assert body["alerts"]["items"][0]["security_code"] is None
    assert body["alerts"]["items"][0]["name"] is None
    assert "alerts" not in {gap["key"] for gap in body["gaps"]}


def test_missing_evidence_skipped_with_one_gap(world: SimpleNamespace) -> None:
    kept = add(world, 300)
    add(world, 301, happened={"evidence_ids": []})
    add(world, 302, happened={"evidence": []})
    add(world, 303, happened={"evidence_ids": ["same", "missing"]})
    add(world, 304, happened={"evidence": None})
    add(world, 305, happened={"evidence": [{"id": "same"}]})
    body = read(world)
    assert len(body["alerts"]["items"]) == 1
    assert body["alerts"]["more"] is False
    assert [item["id"] for item in body["alerts"]["items"]] == [kept]
    gaps = [gap for gap in body["gaps"] if gap["key"] == "alerts"]
    assert len(gaps) == 1
    assert "证据" in gaps[0]["message"]


@pytest.mark.parametrize("count", [50, 51])
def test_missing_evidence_refills_limit(world: SimpleNamespace, count: int) -> None:
    add(world, 500 + count, severity="important", happened={"evidence": []})
    ids = [add(world, number) for number in range(count * 1000, count * 1000 + count)]
    body = read(world)
    assert [item["id"] for item in body["alerts"]["items"]] == ids[:50]
    assert body["alerts"]["more"] is (count > 50)
    assert len([gap for gap in body["gaps"] if gap["key"] == "alerts"]) == 1


def test_empty_alerts_have_no_gap(world: SimpleNamespace) -> None:
    body = read(world)
    assert body["alerts"] == {"items": [], "more": False}
    assert "alerts" not in {gap["key"] for gap in body["gaps"]}


@pytest.mark.parametrize("fault", ["empty", "unresolved", "account_name"])
def test_today_model_rejects_broken_alert(world: SimpleNamespace, fault: str) -> None:
    add(world, 400 + ("empty", "unresolved", "account_name").index(fault))
    body = read(world)
    assert len(body["alerts"]["items"]) == 1
    item = body["alerts"]["items"][0]
    if fault == "empty":
        item["evidence_ids"] = []
    elif fault == "unresolved":
        body["evidence"] = []
    else:
        item["security_code"] = None
    with pytest.raises(ValidationError):
        Today.model_validate_json(json.dumps(body))

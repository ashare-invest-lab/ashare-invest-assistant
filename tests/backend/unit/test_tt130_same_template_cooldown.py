"""T-T130 RS-02: same-template/same-security three-trading-day cooldown.

The candidate writer is exercised against an isolated temporary PostgreSQL
database. All rows are synthetic and the writer is the only code under test that
decides whether the cooldown applies.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from collections.abc import Iterator

import pytest
import psycopg
from sqlalchemy import create_engine, literal, select, text
from sqlalchemy.engine import make_url

from app.config_files import MarketRulesConfig
from app.api.v1.meta import build_enums
from app.signals import service
from app.signals.models import MarketFacts, SignalInput


pytestmark = [pytest.mark.integration]

_HERE = Path(__file__).resolve()

BJT = dt.timezone(dt.timedelta(hours=8))
BASE_DAY = dt.date(2026, 11, 5)
COOLDOWN_DAYS = (dt.date(2026, 11, 5), dt.date(2026, 11, 6), dt.date(2026, 11, 9))
EXPIRY_DAY = dt.date(2026, 11, 9)
SAME_TEMPLATE_COOLDOWN = "SAME_TEMPLATE_COOLDOWN"
IMPLEMENTATION_PENDING = "T-T130 等 T-B244"


def _base_url() -> str:
    configured = os.environ.get("AIA_TEST_DATABASE_URL") or os.environ.get("TT41_DATABASE_URL")
    if configured:
        return configured
    pytest.skip("AIA_TEST_DATABASE_URL 与 TT41_DATABASE_URL 均未设置，跳过隔离 PostgreSQL 测试")


def _psycopg_url(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://", 1).replace(
        "postgresql+psycopg2://", "postgresql://", 1
    )


@pytest.fixture(scope="module")
def isolated_pg() -> Iterator[SimpleNamespace]:
    """Own a temporary database and always drop it, including migration failures."""
    base = make_url(_base_url())
    admin_url = _psycopg_url(
        base.set(database=base.database or "postgres").render_as_string(hide_password=False)
    )
    name = "tt130_" + uuid.uuid4().hex
    created = False
    try:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f'CREATE DATABASE "{name}"')
        created = True
        target = base.set(database=name).render_as_string(hide_password=False)
        migration_url = _psycopg_url(target)
        env = dict(os.environ)
        env.update({"DATABASE_URL": migration_url, "APP_ENV": "test", "PYTHONDONTWRITEBYTECODE": "1"})
        migration = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"],
            cwd=_HERE.parents[3] / "src" / "backend",
            env=env,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if migration.returncode != 0:
            raise RuntimeError("T-T130 隔离 PostgreSQL 迁移失败")
        engine = create_engine(target, hide_parameters=True)
        try:
            yield SimpleNamespace(engine=engine)
        finally:
            engine.dispose()
    except Exception as exc:
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError("T-T130 隔离 PostgreSQL 不可达或临时库创建失败") from None
    finally:
        if created:
            try:
                with psycopg.connect(admin_url, autocommit=True) as admin:
                    admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
            except Exception as exc:
                raise RuntimeError("T-T130 隔离 PostgreSQL 临时库清理失败") from None


@pytest.fixture
def sql(isolated_pg: SimpleNamespace) -> Any:
    def _sql(statement: str, **params: Any) -> list[Any]:
        with isolated_pg.engine.begin() as conn:
            result = conn.execute(text(statement), params)
            return list(result) if result.returns_rows else []

    return _sql


@pytest.fixture
def synthetic_user(sql: Any) -> SimpleNamespace:
    user_id = uuid.uuid4()
    sql(
        "INSERT INTO app.users(id, username, password_hash, role, status) "
        "VALUES (:id, :username, 'synthetic', 'user', 'approved')",
        id=str(user_id), username="tt130_" + user_id.hex[:16],
    )
    return SimpleNamespace(id=user_id)


def _rules() -> MarketRulesConfig:
    import yaml

    root = _HERE.parents[3]
    raw = yaml.safe_load((root / "config" / "market_rules.yaml").read_text(encoding="utf-8"))
    return MarketRulesConfig.model_validate(raw)


def _signal_input(snapshot_id: uuid.UUID, created_at: dt.datetime, security_code: str) -> SignalInput:
    evidence_id = "synthetic-evidence"
    return SignalInput.model_validate(
        {
            "security_code": security_code,
            "proposed_action": "buy",
            "t_leg": None,
            "score": 80,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": [
                {
                    "rule_id": "R1",
                    "snippet_id": None,
                    "snippet_version": None,
                    "role": "entry",
                    "dimension": "technical",
                    "passed": True,
                    "value": None,
                    "threshold": "f.close_qfq > 0",
                    "evidence_ids": [evidence_id],
                }
            ],
            "evidence": [
                {
                    "id": evidence_id,
                    "key": "f.close_qfq",
                    "value": 12.5,
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "data_as_of": created_at,
                    "fetched_at": created_at,
                    "epistemic_type": "fact",
                }
            ],
            "counter_evidence": [
                {"text": "synthetic counter evidence", "expr": None, "evidence_ids": [evidence_id]}
            ],
            "invalidation": [
                {"text": "synthetic invalidation", "expr": None, "evidence_ids": [evidence_id]}
            ],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "snapshot_id": str(snapshot_id),
            "feature_set_version": "synthetic",
            "created_at": created_at,
            "data_status": "fresh",
            "data_as_of": created_at,
            "gaps": [],
        }
    )


def _seed_world(
    sql_call: Any,
    user_id: str,
    *,
    target_security: str = "600001.SH",
    target_content_security: str | None = None,
    target_day: dt.date = COOLDOWN_DAYS[0],
    base_at: dt.datetime | None = None,
    target_at: dt.datetime | None = None,
) -> SimpleNamespace:
    """Create only synthetic owner/template/input rows in the isolated database."""
    account_id = uuid.uuid4()
    strategy_id = uuid.uuid4()
    version_id = uuid.uuid4()
    instance_id = uuid.uuid4()
    snapshot_id = uuid.uuid4()
    prior_snapshot_id = uuid.uuid4()
    prior_id = uuid.uuid4()
    base_at = base_at or dt.datetime.combine(BASE_DAY, dt.time(10, 0), BJT)
    target_at = target_at or dt.datetime.combine(target_day, dt.time(10, 0), BJT)
    target_content_security = target_content_security or target_security
    config = {
        "universe": {"pool": "持仓 ∪ 自选", "security_types": ["stock"], "boards": {"main": True}},
        "spec": {
            "rules": [
                {"id": "R1", "role": "entry", "dimension": "technical", "expr": "f.close_qfq > 0"}
            ]
        },
    }
    sql_call(
        "INSERT INTO app.accounts(id, user_id, name) VALUES (:id, :uid, :name)",
        id=str(account_id), uid=user_id, name="T-T130 synthetic account",
    )
    sql_call(
        "INSERT INTO app.strategies(id, key, name, status, owner_user_id) "
        "VALUES (:id, :key, :name, 'active', NULL)",
        id=str(strategy_id), key=f"tt130-template-{uuid.uuid4().hex[:8]}",
        name="T-T130 synthetic template",
    )
    sql_call(
        "INSERT INTO app.strategy_versions(id, strategy_id, version_no, config, config_hash, "
        "lifecycle, published_at) VALUES (:id, :sid, 1, CAST(:config AS jsonb), :hash, 'published', :at)",
        id=str(version_id), sid=str(strategy_id), config=json.dumps(config, ensure_ascii=False),
        hash=hashlib.sha256(str(config).encode()).hexdigest(), at=base_at,
    )
    sql_call(
        "INSERT INTO app.strategy_instances(id, user_id, strategy_version_id, scope, account_id, "
        "security_code, horizon, status, origin) VALUES (:id, :uid, :vid, 'account', :aid, NULL, 'short', 'active', 'user')",
        id=str(instance_id), uid=user_id, vid=str(version_id), aid=str(account_id),
    )
    for code in {target_security, "600002.SH"}:
        sql_call(
            "INSERT INTO market.securities(code, type, name, exchange, board, listing_status) "
            "VALUES (:code, 'stock', :name, 'SH', 'main', 'listed') "
            "ON CONFLICT (code) DO NOTHING",
            code=code, name=f"Synthetic {code}",
        )
    calendar_days = {
        BASE_DAY,
        *COOLDOWN_DAYS,
        EXPIRY_DAY,
        dt.date(2026, 11, 2),
        dt.date(2026, 11, 3),
        dt.date(2026, 11, 4),
        dt.date(2026, 11, 7),
        dt.date(2026, 11, 8),
        dt.date(2026, 11, 10),
        dt.date(2026, 11, 11),
        dt.date(2026, 11, 12),
    }
    for day in sorted(calendar_days):
        sql_call(
            "INSERT INTO market.trading_calendar(date, is_open) VALUES (:day, :open) "
            "ON CONFLICT (date) DO UPDATE SET is_open = EXCLUDED.is_open",
            day=day, open=day not in {dt.date(2026, 11, 7), dt.date(2026, 11, 8)},
        )
    prior_content = _signal_input(prior_snapshot_id, base_at, target_security)
    prior_facts = MarketFacts(
        price=Decimal("12.5"), required_cash=Decimal("1250"), is_suspended=False,
        list_days=600, limit_locked_up=False, limit_locked_down=False,
    )
    target_content = _signal_input(snapshot_id, target_at, target_content_security)
    target_facts = prior_facts
    for sid, created, content, facts in (
        (prior_snapshot_id, base_at, prior_content, prior_facts),
        (snapshot_id, target_at, target_content, target_facts),
    ):
        items = {
            "signal_input": content.model_dump(mode="json"),
            "market_facts": facts.model_dump(mode="json"),
            "data_status_block": {
                "data_status": content.data_status.value,
                "data_as_of": content.data_as_of.isoformat(),
                "gaps": [],
            },
        }
        sql_call(
            "INSERT INTO app.data_snapshots(id, created_at, purpose, items, hash, user_id) "
            "VALUES (:id, :created, 'candidate', CAST(:items AS jsonb), :hash, :uid)",
            id=str(sid), created=created - dt.timedelta(minutes=1), items=json.dumps(items, ensure_ascii=False),
            hash=hashlib.sha256(str(items).encode()).hexdigest(), uid=user_id,
        )
    prior_body = prior_content.model_dump(mode="json")
    prior_body.pop("snapshot_id")
    prior_body.pop("created_at")
    prior_body.update(
        {
            "id": str(prior_id),
            "user_id": user_id,
            "instance_id": str(instance_id),
            "strategy_version_id": str(version_id),
            "snapshot_id": str(prior_snapshot_id),
            "horizon": "short",
            "confidence_level": "high",
            "confidence": "0.8",
            "rule_refs": prior_body["rule_refs"],
            "evidence": prior_body["evidence"],
            "counter_evidence": prior_body["counter_evidence"],
            "invalidation": prior_body["invalidation"],
            "model_refs": [],
            "gate_results": [],
            "risk_flags": [],
            "crowding_flag": False,
            "state": "open",
            "created_at": base_at,
            "state_changed_at": base_at,
            "cooldown_key": f"prior-{uuid.uuid4()}",
        }
    )
    columns = [
        "id", "user_id", "instance_id", "strategy_version_id", "security_code", "horizon",
        "proposed_action", "t_leg", "score", "confidence_level", "confidence", "stops", "rule_refs",
        "evidence", "counter_evidence", "invalidation", "model_refs", "gate_results", "risk_flags",
        "crowding_flag", "feature_set_version", "snapshot_id", "created_at", "state", "state_changed_at",
        "cooldown_key",
    ]
    values = {key: prior_body.get(key) for key in columns}
    values.update(
        {
            "stops": json.dumps(values["stops"], ensure_ascii=False),
            "rule_refs": json.dumps(values["rule_refs"], ensure_ascii=False),
            "evidence": json.dumps(values["evidence"], ensure_ascii=False),
            "counter_evidence": json.dumps(values["counter_evidence"], ensure_ascii=False),
            "invalidation": json.dumps(values["invalidation"], ensure_ascii=False),
            "model_refs": json.dumps(values["model_refs"], ensure_ascii=False),
            "gate_results": json.dumps(values["gate_results"], ensure_ascii=False),
            "risk_flags": json.dumps(values["risk_flags"], ensure_ascii=False),
        }
    )
    sql_call(
        f"INSERT INTO app.candidate_signals({', '.join(columns)}) "
        f"VALUES ({', '.join('CAST(:' + c + ' AS jsonb)' if c in {'stops', 'rule_refs', 'evidence', 'counter_evidence', 'invalidation', 'model_refs', 'gate_results', 'risk_flags'} else ':' + c for c in columns)})",
        **values,
    )
    return SimpleNamespace(
        account_id=account_id,
        user_id=user_id,
        instance_id=instance_id,
        version_id=version_id,
        snapshot_id=snapshot_id,
        target_content=target_content,
        target_facts=target_facts,
        rules=_rules(),
        target_at=target_at,
        prior_id=prior_id,
    )


def _writer(monkeypatch: pytest.MonkeyPatch, world: SimpleNamespace, engine: Any) -> dict[str, Any]:
    portfolio = SimpleNamespace(positions={}, cash=Decimal("10000"))
    monkeypatch.setattr("app.api.v1.portfolio._account", lambda _conn, _id, _day: portfolio)
    monkeypatch.setattr(service, "lot_spec", lambda *_args, **_kwargs: SimpleNamespace(min_buy=100))
    monkeypatch.setattr(service, "board_in_universe", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "screen_membership", lambda **_kwargs: None)
    monkeypatch.setattr(service, "calendar_state", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(service, "assess", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        service,
        "live_snapshots",
        lambda _id: select(
            literal(None).label("cash_available"), literal(0).label("version_no")
        ),
    )
    with engine.begin() as conn:
        return service.write_candidate(
            conn,
            user_id=uuid.UUID(str(world.user_id)),
            instance_id=world.instance_id,
            content=world.target_content,
            facts=world.target_facts,
            market_rules=world.rules,
        )


def _switch_to_different_template(sql_call: Any, world: SimpleNamespace, user_id: str) -> None:
    other_strategy = uuid.uuid4()
    other_version = uuid.uuid4()
    other_instance = uuid.uuid4()
    config = {
        "universe": {"pool": "持仓 ∪ 自选", "security_types": ["stock"], "boards": {"main": True}},
        "spec": {
            "rules": [
                {"id": "R1", "role": "entry", "dimension": "technical", "expr": "f.close_qfq > 0"}
            ]
        },
    }
    sql_call(
        "INSERT INTO app.strategies(id, key, name, status, owner_user_id) "
        "VALUES (:id, :key, :name, 'active', NULL)",
        id=str(other_strategy), key=f"tt130-other-{uuid.uuid4().hex[:8]}", name="T-T130 other template",
    )
    sql_call(
        "INSERT INTO app.strategy_versions(id, strategy_id, version_no, config, config_hash, "
        "lifecycle, published_at) VALUES (:id, :sid, 1, CAST(:config AS jsonb), :hash, 'published', :at)",
        id=str(other_version), sid=str(other_strategy), config=json.dumps(config, ensure_ascii=False),
        hash=hashlib.sha256(("other" + str(other_strategy)).encode()).hexdigest(),
        at=world.target_at,
    )
    sql_call(
        "INSERT INTO app.strategy_instances(id, user_id, strategy_version_id, scope, account_id, "
        "security_code, horizon, status, origin) VALUES (:id, :uid, :vid, 'account', :aid, NULL, 'short', 'active', 'user')",
        id=str(other_instance), uid=user_id, vid=str(other_version), aid=str(world.account_id),
    )
    world.instance_id = other_instance
    world.version_id = other_version


@pytest.mark.parametrize("target_day", COOLDOWN_DAYS)
def test_same_template_cooldown_blocks_trading_days(
    target_day: dt.date,
    monkeypatch: pytest.MonkeyPatch, isolated_pg: SimpleNamespace, synthetic_user: SimpleNamespace,
    sql: Any,
) -> None:
    """RS-02 ①: each of trading days 1–3 is blocked, including a weekend/holiday gap."""
    world = _seed_world(sql, str(synthetic_user.id), target_day=target_day)
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "blocked"
    rows = sql(
        "SELECT code FROM app.non_executable_reasons WHERE user_id=:uid AND signal_id=:sid",
        uid=str(synthetic_user.id), sid=result["id"],
    )
    assert [row[0] for row in rows] == [SAME_TEMPLATE_COOLDOWN]


def test_same_template_cooldown_releases_after_third_trading_day(
    monkeypatch: pytest.MonkeyPatch, isolated_pg: SimpleNamespace, synthetic_user: SimpleNamespace,
    sql: Any,
) -> None:
    """RS-02 ②: the first candidate after the half-open window is executable."""
    world = _seed_world(
        sql,
        str(synthetic_user.id),
        target_day=EXPIRY_DAY,
        target_at=dt.datetime.combine(EXPIRY_DAY, dt.time(15, 0), BJT),
    )
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "open"
    assert sql(
        "SELECT count(*) FROM app.non_executable_reasons WHERE user_id=:uid AND signal_id=:sid",
        uid=str(synthetic_user.id), sid=result["id"],
    )[0][0] == 0


def _assert_blocked_until(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg: SimpleNamespace,
    synthetic_user: SimpleNamespace,
    sql: Any,
    world: SimpleNamespace,
    expected_at: dt.datetime,
) -> None:
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "blocked"
    rows = sql(
        "SELECT release_condition FROM app.non_executable_reasons "
        "WHERE user_id=:uid AND signal_id=:sid AND code=:code",
        uid=str(synthetic_user.id), sid=result["id"], code=SAME_TEMPLATE_COOLDOWN,
    )
    assert len(rows) == 1
    assert rows[0][0]["at"] == expected_at.isoformat()


def test_same_template_cooldown_after_hours_starts_next_open_day(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg: SimpleNamespace,
    synthetic_user: SimpleNamespace,
    sql: Any,
    request: pytest.FixtureRequest,
) -> None:
    """盘后 2026-11-02 16:00 从下一开市日起算，至 11-05 15:00 到期。"""
    request.applymarker(
        pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason="转绿条件：盘后 2026-11-02 16:00 必须从 11-03 起算并于 11-05 15:00 到期，单号 T-B244",
        )
    )
    world = _seed_world(
        sql,
        str(synthetic_user.id),
        target_day=dt.date(2026, 11, 3),
        base_at=dt.datetime(2026, 11, 2, 16, 0, tzinfo=BJT),
        target_at=dt.datetime(2026, 11, 3, 10, 0, tzinfo=BJT),
    )
    _assert_blocked_until(
        monkeypatch,
        isolated_pg,
        synthetic_user,
        sql,
        world,
        dt.datetime(2026, 11, 5, 15, 0, tzinfo=BJT),
    )


def test_same_template_cooldown_intraday_counts_write_day(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg: SimpleNamespace,
    synthetic_user: SimpleNamespace,
    sql: Any,
) -> None:
    """盘中 2026-11-02 14:00 当天为第 1 日，至 11-04 15:00 到期。"""
    world = _seed_world(
        sql,
        str(synthetic_user.id),
        target_day=dt.date(2026, 11, 3),
        base_at=dt.datetime(2026, 11, 2, 14, 0, tzinfo=BJT),
        target_at=dt.datetime(2026, 11, 3, 10, 0, tzinfo=BJT),
    )
    _assert_blocked_until(
        monkeypatch,
        isolated_pg,
        synthetic_user,
        sql,
        world,
        dt.datetime(2026, 11, 4, 15, 0, tzinfo=BJT),
    )


def test_same_template_cooldown_non_trading_day_starts_next_open_day(
    monkeypatch: pytest.MonkeyPatch,
    isolated_pg: SimpleNamespace,
    synthetic_user: SimpleNamespace,
    sql: Any,
) -> None:
    """非交易日 2026-11-07 写入，从 11-09 起算，至 11-11 15:00 到期。"""
    world = _seed_world(
        sql,
        str(synthetic_user.id),
        target_day=dt.date(2026, 11, 9),
        base_at=dt.datetime(2026, 11, 7, 10, 0, tzinfo=BJT),
        target_at=dt.datetime(2026, 11, 9, 10, 0, tzinfo=BJT),
    )
    _assert_blocked_until(
        monkeypatch,
        isolated_pg,
        synthetic_user,
        sql,
        world,
        dt.datetime(2026, 11, 11, 15, 0, tzinfo=BJT),
    )


def test_same_template_cooldown_release_condition_is_exact(
    monkeypatch: pytest.MonkeyPatch, isolated_pg: SimpleNamespace, synthetic_user: SimpleNamespace,
    sql: Any, request: pytest.FixtureRequest,
) -> None:
    """RS-02 ③: the reason projection carries the exact machine release condition."""
    request.applymarker(
        pytest.mark.xfail(
            strict=True,
            raises=AssertionError,
            reason="转绿条件：release_condition 字段须为精确约定值，单号 T-B244",
        )
    )
    world = _seed_world(sql, str(synthetic_user.id))
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "blocked"
    rows = sql(
        "SELECT release_condition FROM app.non_executable_reasons "
        "WHERE user_id=:uid AND signal_id=:sid AND code=:code",
        uid=str(synthetic_user.id), sid=result["id"], code=SAME_TEMPLATE_COOLDOWN,
    )
    assert len(rows) == 1
    assert rows[0][0] == {
        "kind": "time",
        "at": "2026-11-09T15:00:00+08:00",
        "event": None,
        "action": None,
        "check_on": ["schedule"],
        "human_text": "同模板同证券冷却至到期交易日15:00（北京时间）",
        "machine_checkable": True,
    }


def test_reason_code_table_has_23_codes_and_same_template_code(
    request: pytest.FixtureRequest,
) -> None:
    """RS-02 ④: the public reason-code table has exactly 23 entries."""
    codes = [item.model_dump(mode="json") for item in build_enums().reason_codes]
    assert len(codes) == 23
    assert SAME_TEMPLATE_COOLDOWN in {item["code"] for item in codes}


def test_different_template_does_not_trigger_cooldown(
    monkeypatch: pytest.MonkeyPatch, isolated_pg: SimpleNamespace, synthetic_user: SimpleNamespace, sql: Any,
) -> None:
    """RS-02反例: same security with another template version remains executable."""
    world = _seed_world(sql, str(synthetic_user.id))
    _switch_to_different_template(sql, world, str(synthetic_user.id))
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "open"


def test_different_security_does_not_trigger_cooldown(
    monkeypatch: pytest.MonkeyPatch, isolated_pg: SimpleNamespace, synthetic_user: SimpleNamespace, sql: Any,
) -> None:
    """RS-02反例: same template with another security remains executable."""
    world = _seed_world(sql, str(synthetic_user.id), target_content_security="600002.SH")
    result = _writer(monkeypatch, world, isolated_pg.engine)
    assert result["diagnostic"] == "open"

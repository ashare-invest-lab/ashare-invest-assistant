# fmt: off
"""T-T87 / PR162 PN-06 §12：39个原入口逐一接线；草案未合，真实失败不隐藏。"""

from __future__ import annotations

import ast
import datetime as dt
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import uuid
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from app.aggregates.calendar import market_clock, seed_calendar
from app.aggregates.service import today
from app.api.v1 import aggregates as aggregates_api
from app.api.v1 import daily_reports as reports_api
from app.auth import deps
from app.auth.deps import AuthContext
from app.cli import daily_bars_backfill, tb143_export, tdx_import
from app.common.errors import install_exception_handlers
from app.config import Settings, load_yaml_dir
from app.config_files import BusinessConfig
from app.db.tables.accounts import accounts
from app.db.tables.daily_bars import outbox
from app.db.tables.market import daily_bars, securities, trading_calendar
from app.db.tables.realtime import (
    daily_reports,
    pipeline_runs,
    suggestion_tracking,
    suggestions,
)
from app.db.tables.research import watchlist_items
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import (
    engine_policies,
    feature_catalog,
    strategies,
    strategy_card_versions,
    strategy_cards,
    strategy_instances,
    strategy_versions,
)
from app.db.tables.users import users
from app.features.evaluation import evaluate_snapshot
from app.features.pipeline import prepare
from app.ingest import daily_bars_consumer as consumer
from app.ingest.daily_bars import DailyBarsGrant
from app.ingest.tdx_local import DAY_LAYOUT
from app.marketdata import daily_bars_outbox
from app.marketdata.daily_bars import (
    FakeDailyBarsSource,
    daily_bars_fetch_task,
    fetch_and_record,
)
from app.marketdata.daily_snapshot import build_owned_snapshot, daily_bars_ready
from app.reference_files import CalendarReference
from app.reports.service import build
from app.risk.rc1 import Facts, assess
from app.schemas.enums import GapReason
from app.signals.models import Gap, Stops
from app.suggestions.models import SuggestionInput
from app.suggestions.risk import RiskResult, apply_risk
from app.suggestions.service import archive
from app.tracking import worker as tracking_worker
from app.tracking.engine import evaluate
from app.tracking.service import run_one
from app.tracking.worker import tracking_task
from app.workers import jobs
from app.workers.assembly import archive_conclusions, conclusion
from app.workers.daily import (
    ANALYZE,
    REPORT,
    analysis_task,
    analyze,
    phase,
    recover_task,
    report_task,
)
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, insert, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

ROOT = Path(__file__).resolve().parents[3]
BACKEND = ROOT / "src/backend"
D0, D1, D2, D3 = (dt.date(2030, 12, 30) + dt.timedelta(days=n) for n in range(4))
DAYS = (D0, D1, D2, D3)
CODE_A, CODE_B = "699001.SH", "920999.BJ"
BJ = dt.timezone(dt.timedelta(hours=8))
BUSINESS = BusinessConfig.model_validate(load_yaml_dir(ROOT / "config"))

def _at(day: dt.date, hour=17, minute=30) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), BJ)


F_SETTINGS = "_env_file database_url app_env daily_bars_source config_dir"
F_RUN = "id kind step run_date status started_at finished_at stats"
F_USER = "id username display_name password_hash role status"
F_BAR = "code trade_date adj_type open high low close volume amount source fetched_at is_suspended"

def _map(fields, values):
    return dict(zip(fields.split(), values, strict=True))

def _settings(url: str, source="fake") -> Settings:
    values = [None, url, 'test', source, ROOT / 'config']; return Settings(**_map(F_SETTINGS, values))

def _cfg(conn):
    return _settings(str(conn.engine.url))

def _where(table, filters):
    return [getattr(table.c, key) == value for key, value in filters.items()]

def _select(conn, target, *where, **filters):
    table = target if hasattr(target, 'c') else target.table; return conn.execute(select(target).where(*where, *_where(table, filters)))

def _one(conn, table, *where, **filters):
    return _select(conn, table, *where, **filters).one()

def _scalar(conn, column, *where, **filters):
    return _select(conn, column, *where, **filters).scalar_one()

def _scalars(conn, column, *where, **filters):
    return _select(conn, column, *where, **filters).scalars().all()

def _count(conn, table, *where, **filters):
    statement = select(func.count()).select_from(table); return conn.execute(statement.where(*where, *_where(table, filters))).scalar_one()

def _put(conn, table, fields, *values):
    conn.execute(insert(table).values(_map(fields, values)))

def _put_pg(conn, table, fields, *values):
    statement = pg_insert(table).values(_map(fields, values)); conn.execute(statement.on_conflict_do_nothing())

@pytest.fixture(scope="session")
def pn06_engine(pg_url: str):
    cfg = Config(str(BACKEND / 'alembic.ini')); cfg.cmd_opts = SimpleNamespace(x=['url=' + pg_url]); command.upgrade(cfg, 'head'); engine = create_engine(pg_url); yield engine; engine.dispose()


def _calendar_dates(connection):
    return {row.date for row in connection.execute(select(trading_calendar.c.date))}


def _remove_owned_calendar_rows(connection, baseline):
    owned = _calendar_dates(connection) - baseline
    if owned:
        connection.execute(delete(trading_calendar).where(trading_calendar.c.date.in_(owned)))


@contextmanager
def _pn06_calendar_isolation(engine):
    with engine.begin() as connection:
        baseline = _calendar_dates(connection)
    try:
        yield
    finally:
        with engine.begin() as connection:
            _remove_owned_calendar_rows(connection, baseline)


@pytest.fixture(autouse=True)
def pn06_clean(pn06_engine):
    # 只清本组新增的日历行和可变行情；预存行与其他测试资产保持不变。
    with _pn06_calendar_isolation(pn06_engine):
        with pn06_engine.begin() as connection:
            connection.execute(daily_bars.delete())
        yield
        with pn06_engine.begin() as connection:
            connection.execute(daily_bars.delete())


def test_pn06_calendar_isolation_preserves_preexisting_and_cleans_exception(pn06_engine):
    preserved = dt.date(2030, 6, 11)
    normal = dt.date(2099, 1, 1)
    exceptional = dt.date(2099, 1, 2)
    with pn06_engine.begin() as connection:
        connection.execute(
            pg_insert(trading_calendar)
            .values(date=preserved, is_open=False)
            .on_conflict_do_nothing()
        )
        original = connection.execute(
            select(trading_calendar.c.date, trading_calendar.c.is_open).where(
                trading_calendar.c.date == preserved
            )
        ).one()

    with _pn06_calendar_isolation(pn06_engine):
        with pn06_engine.begin() as connection:
            connection.execute(insert(trading_calendar).values(date=normal, is_open=True))
    with pn06_engine.begin() as connection:
        assert connection.execute(
            select(trading_calendar.c.date, trading_calendar.c.is_open).where(
                trading_calendar.c.date == preserved
            )
        ).one() == original
        assert connection.execute(
            select(trading_calendar.c.date).where(trading_calendar.c.date == normal)
        ).first() is None

    with pytest.raises(RuntimeError, match="synthetic cleanup probe"):
        with _pn06_calendar_isolation(pn06_engine):
            with pn06_engine.begin() as connection:
                connection.execute(
                    insert(trading_calendar).values(date=exceptional, is_open=True)
                )
            raise RuntimeError("synthetic cleanup probe")
    with pn06_engine.begin() as connection:
        assert connection.execute(
            select(trading_calendar.c.date, trading_calendar.c.is_open).where(
                trading_calendar.c.date == preserved
            )
        ).one() == original
        assert connection.execute(
            select(trading_calendar.c.date).where(trading_calendar.c.date == exceptional)
        ).first() is None


@pytest.fixture(autouse=True)
def pn06_no_external(monkeypatch):
    original = socket.socket.connect

    def guarded(sock, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and (
            host in {"127.0.0.1", "localhost", "::1"} or host.startswith("/")
        ):
            return original(sock, address)
        pytest.fail(f"PN-06禁止外呼：{host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded)
    from app.ingest import egress

    monkeypatch.setattr(egress, 'mairui_get', lambda *a, **k: pytest.fail('禁止真调麦蕊'))

@pytest.fixture
def conn(pn06_engine):
    with pn06_engine.connect() as connection:
        tx = connection.begin(); yield connection; tx.rollback()

@pytest.fixture
def pg_conn(pg_url):
    # 共享pg_url供SQLAlchemy使用；原psycopg入口只接受libpq DSN。
    with psycopg.connect(
        pg_url.replace("postgresql+psycopg://", "postgresql://")
    ) as connection:
        yield connection; connection.rollback()

def _seed(conn, end=D3, opens=(D0, D2, D3)):
    days = [D0 + dt.timedelta(days=i) for i in range((end - D0).days + 1)]
    values = [D0.isoformat(), end.isoformat(), [d.isoformat() for d in opens], "fake"]
    fields = "coverage_start coverage_end open_days source"
    seed_calendar(conn, CalendarReference(**_map(fields, values)))
    count = _count(conn, trading_calendar, trading_calendar.c.date.between(D0, end))
    assert count == len(days)

def _seed_backfill_window(conn, years=1):
    start = D0.replace(year=D0.year - years); rows = [{'date': start + dt.timedelta(days=i), 'is_open': True} for i in range((D0 - start).days)]; conn.execute(pg_insert(trading_calendar).values(rows).on_conflict_do_nothing())

def _bar(code=CODE_A, day=D0, close="10", source="fake", seen=None):
    values = [code, day, 'none', *[close] * 4, 100, 1000]; values += [source, seen or _at(day, 17, 15), False]; return _map(F_BAR, values)

def _run(conn, owner, day=D2, **options):
    kind = options.pop("kind", "daily")
    status = options.pop("status", "ok")
    window = options.pop("window", None)
    step = options.pop("step", "daily_bars.fetch")
    started = options.pop("started", None)
    assert not options
    stats = {"user_id": str(owner)}
    if window is not None:
        stats["window_trading_days"] = window
    if kind != "daily":
        stats["batch_kind"] = kind
    values = [uuid.uuid4(), 'daily_batch', step, day, status]; values += [started or _at(day, 17, 15), _at(day, 17, 16), stats]; _put(conn, pipeline_runs, F_RUN, *values); return values[0]

def _base(conn, *, strategy=False):
    owners = [uuid.uuid4(), uuid.uuid4()]
    for owner in owners:
        row = [owner, owner.hex, "合成", "not-a-password", "user", "approved"]
        _put(conn, users, F_USER, *row)
        row = [uuid.uuid5(owner, "account"), owner, "纯合成账户"]
        _put(conn, accounts, "id user_id name", *row)
        row = [uuid.uuid4(), owner, CODE_A]
        _put(conn, watchlist_items, "id user_id security_code", *row)
    for code, board in ((CODE_A, "main"), (CODE_B, "bse")):
        row = [code, 'stock', '合成' + code, code[-2:], board, 'listed']; _put_pg(conn, securities, 'code type name exchange board listing_status', *row)
    _seed(conn)
    for day, close in ((D0, "10"), (D2, "20")):
        conn.execute(insert(daily_bars).values(**_bar(day=day, close=close)))
    if strategy:
        _strategy(conn, owners[0])
    return owners

def _strategy(conn, owner):
    card, cv, template, version, instance = [uuid.uuid4() for _ in range(5)]; rules = []
    for key, role, expr in (
        ("E", "entry", "f.close_qfq > 0"),
        ("X", "exit", "f.close_qfq < 0"),
        ("C", "counter", "f.close_qfq < 0"),
        ("I", "invalidation", "f.close_qfq < 0"),
    ):
        row = [key, 'technical', role, expr, 'daily_close', 1]; rules.append(_map('id dimension role expr eval_time weight', row))
    action = _map('entry_all_core_pass held_hold exit else', ['buy', 'hold', 'sell', 'wait'])
    spec_fields = 'params_schema rules action_map dimension_view_thresholds stops valid_until'
    row = [{}, rules, action, {"bullish": 0.67, "bearish": 0.33}]
    row += [{'stop_loss': None, 'take_profit': None, 'time_stop_days': 5}, {'trading_days': 40}]
    spec = _map(spec_fields, row)
    universe = _map('pool boards security_types', ['持仓 ∪ 自选', {'star': True, 'chinext': True}, ['stock']])
    fields = _map("mount_policy universe", ["user", universe])
    row = [card, "fake_" + card.hex, "纯合成", "user", owner]
    _put(conn, strategy_cards, "id key title source_kind owner_user_id", *row)
    row = [cv, card, 1, fields]
    _put(conn, strategy_card_versions, "id card_id version_no fields", *row)
    row = [template, "fake_" + template.hex, "纯合成", owner, ["swing"]]
    _put(conn, strategies, "id key name owner_user_id horizons", *row)
    row = [version, template, cv, 1, spec, version.hex, version.hex, "published"]
    fields = "id strategy_id card_version_id version_no config config_hash param_hash lifecycle"
    _put(conn, strategy_versions, fields, *row)
    row = [instance, owner, version, "security", CODE_A]
    row += [uuid.uuid5(owner, "account"), "active", "user", "swing"]
    fields = "id user_id strategy_version_id scope security_code account_id status origin horizon"
    _put(conn, strategy_instances, fields, *row)
    for key in ("f.close_qfq", "f.open_qfq", "f.high_qfq", "f.low_qfq"):
        row = [key, 'CNY/share', 'verified_live', {'synthetic': True}]; _put_pg(conn, feature_catalog, 'feature_key unit status source', *row)
    from app.engine_policies import load, seed

    seed(conn, load(ROOT / "config"))

def _visible_bar(day):
    extra = _map('trade_date first_seen_at is_final', [day.isoformat(), _at(day, 17, 15).isoformat(), True]); return {**_bar(day=day, close='10' if day == D0 else '20'), **extra}

def _instrument(code=CODE_A):
    fields = "security_code adjust currency board price_unit volume_unit amount_unit gaps bars"
    values = [code, "none", "CNY", "main", "CNY/share", "share", "CNY"]
    values += [[], [_visible_bar(day) for day in (D0, D2)]]
    return _map(fields, values)

def _prepare(*, factors=(), as_of=None, extra=None):
    instrument = _instrument(); days = [D0, D2]
    if extra:
        instrument["bars"].insert(0, _visible_bar(extra)); days.insert(0, extra)
    values = [as_of or _at(D2), list(factors), {}]; return prepare(instrument, [day.isoformat() for day in days], **_map('as_of factors registry', values))

def _registry(conn):
    return {r.feature_key: _map('unit status source', [r.unit, r.status, r.source]) for r in conn.execute(select(feature_catalog))}

def _evaluation(conn, owner):
    snap, _ = build_owned_snapshot(conn, owner, D2)
    assert snap is not None
    instance = _one(conn, strategy_instances, user_id=owner)
    version = _one(conn, strategy_versions, id=instance.strategy_version_id)
    card = _scalar(conn, strategy_card_versions.c.fields, id=version.card_version_id)
    values = [owner, snap, CODE_A, _at(D2), card, version.config]
    values += [_registry(conn), BUSINESS.market_rules, []]
    fields = "user_id snapshot_id security_code as_of card spec registry market_rules factors"
    return evaluate_snapshot(conn, **_map(fields, values)), snap

def _conclusion(conn, owner):
    result, snap = _evaluation(conn, owner)
    instance = _one(conn, strategy_instances, user_id=owner)
    version = _one(conn, strategy_versions, id=instance.strategy_version_id)
    strategy = _one(conn, strategies, id=version.strategy_id)
    source = _one(conn, data_snapshots, id=snap)
    policy = _one(conn, engine_policies)
    values = [owner, instance, version, strategy, result]
    values += [_registry(conn), source, policy, _cfg(conn)]
    fields = "owner instance version strategy result registry source policy settings"
    return conclusion(conn, **_map(fields, values)), policy

def _tracking_seed(conn, owner, url):
    _run(conn, owner); analyze(conn, _settings(url), owner, D2, 'user', policy=_one(conn, engine_policies)); return _one(conn, suggestions, user_id=owner)

def _frozen(when):
    class Frozen(dt.datetime):
        @classmethod
        def now(cls, tz=None):
            return when.astimezone(tz) if tz else when.replace(tzinfo=None)

    return Frozen


class _Redis:
    def __init__(self):
        self.rows, self.keys = [], set()

    def set(self, key, *args, nx=False, **kwargs):
        if nx and key in self.keys:
            return False
        self.keys.add(key); return True

    lpush = lambda self, key, value: self.rows.append(json.loads(value)); rpop = lambda self, key: self.rows.pop() if self.rows else None; close = lambda self: None; zrangebyscore = lambda self, *args: []; zrem = lambda self, *args: 0

def test_pn06_entry_ready(conn):
    good, windowed, failed = [uuid.uuid4() for _ in range(3)]
    _run(conn, good)
    _run(conn, good, window=20, started=_at(D2, 18))
    _run(conn, windowed, kind="backfill")
    _run(conn, failed, status="failed", started=_at(D2, 18))
    assert daily_bars_ready(conn, good, D2)[0] is True
    assert daily_bars_ready(conn, windowed, D2)[0] is False
    assert daily_bars_ready(conn, failed, D2)[0] is False

def test_pn06_entry_snapshot(conn):
    owner = _base(conn)[0]
    _put(conn, watchlist_items, "id user_id security_code", uuid.uuid4(), owner, CODE_B)
    conn.execute(insert(daily_bars).values(**_bar(CODE_B, D2, source="tdx_local")))
    snap, issues = build_owned_snapshot(conn, owner, D2)
    body = _scalar(conn, data_snapshots.c["items"], id=snap)
    assert body["instruments"][0]["security_code"] == CODE_A
    assert all(i["security_code"] != CODE_B for i in body["instruments"])
    assert f"daily_bars_missing:{CODE_B}" in issues
    assert "factors" not in body["instruments"][0]
    assert f"adjust_factor_missing:{D2}" in _prepare()["gaps"]

def test_pn06_entry_fetch_task(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        owner = _base(conn)[0]
    settings = _settings(pg_url); assert daily_bars_fetch_task(settings, str(D3), user_id=str(owner)) == 1
    with pn06_engine.connect() as conn:
        assert _scalar(conn, daily_bars.c.source, code=CODE_A, trade_date=D3) == "fake"
    with pytest.raises(ValueError):
        daily_bars_fetch_task(settings, str(D2), user_id=str(owner), batch_kind='backfill')

def test_pn06_entry_fetch_record(conn):
    owner = _base(conn)[0]
    fields = "trade_date user_id window_trading_days fetched_at"
    values = [D3, owner, None, _at(D3, 17, 15)]
    assert fetch_and_record(conn, FakeDailyBarsSource(), **_map(fields, values)) == 1
    run = _one(conn, pipeline_runs, pipeline_runs.c.stats['user_id'].as_string() == str(owner))
    assert run.status == "ok" and run.stats["user_id"] == str(owner)
    assert _scalar(conn, daily_bars.c.source, code=CODE_A, trade_date=D3) == "fake"

def test_pn06_entry_analyze(conn):
    owner = _base(conn, strategy=True)[0]
    result = analyze(conn, _cfg(conn), owner, D2, "user")
    assert "daily_bars_not_ready" in result["issues"]
    _run(conn, owner)
    result = analyze(conn, _cfg(conn), owner, D2, "user")
    assert result["evaluations"] and result["evaluations"][0]["simulation"] is True
    assert any('adjust_factor_missing' in gap for gap in result['evaluations'][0]['gaps'])

def test_pn06_entry_phase(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        owners = _base(conn)
        for owner in owners:
            _run(conn, owner)
        expected = _count(conn, users, status="approved")
    settings = _settings(pg_url); assert phase(settings, ANALYZE, str(D2)) == expected; assert phase(settings, REPORT, str(D2)) == expected
    with pn06_engine.connect() as conn:
        rows = _scalars(conn, pipeline_runs.c.stats, step="tb76.daily_analysis")
    expected_users = {str(x) for x in owners}; assert any(expected_users <= set(row['users']) for row in rows)

def test_pn06_entry_analysis_task(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        owner = _base(conn, strategy=True)[0]
    assert analysis_task(_settings(pg_url), str(D2), str(owner)) == 1
    with pn06_engine.connect() as conn:
        stats = _scalar(conn, pipeline_runs.c.stats, pipeline_runs.c.stats['user_id'].as_string() == str(owner), step='tb76.daily_analysis')
    assert "daily_bars_not_ready" in stats["users"][str(owner)]["issues"]

def test_pn06_entry_report_task(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        owner = _base(conn)[0]
    assert report_task(_settings(pg_url), str(D2), str(owner)) == 1
    with pn06_engine.connect() as conn:
        row = _one(conn, daily_reports, user_id=owner)
    assert row.body["data_status"] == "unavailable" and row.body["gaps"]

def test_pn06_entry_recover_task(pn06_engine, pg_url, monkeypatch):
    with pn06_engine.begin() as conn:
        owner = _base(conn)[0]; _run(conn, owner, step='tb76.intent.daily_analysis', status='running', started=dt.datetime.now(dt.UTC) - dt.timedelta(hours=3))
    cache = _Redis()
    monkeypatch.setattr(jobs, "_redis", lambda settings: cache)
    settings = _settings(pg_url)
    assert recover_task(settings) >= 1 and recover_task(settings) == 0
    assert any(x['task'] == ANALYZE and x['args'].get('user_id') == str(owner) for x in cache.rows)

def test_pn06_entry_prepare():
    values = [D0.isoformat(), "2", _at(D0, 18).isoformat()]
    factor = _map("date value available_at", values)
    result = _prepare(factors=[factor])
    assert result["series"]["f.close_qfq"] == [Decimal(10), Decimal(20)]
    late = {**factor, "available_at": _at(D3).isoformat()}
    assert f"adjust_factor_missing:{D2}" in _prepare(factors=[late])["gaps"]
    assert f"adjust_factor_missing:{D0}" in _prepare()["gaps"]

def test_pn06_entry_evaluate_snapshot(conn):
    owner = _base(conn, strategy=True)[0]; result, snap = _evaluation(conn, owner); assert result['simulation'] is True and result['snapshot_id'] == str(snap); assert any('adjust_factor_missing' in gap for gap in result['gaps'])

def test_pn06_entry_conclusion(conn):
    owner = _base(conn, strategy=True)[0]; produced, _ = _conclusion(conn, owner); assert produced.signal.snapshot_id and produced.signal.proposed_action == 'wait'; assert produced.signal.gaps and produced.state == 'insufficient_data'

def test_pn06_entry_assess():
    stops = Stops(**_map('stop_loss take_profit time_stop_days', [9, None, None])); flags, _evidence, gaps = assess(stops, Facts(), _at(D2)); assert not flags and 'rc1.stops_basis_unknown' in gaps

def test_pn06_entry_apply_risk(conn):
    owner = _base(conn, strategy=True)[0]
    produced, _ = _conclusion(conn, owner)
    signal = produced.signal
    gap = Gap(key="synthetic", reason=GapReason.NO_SOURCE, message="合成缺口")
    values = [signal.stops, [], [], [gap.key], None]
    values += [signal.t_leg, False, None]
    fields = "stops flags evidence gaps quantity_cap t_leg pause_required pause_days"
    risk = RiskResult(**_map(fields, values))
    changed = apply_risk(signal, risk, gaps=[gap])
    assert changed.proposed_action == signal.proposed_action and gap in changed.gaps

def test_pn06_entry_archive_conclusions(conn):
    owner = _base(conn, strategy=True)[0]
    produced, policy = _conclusion(conn, owner)
    first = archive_conclusions(conn, owner, CODE_A, [produced], policy)
    second = archive_conclusions(conn, owner, CODE_A, [produced], policy)
    assert first["suggestion"]["id"] == second["suggestion"]["id"]
    assert _count(conn, suggestions, user_id=owner) == 1

def test_pn06_entry_archive(conn):
    owner = _base(conn, strategy=True)[0]
    produced, policy = _conclusion(conn, owner)
    saved = archive_conclusions(conn, owner, CODE_A, [produced], policy)
    suggestion = _one(conn, suggestions, id=uuid.UUID(str(saved["suggestion"]["id"])))
    snapshot = _one(conn, data_snapshots, id=suggestion.snapshot_id)
    content = SuggestionInput.model_validate(snapshot.items["input"])
    again = archive(conn, user_id=owner, content=content)
    assert again["suggestion"]["id"] == saved["suggestion"]["id"]
    assert _scalar(conn, data_snapshots.c.hash, id=content.snapshot_id) == snapshot.hash

def test_pn06_entry_report_build(conn):
    owner = _base(conn)[0]
    first = build(conn, owner, D2, _at(D2, 18))
    second = build(conn, owner, D2, _at(D2, 18))
    rows = _select(conn, daily_reports, user_id=owner).all()
    assert first == second and len(rows) == 1 and rows[0].body["gaps"]

@pytest.mark.parametrize(
    "own_issues", [None, [], ["synthetic_latest_own"]], ids=["absent", "complete", "partial"],
)
def test_report_build_uses_latest_analysis_for_requesting_owner(conn, own_issues):
    # Virtual owners and run results in the isolated PG transaction.
    owner, other = _base(conn)
    owner_key, other_key = str(owner), str(other)
    foreign_result = {"issues": ["synthetic_other"]}
    rows = [
        (10, "ok", {"users": [owner_key]}),
        (11, "ok", {"users": {owner_key: None}}),
        (12, "failed", {"users": {owner_key: {"issues": ["synthetic_failed"]}}}),
        (13, "partial", {"user_id": other_key, "users": {other_key: foreign_result}}),
    ]
    if own_issues is not None:
        older = {owner_key: {"issues": ["synthetic_old"]}}
        batch = {owner_key: {"issues": own_issues}, other_key: foreign_result}
        rows.extend([
            (5, "ok", {"user_id": owner_key, "users": older}),
            (6, "partial", {"user_id": None, "users": batch}),
        ])
    conn.execute(
        insert(pipeline_runs),
        [
            {
                "kind": "daily_batch",
                "step": "tb76.daily_analysis",
                "run_date": D2,
                "finished_at": _at(D2, 17, minute),
                "status": status,
                "stats": stats,
            }
            for minute, status, stats in rows
        ],
    )

    report_id = build(conn, owner, D2, _at(D2, 18))
    report = _scalar(conn, daily_reports.c.body, id=report_id, user_id=owner)
    pipeline_keys = {gap["key"] for gap in report["gaps"] if gap["key"].startswith("pipeline.")}
    expected = {"pipeline.analysis"} if own_issues is None else {f"pipeline.{issue}" for issue in own_issues}
    assert pipeline_keys == expected


def test_pn06_entry_today_service(conn):
    owner = _base(conn)[0]
    account_id = uuid.uuid5(owner, "account")
    clock = market_clock(conn, _at(D2, 18), BUSINESS.market_rules)
    empty = today(conn, owner, account_id, clock, _at(D2, 18), interval_s=60)
    assert empty.daily_report.status == "not_yet" and empty.gaps
    build(conn, owner, D2, _at(D2, 18))
    ready = today(conn, owner, account_id, clock, _at(D2, 18), interval_s=60)
    assert ready.daily_report.status == "ready" and ready.gaps

def test_pn06_entry_tracking_task(pn06_engine, pg_url, monkeypatch):
    with pn06_engine.begin() as conn:
        owner = _base(conn, strategy=True)[0]; _tracking_seed(conn, owner, pg_url)
    monkeypatch.setattr(tracking_worker, 'dt', SimpleNamespace(datetime=_frozen(_at(D3, 18)), UTC=dt.UTC)); assert tracking_task(_settings(pg_url), str(owner)) >= 1
    with pn06_engine.connect() as conn:
        track = conn.execute(select(suggestion_tracking).join(suggestions, suggestion_tracking.c.suggestion_id == suggestions.c.id).where(suggestions.c.user_id == owner)).first()
    assert track is not None

def test_pn06_entry_run_one(conn):
    owner = _base(conn, strategy=True)[0]; row = _tracking_seed(conn, owner, str(conn.engine.url)); assert isinstance(run_one(conn, owner, row.id, _at(D3, 18)), int); assert _one(conn, suggestion_tracking, suggestion_id=row.id) is not None

def test_pn06_entry_tracking_evaluate():
    from selfchecks.test_p2n03_tracking import close_at, sample

    args = sample()
    args["now"] = close_at(args["created"].date()) + dt.timedelta(days=1)
    pending = evaluate(**args)
    args["now"] = close_at(max(args["calendar"]))
    args["benchmark"] = {"bars": []}
    missing = evaluate(**args)
    assert pending.state == "pending" and missing.benchmark_return_pct is None
    assert "benchmark_prices" in {x.key for x in missing.gaps}
    assert missing.return_pct is not None and missing.direction_correct is None

def _client(engine, monkeypatch, owner, when=None):
    when = when or _at(D2, 18)
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(aggregates_api.router, prefix="/api/v1")
    app.include_router(reports_api.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_settings] = lambda: _settings(str(engine.url))
    app.dependency_overrides[deps.current_auth] = lambda: AuthContext(user=SimpleNamespace(id=owner), session=None)
    monkeypatch.setattr(aggregates_api, 'dt', SimpleNamespace(datetime=_frozen(when), UTC=dt.UTC))
    return TestClient(app, raise_server_exceptions=False)

def test_pn06_entry_today_http(pn06_engine, monkeypatch):
    with pn06_engine.begin() as conn:
        owner, stranger = _base(conn); build(conn, owner, D2, _at(D2, 18))
    with _client(pn06_engine, monkeypatch, owner) as client:
        body = client.get('/api/v1/today').json(); assert body['daily_report']['status'] == 'ready' and body['gaps']
    with _client(pn06_engine, monkeypatch, stranger) as client:
        assert client.get("/api/v1/today").json()["daily_report"]["status"] == "not_yet"

def test_pn06_entry_reports_list_http(pn06_engine, monkeypatch):
    with pn06_engine.begin() as conn:
        owner, stranger = _base(conn); build(conn, owner, D2, _at(D2, 18))
    with _client(pn06_engine, monkeypatch, owner) as client:
        response = client.get('/api/v1/daily-reports', params={'limit': 1}); assert response.status_code == 200, response.text; assert [x['date'] for x in response.json()['items']] == [D2.isoformat()]
    with _client(pn06_engine, monkeypatch, stranger) as client:
        assert client.get("/api/v1/daily-reports").json()["items"] == []

def test_pn06_entry_report_detail_http(pn06_engine, monkeypatch):
    with pn06_engine.begin() as conn:
        owner, stranger = _base(conn); build(conn, owner, D2, _at(D2, 18)); original = _scalar(conn, daily_reports.c.body, user_id=owner)
    with _client(pn06_engine, monkeypatch, owner) as client:
        response = client.get('/api/v1/daily-reports/' + str(D2)); assert response.status_code == 200 and response.json()['gaps']
    with _client(pn06_engine, monkeypatch, stranger) as client:
        assert client.get("/api/v1/daily-reports/" + str(D2)).status_code == 404
    with pn06_engine.connect() as conn:
        assert _scalar(conn, daily_reports.c.body, user_id=owner) == original

def test_pn06_entry_backfill_cli(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        _base(conn); _seed_backfill_window(conn)
    settings, cache = _settings(pg_url), _Redis()
    args = ["--years", "1", "--trade-date", str(D0)]
    options = _map("now redis_client settings", [_at(D1, 16), cache, settings])
    assert daily_bars_backfill.main(args, **options) == 0
    assert not cache.rows
    assert daily_bars_backfill.main([*args, "--apply"], **options) == 0
    row = cache.rows[0]
    assert row["task"] == "daily_bars_fetch" and row["args"]["batch_kind"] == "backfill"

def _day_record(day):
    values = [int(day.strftime('%Y%m%d')), 1234, 1234, 1234, 1234, 8638.0, 700, 0]; return DAY_LAYOUT.pack(*values)

def test_pn06_entry_tdx_cli(tmp_path, pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        owner = _base(conn)[0]; _seed_backfill_window(conn, years=3)
    # 只导入麦蕊三年回填起点之前的离线历史；近期日期由原入口保守拒绝。
    day = D0.replace(year=D0.year - 3) + dt.timedelta(days=2); root = tmp_path / 'root'
    for market in ("sh", "sz", "bj"):
        (root / market / "lday").mkdir(parents=True)
    (tmp_path / "audit").mkdir()
    (root / "sh/lday/sh699001.day").write_bytes(_day_record(day))
    argv = ["--root", str(root), "--audit-dir", str(tmp_path / "audit")]
    argv += ["--until", str(day), "--from", str(day), "--apply"]
    options = _map("now settings run_id", [_at(D3, 18), _settings(pg_url), "pn06"])
    assert tdx_import.daily_main(argv, **options) == 0
    with pn06_engine.connect() as conn:
        assert daily_bars_ready(conn, owner, D2)[0] is False; snap, _ = build_owned_snapshot(conn, owner, D2); bars = _scalar(conn, data_snapshots.c["items"], id=snap)['instruments'][0]['bars']
    assert any(row['trade_date'] == str(D2) for row in bars); assert all(row['trade_date'] != str(day) for row in bars)

def _day_args(directory: Path, days):
    archive, eligible = directory / "day.zip", directory / "eligible.txt"
    with ZipFile(archive, "w") as bundle:
        bundle.writestr("sh/lday/sh699001.day", b"".join(_day_record(d) for d in days))
    eligible.write_text(CODE_A, encoding='utf-8'); args = ['day', '--zip', str(archive), '--eligible-codes', str(eligible)]; return [*args, '--generator', 'c' * 40]

def test_pn06_entry_day_cli(tmp_path, conn):
    runs = _count(conn, pipeline_runs)
    before = dt.date(2023, 11, 13)
    args = _day_args(tmp_path, (before - dt.timedelta(days=3), before))
    assert tb143_export.main([*args, "--out", str(tmp_path / "all")]) == 0
    filtered = [*args, "--before", str(before), "--out", str(tmp_path / "filtered")]
    assert tb143_export.main(filtered) == 0
    summary = json.loads((tmp_path / "filtered/summary.json").read_text())["day"]
    assert summary['before'] == str(before) and summary['counts']['record:filtered_before'] == 1
    assert _count(conn, pipeline_runs) == runs

def test_pn06_entry_tb140_daily_bars():
    path = BACKEND / "probes/tb140_daily_bars.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'mkt')
    namespace = {"history_load": _probe("tb140_history_load")}
    exec(  # noqa: S102 - 仅执行从原文件AST隔离出的mkt函数
        compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace
    )
    # T-A157 §10.3：mkt 薄调用单一映射，920 新码归 BJ，不得判成 SH。
    assert namespace["mkt"]("920999") == "BJ"
    assert "20231113" in source and "20261113" in source
    assert all(x in source for x in ("latest20", "ssjy_all", "history"))

def _probe(name):
    path = BACKEND / "probes" / (name + ".py")
    spec = importlib.util.spec_from_file_location("pn06_" + name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    search = str(BACKEND / "probes")
    sys.path.insert(0, search)
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(search)
    return module

def test_pn06_entry_history_load(conn, pg_conn):
    load = _probe("tb140_history_load")
    body = [{"t": "2024-01-02", "o": 1, "h": 2, "l": 1, "c": 2, "v": 1, "a": 100}]
    rows, rejects = load.normalize_history("600000", body)
    assert not rejects and rows[0]["source"] == "mairui"
    assert load.apply_daily_bars(pg_conn, rows)["inserted"] == 1
    assert daily_bars_ready(conn, uuid.uuid4(), D2)[0] is False

def _history_args(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    args = {'codes_file': tmp_path / 'codes', 'licence_file': tmp_path / 'licence', 'counter_path': tmp_path / 'missing', 'stop_path': tmp_path / 'STOP', 'run_dir': tmp_path}
    argv = "--codes-file codes --licence-file licence --counter missing --stop-file STOP --run-dir .".split(  # noqa: SIM905
        " "
    )
    return args, argv

def test_pn06_entry_history_backfill(tmp_path, monkeypatch):
    module = _probe('tb140_history_backfill'); args, argv = _history_args(tmp_path, monkeypatch)
    with pytest.raises(module.Halt, match="counter_missing_fail_closed"):
        module.run_batch(**args)
    assert module.main(argv) == 1

@pytest.mark.xfail(os.name == 'nt', strict=True, reason="T-B168: Windows history probe 权限负控仍失败")
def test_pn06_entry_history_selfcheck():
    script = BACKEND / "probes/tb140_history_selfcheck.py"
    done = subprocess.run([sys.executable, str(script)], check=False, capture_output=True, text=True, timeout=30)
    assert done.returncode == 0 and "PASS" in done.stdout
    source = script.read_text(encoding="utf-8")
    assert "old_buggy_mkt" in source
    daily = (BACKEND / "probes/tb140_daily_bars.py").read_text(encoding="utf-8")
    assert "def mkt" in daily and "old_buggy_mkt" not in daily

def test_pn06_entry_history_supervisor(tmp_path, monkeypatch):
    module = _probe('tb140_history_supervisor'); args, argv = _history_args(tmp_path, monkeypatch)
    with pytest.raises(module.Halt, match="counter_missing_fail_closed"):
        module.run_supervised(**args)
    assert module.main(argv) == 1

@pytest.mark.parametrize("before", [None, str(D2)], ids=["default", "explicit"])
def test_pn06_entry_day_runner_ps1(tmp_path, before):
    shell = shutil.which("pwsh") or shutil.which("powershell")
    assert shell is not None, "需要 PowerShell 验证旧入口拒绝行为"
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()
    archive = artifacts / "all.bin"
    original = b"synthetic archive\n"
    archive.write_bytes(original)
    bindir = tmp_path / "bin"
    bindir.mkdir()
    calls = tmp_path / "external-calls"
    # 优先命中本地替身，确保旧入口回归时也不会运行真实 Docker 或 psql。
    for name in ("docker", "psql"):
        if os.name == "nt":
            (bindir / f"{name}.cmd").write_text(
                f'@echo {name}>>"%PN06_CALLS%"\n@exit /b 1\n', encoding="utf-8"
            )
        else:
            command = bindir / name
            command.write_text(f'#!/bin/sh\necho {name} >> "$PN06_CALLS"\nexit 1\n')
            command.chmod(0o755)
    env = dict(os.environ, PATH=str(bindir) + os.pathsep + os.environ["PATH"], PN06_CALLS=str(calls))
    lock, log = tmp_path / "lock", tmp_path / "run.log"
    argv = [shell, "-NoProfile", "-File", str(BACKEND / "probes/tb143_day_load_runner.ps1"),
            "-Dir", str(artifacts), "-AllSha", "a" * 64, "-BundleSizes", "1",
            "-Lock", str(lock), "-Log", str(log), "-PauseSeconds", "0"]
    if before is not None:
        argv += ["-Before", before]
    done = subprocess.run(argv, check=False, capture_output=True, text=True, timeout=30, env=env)
    output = done.stdout + done.stderr
    assert done.returncode == 1, output
    assert "legacy tb143 load path is disabled" in output
    assert "app.cli.tb143_day_load" in output
    assert not calls.exists() and not lock.exists() and not log.exists()
    assert list(artifacts.iterdir()) == [archive]
    assert archive.read_bytes() == original

def _probe_schema(conn):
    schema = "pn06_" + uuid.uuid4().hex
    conn.execute(f'CREATE SCHEMA "{schema}"')
    conn.execute(f'''CREATE TABLE "{schema}".daily_bars (code text, trade_date date, adj_type text,
      open numeric, high numeric, low numeric, close numeric, volume numeric, amount numeric,
      pre_close numeric, is_suspended boolean, source text, source_licence_id uuid, fetched_at timestamptz,
      PRIMARY KEY (code, trade_date, adj_type))''')
    conn.execute(f'''CREATE TABLE "{schema}".ex_rights_events (code text, ex_date date,
      cash_per_share numeric, rights_price numeric, bonus_ratio numeric, rights_ratio numeric,
      source text, snapshot_sha256 text, registered_at timestamptz DEFAULT now(),
      PRIMARY KEY (code, ex_date, snapshot_sha256))''')
    conn.execute(f'''CREATE TABLE "{schema}".minute_file_catalog (source text, code text, kind text,
      date_from date, date_to date, rel_path text, sha256 text, row_count bigint, splice_segment text,
      generator text, registered_at timestamptz DEFAULT now(), PRIMARY KEY (source, code, kind, rel_path))''')
    return schema

def _run_sql(conn, schema, name, before="2025-01-01"):
    path = ROOT / "tests/backend/unit/test_tb143_multi_source_pg.py"; spec = importlib.util.spec_from_file_location("pn06_tb143_sql", path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module._load(conn, schema, meta=name == "tb143_load_meta.sql", before=before)
    if name == "tb143_load_day.sql":
        result = conn.execute("SELECT * FROM pg_temp.day_stage").fetchall()
    else:
        result = conn.execute("SELECT * FROM load_counts").fetchall()
    conn.execute("DROP VIEW IF EXISTS catalog_effective, mairui_count")
    conn.execute('DROP TABLE IF EXISTS gbbq_stage, catalog_stage, day_stage, load_params, load_counts, mairui_before, mairui_after')
    return result

def test_pn06_entry_load_day_sql(pg_conn):
    schema = _probe_schema(pg_conn)
    calendars = pg_conn.execute('SELECT count(*) FROM market.trading_calendar').fetchone()
    # SQL 仅填充临时表，目标日线写入由 Python 公共 writer 负责。
    price = Decimal("12.34")
    assert _run_sql(pg_conn, schema, "tb143_load_day.sql") == [
        ("600999.SH", dt.date(2024, 1, 2), "none", price, price, price, price, 700, 8638)
    ]
    assert pg_conn.execute(f'SELECT count(*) FROM "{schema}".daily_bars').fetchone() == (0,)
    with (
        pytest.raises(
            psycopg.errors.RaiseException, match="日线日期必须全部小于 before"
        ),
        pg_conn.transaction(),
    ):
        _run_sql(pg_conn, schema, "tb143_load_day.sql", "2024-01-02")
    assert pg_conn.execute(f'SELECT count(*) FROM "{schema}".daily_bars').fetchone() == (0,)
    assert pg_conn.execute('SELECT count(*) FROM market.trading_calendar').fetchone() == calendars

def test_pn06_entry_load_meta_sql(pg_conn):
    schema = _probe_schema(pg_conn)
    expected = [("ex_rights_events", 1, 1, 0), ("minute_file_catalog", 1, 1, 0)]
    assert _run_sql(pg_conn, schema, "tb143_load_meta.sql") == expected
    query = f'SELECT ex_date FROM "{schema}".ex_rights_events'
    registered = pg_conn.execute(query).fetchone()[0]
    # 原stage只注册事件、没有available_at；不能把注册记录伪造成当时可见因子。
    assert f"adjust_factor_missing:{registered}" in _prepare(extra=registered)["gaps"]

def _require_pg17():
    programs = ('initdb', 'pg_ctl', 'postgres', 'psql')
    if os.name == 'nt':
        if shutil.which('wsl.exe') is None:
            pytest.skip('PG17 自检需要 WSL 与隔离 PG17；当前无 wsl.exe')
        command = 'for p in initdb pg_ctl postgres psql; do test -x /usr/lib/postgresql/17/bin/$p || exit 1; done'
        try:
            probe = subprocess.run(['wsl.exe', 'bash', '-lc', command], check=False, capture_output=True, timeout=15)
            available = probe.returncode == 0
        except (OSError, subprocess.SubprocessError):
            available = False
        if not available:
            pytest.skip('PG17 自检需要可用 WSL 与隔离 PG17；当前环境不满足')
    elif not all(os.access(f'/usr/lib/postgresql/17/bin/{program}', os.X_OK) for program in programs):
        pytest.skip('PG17 自检需要隔离 PG17；CI 仅提供 PG16')

def test_pn06_entry_pg_selfcheck():
    _require_pg17()
    script = BACKEND / 'probes/tb143_pg_selfcheck.sh'; target = str(script)
    if os.name == "nt":
        args = ['wsl.exe', 'wslpath', '-a', script.as_posix()]; target = subprocess.check_output(args, text=True).strip()
    values = [True, 120, {"PATH": os.environ.get("PATH", "")}]
    options = _map("capture_output timeout env", values)
    done = subprocess.run(["bash", target], check=False, **options)
    encoding = "utf-16" if b"\0" in done.stdout + done.stderr else "utf-8"
    output = (done.stdout + done.stderr).decode(encoding, errors="replace")
    assert done.returncode == 0, output
    assert "PASS:" in output and "CLEANUP:" in output
    source = script.read_text(encoding="utf-8")
    assert "daily_bars_ready" not in source and "build_owned_snapshot" not in source

def test_pn06_entry_worker_dispatch(pn06_engine, pg_url):
    with pn06_engine.begin() as conn:
        _seed(conn, end=D2, opens=(D0, D2))
    settings = _settings(pg_url)
    fetch = jobs.slot_jobs(settings, _at(D2, 17, 15))
    analysis = jobs.slot_jobs(settings, _at(D2, 17, 30))
    assert any(x[0] == jobs.DAILY_BARS_FETCH for x in fetch)
    assert any(x[0] == ANALYZE for x in analysis)
    queued = jobs.beat_slots(settings, client=_Redis(), now=_at(D2, 17, 30))
    assert ANALYZE in queued and REPORT not in queued
    assert jobs.worker_tick(settings, client=_Redis()) == []
    assert 'daily_bars_ready' not in jobs.TASKS and 'build_owned_snapshot' not in jobs.TASKS

def test_pn06_entry_outbox(conn, monkeypatch):
    monkeypatch.setattr(daily_bars_outbox.ingest, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 1)
    owner = _base(conn)[0]
    now = _at(D2, 17, 15)
    grant = DailyBarsGrant(user_id=owner, licence_id=uuid.uuid4(), receipt_id=uuid.uuid4(), digest='a' * 64, start=now - dt.timedelta(minutes=1), end=now + dt.timedelta(minutes=1))
    kwargs = {'trade_date': D2, 'user_id': owner, 'batch_kind': 'backfill', 'grant_reader': lambda uid: grant, 'now': now}
    assert daily_bars_outbox.enqueue(conn, **kwargs) == 1
    assert daily_bars_outbox.enqueue(conn, **kwargs) == 0
    row = _one(conn, outbox, user_id=owner)
    assert row.batch_kind == "backfill" and row.status == "pending"
    assert daily_bars_ready(conn, owner, D2)[0] is False

def test_pn06_entry_consumer(pn06_engine):
    with pn06_engine.connect() as conn:
        before = _count(conn, outbox)
    transport = lambda *a: pytest.fail("禁止外呼")
    assert consumer.process(pn06_engine, uuid.uuid4(), transport=transport) == "missing"
    assert consumer.tick(pn06_engine, transport=transport) == 0
    assert consumer.wake_delayed(pn06_engine, _Redis(), clock=lambda: _at(D2, 18)) is None
    with pn06_engine.connect() as conn:
        assert _count(conn, outbox) == before

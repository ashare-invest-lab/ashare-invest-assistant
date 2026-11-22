"""Offline adapters for T-A172 §10.11; never open a DB, licence, or transport.

All pairs are synthetic protocol fixtures, NOT evidence for production admission.
Threshold 20, one common day, exclusion rules, exact v*100 and lifecycle: DS
§10.2/10.10. Midnight syntax: multi-source-ingest §2.2/C9. No other numerical
threshold authorizes admission. SQL/Windows checks below are source checks only.
"""
from __future__ import annotations

import datetime as dt
import importlib
import inspect
import json
import re
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from sqlalchemy.dialects.postgresql import dialect

ROOT = Path(__file__).resolve().parents[3]
DAY = dt.date(2031, 1, 2)
NOW = dt.datetime(2031, 1, 2, 13, tzinfo=dt.UTC)
BJ, SH, SZ = "920999.BJ", "600999.SH", "000999.SZ"
CODES = (SH, SZ, BJ)
IDENT = UUID("00000000-0000-0000-0000-000000000172")
OTHER = UUID("00000000-0000-0000-0000-000000000173")
SCENARIOS = (
    "bj_default_blocked", "cross_day", "zero_volume", "suspended_mairui",
    "suspended_tdx_local", "precision_tail", "blocked_not_ok",
    "midnight_date", "midnight_date_nonzero",
)


def module(name):
    # Missing proposed entries must fail assertions inside a test, not collection.
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        raise AssertionError(f"§10.11 missing entry module {name}: {exc.name}") from None


def entry(obj, name):
    assert hasattr(obj, name), f"§10.11 missing entry {obj.__name__}.{name}"
    return getattr(obj, name)


def pairs(scenario="valid"):
    result = []
    # Synthetic trading calendar: weekdays only, no claim about a real exchange calendar.
    trading_days = []
    day = DAY
    while len(trading_days) < 20:
        if day.weekday() < 5:
            trading_days.append(day)
        day += dt.timedelta(days=1)
    for n in range(20):  # §10.2: >=20 distinct legal .BJ codes, not sample stocks.
        code = f"9209{n:02d}.BJ"
        day = trading_days[n] if scenario == "cross_day" else DAY
        result.append({
            "mairui": {"code": code, "t": day.isoformat(), "v": "1", "sf": 0},
            "tdx_local": {"code": code, "trade_date": day.isoformat(),
                          "volume": "100", "source": "tdx_local", "is_suspended": False},
        })
    if scenario == "zero_volume":
        result[0]["mairui"]["v"] = "0"
        result[0]["tdx_local"]["volume"] = "0"
    elif scenario == "suspended_mairui":
        result[0]["mairui"]["sf"] = 1
    elif scenario == "suspended_tdx_local":
        result[0]["tdx_local"]["is_suspended"] = True
    elif scenario == "precision_tail":
        result[0]["mairui"]["v"] = "1.000000000000000000000000000001"
    elif scenario.startswith("midnight_date"):
        time = "10:00:00" if scenario.endswith("nonzero") else "00:00:00"
        for pair in result:
            pair["mairui"]["t"] += f" {time}"
    return result


def raw(code=BJ):
    return {"code": code, "t": DAY.isoformat(), "o": "10", "h": "11", "l": "9",
            "c": "10", "pc": "9", "v": "1", "a": "1000", "sf": 0}


def normalized(code=BJ):
    return {"code": code, "trade_date": DAY.isoformat(), "adj_type": "none",
            "open": "10", "high": "11", "low": "9", "close": "10", "pre_close": "9",
            "volume": 100, "amount": "1000", "is_suspended": False, "source": "mairui"}


def bar(code=BJ):
    writer = module("app.marketdata.daily_bars")
    return writer.DailyBar(code, DAY, "none", Decimal(10), Decimal(11), Decimal(9),
                           Decimal(10), Decimal(9), Decimal(100), Decimal(1000), False)


def confirm(material):
    load = module("probes.tb140_history_load")
    try:
        codes = entry(load, "confirm_bj_offline_volume_units")(material)
        return bool(codes), ""
    except ValueError as exc:
        return False, str(exc)


def revoke():
    accepted, _ = confirm([])
    assert not accepted, "§10.10 empty evidence must revoke admission"


def setup_scenario(scenario):
    """Return findings without aborting: each adapter is still exercised on bad proof.

    Prime a synthetically valid state before EACH negative confirmation, so tests
    also detect failure to clear old admission. This test-only state is revoked
    by the fixture and never serialized as a production credential.
    """
    revoke()
    issues = []
    if scenario in ("bj_default_blocked", "blocked_not_ok"):
        return False, issues
    primed, reason = confirm(pairs())
    if not primed:
        issues.append(f"synthetic positive control rejected: {reason}")
    accepted, reason = confirm(pairs(scenario))
    expected = scenario == "midnight_date"
    if accepted != expected:
        issues.append(f"§10.2/B2/B6 {scenario}: accepted={accepted}, reason={reason!r}")
    if scenario == "midnight_date":
        load = module("probes.tb140_history_load")
        try:
            parsed = entry(load, "_trade_date")("2031-01-02 00:00:00")
            if parsed != DAY:
                issues.append("§2.2/C9 zero-time date parsed incorrectly")
        except ValueError as exc:
            issues.append(f"§2.2/C9 midnight must not be trade_date_invalid: {exc}")
    return expected, issues


@dataclass
class Observation:
    rows: list = field(default_factory=list)
    stats: object = None
    runs: list = field(default_factory=list)
    ledger: dict = field(default_factory=dict)
    sql: str = ""
    public_calls: int = 0


class Result:
    def __init__(self, rows=(), scalar=0):
        self.rows, self.scalar = list(rows), scalar
        self.rowcount = len(self.rows)

    def all(self):
        return self.rows

    def mappings(self):
        return self.rows

    def scalar_one(self):
        return self.scalar

    scalar_one_or_none = scalar_one


class MemoryDB:
    """Capture real compiled SQLAlchemy / DBAPI writes, never fake writer success.

    Empty initial table, fresh keys; RETURNING represents captured INSERTs only.
    SQLAlchemy bound keys are inspected rather than executing any SQL.
    """
    def __init__(self):
        self.rows = []
        self.statements = []
        self.info = SimpleNamespace(transaction_status=0)

    def execute(self, statement):
        compiled = statement.compile(dialect=dialect())
        self.statements.append(str(compiled))
        params = compiled.params
        if getattr(statement, "is_insert", False):
            rows = []
            for key, code in params.items():
                if key == "code" or key.startswith("code_m"):
                    suffix = key[4:]
                    rows.append({name: params.get(name + suffix) for name in (
                        "code", "trade_date", "adj_type", "volume", "source")})
            self.rows.extend(rows)
            return Result([SimpleNamespace(**row) for row in rows])
        if getattr(statement, "is_update", False):
            codes = list(dict.fromkeys(v for v in params.values() if isinstance(v, str) and v in CODES))
            rows = [{"code": code, "volume": 100} for code in codes]
            self.rows.extend(rows)
            return Result(rows)
        return Result()

    def cursor(self):
        return Cursor(self)

    @contextmanager
    def transaction(self):
        yield self

    def close(self):
        pass


class Cursor:
    def __init__(self, db):
        self.db, self.output, self.rowcount = db, [], 0

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def execute(self, sql, params=None):
        self.db.statements.append(str(sql))
        self.output = [(len(self.db.rows),)] if "count(*)" in str(sql).lower() else []

    def executemany(self, sql, params):
        self.db.statements.append(str(sql))
        for values in params:
            self.db.rows.append(dict(zip((
                "code", "trade_date", "adj_type", "open", "high", "low", "close",
                "pre_close", "volume", "amount", "is_suspended", "source", "source_licence_id",
            ), values)))

    def fetchone(self):
        return self.output[0] if self.output else None

    def fetchall(self):
        return self.output


def instrument(monkeypatch):
    """Spy on actual public writer (including imported aliases), do not stub its gate."""
    writer = module("app.marketdata.daily_bars")
    original = writer.upsert_daily_bars
    calls = []

    def call(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)

    for name in ("app.marketdata.daily_bars", "app.ingest.daily_bars", "app.cli.tdx_import",
                 "probes.tb140_history_load"):
        obj = module(name)
        if hasattr(obj, "upsert_daily_bars"):
            monkeypatch.setattr(obj, "upsert_daily_bars", call)
    return calls


def run_public(monkeypatch, kind, tmp_path, source="mairui", codes=CODES):
    writer = module("app.marketdata.daily_bars")
    load = module("probes.tb140_history_load")
    db, runs = MemoryDB(), []
    calls = instrument(monkeypatch)
    bars = [bar(code) for code in codes]
    if kind == "marketdata.daily_bars.upsert_daily_bars":
        stats = entry(writer, "upsert_daily_bars")(
            db, writer.DailyBarsResult(bars=bars), source=source,
            licence_id=None, fetched_at=NOW)
    elif kind == "app.cli.tdx_import":
        tdx = module(kind)
        local = module("app.ingest.tdx_local")
        tdx_bars = [local.TdxBar(code=b.code, trade_date=DAY, ts=None, open=b.open,
                               high=b.high, low=b.low, close=b.close,
                               volume=b.volume, amount=b.amount) for b in bars]
        stats = entry(tdx, "DbDeps")(db).write("day", tdx_bars, NOW)
    elif kind == "marketdata.daily_bars.fetch_and_record":
        monkeypatch.setattr(writer, "covered", lambda *_: True)
        monkeypatch.setattr(writer, "_union_universe", lambda *_: list(codes))
        monkeypatch.setattr(writer, "_record_run", lambda *a, **kw: runs.append(kw))
        fake_source = SimpleNamespace(name=source, fetch=lambda *_: writer.DailyBarsResult(bars=bars))
        stats = entry(writer, "fetch_and_record")(
            db, fake_source, trade_date=DAY, user_id=IDENT,
            window_trading_days=None, fetched_at=NOW)
    elif kind == "app.ingest.daily_bars":
        ingest = module(kind)
        monkeypatch.setattr(ingest, "covered", lambda *_: True)
        monkeypatch.setattr(ingest, "daily_universe", lambda *_: list(codes))
        # Batch budget is only a fixture to reach the writer; not an admission threshold.
        monkeypatch.setattr(ingest, "DAILY_BARS_BATCH_LIMIT", len(codes))
        grant = ingest.DailyBarsGrant(IDENT, OTHER, IDENT, NOW - dt.timedelta(hours=1),
                                     NOW + dt.timedelta(hours=1), "synthetic")
        stats = entry(ingest, "fetch_mairui_daily_bars")(
            db, trade_date=DAY, user_id=IDENT, transport=lambda code, *_: (200, bar(code)),
            grant_reader=lambda: grant, clock=lambda: NOW,
            stop_path=tmp_path / "STOP", halt_path=tmp_path / "HALT",
            run_recorder=lambda *a, **kw: runs.append(kw))
    elif kind == "tb140_history_load.apply_daily_bars":
        stats = entry(load, "apply_daily_bars")(
            db, [normalized(code) for code in codes], reconcile_sink=lambda _: None)
    elif kind == "tb140_history_load.apply_insert_artifact":
        path = tmp_path / "synthetic.sql"
        # Persist data, never a confirmation flag; consumer must recheck its own state.
        path.write_text(load.APPLY_PAYLOAD_PREFIX + json.dumps({
            "bars": [normalized(code) for code in codes], "licence_id": None}), encoding="utf-8")
        stats = entry(load, "apply_insert_artifact")(db, path, reconcile_path=tmp_path / "audit.jsonl")
    else:
        assert False, f"missing test adapter: {kind}"
    return Observation(rows=db.rows, stats=stats, runs=runs, public_calls=len(calls))


def check_observation(obs, allowed, *, runtime_status=False, require_public=True):
    issues = []
    written = {row["code"] for row in obs.rows}
    if {SH, SZ} - written:
        issues.append("§10.2 SH/SZ original path must still write both synthetic rows")
    if (BJ in written) != allowed:
        issues.append(f"§10.2/B4 BJ target writes={BJ in written}; expected={allowed}")
    if require_public and not obs.public_calls:
        issues.append("§10.10/B1 must actually call upsert_daily_bars, not a local writer")
    for row in obs.rows:
        if row.get("volume") != 100:
            issues.append(f"§10.2 shares must stay 100, never x100 again: {row}")
    if not allowed:
        stats = obs.stats
        if hasattr(stats, "__dict__"):
            stats = vars(stats)
        if isinstance(stats, dict):
            visible = (stats.get("blocked_bj_unconfirmed", 0)
                       or stats.get("db_blocked_bj_unconfirmed", 0) or stats.get("issues"))
            if not visible:
                issues.append("§10.10/B5 blocked BJ needs inspectable rejection/skip accounting")
        elif not obs.runs:
            issues.append("§10.10/B5 scalar-only result loses BJ rejection reason/count")
        if runtime_status:
            if not obs.runs or any(run.get("status") == "ok" for run in obs.runs):
                issues.append("§10.10/B5 BJ not written must not report ok")
            if not any(run.get("stats", {}).get("issues") or
                       run.get("stats", {}).get("missing") or
                       run.get("stats", {}).get("blocked_bj_unconfirmed") for run in obs.runs):
                issues.append("§10.10/B5 run must expose blocked BJ gap")
    return issues


def source(path):
    file = ROOT / path
    assert file.is_file(), f"§10.11 missing entry {path}"
    return file.read_text(encoding="utf-8-sig")


TARGET_DML = re.compile(
    r"\b(?:insert\s+into|update|delete\s+from|truncate(?:\s+table)?|merge\s+into)"
    r"\s+(?:only\s+)?[\"]?market[\"]?\s*\.\s*[\"]?daily_bars\b", re.I)


def executable_sql(text):
    return re.sub(r"--[^\n]*|/\*.*?\*/", "", text, flags=re.S)


def sql_findings(text, scenario):
    """Only source guarantees; no claim of executing PostgreSQL date/numeric rules."""
    code = executable_sql(text)
    issues = []
    if TARGET_DML.search(code):
        issues.append("§10.10/10.11/B1 SQL must stage only; direct target DML still executable")
    if scenario == "cross_day" and "tb143_bj_volume_pairs" in code:
        if not re.search(r"(?:group\s+by[^;]*trade_date|count\s*\(\s*distinct\s+\w+\.trade_date\s*\)\s*=\s*1)", code, re.I):
            issues.append("§10.2/B2 SQL lacks one common trade day across 20 pairs")
    if scenario == "zero_volume" and "tb143_bj_volume_pairs" in code:
        if not (re.search(r"mairui_v\s*>\s*0", code) and re.search(r"volume\s*>\s*0", code)):
            issues.append("§10.2/B2 SQL does not exclude both zero volumes before counting")
    if scenario.startswith("suspended") and "tb143_bj_volume_pairs" in code:
        if not ("sf" in code and "is_suspended" in code):
            issues.append("§10.2/B2 SQL evidence schema cannot exclude suspension on both sides")
    if scenario == "precision_tail" and re.search(r"(?:float|double\s+precision|real)\b", code, re.I):
        issues.append("§10.2/B2 exact numeric confirmation cannot use floating point")
    return issues


def function_source(obj, name):
    return inspect.getsource(entry(obj, name))


def fail_findings(issues):
    assert not issues, "\n".join(issues)

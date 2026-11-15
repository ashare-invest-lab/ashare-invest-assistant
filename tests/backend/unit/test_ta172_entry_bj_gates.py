"""T-T94 / T-A176 B7: red acceptance matrix for PR #182 §10.11.

Official entry names are preserved verbatim in ENTRY_TESTS. Every row uses the
same synthetic scenarios (two suspension sides and both midnight forms).
Runtime = fake connection/transport only. SQL/runner = source contract; drill
guards use extracted shell functions and fake commands. Real Windows / psql /
Docker / restore are UNVERIFIED, never skipped.
Synthetic confirmation is a process-local test fixture, not production evidence.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ta172_bj_gate_support import (
    BJ, CODES, DAY, IDENT, NOW, OTHER, ROOT, SCENARIOS, SH, SZ, MemoryDB,
    Observation, TARGET_DML, bar, check_observation, confirm, entry, executable_sql,
    fail_findings, function_source, instrument, module, normalized, pairs, raw,
    revoke, run_public, setup_scenario, source, sql_findings,
)

_CONTROLLED_POPEN = subprocess.Popen

ENTRY_TESTS = {
    "marketdata.daily_bars.upsert_daily_bars": "test_ta172_upsert_daily_bars_bj_gate_all_sources",
    "app.ingest.daily_bars": "test_ta172_ingest_daily_bars_uses_bj_gate",
    "app.cli.tdx_import": "test_ta172_tdx_import_bj_gate_shares_unchanged",
    "marketdata.daily_bars.fetch_and_record": "test_ta172_fetch_and_record_uses_bj_gate",
    "mairui-licence-bind → update_mairui_source_licence_id": "test_ta172_licence_bind_rebind_rollback_bj_gate",
    "tb143_reconcile_load --apply": "test_ta172_reconcile_apply_bj_gate",
    "repo.insert（reconcile）": "test_ta172_repo_insert_no_bypass",
    "tb140_history_load.render_insert_sql": "test_ta172_render_insert_sql_bj_gate",
    "tb140_history_load.apply_daily_bars": "test_ta172_apply_daily_bars_bj_gate",
    "tb140_history_load.apply_insert_artifact": "test_ta172_apply_insert_artifact_bj_gate",
    "tb140_history_load.apply_insert_offline": "test_ta172_apply_insert_offline_bj_gate",
    "tb140_history_backfill.run_batch": "test_ta172_backfill_run_batch_bj_gate",
    "tb140_history_supervisor.run_supervised": "test_ta172_supervisor_persistence_bj_gate",
    "src/backend/probes/tb143_load_day.sql": "test_ta172_load_day_sql_session_bj_gate",
    "src/backend/probes/tb143_day_load_runner.ps1": "test_ta172_day_load_runner_new_session_bj_gate",
    "deploy/db/drill/sample-data.sql": "test_ta172_drill_sample_data_bj_gate",
    "deploy/scripts/db-restore-drill.sh": "test_ta172_restore_drill_no_production_bj_support",
    "src/backend/probes/tb143_pg_selfcheck.sh": "test_ta172_pg_selfcheck_isolated_seed_only",
    "src/backend/selfchecks 隔离 DML": "test_ta172_selfcheck_dml_isolated_only",
    "tests/backend 隔离 DML": "test_ta172_test_dml_no_production_confirmation",
}
scenarios = pytest.mark.parametrize("scenario", SCENARIOS)


@pytest.fixture(autouse=True)
def offline_and_unconfirmed(monkeypatch):
    """Reject even localhost DB/network and external commands; no real credentials."""
    monkeypatch.delenv("MAIRUI_LICENCE", raising=False)

    def denied(*_, **__):
        raise AssertionError("T-T94 offline boundary: network/external process prohibited")

    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        monkeypatch.setattr(socket, name, denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    monkeypatch.setattr(os, "system", denied)
    revoke()
    yield
    revoke()


def exercise(monkeypatch, tmp_path, scenario, name, *, source_name="mairui"):
    allowed, issues = setup_scenario(scenario)
    obs = run_public(monkeypatch, name, tmp_path, source=source_name)
    issues += check_observation(obs, allowed, runtime_status=name in (
        "app.ingest.daily_bars", "marketdata.daily_bars.fetch_and_record"))
    fail_findings(issues)


@scenarios
@pytest.mark.parametrize("source_name", ["tdx_local", "mairui", "fake", "synthetic_other"])
def test_ta172_upsert_daily_bars_bj_gate_all_sources(monkeypatch, tmp_path, scenario, source_name):
    exercise(monkeypatch, tmp_path, scenario, "marketdata.daily_bars.upsert_daily_bars",
             source_name=source_name)


@scenarios
def test_ta172_ingest_daily_bars_uses_bj_gate(monkeypatch, tmp_path, scenario):
    exercise(monkeypatch, tmp_path, scenario, "app.ingest.daily_bars")


@scenarios
def test_ta172_tdx_import_bj_gate_shares_unchanged(monkeypatch, tmp_path, scenario):
    # check_observation asserts every captured row is 100 shares (also on confirmed path).
    exercise(monkeypatch, tmp_path, scenario, "app.cli.tdx_import")


@scenarios
def test_ta172_fetch_and_record_uses_bj_gate(monkeypatch, tmp_path, scenario):
    exercise(monkeypatch, tmp_path, scenario, "marketdata.daily_bars.fetch_and_record")


@scenarios
@pytest.mark.parametrize("operation", ["bind", "rebind", "rollback"])
def test_ta172_licence_bind_rebind_rollback_bj_gate(monkeypatch, scenario, operation):
    _, issues = setup_scenario(scenario)
    writer = module("app.marketdata.daily_bars")
    db = MemoryDB()
    calls = instrument(monkeypatch)
    match, value = {"bind": (None, IDENT), "rebind": (IDENT, OTHER),
                    "rollback": (OTHER, IDENT)}[operation]
    try:
        count = entry(writer, "update_mairui_source_licence_id")(
            db, [(code, DAY, "none") for code in CODES],
            match=match, value=value, apply=True)
    except ValueError:
        count = 0  # Explicit refusal is allowed while this entry is awaiting migration.
    if any(row["code"] == BJ for row in db.rows):
        issues.append(f"§10.10/10.11 {operation}: pending migration must block BJ UPDATE")
    if not {SH, SZ} <= {row["code"] for row in db.rows}:
        issues.append(f"§10.2 {operation}: SH/SZ metadata updates must remain available")
    if count and not calls:
        issues.append("§10.10/B1 independent metadata UPDATE bypasses upsert_daily_bars")
    fail_findings(issues)


def reconcile_source_contract(scenario, repository):
    # §10.12(4) applies ONLY to these two proposed reconcile entries.
    # A missing dependency of an existing module must still fail via module().
    if importlib.util.find_spec("app.cli.tb143_reconcile_load") is None:
        return
    _, issues = setup_scenario(scenario)
    reconcile = module("app.cli.tb143_reconcile_load")
    if repository:
        repo = entry(reconcile, "PgRepository")
        text = function_source(repo, "insert")
        if "upsert_daily_bars" not in text:
            issues.append("§10.11 repo.insert must call upsert_daily_bars")
    else:
        entry(reconcile, "main")
        text = inspect.getsource(reconcile)
        if "--apply" not in text or "upsert_daily_bars" not in text:
            issues.append("§10.11 tb143_reconcile_load --apply must reach public writer")
        if scenario == "blocked_not_ok" and not (
            "blocked_bj_unconfirmed" in text and "partial" in text
        ):
            issues.append("§10.10/B5 reconcile must expose blocked gap and partial status")
    if TARGET_DML.search(text):
        issues.append("§10.10/B1 reconcile has independent target DML")
    fail_findings(issues)


@scenarios
def test_ta172_reconcile_apply_bj_gate(scenario):
    reconcile_source_contract(scenario, repository=False)


@scenarios
def test_ta172_repo_insert_no_bypass(scenario):
    reconcile_source_contract(scenario, repository=True)


@scenarios
def test_ta172_render_insert_sql_bj_gate(scenario):
    allowed, issues = setup_scenario(scenario)
    load = module("probes.tb140_history_load")
    text = entry(load, "render_insert_sql")(
        [normalized(code) for code in CODES], None, bind_note="synthetic")
    executable = executable_sql(text)
    # Even successful generator confirmation cannot authorize another SQL session.
    issues += sql_findings(text, scenario)
    if not allowed and BJ in executable:
        issues.append("§10.10/B3 blocked BJ remains in executable artifact")
    if not allowed and "bj_offline_volume_units_unconfirmed" not in text:
        issues.append("§10.10/B5 artifact must record its BJ rejection")
    if not all(code in text for code in (SH, SZ)):
        issues.append("§10.2 artifact must retain SH/SZ data for original writer path")
    # Revoke AFTER rendering: a file must never carry forward a previous admission.
    revoke()
    if TARGET_DML.search(executable) and BJ in executable:
        issues.append("§10.10/B3 saved artifact still executes BJ INSERT after revocation")
    fail_findings(issues)


@scenarios
def test_ta172_apply_daily_bars_bj_gate(monkeypatch, tmp_path, scenario):
    exercise(monkeypatch, tmp_path, scenario, "tb140_history_load.apply_daily_bars")


@scenarios
def test_ta172_apply_insert_artifact_bj_gate(monkeypatch, tmp_path, scenario):
    exercise(monkeypatch, tmp_path, scenario, "tb140_history_load.apply_insert_artifact")


@scenarios
def test_ta172_apply_insert_offline_bj_gate(scenario):
    allowed, issues = setup_scenario(scenario)
    load = module("probes.tb140_history_load")
    original = set()
    stats = entry(load, "apply_insert_offline")(original, [normalized(c) for c in CODES])
    if original:
        issues.append("§10.11 isolated simulation must not mutate caller's table")
    if stats["inserted"] != (3 if allowed else 2):
        issues.append(f"§10.2 isolated simulation admitted invalid evidence: {stats}")
    if not allowed and stats.get("blocked_bj_unconfirmed") != 1:
        issues.append("§10.10/B5 simulation must expose exactly one blocked BJ row")
    # Simulated writes/normalization must never create admission from an empty state.
    if scenario in ("bj_default_blocked", "blocked_not_ok"):
        if not load._bj_write_unconfirmed(normalized()):
            issues.append("§10.10 isolated seed created production confirmation")
    fail_findings(issues)


def batch_observation(monkeypatch, tmp_path, supervised):
    backfill = module("probes.tb140_history_backfill")
    supervisor = module("probes.tb140_history_supervisor")
    load = module("probes.tb140_history_load")
    db = MemoryDB()
    calls = instrument(monkeypatch)
    counter = tmp_path / "counter.json"
    backfill.atomic_save(counter, backfill.default_counter())
    codes = tmp_path / "codes.txt"
    codes.write_text("\n".join(code[:6] for code in CODES), encoding="utf-8")

    def fake_history(self, state, _synthetic_secret, code, *_):
        # Bound loop if a repaired supervisor leaves BJ pending without stopping.
        assert self.calls_this_run < 6, "§10.10 blocked BJ must not auto-refetch indefinitely"
        self.calls_this_run += 1
        state["total"] += 1
        return 200, [raw(load.qualified_code(code))]

    monkeypatch.setattr(backfill.Backfill, "call_history", fake_history)
    # No licence file is created or read. Supervisor's file functions are replaced.
    monkeypatch.setattr(supervisor, "read_licence_file", lambda _: "synthetic-placeholder")
    monkeypatch.setattr(supervisor, "delete_licence_file", lambda _: True)
    options = dict(codes_file=codes, counter_path=counter, stop_path=tmp_path / "STOP",
                   run_dir=tmp_path / "run", max_calls=3, interval=5,
                   sleeper=lambda _: None, clock=lambda: 1.0)
    stats = {}
    try:
        if supervised:
            stats = entry(supervisor, "run_supervised")(
                **options, licence_file=tmp_path / "nonexistent-synthetic",
                environ={"TA172_SYNTHETIC_DB": "postgresql://synthetic.invalid/never-connect"},
                db_url_env="TA172_SYNTHETIC_DB", db_connect=lambda _: db)
        else:
            stats = entry(backfill, "run_batch")(
                **options, licence_file=None, secret="synthetic",
                persist_rows=lambda rows: load.apply_daily_bars(db, rows, reconcile_sink=lambda _: None))
    except backfill.Halt as exc:
        stats = {"halt": str(exc)}
    ledger = json.loads(counter.read_text()) if counter.is_file() else {}
    text = "\n".join(path.read_text() for path in (tmp_path / "run/sql").glob("*.sql"))
    return Observation(rows=db.rows, stats=stats, ledger=ledger, sql=text, public_calls=len(calls))


def exercise_batch(monkeypatch, tmp_path, scenario, supervised):
    allowed, issues = setup_scenario(scenario)
    obs = batch_observation(monkeypatch, tmp_path, supervised)
    issues += check_observation(obs, allowed)
    issues += sql_findings(obs.sql, scenario)
    if not allowed:
        if BJ[:6] in obs.ledger.get("done_history", []):
            issues.append("§10.10/B5 blocked BJ is in done_history and cannot resume")
        if obs.stats.get("done", 0) > 2:
            issues.append("§10.10/B5 blocked BJ must not contribute to done")
    fail_findings(issues)


@scenarios
def test_ta172_backfill_run_batch_bj_gate(monkeypatch, tmp_path, scenario):
    exercise_batch(monkeypatch, tmp_path, scenario, supervised=False)


@scenarios
def test_ta172_supervisor_persistence_bj_gate(monkeypatch, tmp_path, scenario):
    exercise_batch(monkeypatch, tmp_path, scenario, supervised=True)


@scenarios
def test_ta172_load_day_sql_session_bj_gate(scenario):
    _, issues = setup_scenario(scenario)
    text = source("src/backend/probes/tb143_load_day.sql")
    issues += sql_findings(text, scenario)
    code = executable_sql(text)
    temps = set(re.findall(r'\bCREATE\s+TEMP(?:ORARY)?\s+TABLE\s+(\w+)', code, re.I))
    writes = re.findall(
        r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|'
        r'TRUNCATE(?:\s+TABLE)?|COPY)\s+([\w.\"]+)', code, re.I)
    if not temps or any(name not in temps for name in writes):
        issues.append("§10.12 SQL may write only declared session TEMP tables")
    creates = re.findall(r'\bCREATE\s+((?:TEMP(?:ORARY)?\s+)?TABLE)\b', code, re.I)
    if any(not kind.upper().startswith("TEMP") for kind in creates):
        issues.append("§10.12 SQL cannot create persistent tables")
    if re.search(r'\bCOMMIT\b(?!\s+DROP\b)', code, re.I):
        issues.append("§10.12 staging SQL cannot COMMIT; load_day owns the transaction")
    if scenario == "bj_default_blocked":
        if re.search(r"v_bj_confirmed\s*(?::=|boolean\s+default)\s*true", text, re.I):
            issues.append("§10.10 new SQL session cannot start confirmed")
        if "CREATE TEMP TABLE" not in text:
            issues.append("§10.11 retained SQL must stage in TEMP tables only")
    if scenario == "blocked_not_ok" and not re.search(r"(?:skipped|blocked|reject)", text, re.I):
        issues.append("§10.10/B5 SQL must report rejected rows")
    fail_findings(issues)


def startup_refusal_findings(text, *, powershell):
    """Check the first active path, never strings in an unreachable legacy body.

    A literal refusal followed by unconditional nonzero termination, with only
    parameter/options setup before it, also proves no artifact cleanup ran.
    These are source checks; Windows and a real PostgreSQL session stay unverified.
    """
    code = re.sub(r'<#.*?#>', '', text, flags=re.S) if powershell else text
    code = '\n'.join(line for line in code.splitlines() if not line.lstrip().startswith('#')).strip()
    if powershell:
        code = re.sub(r'^\[CmdletBinding\(\)\]\s*', '', code, flags=re.I)
        if re.match(r'param\s*\(', code, re.I):
            depth = 0
            for index, char in enumerate(code[code.index('('):], code.index('(')):
                depth += (char == '(') - (char == ')')
                if depth == 0:
                    params, code = code[:index + 1], code[index + 1:].strip()
                    break
            else:
                return ["§10.12 runner parameter block is not closed"]
            if '$(' in params:
                return ["§10.12 runner cannot execute commands during parameter setup"]
        match = re.fullmatch(
            r"(?:\$ErrorActionPreference\s*=\s*'Stop'\s*)?"
            r"Write-Error\s+'(?P<message>[^'\n]+)'\s*\nexit\s+(?P<status>[1-9]\d*)\s*", code, re.I)
    else:
        match = re.match(
            r"(?:set -euo pipefail\s*)?printf\s+'%s\\n'\s+'(?P<message>[^'\n]+)'"
            r"\s+>&2\s*\nexit\s+(?P<status>[1-9]\d*)\s*(?:\n|$)", code)
    if match is None:
        return ["§10.12 legacy entry must refuse at startup and exit nonzero before commands/cleanup"]
    message = match['message']
    issues = []
    if not re.search(r'refus|disabled', message, re.I):
        issues.append("§10.12 startup message must explicitly refuse legacy loading")
    if "python -m app.cli daily-bars-import-tdx" not in message:
        issues.append("§10.12 startup refusal must give python -m app.cli daily-bars-import-tdx")
    return issues


@scenarios
def test_ta172_day_load_runner_new_session_bj_gate(scenario):
    _, issues = setup_scenario(scenario)
    text = source("src/backend/probes/tb143_day_load_runner.ps1")
    code = re.sub(r'<#.*?#>', '', text, flags=re.S)
    code = '\n'.join(line for line in code.splitlines() if not line.lstrip().startswith('#'))
    if re.search(r'\b(?:confirmed|bj_confirmed)\s*=\s*[\"\x27]?1\b', code, re.I):
        issues.append("§10.10 new runner session inherits boolean admission")
    annual = re.search(
        r'for\s*\(\$i\s*=\s*0;\s*\$i\s*-lt\s*\$csvs\.Count;[^\n]+\)\s*\{'
        r'(?P<body>.*?)Write-Log\s+"TOTAL', code, re.S | re.I)
    if annual is None or not re.search(
        r'&\s*\$python\s+-m\s+app\.cli\.tb143_day_load\s+'
        r'--csv\s+\$localCsv\s+--before\s+\$Before\b', annual['body'], re.I
    ):
        issues.append("§10.12 each annual CSV must start python -m app.cli.tb143_day_load")
    if re.search(r'\bpsql\b|\bInvoke-Sqlcmd\b', code, re.I) or TARGET_DML.search(code):
        issues.append("§10.12 runner must not execute package SQL or direct target DML")
    if not re.search(r'if\s*\(\$loadExit\s*-ne\s*0\)\s*\{\s*throw\b', code, re.I):
        issues.append("§10.12 Python failure must stop annual loading")
    if not re.search(r'\}\s*catch\s*\{\s*\$exitCode\s*=\s*[1-9]\d*', code, re.I) or not re.search(
        r'\bexit\s+\$exitCode\s*$', code, re.I
    ):
        issues.append("§10.12 runner failure must exit nonzero")
    # Both container and local artifact cleanup must be conditional on every year succeeding.
    if not re.search(r'\$allYearsSucceeded\s*=\s*\$false', code, re.I) or not re.search(
        r'Write-Log\s+"TOTAL[^\n]*\n\s*\$allYearsSucceeded\s*=\s*\$true', code, re.I
    ):
        issues.append("§10.12 artifact cleanup may be enabled only after all years succeed")
    container_cleanup = re.search(
        r'if\s*\(\$allYearsSucceeded\)\s*\{\s*Invoke-Docker\s+@\('
        r"'exec',\s*\$Container,\s*'rm',\s*'-rf',\s*'/tmp/tb143d'\)", code, re.I
    )
    local_cleanup = re.search(
        r'if\s*\(\$allYearsSucceeded\s+-and\s+\$exitCode\s+-eq\s*0\)\s*\{'
        r"(?P<body>.*?)\}\s*else\s*\{\s*Write-Log\s+'KEEP local", code, re.S | re.I
    )
    if not container_cleanup or not local_cleanup or not re.search(
        r'\bRemove-Item\s+-LiteralPath\s+\$file\.FullName', local_cleanup['body'], re.I
    ):
        issues.append("§10.12 failed runner must retain container and local artifacts")
    if "失败保留文件" not in text:
        issues.append("§10.12 runner must describe retaining files on failure")
    if "python -m app.cli daily-bars-import-tdx" not in code:
        issues.append("§10.12 runner errors must give python -m app.cli daily-bars-import-tdx")
    if scenario == "blocked_not_ok" and not re.search(
        r'if\s*\(\$skippedBj\s*-gt\s*0\)\s*\{\s*throw\b', code, re.I
    ):
        issues.append("§10.10/B5 BJ blocked rows must stop loading and keep artifacts")
    fail_findings(issues)


@scenarios
def test_ta172_drill_sample_data_bj_gate(scenario):
    _, issues = setup_scenario(scenario)
    text = source("deploy/db/drill/sample-data.sql")
    issues += drill_isolation_findings()
    if "confirm_bj_offline_volume_units" in executable_sql(text):
        issues.append("§10.10 isolated security_id seeds cannot produce production admission")
    fail_findings(issues)


@scenarios
def test_ta172_restore_drill_no_production_bj_support(scenario):
    _, issues = setup_scenario(scenario)
    text = source("deploy/scripts/db-restore-drill.sh")
    # Check actual isolation boundary, not permission to use a production endpoint.
    if not all(token in text for token in (
        "SRC_DB=aia_drill", "DST_DB=aia_drill_restored", "start_pg", "trap cleanup EXIT",
    )):
        issues.append("§10.11 restore drill must stay in disposable drill databases")
    issues += drill_isolation_findings()
    if "confirm_bj_offline_volume_units" in text:
        issues.append("§10.10 restore results must not be production BJ credentials")
    fail_findings(issues)


def shell_functions(text):
    """Extract top-level function definitions, excluding all script startup code.

    The registered scripts use either one-line functions or a closing brace at
    column zero. Fail closed on a changed format; never source the drill script.
    """
    functions = []
    pending = []
    for line in text.splitlines():
        if not pending and re.match(r'^\w+\(\)\s*\{', line):
            pending = [line]
            if re.search(r';\s*}\s*$', line):
                functions.append(line)
                pending = []
        elif pending:
            pending.append(line)
            if re.fullmatch(r'}\s*', line):
                functions.append('\n'.join(pending))
                pending = []
    assert not pending, "unclosed shell function: isolated drill harness must be reviewed"
    return '\n'.join(functions)


def drill_sql_probe(definitions, *, container, database, mode, label):
    """Only shell builtins and fake command sinks; no Docker, psql or network.

    Execute the real psql_in/common.aia_psql guard chain with synthetic targets.
    No script startup, file sourcing, SQL, report writes or cleanup is executed.
    """
    script = 'set -euo pipefail\n' + definitions + r'''
RUN_ID=synthetic-run
SRC=aia-drill-src-synthetic; DST=aia-drill-dst-synthetic
SRC_DB=aia_drill; DST_DB=aia_drill_restored
aia_log() { printf '%s\n' "$*" >&2; }
aia_die() { aia_log "$*"; exit 1; }
aia_docker() {
    if [[ "$1" == inspect || ( "$1" == container && "${2:-}" == inspect ) ]]; then
        printf 'INSPECT|%s\n' "$*" >&2
        if [[ "$*" != *aia.drill* ]]; then
            printf 'UNEXPECTED_INSPECTION\n' >&2; return 97
        fi
        printf '%s\n' "$SYNTHETIC_LABEL"
    elif [[ "$1" == exec ]]; then
        printf 'EVENT_SQL\n' >&2
        printf 'TARGET_SQL|%s\n' "$*"
    else
        printf 'UNEXPECTED_DOCKER|%s\n' "$*" >&2; return 97
    fi
}
docker() { aia_docker "$@"; }
psql() { printf 'DIRECT_SQL|%s\n' "$*"; }
psql_in "$SYNTHETIC_CONTAINER" "$SYNTHETIC_DATABASE" -c 'SELECT synthetic_probe'
'''
    # Deliberately bypass only the blanket Popen denial for this fixed bash input.
    # Empty PATH and env prevent real tools, user config, credentials or endpoints.
    with _CONTROLLED_POPEN(
        ['/bin/bash', '--noprofile', '--norc'], stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        env={"PATH": "/nonexistent", "LC_ALL": "C", "AIA_PSQL_MODE": mode,
             "SYNTHETIC_CONTAINER": container, "SYNTHETIC_DATABASE": database,
             "SYNTHETIC_LABEL": label},
    ) as proc:
        stdout, stderr = proc.communicate(script, timeout=5)
        return proc.returncode, stdout, stderr


def drill_isolation_findings():
    issues = []
    sample = executable_sql(source("deploy/db/drill/sample-data.sql"))
    schema = executable_sql(source("deploy/db/drill/sample-schema.sql"))
    drill = source("deploy/scripts/db-restore-drill.sh")
    if re.search(r'\bcode\b|\.BJ\b|\b(?:[489]\d{5}|920\d{3})\b', sample + schema, re.I):
        issues.append("§10.12 drill sample must have no BJ codes or code-column mapping")
    if not re.search(r'INSERT\s+INTO\s+market\.daily_bars\s*\(\s*security_id\b', sample, re.I):
        issues.append("§10.12 drill sample must model real drill data by security_id")
    if "confirm_bj_offline_volume_units" in sample + schema + drill:
        issues.append("§10.12 isolated drill cannot produce production confirmation credentials")
    definitions = shell_functions(source("deploy/scripts/lib/common.sh")) + '\n' + shell_functions(drill)
    if not re.search(r'^psql_in\(\)', definitions, re.M):
        return issues + ["§10.12 isolated drill SQL boundary psql_in is missing"]
    # Positive controls forbid satisfying rejection checks by disabling all SQL.
    for container, database in (("aia-drill-src-synthetic", "aia_drill"),
                                ("aia-drill-dst-synthetic", "aia_drill_restored")):
        rc, out, err = drill_sql_probe(definitions, container=container, database=database,
                                      mode="exec", label="synthetic-run")
        if not (rc == 0 and "TARGET_SQL|" in out and "INSPECT|" in err
                and "EVENT_SQL" in err and err.index("INSPECT|") < err.index("EVENT_SQL")
                and "aia.drill" in err and container in out
                and f"AIA_TARGET_DB={database}" in out and "DIRECT_SQL|" not in out):
            issues.append(f"§10.12 labelled drill container/database must be verified before SQL: {container}/{database}")
    for container, database, mode, label in (
        ("synthetic-production", "aia_drill", "exec", ""),
        ("aia-drill-src-synthetic", "aia_drill", "exec", ""),
        ("aia-drill-src-synthetic", "synthetic_production", "exec", "synthetic-run"),
        ("aia-drill-src-synthetic", "postgres", "exec", "synthetic-run"),
        ("aia-drill-src-synthetic", "aia_drill", "direct", "synthetic-run"),
        ("direct", "aia_drill", "exec", "synthetic-run"),
    ):
        rc, out, err = drill_sql_probe(definitions, container=container, database=database,
                                      mode=mode, label=label)
        if not (rc not in (0, 97, 127) and err.strip() and "command not found" not in err
                and "TARGET_SQL|" not in out and "DIRECT_SQL|" not in out):
            issues.append(f"§10.12 drill must refuse non-drill/direct target before SQL: {container}/{database}/{mode}")
    return issues


@scenarios
def test_ta172_pg_selfcheck_isolated_seed_only(scenario):
    _, issues = setup_scenario(scenario)
    text = source("src/backend/probes/tb143_pg_selfcheck.sh")
    issues += startup_refusal_findings(text, powershell=False)
    # Isolated FAKE seeds are allowed. Its load chain cannot retain production DML.
    if "tb143_load_day.sql" in text:
        issues += sql_findings(source("src/backend/probes/tb143_load_day.sql"), scenario)
    if re.search(r"(?:export|set_config)[^\n]*(?:bj_confirmed|BJ_CONFIRMED)", text):
        issues.append("§10.10 fake seed exports a production admission flag")
    fail_findings(issues)


SELFCHECK_DML = (
    "tb49c.py", "test_tb91_fixes.py", "test_tb91_closing.py", "test_tb127_daily_bars.py",
    "test_tb128_daily_snapshot.py", "test_p2n03_tracking.py", "test_s2_owned_daily_bars.py",
    "test_ta26_rc1.py", "test_tb133_tdx_db.py", "test_tb141_verify_and_owned_snapshot.py",
)
TEST_DML = (
    "unit/test_daily_bars_plan_c2.py", "unit/test_daily_bars_resume_c2.py",
    "unit/test_daily_bars_window_consumer_c2.py", "unit/test_daily_bars_late_history_c2.py",
    "unit/test_daily_snapshot_impl_b.py", "unit/test_mairui_licence_bind_t_b141.py",
    "unit/test_set_licence_retain_id_t_b141.py", "unit/test_daily_bars_source_impl_a_t_t70.py",
    "unit/test_tb143_multi_source_pg.py", "api_app/test_rulings_t_b46_47_t_t25d.py",
)


def isolated_dml_contract(scenario, prefix, files):
    _, issues = setup_scenario(scenario)
    for filename in files:
        text = source(prefix + filename)
        tree = ast.parse(text)
        # Read AST only: importing historical selfchecks can connect to PG at import.
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]
        for call in calls:
            name = ast.unparse(call.func)
            if name.endswith("confirm_bj_offline_volume_units"):
                issues.append(f"§10.10 {filename}: isolated DML cannot grant production admission")
            if name.endswith(("write_text", "write_bytes", "setenv", "putenv")):
                if re.search(r"bj[_-]?(?:confirmed|confirmation)", ast.unparse(call), re.I):
                    issues.append(f"§10.10 {filename}: persisted production BJ confirmation")
        # Static declaration of isolation must be backed by an actual temp DB,
        # fixture, or the registered selfcheck harness (not just a comment).
        isolation_refs = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        isolation_refs.update(node.asname or node.name for node in ast.walk(tree)
                              if isinstance(node, ast.alias))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        if not (isolation_refs & {"pg_conn", "temp_db", "head_db", "_open_temp_db", "world", "env"}
                or "_common" in imports or "selfchecks._common" in imports
                or "CREATE DATABASE" in text or "create_database" in text):
            if "authdb" in isolation_refs:
                harness = source("tests/backend/api_app/test_auth_t_b03.py")
                if not all(token in harness for token in ("def authdb(pg_url:", "CREATE DATABASE",
                                                         "DROP DATABASE IF EXISTS")):
                    issues.append(f"§10.11 {filename}: authdb lifetime is unverified")
            else:
                issues.append(f"§10.11 {filename}: isolation of DML is unverified")
    # Regardless of which malformed synthetic proof preceded this source scan,
    # seed/model construction alone must not restore admission after revocation.
    revoke()
    load = module("probes.tb140_history_load")
    load.apply_insert_offline(set(), [normalized(SH), normalized(SZ), normalized(BJ)])
    if not load._bj_write_unconfirmed(normalized(BJ)):
        issues.append("§10.10 isolated DML seed created production confirmation")
    fail_findings(issues)


@scenarios
def test_ta172_selfcheck_dml_isolated_only(scenario):
    isolated_dml_contract(scenario, "src/backend/selfchecks/", SELFCHECK_DML)


@scenarios
def test_ta172_test_dml_no_production_confirmation(scenario):
    isolated_dml_contract(scenario, "tests/backend/", TEST_DML)


def test_ta172_tdx_import_confirmed_keeps_shares(monkeypatch, tmp_path):
    accepted, reason = confirm(pairs())
    assert accepted, f"synthetic protocol positive control: {reason}"
    obs = run_public(monkeypatch, "app.cli.tdx_import", tmp_path)
    fail_findings(check_observation(obs, True))
    assert next(row for row in obs.rows if row["code"] == BJ)["volume"] == 100


@pytest.mark.parametrize("code", ["920999.SH", "920999", "009999.BJ"])
def test_ta172_confirmation_does_not_waive_identity(monkeypatch, tmp_path, code):
    accepted, reason = confirm(pairs())
    assert accepted, f"synthetic protocol positive control: {reason}"
    try:
        obs = run_public(monkeypatch, "marketdata.daily_bars.upsert_daily_bars",
                         tmp_path, codes=(code,))
    except ValueError:
        return  # Explicit invalid-identity rejection is valid; no success assertion.
    assert not obs.rows, "§10.2/B2 confirmation must not waive qualified-code identity validation"


@pytest.mark.parametrize("consumer", [
    "marketdata.daily_bars.upsert_daily_bars", "app.ingest.daily_bars", "app.cli.tdx_import",
    "marketdata.daily_bars.fetch_and_record", "tb140_history_load.apply_daily_bars",
    "tb140_history_load.apply_insert_artifact",
])
def test_ta172_failed_confirmation_clears_old_state(monkeypatch, tmp_path, consumer):
    assert confirm(pairs())[0]
    assert not confirm(pairs()[:19])[0], "§10.2 19 distinct codes cannot confirm"
    obs = run_public(monkeypatch, consumer, tmp_path)
    assert BJ not in {row["code"] for row in obs.rows}, "§10.10 failed confirmation retained old admission"


def test_ta172_rendered_artifact_replay_after_revocation(monkeypatch, tmp_path):
    load = module("probes.tb140_history_load")
    assert confirm(pairs())[0]
    text = load.render_insert_sql([normalized(code) for code in CODES], None, bind_note="synthetic")
    path = tmp_path / "generated-then-revoked.sql"
    path.write_text(text, encoding="utf-8")
    assert not confirm(pairs()[:19])[0]
    db = MemoryDB()
    calls = instrument(monkeypatch)
    stats = load.apply_insert_artifact(db, path, reconcile_path=tmp_path / "audit.jsonl")
    obs = Observation(rows=db.rows, stats=stats, public_calls=len(calls))
    issues = check_observation(obs, False) + sql_findings(text, "bj_default_blocked")
    fail_findings(issues)


@scenarios
def test_ta172_upsert_gate_precedes_cross_source_update(scenario):
    from ta172_bj_gate_support import Result

    allowed, issues = setup_scenario(scenario)
    writer = module("app.marketdata.daily_bars")

    class ExistingTdx(MemoryDB):
        def execute(self, statement):
            if getattr(statement, "is_insert", False):
                return Result()  # Existing tdx_local PK, so INSERT conflicts.
            if getattr(statement, "is_select", False):
                old = vars(bar()).copy()
                old.update(source="tdx_local", volume=200)
                return Result([old])
            return super().execute(statement)

    db, audit = ExistingTdx(), []
    stats = writer.upsert_daily_bars(
        db, writer.DailyBarsResult(bars=(bar(),)), source="mairui",
        licence_id=None, fetched_at=NOW, reconcile_sink=audit.append)
    if not allowed and (db.rows or stats.replaced):
        issues.append("§10.2/10.10/B4 unconfirmed BJ reached cross-source UPDATE")
    if allowed and stats.replaced != 1:
        issues.append("§10.10 valid synthetic confirmation must reach audited public writer")
    fail_findings(issues)


def test_ta172_fixture_precision_is_exact():
    # The independent oracle uses integer ratios, never float or Decimal arithmetic
    # under a 28-digit context; production is tested under its normal context.
    from decimal import Decimal

    pair = pairs("precision_tail")[0]
    n, d = Decimal(pair["mairui"]["v"]).as_integer_ratio()
    assert n * 100 != 100 * d
    assert len({p["mairui"]["t"] for p in pairs("cross_day")}) == 20


def test_ta172_official_matrix_names_complete():
    assert len(ENTRY_TESTS) == 20
    for name in ENTRY_TESTS.values():
        assert name in globals() and callable(globals()[name]), name


PROCESS_ENTRIES = (
    "marketdata.daily_bars.upsert_daily_bars", "app.ingest.daily_bars", "app.cli.tdx_import",
    "marketdata.daily_bars.fetch_and_record", "tb140_history_load.render_insert_sql",
    "tb140_history_load.apply_daily_bars", "tb140_history_load.apply_insert_artifact",
    "tb140_history_load.apply_insert_offline", "tb140_history_backfill.run_batch",
    "tb140_history_supervisor.run_supervised",
    "mairui-licence-bind → update_mairui_source_licence_id",
)


def child_observation(name, tmp_path):
    """Actual adapters in a fresh interpreter or fork, never replace gate decisions."""
    load = module("probes.tb140_history_load")
    with pytest.MonkeyPatch.context() as patch:
        if name in PROCESS_ENTRIES[:4] or name in PROCESS_ENTRIES[5:7]:
            obs = run_public(patch, name, tmp_path)
            findings = check_observation(obs, False, runtime_status=name in PROCESS_ENTRIES[1:2] + PROCESS_ENTRIES[3:4])
        elif name == "tb140_history_load.render_insert_sql":
            text = load.render_insert_sql([normalized(code) for code in CODES], None, bind_note="synthetic")
            findings = sql_findings(text, "bj_default_blocked")
            if BJ in executable_sql(text):
                findings.append("§10.10/B3 child process inherited BJ SQL generation admission")
        elif name == "tb140_history_load.apply_insert_offline":
            stats = load.apply_insert_offline(set(), [normalized(code) for code in CODES])
            findings = [] if stats.get("blocked_bj_unconfirmed") == 1 and stats["inserted"] == 2 else [
                "§10.10/B3 child process inherited simulation admission"]
        elif name == "mairui-licence-bind → update_mairui_source_licence_id":
            writer = module("app.marketdata.daily_bars")
            findings = []
            calls = instrument(patch)
            for operation, match, value in (("bind", None, IDENT), ("rebind", IDENT, OTHER),
                                            ("rollback", OTHER, IDENT)):
                db = MemoryDB()
                writer.update_mairui_source_licence_id(
                    db, [(code, DAY, "none") for code in CODES],
                    match=match, value=value, apply=True)
                if BJ in {row["code"] for row in db.rows}:
                    findings.append(f"§10.10 {operation}: new process wrote unconfirmed BJ metadata")
                if not {SH, SZ} <= {row["code"] for row in db.rows}:
                    findings.append(f"§10.2 {operation}: SH/SZ original path unavailable")
            if not calls:
                findings.append("§10.10 independent metadata UPDATE still bypasses public writer")
        else:
            obs = batch_observation(patch, tmp_path, name.endswith("run_supervised"))
            findings = check_observation(obs, False) + sql_findings(obs.sql, "bj_default_blocked")
            if BJ[:6] in obs.ledger.get("done_history", []):
                findings.append("§10.10/B5 child process marked blocked BJ complete")
    if not load._bj_write_unconfirmed(normalized()):
        findings.append("§10.10/B3 new process inherited parent confirmation")
    return findings


# -I ignores Python/user environment; only these two explicit repository paths are
# inserted. The child gets a clean environment and audit hook before app imports.
_CHILD = r'''
import importlib.util, json, os, pathlib, sys
def guard(event, args):
    if event.startswith('socket.') or event in ('subprocess.Popen', 'os.system', 'os.exec', 'os.posix_spawn'):
        raise AssertionError('T-T94 child: network/external command forbidden')
    if event == 'open' and isinstance(args[0], (str, bytes)):
        path = pathlib.Path(os.fsdecode(args[0]))
        if any(p in ('.aws', '.ssh') for p in path.parts) or path.name.startswith('.env') or path.suffix in ('.pem', '.key'):
            raise AssertionError('T-T94 child: credential path forbidden')
sys.addaudithook(guard)
sys.dont_write_bytecode = True
sys.path[:0] = sys.argv[1:3]
spec = importlib.util.spec_from_file_location('ta172_controlled_child', sys.argv[3])
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
result = suite.child_observation(sys.argv[4], pathlib.Path(sys.argv[5]))
print('TA172_RESULT=' + json.dumps(result))
'''


@pytest.mark.parametrize("name", PROCESS_ENTRIES)
@pytest.mark.parametrize("context", ["new_interpreter", "fork"])
def test_ta172_python_entries_do_not_inherit_confirmation(monkeypatch, tmp_path, name, context):
    assert confirm(pairs())[0], "synthetic protocol positive control"
    if context == "new_interpreter":
        # Sole subprocess exception: fixed -I program, clean env, in-child audit
        # denies all network/external commands, no shell and no user configuration.
        with monkeypatch.context() as controlled:
            controlled.setattr(subprocess, "Popen", _CONTROLLED_POPEN)
            result = subprocess.run(
                [sys.executable, "-I", "-c", _CHILD, str(ROOT / "src/backend"),
                 str(Path(__file__).parent), str(Path(__file__)), name, str(tmp_path)],
                env={"PATH": os.defpath, "PYTHONDONTWRITEBYTECODE": "1"},
                cwd=tmp_path, text=True, capture_output=True, timeout=30, check=False)
        assert result.returncode == 0, f"controlled child failed: {result.stderr}"
        payloads = [line.partition("=")[2] for line in result.stdout.splitlines()
                    if line.startswith("TA172_RESULT=")]
        assert len(payloads) == 1, result.stdout
        findings = json.loads(payloads[0])
    else:
        # Anonymous pipe only. Inherited fixture already denies sockets/commands.
        assert hasattr(os, "fork"), "fork isolation is unverified on this platform"
        read_fd, write_fd = os.pipe()
        pid = os.fork()
        if pid == 0:
            os.close(read_fd)
            try:
                findings = child_observation(name, tmp_path)
                os.write(write_fd, json.dumps(findings).encode())
                os._exit(0)
            except BaseException as exc:
                os.write(write_fd, json.dumps([f"child adapter error: {type(exc).__name__}: {exc}"]).encode())
                os._exit(1)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as pipe:
            payload = pipe.read()
        _, status = os.waitpid(pid, 0)
        assert status == 0, payload.decode()
        findings = json.loads(payload)
    fail_findings(findings)

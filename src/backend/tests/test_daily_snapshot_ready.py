"""Routine readiness with synthetic query results, without a database or transport."""

# ruff: noqa: S101

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from sqlalchemy import Connection
from sqlalchemy.dialects import postgresql

from app.config import Settings
from app.marketdata import daily_snapshot
from app.marketdata.daily_bars import daily_bars_fetch_task
from app.workers import jobs

OWNER = uuid.UUID(int=168)
OTHER = uuid.UUID(int=169)
DAY = dt.date(2030, 12, 31)
CODE = "699001.SH"
MISSING = "missing"


def _run(
    *, status: str = "ok", owner: uuid.UUID | None = OWNER, **stats: object
) -> SimpleNamespace:
    return SimpleNamespace(status=status, stats={"user_id": str(owner) if owner else None, **stats})


@pytest.fixture
def conn(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    connection = MagicMock(spec=Connection)
    # Only readiness may decide whether to query the synthetic owner's universe.
    monkeypatch.setattr(daily_snapshot, "daily_universe", lambda *_: [CODE])
    return connection


@pytest.mark.parametrize("status", ["ok", "partial", "failed", "running"])
@pytest.mark.parametrize("window", [MISSING, None])
def test_windowed_run_does_not_shadow_routine_run(
    conn: MagicMock, status: str, window: str | None
) -> None:
    stats = {} if window == MISSING else {"window_trading_days": window}
    missing = f"daily_bars_missing:{CODE}"
    conflict = f"daily_bar_conflict:{CODE}:{DAY}"
    routine = _run(
        **stats,
        issues=[missing, conflict, missing, "daily_bars_missing:920999.BJ", "unrelated", 1],
    )
    # execute().all() supplies rows in the query's descending timestamp order.
    conn.execute.return_value.all.return_value = [
        _run(status=status, window_trading_days=20, issues=["daily_bars_missing:920999.BJ"]),
        routine,
    ]

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (
        True,
        tuple(sorted([missing, conflict])),
    )


@pytest.mark.parametrize("status", ["ok", "partial"])
@pytest.mark.parametrize(
    "stats",
    [
        {"window_trading_days": 20},
        {"batch_kind": "backfill"},
        {"batch_kind": "backfill", "window_trading_days": None},
        {"batch_kind": "backfill", "window_trading_days": 20},
    ],
)
def test_history_only_is_not_ready(
    conn: MagicMock, status: str, stats: dict[str, object]
) -> None:
    conn.execute.return_value.all.return_value = [_run(status=status, **stats)]

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (False, ())


@pytest.mark.parametrize("window", [MISSING, None, 20])
@pytest.mark.parametrize("status", ["ok", "failed"])
def test_backfill_does_not_shadow_routine_run(
    conn: MagicMock, window: str | int | None, status: str
) -> None:
    stats = {} if window == MISSING else {"window_trading_days": window}
    issue = f"daily_bars_missing:{CODE}"
    conn.execute.return_value.all.return_value = [
        _run(batch_kind="backfill", status=status, **stats),
        _run(issues=[issue]),
    ]

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (True, (issue,))


@pytest.mark.parametrize("older_success", [False, True])
def test_latest_failed_routine_does_not_fall_back(conn: MagicMock, older_success: bool) -> None:
    rows = [_run(window_trading_days=20), _run(status="failed")]
    if older_success:
        rows.append(_run())
    conn.execute.return_value.all.return_value = rows

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (False, ())


@pytest.mark.parametrize(
    ("status", "expected"), [("ok", True), ("partial", True), ("failed", False)]
)
@pytest.mark.parametrize("owner", [OWNER, None])
def test_latest_applicable_routine_keeps_owner_scope(
    conn: MagicMock, status: str, expected: bool, owner: uuid.UUID | None
) -> None:
    conn.execute.return_value.all.return_value = [
        _run(owner=OTHER),
        _run(owner=owner, status=status),
        _run(),
    ]

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (expected, ())


def test_another_owners_routine_is_not_ready(conn: MagicMock) -> None:
    conn.execute.return_value.all.return_value = [_run(owner=OTHER)]

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (False, ())


def test_query_keeps_date_kind_step_and_timestamp_order(conn: MagicMock) -> None:
    conn.execute.return_value.all.return_value = []

    assert daily_snapshot.daily_bars_ready(conn, OWNER, DAY) == (False, ())
    statement = conn.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert set(statement.params.values()) == {"daily_batch", "daily_bars.fetch", DAY}
    assert "ORDER BY app.pipeline_runs.started_at DESC, app.pipeline_runs.finished_at DESC" in str(
        statement
    )


def test_fetch_task_rejects_backfill_without_window_before_opening_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Mock(side_effect=AssertionError("invalid backfill must not open an engine"))
    monkeypatch.setattr(jobs, "_engine", engine)
    settings = Settings(_env_file=None, app_env="test")

    with pytest.raises(ValueError, match="window_trading_days is required for backfill"):
        daily_bars_fetch_task(settings, DAY.isoformat(), str(OWNER), batch_kind="backfill")

    engine.assert_not_called()

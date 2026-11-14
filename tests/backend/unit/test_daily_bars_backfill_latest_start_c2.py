"""Latest-start guard with synthetic Redis/transport; no upstream or credentials."""

from __future__ import annotations

import datetime as dt
from dataclasses import replace
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

import pytest
from app.cli import daily_bars_backfill as cli
from app.ingest import daily_bars as fetcher
from app.ingest import daily_bars_plan as plan
from app.workers import jobs
from sqlalchemy import Engine

from tests.backend.unit.test_daily_bars_consumer_c2 import (
    DAY,
    facts,
    implementation,
    queue,
    world,  # noqa: F401
)
from tests.backend.unit.test_daily_bars_time_gate_c2 import Redis, at

DENVER = ZoneInfo("America/Denver")


@pytest.fixture
def cli_state(monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    engine = MagicMock(spec=Engine)
    monkeypatch.setattr(jobs, "_engine", lambda _: engine)
    monkeypatch.setattr(cli, "_is_open", lambda *_: True)
    monkeypatch.setattr(cli, "_previous_open", lambda *_: DAY)
    monkeypatch.setattr(cli, "backfill_window_days", lambda *_: 5)
    monkeypatch.setattr(cli, "_universe_size", lambda *_: 2)

    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("CLI must only enqueue; no outbox, transport or real Redis")

    monkeypatch.setattr(jobs, "_redis", forbidden)
    monkeypatch.setattr(fetcher, "fetch_mairui_daily_bars", forbidden)
    return SimpleNamespace(engine=engine, redis=Redis())


def run_cli(state: SimpleNamespace, stamp: dt.datetime, *, apply: bool = True) -> int:
    args = ["--years", "3", "--trade-date", DAY.isoformat()]
    if apply:
        args.append("--apply")
    return cli.main(args, now=stamp, redis_client=state.redis, settings=SimpleNamespace())


@pytest.mark.parametrize(
    ("stamp", "blocked"),
    [
        (at(22, 44, 59), False),
        (at(22, 45), True),
        (at(22, 45, 1), True),
        (dt.datetime(2026, 11, 12, 7, 44, 59, tzinfo=DENVER), False),
        (dt.datetime(2026, 11, 12, 7, 45, tzinfo=DENVER), True),
        (dt.datetime(2026, 11, 12, 14, 44, 59, tzinfo=dt.UTC), False),
        (dt.datetime(2026, 11, 12, 14, 45, tzinfo=dt.UTC), True),
        (at(0) + dt.timedelta(days=1), False),
    ],
)
def test_cli_apply_boundary_and_timezones(
    cli_state: SimpleNamespace,
    stamp: dt.datetime,
    blocked: bool,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert plan.backfill_start_blocked(stamp) is blocked
    assert (run_cli(cli_state, stamp) != 0) is blocked
    assert len(cli_state.redis.queued) == int(not blocked)
    cli_state.engine.begin.assert_not_called()
    if blocked:
        assert "北京时间最晚启动守卫" in capsys.readouterr().out
        cli_state.engine.connect.assert_not_called()


def test_cli_dry_run_after_guard(
    cli_state: SimpleNamespace,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert run_cli(cli_state, at(22, 45, 1), apply=False) == 0
    assert "dry-run" in capsys.readouterr().out
    assert cli_state.redis.queued == []
    cli_state.engine.begin.assert_not_called()


def test_guard_applies_on_closed_day(
    cli_state: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli, "_is_open", lambda *_: False)
    assert (
        cli.main(
            ["--years", "3", "--apply"],
            now=at(22, 44, 59),
            redis_client=cli_state.redis,
            settings=SimpleNamespace(),
        )
        == 0
    )
    cli_state.redis.queued.clear()
    assert run_cli(cli_state, at(22, 45)) != 0
    assert cli_state.redis.queued == []


def test_shared_threshold_is_patchable(
    cli_state: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plan, "BACKFILL_LATEST_START", dt.time(21))
    assert not plan.backfill_start_blocked(at(20, 59, 59))
    assert plan.backfill_start_blocked(at(21))
    assert run_cli(cli_state, at(21)) != 0
    assert cli_state.redis.queued == []


def test_naive_datetime_is_rejected(cli_state: SimpleNamespace) -> None:
    naive = dt.datetime(2026, 11, 12, 22, 45)
    with pytest.raises(ValueError, match="now must be timezone-aware"):
        plan.backfill_start_blocked(naive)
    assert run_cli(cli_state, naive) != 0
    assert cli_state.redis.queued == []


@pytest.fixture
def late(world: SimpleNamespace) -> SimpleNamespace:  # noqa: F811 - reused fixture
    world.grant = replace(world.grant, end=at(23, 59, 59))
    world.stamp = at(22, 44, 59)
    world.redis = Redis()
    return world


def tick(state: SimpleNamespace) -> int:
    return implementation().tick(
        state.engine,
        redis_client=state.redis,
        transport=state.transport,
        grant_reader=lambda _: state.grant,
        clock=lambda: state.stamp,
        stop=state.root / "STOP",
        halt=state.root / "HALTED",
    )


@pytest.mark.parametrize("seq", [0, 1])
@pytest.mark.parametrize("entry", ["tick", "process"])
def test_unstarted_backfill_expires_without_transport(
    late: SimpleNamespace,
    seq: int,
    entry: str,
) -> None:
    bid = queue(late, kind="backfill", seq=seq)
    late.stamp = at(22, 45)
    if entry == "tick":
        assert tick(late) == 1
    else:
        assert (
            implementation().process(
                late.engine,
                bid,
                transport=late.transport,
                grant_reader=lambda _: late.grant,
                clock=lambda: late.stamp,
                stop=late.root / "STOP",
                halt=late.root / "HALTED",
                continue_batches=True,
            )
            == "failed"
        )
    items, runs, count = facts(late)
    assert items[0].status == "failed"
    assert items[0].attempted_at is None
    assert items[0].error_code == runs[0].error == "daily_bars_batch_expired"
    assert count == 0
    assert late.calls == []
    assert late.redis.delayed == {}


def test_daily_starts_after_guard(late: SimpleNamespace) -> None:
    queue(late, kind="daily")
    late.stamp = at(22, 45, 1)
    assert tick(late) == 1
    assert facts(late)[0][0].status == "done"
    assert len(late.calls) == 2


def test_committed_resume_expires_after_guard(
    late: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 1)
    bid = queue(late, kind="backfill")
    module = implementation()
    assert (
        module.process(
            late.engine,
            bid,
            transport=late.transport,
            grant_reader=lambda _: late.grant,
            clock=lambda: late.stamp,
            stop=late.root / "STOP",
            halt=late.root / "HALTED",
            continue_batches=True,
        )
        == "done"
    )
    assert facts(late)[0][0].error_code == module.RESUME_PENDING
    late.stamp = at(22, 45)
    assert tick(late) == 0
    items, runs, count = facts(late)
    assert len(items) == len(runs) == count == len(late.calls) == 1
    assert items[0].error_code == "daily_bars_batch_expired"
    assert "daily_bars_batch_expired" in runs[0].stats["issues"]
    assert late.redis.delayed == {}


def test_running_backfill_finishes_across_guard_without_continuation(
    late: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    codes = ["999991.SH", "999992.SH", "999993.SH"]
    monkeypatch.setattr(fetcher, "daily_universe", lambda *_: codes)
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 2)
    original = cast(fetcher.Transport, late.transport)

    def send(
        code: str,
        start: dt.date,
        end: dt.date,
    ) -> tuple[int, fetcher.DailyBar | fetcher.DailyBarsResult | None]:
        result = original(code, start, end)
        late.stamp = at(22, 45)
        return result

    late.transport = send
    queue(late, kind="backfill")
    assert tick(late) == 1
    items, runs, count = facts(late)
    assert len(late.calls) == count == 2
    assert len(items) == len(runs) == 1
    assert items[0].status == "done"
    assert items[0].error_code == "daily_bars_batch_expired"
    assert tick(late) == 0
    assert len(late.calls) == 2




def test_resume_rechecks_guard_after_grant(
    late: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetcher, "DAILY_BARS_BACKFILL_BATCH_LIMIT", 1)
    bid = queue(late, kind="backfill")
    module = implementation()
    assert (
        module.process(
            late.engine,
            bid,
            transport=late.transport,
            grant_reader=lambda _: late.grant,
            clock=lambda: late.stamp,
            stop=late.root / "STOP",
            halt=late.root / "HALTED",
            continue_batches=True,
        )
        == "done"
    )
    assert facts(late)[0][0].error_code == module.RESUME_PENDING

    def read(_: object) -> object:
        late.stamp = at(22, 45)
        return late.grant

    assert (
        module.tick(
            late.engine,
            redis_client=late.redis,
            transport=late.transport,
            grant_reader=read,
            clock=lambda: late.stamp,
            stop=late.root / "STOP",
            halt=late.root / "HALTED",
        )
        == 0
    )
    items, runs, count = facts(late)
    assert len(items) == len(runs) == count == len(late.calls) == 1
    assert items[0].error_code == "daily_bars_batch_expired"
    assert "daily_bars_batch_expired" in runs[0].stats["issues"]
    assert late.redis.delayed == {}

def test_wake_delayed_skips_backfill_after_guard(
    late: SimpleNamespace,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Overlap the existing 17:00–17:45 delay to prove the shared guard wins.
    monkeypatch.setattr(plan, "BACKFILL_LATEST_START", dt.time(17, 15))
    queue(late, kind="backfill")
    late.stamp = at(17, 20)
    implementation().wake_delayed(
        late.engine,
        late.redis,
        clock=lambda: late.stamp,
        stop=late.root / "STOP",
        halt=late.root / "HALTED",
    )
    assert late.redis.delayed == {}
    assert late.redis.queued == []
    assert late.calls == []
    assert facts(late)[0][0].status == "pending"
    assert tick(late) == 1
    assert facts(late)[0][0].error_code == "daily_bars_batch_expired"

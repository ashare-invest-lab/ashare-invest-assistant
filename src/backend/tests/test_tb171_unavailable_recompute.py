"""T-B171: synthetic tracking recomputation, only on the explicit temporary test DB."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import os
import uuid
from argparse import Namespace
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import Engine, make_url

from app.db.tables.accounts import accounts
from app.db.tables.market import daily_bars, trading_calendar
from app.db.tables.realtime import suggestion_threads, suggestion_tracking, suggestions
from app.db.tables.reviews import data_snapshots
from app.db.tables.strategy import strategies, strategy_instances, strategy_versions
from app.db.tables.users import users
from app.tracking import service
from app.tracking.engine import BEIJING, close_at
from selfchecks.test_p2n03_tracking import sample


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = os.environ.get("AIA_TEST_DATABASE_URL") or os.environ.get("TT41_DATABASE_URL")
    if not url:
        pytest.skip("AIA_TEST_DATABASE_URL or TT41_DATABASE_URL is required")
    parsed = make_url(url)
    assert parsed.host in {"127.0.0.1", "localhost", "::1"}, "T-B171 requires a local test database"
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "migrations"))
    cfg.cmd_opts = Namespace(x=["url=" + url])
    command.upgrade(cfg, "head")
    db = create_engine(url, hide_parameters=True)
    try:
        yield db
    finally:
        db.dispose()


@pytest.fixture
def case(engine: Engine) -> Iterator[Any]:
    # All synthetic rows and market changes roll back, including failed assertions.
    with engine.connect() as conn, conn.begin() as transaction:
        args = sample()
        owner, account, thread, suggestion, generation = [uuid.uuid4() for _ in range(5)]
        conn.execute(
            insert(users).values(
                id=owner,
                username="tb171_" + owner.hex[:16],
                password_hash=uuid.uuid4().hex,
                role="user",
                status="approved",
            )
        )
        conn.execute(insert(accounts).values(id=account, user_id=owner, name="T-B171 synthetic"))
        conclusions = []
        for action in ("buy", "sell"):
            strategy, version, instance = [uuid.uuid4() for _ in range(3)]
            conn.execute(insert(strategies).values(id=strategy, key=strategy.hex, name="synthetic"))
            conn.execute(
                insert(strategy_versions).values(
                    id=version,
                    strategy_id=strategy,
                    version_no=1,
                    config={},
                    config_hash=version.hex,
                )
            )
            conn.execute(
                insert(strategy_instances).values(
                    id=instance,
                    user_id=owner,
                    account_id=account,
                    strategy_version_id=version,
                    scope="account",
                    origin="user",
                    created_at=args["created"],
                )
            )
            conclusions.append(
                {
                    "strategy_version_id": str(version),
                    "instance_id": str(instance),
                    "signal": {"snapshot_id": str(generation), "proposed_action": action},
                }
            )
        body = {"schema_version": "tb75-suggestion-input-v1", "input": {"conclusions": conclusions}}
        conn.execute(
            insert(data_snapshots).values(
                id=generation,
                user_id=owner,
                purpose="suggestion",
                items=body,
                hash=service.digest(body),
                created_at=args["created"],
            )
        )
        conn.execute(
            insert(suggestion_threads).values(
                id=thread,
                user_id=owner,
                security_code="TB171.SYN",
            )
        )
        conn.execute(
            insert(suggestions).values(
                id=suggestion,
                thread_id=thread,
                user_id=owner,
                security_code="TB171.SYN",
                seq_no=1,
                origin="daily_batch",
                data_status="partial",
                snapshot_id=generation,
                created_at=args["created"],
            )
        )
        for day, is_open in args["calendar"].items():
            conn.execute(
                pg_insert(trading_calendar)
                .values(date=day, is_open=is_open)
                .on_conflict_do_update(index_elements=["date"], set_={"is_open": is_open})
            )
        due = service.due_date(args["created"], 1, args["calendar"])
        opened = [d for d, yes in sorted(args["calendar"].items()) if yes and d > due]
        scenario = {
            "conn": conn,
            "owner": owner,
            "id": suggestion,
            "args": args,
            "due": due,
            "after": opened,
            "conclusions": conclusions,
        }
        observe(scenario, close_at(due))
        yield scenario
        transaction.rollback()


def observe(case: Any, at: dt.datetime, *, missing_sell_fact: bool = False) -> None:
    values = dict(case["args"]["facts"][case["due"].isoformat()])
    if missing_sell_fact:
        values["limit_locked_down"] = None
    body = {
        "schema_version": service.OBS_SCHEMA,
        "instruments": {
            "TB171.SYN": {
                "factors": case["args"]["factors"],
                "facts": {
                    case["due"].isoformat(): {"available_at": at.isoformat(), "values": values}
                },
            }
        },
    }
    case["conn"].execute(
        insert(data_snapshots).values(
            id=uuid.uuid4(),
            user_id=case["owner"],
            purpose="report",
            items=body,
            hash=service.digest(body),
            created_at=at,
        )
    )


def bar(case: Any, day: dt.date, fetched: dt.datetime) -> None:
    value = case["args"]["instrument"]["bars"][0]
    case["conn"].execute(
        pg_insert(daily_bars)
        .values(
            code="TB171.SYN",
            trade_date=day,
            adj_type="none",
            **{key: value[key] for key in ("open", "high", "low", "close", "amount")},
            volume=100,
            fetched_at=fetched,
        )
        .on_conflict_do_update(
            index_elements=["code", "trade_date", "adj_type"],
            set_={"close": 999, "high": 1000, "fetched_at": fetched},
        )
    )


def run(case: Any, at: dt.datetime) -> tuple[Any, Any]:
    conn: Connection = case["conn"]
    service.run_one(conn, case["owner"], case["id"], at)
    row = conn.execute(
        select(suggestion_tracking).where(
            suggestion_tracking.c.suggestion_id == case["id"],
            suggestion_tracking.c.horizon_days == 1,
        )
    ).one()
    snapshot = conn.execute(
        select(data_snapshots).where(data_snapshots.c.id == row.snapshot_id)
    ).one()
    assert snapshot.hash == service.digest(snapshot._mapping["items"])
    return row, snapshot


@pytest.mark.parametrize("offset", [1, 2, 3, 4, 5])
def test_late_due_bar_completes_within_each_trading_day(case: Any, offset: int) -> None:
    first, old = run(case, close_at(case["due"]))
    assert {r["state"] for r in old._mapping["items"]["results"]} == {"unavailable"}
    assert first.status == "pending"
    at = close_at(case["after"][offset - 1])
    bar(case, case["due"], at - dt.timedelta(minutes=1))
    # A bar whose fetch is still in the future must remain invisible.
    bar(case, case["after"][0], at + dt.timedelta(minutes=1))
    row, snapshot = run(case, at)
    body = snapshot._mapping["items"]
    assert row.status == "done"
    assert {r["state"] for r in body["results"]} == {"complete"}
    assert dt.datetime.fromisoformat(body["as_of"]) == at
    assert snapshot.id != old.id
    assert body["history"][-1] == {
        "snapshot_id": str(old.id),
        "hash": old.hash,
        "as_of": old._mapping["items"]["as_of"],
        "results": old._mapping["items"]["results"],
    }
    assert all(b["trade_date"] <= case["due"].isoformat() for b in body["raw_stock"]["bars"])
    assert run(case, at + dt.timedelta(days=1))[1].id == snapshot.id
    assert service.view(case["conn"], case["owner"], case["id"])["t1"]["n"] == 2


def test_fifth_day_inclusive_then_freeze_without_another_evaluation(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run(case, close_at(case["due"]))
    row, snapshot = run(case, close_at(case["after"][4]))
    assert row.status == "pending"
    assert len(snapshot._mapping["items"]["history"]) == 1
    at = dt.datetime.combine(case["after"][4] + dt.timedelta(days=1), dt.time.min, BEIJING)

    def forbidden(**kwargs: Any) -> Any:
        if kwargs["period"] == 1:
            pytest.fail("expired unavailable must freeze without evaluation")
        return original(**kwargs)

    original = service.evaluate
    monkeypatch.setattr(service, "evaluate", forbidden)
    # UTC date is still D+5; Beijing has already passed the window boundary.
    frozen, kept = run(case, at.astimezone(dt.UTC))
    assert frozen.status == "done"
    assert kept.id == snapshot.id
    assert frozen.computed_at == row.computed_at
    bar(case, case["due"], at)
    assert run(case, at + dt.timedelta(days=1))[1].id == kept.id


def test_first_computation_outside_window_runs_once_then_freezes(case: Any) -> None:
    at = close_at(case["after"][5])
    row, snapshot = run(case, at)
    assert row.status == "done"
    assert {r["state"] for r in snapshot._mapping["items"]["results"]} == {"unavailable"}
    assert snapshot._mapping["items"]["history"] == []
    bar(case, case["due"], at)
    assert run(case, at + dt.timedelta(days=1))[1].id == snapshot.id


def test_mixed_conclusions_freeze_complete_and_keep_flat_history(
    case: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    at = close_at(case["due"]) + dt.timedelta(minutes=1)
    observe(case, at, missing_sell_fact=True)
    bar(case, case["due"], at)
    row, first = run(case, at)
    initial = {r["action"]: r for r in first._mapping["items"]["results"]}
    assert initial["buy"]["state"] == "complete"
    assert initial["sell"]["state"] == "unavailable"
    assert row.status == "pending"
    evaluated = []
    original = service.evaluate

    def record(**kwargs: Any) -> Any:
        evaluated.append(kwargs["conclusion"]["action"])
        return original(**kwargs)

    monkeypatch.setattr(service, "evaluate", record)
    _, second = run(case, close_at(case["after"][0]))
    assert evaluated == ["sell"]
    at = close_at(case["after"][1])
    observe(case, at)
    bar(case, case["due"], at)
    row, third = run(case, at)
    body = third._mapping["items"]
    assert evaluated == ["sell", "sell"]
    assert row.status == "done"
    final = {r["action"]: r for r in body["results"]}
    assert final["buy"] == initial["buy"]
    assert final["sell"]["state"] == "complete"
    assert [h["snapshot_id"] for h in body["history"]] == [str(first.id), str(second.id)]
    assert all("history" not in h for h in body["history"])
    assert body["history"][0]["results"] == first._mapping["items"]["results"]
    assert body["history"][1]["results"] == second._mapping["items"]["results"]


def test_future_trade_date_never_fills_missing_due_bar(case: Any) -> None:
    run(case, close_at(case["due"]))
    at = close_at(case["after"][0])
    bar(case, case["after"][0], at)
    row, snapshot = run(case, at)
    body = snapshot._mapping["items"]
    assert dt.datetime.fromisoformat(body["as_of"]) == at
    assert body["raw_stock"]["bars"] == []
    assert {r["state"] for r in body["results"]} == {"unavailable"}
    assert row.status == "pending"


def test_calendar_gap_conservatively_freezes_without_recompute(case: Any) -> None:
    _, first = run(case, close_at(case["due"]))
    case["conn"].execute(
        delete(trading_calendar).where(trading_calendar.c.date == case["after"][0])
    )
    at = close_at(case["after"][1])
    bar(case, case["due"], at)
    row, snapshot = run(case, at)
    assert row.status == "done"
    assert snapshot.id == first.id


def test_legacy_done_unavailable_is_recomputed_when_still_in_window(case: Any) -> None:
    _, first = run(case, close_at(case["due"]))
    case["conn"].execute(
        update(suggestion_tracking)
        .where(
            suggestion_tracking.c.suggestion_id == case["id"],
            suggestion_tracking.c.horizon_days == 1,
        )
        .values(status="done")
    )
    at = close_at(case["after"][0])
    bar(case, case["due"], at)
    row, snapshot = run(case, at)
    assert row.status == "done"
    assert snapshot.id != first.id
    assert {r["state"] for r in snapshot._mapping["items"]["results"]} == {"complete"}

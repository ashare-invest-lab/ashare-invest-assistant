"""T-B171: synthetic tracking recomputation, only on the explicit temporary test DB."""

# ruff: noqa: S101, ANN401
from __future__ import annotations

import datetime as dt
import os
import uuid
from argparse import Namespace
from collections.abc import Iterator
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from fastapi import Response
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
from app.tracking.api import strategy_tracking_view
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
def case(engine: Engine, request: pytest.FixtureRequest) -> Iterator[Any]:
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
        for action in getattr(request, "param", ("buy", "sell")):
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


def observe(
    case: Any,
    at: dt.datetime,
    *,
    missing_sell_fact: bool = False,
    fact_at: dt.datetime | None = None,
    suspended_on: dt.date | None = None,
) -> None:
    values = dict(case["args"]["facts"][case["due"].isoformat()])
    if missing_sell_fact:
        values["limit_locked_down"] = None
    facts = {
        case["due"].isoformat(): {
            "available_at": (fact_at or at).isoformat(),
            "values": values,
        }
    }
    if suspended_on is not None:
        facts[suspended_on.isoformat()] = {
            "available_at": at.isoformat(),
            "values": {"is_suspended": True},
        }
    body = {
        "schema_version": service.OBS_SCHEMA,
        "instruments": {
            "TB171.SYN": {
                "factors": case["args"]["factors"],
                "facts": facts,
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


def bar(case: Any, day: dt.date, fetched: dt.datetime, code: str = "TB171.SYN") -> None:
    value = case["args"]["instrument"]["bars"][0]
    case["conn"].execute(
        pg_insert(daily_bars)
        .values(
            code=code,
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
def test_tb171_retry_late_due_bar_uses_same_asof_in_service_and_engine(
    case: Any, offset: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    first, old = run(case, close_at(case["due"]))
    assert {r["state"] for r in old._mapping["items"]["results"]} == {"unavailable"}
    assert first.status == "pending"
    at = close_at(case["after"][offset - 1])
    visible = at + dt.timedelta(minutes=1)
    known = at + dt.timedelta(minutes=2)
    bar(case, case["due"], visible)
    # A visible price after D and a D price fetched after as_of are both excluded.
    bar(case, case["after"][0], at)
    case["args"]["factors"][0]["available_at"] = known.isoformat()
    observe(case, at, fact_at=known)
    evaluated = []
    original = service.evaluate

    def record(**kwargs: Any) -> Any:
        if kwargs["period"] == 1:
            evaluated.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(service, "evaluate", record)
    _, hidden = run(case, at)
    body = hidden._mapping["items"]
    assert body["raw_stock"]["bars"] == []
    assert all(r["state"] == "unavailable" for r in body["results"])
    assert all(k["now"] == at and k["recompute"] and not k["facts"] for k in evaluated)
    # Visible prices alone cannot bypass independent facts/factor availability.
    evaluated.clear()
    _, prices_only = run(case, visible)
    assert prices_only._mapping["items"]["raw_stock"]["bars"]
    assert all(
        r["entry_price"] is None and r["state"] == "unavailable"
        for r in prices_only._mapping["items"]["results"]
    )
    assert all(not k["facts"] for k in evaluated)
    # Once the same inputs become known, both service SQL and engine qfq use now.
    evaluated.clear()
    row, snapshot = run(case, known)
    body = snapshot._mapping["items"]
    assert row.status == "done"
    assert {r["state"] for r in body["results"]} == {"complete"}
    assert dt.datetime.fromisoformat(body["as_of"]) == known
    assert all(k["now"] == known and k["recompute"] for k in evaluated)
    assert {b["trade_date"] for b in body["raw_stock"]["bars"]} == {case["due"].isoformat()}
    assert all(
        dt.datetime.fromisoformat(b["first_seen_at"]) <= visible for b in body["raw_stock"]["bars"]
    )
    assert [h["snapshot_id"] for h in body["history"]] == [
        str(old.id),
        str(hidden.id),
        str(prices_only.id),
    ]
    assert body["history"][0]["hash"] == old.hash
    assert run(case, visible + dt.timedelta(days=1))[1].id == snapshot.id


@pytest.mark.parametrize(
    "scenario",
    [
        "d0",
        "d1",
        "d5",
        "d6",
        "same_instant_utc",
        "known_closed",
        "suspended",
        "calendar_hole",
        "calendar_hole_after_nominal_d6",
    ],
)
def test_tb171_beijing_d0_d5_d6_and_calendar_hole(case: Any, scenario: str) -> None:
    pending, pending_snapshot = run(case, close_at(case["due"]) - dt.timedelta(minutes=1))
    assert pending.status == "pending"
    assert {r["state"] for r in pending_snapshot._mapping["items"]["results"]} == {"pending"}
    # A later pre-due clock must preserve the original pending observation.
    assert run(case, close_at(case["due"]) - dt.timedelta(seconds=1))[1].id == pending_snapshot.id
    _, first = run(case, close_at(case["due"]))
    if scenario == "d0":
        at = close_at(case["due"]) + dt.timedelta(minutes=1)
    elif scenario in {"d1", "calendar_hole"}:
        at = close_at(case["after"][0])
    elif scenario == "d5":
        at = close_at(case["after"][4])
    elif scenario in {"d6", "suspended", "calendar_hole_after_nominal_d6"}:
        at = close_at(case["after"][5])
    elif scenario == "same_instant_utc":
        # UTC is still D+5, while Beijing has passed that calendar date.
        at = dt.datetime.combine(
            case["after"][4] + dt.timedelta(days=1), dt.time.min, BEIJING
        ).astimezone(dt.UTC)
    else:
        closed = case["after"][3] + dt.timedelta(days=1)
        assert case["args"]["calendar"][closed] is False
        at = close_at(closed)
    if scenario.startswith("calendar_hole"):
        case["conn"].execute(
            delete(trading_calendar).where(trading_calendar.c.date == case["after"][0])
        )
    if scenario == "suspended":
        observe(case, close_at(case["after"][0]), suspended_on=case["after"][0])
    frozen = scenario in {"d6", "same_instant_utc", "suspended"}
    row, snapshot = run(case, at)
    assert row.status == ("done" if frozen else "pending")
    assert (snapshot.id == first.id) is frozen
    assert {r["state"] for r in snapshot._mapping["items"]["results"]} == {"unavailable"}
    if scenario.startswith("calendar_hole"):
        assert all(
            "calendar_not_covered" in {g["key"] for g in r["gaps"]}
            for r in snapshot._mapping["items"]["results"]
        )
        # Missing coverage must neither freeze nor prevent a later data repair.
        later = at + dt.timedelta(minutes=1)
        bar(case, case["due"], later)
        assert {r["state"] for r in run(case, later)[1]._mapping["items"]["results"]} == {
            "complete"
        }
    replay_at = at.astimezone(BEIJING) if at.tzinfo == dt.UTC else at.astimezone(dt.UTC)
    before_replay = run(case, at)[1]
    assert run(case, replay_at)[1].id == before_replay.id


def test_tb171_first_run_after_window_computes_once(case: Any) -> None:
    at = close_at(case["after"][5])
    row, snapshot = run(case, at)
    assert row.status == "done"
    assert {r["state"] for r in snapshot._mapping["items"]["results"]} == {"unavailable"}
    assert snapshot._mapping["items"]["history"] == []
    bar(case, case["due"], at)
    assert run(case, at)[1].id == snapshot.id
    assert run(case, at + dt.timedelta(days=1))[1].id == snapshot.id


@pytest.mark.parametrize("closed_offset", [1, 2], ids=["saturday", "sunday"])
@pytest.mark.parametrize("repair", [True, False], ids=["late_due_bar", "still_missing"])
def test_tb171_closed_days_after_fifth_open_friday_remain_in_window(
    case: Any, monkeypatch: pytest.MonkeyPatch, closed_offset: int, repair: bool
) -> None:
    # A synthetic exchange holiday makes D+5 a Friday, followed by a closed weekend.
    for day in case["after"][4:8]:
        case["args"]["calendar"][day] = False
        case["conn"].execute(
            update(trading_calendar).where(trading_calendar.c.date == day).values(is_open=False)
        )
    opened = [
        d for d, yes in sorted(case["args"]["calendar"].items()) if yes and d > case["due"]
    ]
    fifth, sixth = opened[4:6]
    assert fifth.weekday() == 4
    run(case, close_at(case["due"]))
    row, fifth_snapshot = run(case, close_at(fifth))
    assert row.status == "pending"
    closed = fifth + dt.timedelta(days=closed_offset)
    assert case["args"]["calendar"][closed] is False
    # The job is passed a UTC instant whose Beijing date is the closed day.
    at = dt.datetime.combine(closed, dt.time.min, BEIJING).astimezone(dt.UTC)
    if repair:
        bar(case, case["due"], at - dt.timedelta(minutes=1))
    row, snapshot = run(case, at)
    assert snapshot.id != fifth_snapshot.id
    assert row.status == ("done" if repair else "pending")
    assert {r["state"] for r in snapshot._mapping["items"]["results"]} == {
        "complete" if repair else "unavailable"
    }
    assert dt.datetime.fromisoformat(snapshot._mapping["items"]["as_of"]) == at

    def forbidden(**kwargs: Any) -> Any:
        if kwargs["period"] == 1:
            pytest.fail("the sixth open day must freeze without evaluation")
        return original(**kwargs)

    original = service.evaluate
    monkeypatch.setattr(service, "evaluate", forbidden)
    sixth_at = dt.datetime.combine(sixth, dt.time.min, BEIJING)
    frozen, kept = run(case, sixth_at)
    assert frozen.status == "done"
    assert kept.id == snapshot.id
    assert frozen.computed_at == row.computed_at
    bar(case, case["due"], sixth_at)
    assert run(case, close_at(sixth))[1].id == kept.id


@pytest.mark.parametrize(
    ("terminal", "case"),
    [
        ("complete", ("buy", "sell")),
        ("untradable", ("buy", "sell")),
        ("excluded", ("wait", "sell")),
    ],
    indirect=["case"],
)
def test_tb171_mixed_terminal_results_and_history_hash_preserved(
    case: Any, monkeypatch: pytest.MonkeyPatch, terminal: str
) -> None:
    if terminal == "untradable":
        case["args"]["facts"][case["due"].isoformat()]["limit_locked_up"] = True
    at = close_at(case["due"]) + dt.timedelta(minutes=1)
    observe(case, at, missing_sell_fact=True)
    bar(case, case["due"], at)
    row, first = run(case, at)
    initial = {r["action"]: r for r in first._mapping["items"]["results"]}
    kept_action = "wait" if terminal == "excluded" else "buy"
    assert initial[kept_action]["state"] == terminal
    assert initial["sell"]["state"] == "unavailable"
    assert row.status == "pending"
    evaluated = []
    original = service.evaluate

    def record(**kwargs: Any) -> Any:
        evaluated.append(kwargs["conclusion"]["action"])
        return original(**kwargs)

    monkeypatch.setattr(service, "evaluate", record)
    retry = close_at(case["after"][0])
    _, second = run(case, retry)
    assert evaluated == ["sell"]
    assert service.view(case["conn"], case["owner"], case["id"])["t1"]["n"] == (
        1 if terminal == "complete" else 0
    )
    assert run(case, retry)[1].id == second.id
    assert evaluated == ["sell"]
    at = close_at(case["after"][1])
    # Source revisions cannot thaw the other result in this same container.
    case["args"]["facts"][case["due"].isoformat()]["limit_locked_up"] = False
    observe(case, at)
    bar(case, case["due"], at)
    row, third = run(case, at)
    body = third._mapping["items"]
    assert evaluated == ["sell", "sell"]
    assert row.status == "done"
    final = {r["action"]: r for r in body["results"]}
    assert final[kept_action] == initial[kept_action]
    assert final["sell"]["state"] == "complete"
    assert [h["snapshot_id"] for h in body["history"]] == [str(first.id), str(second.id)]
    for history, old in zip(body["history"], [first, second], strict=True):
        saved = (
            case["conn"].execute(select(data_snapshots).where(data_snapshots.c.id == old.id)).one()
        )
        assert history == {
            "snapshot_id": str(old.id),
            "hash": old.hash,
            "as_of": old._mapping["items"]["as_of"],
            "results": old._mapping["items"]["results"],
        }
        assert saved.hash == service.digest(saved._mapping["items"]) == old.hash
        assert saved._mapping["items"] == old._mapping["items"]
    assert run(case, at)[1].id == third.id
    assert run(case, at + dt.timedelta(days=1))[1].id == third.id
    assert service.view(case["conn"], case["owner"], case["id"])["t1"]["n"] == (
        2 if terminal == "complete" else 1
    )


def test_tb171_current_only_stats_refresh_after_retry(case: Any) -> None:
    def aggregate(version: str) -> dict[str, Any]:
        strategy = (
            case["conn"]
            .execute(
                select(strategy_versions.c.strategy_id).where(
                    strategy_versions.c.id == uuid.UUID(version)
                )
            )
            .scalar_one()
        )
        return strategy_tracking_view(
            strategy,
            uuid.UUID(version),
            SimpleNamespace(user_id=case["owner"]),
            SimpleNamespace(connect=lambda: nullcontext(case["conn"])),
            Response(),
        )["by_horizon"][0]

    at = close_at(case["due"]) + dt.timedelta(minutes=1)
    observe(case, at, missing_sell_fact=True)
    bar(case, case["due"], at)
    run(case, at)
    buy, sell = [c["strategy_version_id"] for c in case["conclusions"]]
    assert service.view(case["conn"], case["owner"], case["id"])["t1"]["n"] == 1
    assert aggregate(buy)["avg_return_pct"]["n"] == 1
    assert aggregate(sell)["avg_return_pct"]["n"] == 0
    run(case, close_at(case["after"][0]))
    at = close_at(case["after"][1])
    observe(case, at)
    _, snapshot = run(case, at)
    assert len(snapshot._mapping["items"]["history"]) == 2
    results, _ = service.results_for(case["conn"], case["owner"], case["id"])
    assert len([r for r in results if r.horizon_days == 1]) == 2
    for _ in range(2):
        assert service.view(case["conn"], case["owner"], case["id"])["t1"]["n"] == 2
        assert aggregate(buy)["avg_return_pct"]["n"] == 1
        assert aggregate(sell)["avg_return_pct"]["n"] == 1
        assert aggregate(buy)["profit_loss_ratio"]["n"] == 1
        assert aggregate(sell)["profit_loss_ratio"]["n"] == 0
        assert aggregate(sell)["avg_return_pct"]["value"] is None


def test_tb171_complete_with_missing_benchmark_stays_frozen(case: Any) -> None:
    at = close_at(case["due"])
    bar(case, case["due"], at)
    row, first = run(case, at)
    assert row.status == "done"
    for result in first._mapping["items"]["results"]:
        assert result["state"] == "complete"
        assert result["benchmark_return_pct"] is None
        assert result["excess_pct"] is None
        assert "benchmark_prices" in {g["key"] for g in result["gaps"]}
    later = close_at(case["after"][0])
    bar(case, case["due"], later, code="000300.SH")
    bar(case, case["due"], later)
    assert run(case, later)[1].id == first.id
    assert run(case, close_at(case["after"][5]))[1].id == first.id


@pytest.mark.parametrize(
    ("terminal", "case"),
    [("untradable", ("buy", "sell")), ("excluded", ("wait", "wait"))],
    indirect=["case"],
)
def test_not_applicable_preserves_existing_meaning(case: Any, terminal: str) -> None:
    if terminal == "untradable":
        case["args"]["facts"][case["due"].isoformat()]["is_suspended"] = True
    at = close_at(case["due"]) + dt.timedelta(minutes=1)
    observe(case, at)
    row, first = run(case, at)
    assert row.status == "not_applicable"
    assert {r["state"] for r in first._mapping["items"]["results"]} == {terminal}
    case["args"]["facts"][case["due"].isoformat()]["is_suspended"] = False
    observe(case, close_at(case["after"][0]))
    bar(case, case["due"], close_at(case["after"][0]))
    row, kept = run(case, close_at(case["after"][5]))
    assert row.status == "not_applicable"
    assert kept.id == first.id


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

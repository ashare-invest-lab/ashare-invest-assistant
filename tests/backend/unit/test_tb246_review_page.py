"""T-B246 offline acceptance cases for the review-page backend.

§7.8.1 trade_ids 定义将随 #438 新头修订（与 RV-06 旧版本冻结对齐）。
本文件不编造 POST/revise 的 trade_ids 纳入规则，相关实现等新契约头。
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from app.config_files import RiskControlsConfig
from app.feedback.plans import Facts
from app.reviews import service
from app.risk import rc1
from app.risk.evaluation import Inputs, assessed
from app.signals.models import Stops
from app.suggestions.risk import RiskContext
from app.tracking.engine import BEIJING, close_at, due_date, evaluate

OWNER = uuid.UUID(int=246)
ACCOUNT = uuid.UUID(int=247)
CODE = "600000.SH"
AT = dt.datetime(2026, 1, 5, 16, tzinfo=BEIJING)


def risk_config() -> RiskControlsConfig:
    root = Path(__file__).resolve().parents[3]
    return RiskControlsConfig.model_validate(
        yaml.safe_load((root / "config/risk_controls.yaml").read_text())
    )


def test_rv04_rc6_disconnected_checks_are_unknown_and_keep_all_gaps() -> None:
    facts = Facts(OWNER, ACCOUNT, CODE, (), (), AT, True)
    source = Inputs(
        ACCOUNT,
        RiskContext(
            observations={},
            regime=None,
            t_leg=None,
            sector_memberships=None,
            trade_action=None,
            plan_action=None,
            invalidated=None,
            plan_stop_loss=None,
        ),
        None,
        False,
        [],
        owner_id=OWNER,
        security_code=CODE,
        rc6=facts,
    )
    _, controls = assessed(
        risk_config(),
        source,
        action="hold",
        horizon="short",
        stops=Stops(stop_loss=None, take_profit=None, time_stop_days=None),
        at=AT,
    )
    rc6_control = next(item for item in controls if item["control"] == "plan_violation")
    assert rc6_control["state"] == "unknown"
    assert {item["key"] for item in rc6_control["gaps"]} >= {
        "plan_check_not_connected:held_after_invalidation",
        "plan_check_not_connected:buy_without_stop",
        "plan_check_not_connected:buy_during_wait",
    }


def test_rv04_unknown_rc6_is_not_projected_as_passed_or_ok() -> None:
    facts = Facts(OWNER, ACCOUNT, CODE, (), (), AT, True)
    _, controls = assessed(
        risk_config(),
        Inputs(
            ACCOUNT,
            RiskContext(
                observations={},
                regime=None,
                t_leg=None,
                sector_memberships=None,
                trade_action=None,
                plan_action=None,
                invalidated=None,
                plan_stop_loss=None,
            ),
            None,
            False,
            [],
            owner_id=OWNER,
            security_code=CODE,
            rc6=facts,
        ),
        action="hold",
        horizon="short",
        stops=Stops(stop_loss=None, take_profit=None, time_stop_days=None),
        at=AT,
    )
    rc6_control = next(item for item in controls if item["control"] == "plan_violation")
    assert rc6_control["state"] == "unknown"
    assert rc6_control["state"] not in {"ok", "disabled"}
    # Candidate/reason projection must not treat this unknown control as passed.
    assert rc6_control["enabled"] is True


def test_rv05_rc1_event_uses_observed_intraday_and_close_times() -> None:
    intraday_at = dt.datetime(2026, 1, 5, 10, 30, tzinfo=BEIJING)
    intraday = rc1.Facts(
        mode="intraday",
        observed_at=intraday_at,
        fetched_at=intraday_at,
        last=Decimal(9),
        ex_rights=False,
        calendar={intraday_at.date(): True},
    )
    flags, evidence, _ = rc1.assess(
        Stops(stop_loss=Decimal("9.5"), take_profit=None, time_stop_days=None),
        intraday,
        intraday_at,
    )
    event = next(item for item in evidence if item.key == "rc1.event_at:stop_loss")
    assert flags and event.value == intraday_at.isoformat()

    close_at_point = dt.datetime(2026, 1, 5, 15, tzinfo=BEIJING)
    close = rc1.Facts(
        mode="close",
        observed_at=close_at_point,
        fetched_at=close_at_point,
        low=Decimal(9),
        high=Decimal(11),
        ex_rights=False,
        calendar={close_at_point.date(): True},
    )
    _, evidence, _ = rc1.assess(
        Stops(stop_loss=Decimal("9.5"), take_profit=None, time_stop_days=None),
        close,
        dt.datetime(2026, 1, 5, 16, tzinfo=BEIJING),
    )
    event = next(item for item in evidence if item.key == "rc1.event_at:stop_loss")
    assert event.value == close_at_point.isoformat()


def test_rv05_tracking_exit_is_t1_close_and_t1_evidence_remains() -> None:
    created = dt.datetime(2026, 1, 1, 10, tzinfo=BEIJING)
    calendar = {
        dt.date(2026, 1, 1): True,
        dt.date(2026, 1, 2): True,
        dt.date(2026, 1, 3): True,
    }
    result = evaluate(
        conclusion={
            "strategy_version_id": uuid.UUID(int=1),
            "instance_id": uuid.UUID(int=2),
            "action": "hold",
            "security_code": CODE,
        },
        created=created,
        period=1,
        calendar=calendar,
        instrument={"bars": [], "factors": []},
        benchmark={"bars": []},
        factors=[],
        facts={"2026-01-02": {"is_suspended": None, "limit_locked_down": None}},
        forced_hold=None,
        now=dt.datetime(2026, 1, 2, 16, tzinfo=BEIJING),
        minutes=[],
    )
    due = due_date(created, 1, calendar)
    assert due is not None and result.exit_at == close_at(due)
    assert result.exit_at >= close_at(due)
    assert {item.key for item in result.evidence} >= {
        "t1.is_suspended",
        "t1.limit_locked_down",
    }
    assert {item.key for item in result.gaps} >= {
        "t1.is_suspended",
        "t1.limit_locked_down",
    }


def _trade(number: int, voided_at: dt.datetime | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=number),
        account_id=ACCOUNT,
        security_code=CODE,
        trade_date=dt.date(2026, 1, 2),
        side="buy",
        quantity=Decimal(10),
        net_amount=Decimal("-101.50"),
        traded_at=dt.datetime(2026, 1, 2, 10, tzinfo=dt.UTC),
        created_at=dt.datetime(2026, 1, 2, 10, tzinfo=dt.UTC),
        source="manual",
        import_batch_id=None,
        voided_at=voided_at,
        epistemic_type="execution",
        commission=Decimal("1.00"),
        stamp_tax=Decimal("0.00"),
        transfer_fee=Decimal("0.50"),
        other_fee=Decimal("0.00"),
    )


def test_rv06_void_cutoff_and_fee_snapshot_are_frozen() -> None:
    cutoff = dt.datetime(2026, 1, 4, tzinfo=dt.UTC)
    before = _trade(10, dt.datetime(2026, 1, 3, tzinfo=dt.UTC))
    after = _trade(11, dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    visible, _ = service._visible_trade_rows(
        [before, after], cutoff, dt.date(2026, 1, 1), dt.date(2026, 1, 5)
    )
    assert [row.id for row in visible] == [after.id]
    evidence = service._trade_evidence(after)
    assert evidence is not None
    assert evidence["fee_snapshot"]["fee_total"] == "1.50"
    assert evidence["fee_snapshot"]["net_amount"] == "-101.50"
    assert evidence["fee_snapshot"]["label"] == "未验证"

    class Connection:
        def execute(self, statement: object) -> Any:
            text = str(statement)
            if "trading_calendar" in text:
                return SimpleNamespace(
                    first=lambda: SimpleNamespace(
                        date=dt.date(2026, 1, 5), is_open=True
                    )
                )
            if "daily_bars" in text:
                return SimpleNamespace(all=list)
            return SimpleNamespace(all=lambda: [after])

    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
        None,
        [],
        [],
        True,
        conn=Connection(),
        owner=OWNER,
        trade_ids=[after.id],
        calculation_as_of=cutoff,
    )
    assert snapshot["fee_snapshots"][0]["trade_id"] == str(after.id)
    assert snapshot["fee_snapshots"][0]["fee_total"] == "1.50"


def test_rv05_rc1_event_is_independent_of_t1_exit() -> None:
    buy_day = dt.datetime(2026, 1, 5, 10, 30, tzinfo=BEIJING)
    flags, evidence, _ = rc1.assess(
        Stops(stop_loss=Decimal("9.5"), take_profit=None, time_stop_days=None),
        rc1.Facts(
            mode="intraday",
            observed_at=buy_day,
            fetched_at=buy_day,
            last=Decimal(9),
            ex_rights=False,
            calendar={buy_day.date(): True},
        ),
        buy_day,
    )
    event = next(item for item in evidence if item.key == "rc1.event_at:stop_loss")
    calendar = {
        dt.date(2026, 1, 5): True,
        dt.date(2026, 1, 6): True,
        dt.date(2026, 1, 7): True,
    }
    due = due_date(buy_day, 1, calendar)
    assert flags and due is not None
    assert event.value == buy_day.isoformat()
    assert close_at(due) > buy_day
    assert due == dt.date(2026, 1, 6)


def test_rv06_missing_fee_evidence_nulls_fee_metrics() -> None:
    cutoff = dt.datetime(2026, 1, 4, tzinfo=dt.UTC)
    row = _trade(12, None)
    row.commission = None
    row.stamp_tax = None
    row.transfer_fee = None
    row.other_fee = None
    row.net_amount = None

    class Connection:
        def execute(self, statement: object) -> Any:
            text = str(statement)
            if "trading_calendar" in text:
                return SimpleNamespace(
                    first=lambda: SimpleNamespace(
                        date=dt.date(2026, 1, 5), is_open=True
                    )
                )
            if "daily_bars" in text:
                return SimpleNamespace(all=list)
            return SimpleNamespace(all=lambda: [row])

    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
        None,
        [],
        [],
        True,
        conn=Connection(),
        owner=OWNER,
        trade_ids=[row.id],
        calculation_as_of=cutoff,
    )
    assert snapshot["fee_snapshots"][0]["fee_total"] is None
    assert snapshot["fee_snapshots"][0]["label"] == "未验证"
    assert snapshot["outcome_metrics"]["holding_return"]["value"] is None
    assert any(
        gap.get("reason") == "no_source" and "holding_return" in str(gap.get("key"))
        for gap in snapshot.get("gaps", [])
    )

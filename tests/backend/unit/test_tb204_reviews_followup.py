"""T-B204 offline regression tests using only synthetic rows and connections."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.reviews import service
from app.reviews.metrics import period_pending, project_metrics

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")


def test_a_weekend_does_not_reopen_friday_period() -> None:
    saturday = dt.datetime(2026, 1, 10, 10, tzinfo=dt.UTC)
    assert not period_pending(dt.date(2026, 1, 9), now=saturday)
    projected = project_metrics(
        {},
        period_end=dt.date(2026, 1, 12),
        now=dt.datetime(2026, 1, 12, 2, tzinfo=dt.UTC),
    )
    assert projected["holding_return"]["value"] is None


def test_a_missing_calendar_cannot_release_period() -> None:
    class Connection:
        def execute(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(first=lambda: None)

    assert period_pending(
        dt.date(2026, 1, 9),
        now=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        conn=Connection(),
    )


def test_a_gap_reason_and_simulation_source_are_preserved() -> None:
    projected = project_metrics(
        {
            "holding_return": {
                "value": "12.5",
                "n": 5,
                "window": "2026-01-01/2026-01-05",
                "small_sample": True,
                "source": "simulated_tracking",
                "gaps": ["future_reason"],
            }
        },
        period_end=dt.date(2026, 1, 5),
        now=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
    )
    holding = projected["holding_return"]
    assert holding["source"] == "simulated_tracking"
    assert holding["label"] == "模拟跟踪"
    assert holding["value"] is None
    assert "gaps" not in holding


def test_b_frozen_as_of_is_kept_in_snapshot() -> None:
    fixed = dt.datetime(2026, 1, 6, 8, tzinfo=dt.UTC)
    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        None,
        [],
        [],
        False,
        calculation_as_of=fixed,
    )
    assert snapshot["calculation_as_of"] == fixed.isoformat()
    assert snapshot["data_as_of"] is None
    projected = project_metrics(
        snapshot["outcome_metrics"],
        period_end=dt.date(2026, 1, 2),
        now=dt.datetime(2026, 2, 1, tzinfo=dt.UTC),
    )
    assert (
        projected["holding_return"]["value"]
        == snapshot["outcome_metrics"]["holding_return"]["value"]
    )


class TradeConnection:
    def __init__(self, rows: list[SimpleNamespace]) -> None:
        self.rows = rows

    def execute(self, _statement: object) -> SimpleNamespace:
        if "trading_calendar" in str(_statement):
            return SimpleNamespace(
                first=lambda: SimpleNamespace(date=dt.date(2026, 1, 5), is_open=True)
            )
        if "daily_bars" in str(_statement):
            return SimpleNamespace(all=list)
        return SimpleNamespace(all=lambda: self.rows)


def _trade(
    number: int,
    *,
    side: str,
    quantity: str,
    net_amount: str,
    traded_at: dt.datetime,
    created_at: dt.datetime | None = None,
    source: str = "import",
    voided_at: dt.datetime | None = None,
    epistemic_type: str = "execution",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=number),
        security_code="600000.SH",
        trade_date=traded_at.date(),
        side=side,
        quantity=Decimal(quantity),
        net_amount=Decimal(net_amount),
        traded_at=traded_at,
        created_at=created_at or traded_at,
        source=source,
        voided_at=voided_at,
        epistemic_type=epistemic_type,
    )


def test_c_actual_trades_are_used_and_missing_sources_are_gaps() -> None:
    at = dt.datetime(2026, 1, 10, tzinfo=dt.UTC)
    rows = [
        item
        for i in range(5)
        for item in (
            _trade(
                i * 2 + 1,
                side="buy",
                quantity="10",
                net_amount="-100",
                traded_at=dt.datetime(2026, 1, 1 + i, tzinfo=dt.UTC),
            ),
            _trade(
                i * 2 + 2,
                side="sell",
                quantity="10",
                net_amount="110",
                traded_at=dt.datetime(2026, 1, 1 + i, 1, tzinfo=dt.UTC),
            ),
        )
    ]
    metrics, _, _, metric_gaps = service._compute_outcome_metrics(
        TradeConnection(rows),
        OWNER,
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
        [r.id for r in rows],
        at,
    )
    assert metrics["holding_return"]["value"] == "10.0"
    assert metrics["benchmark_return"]["value"] is None
    assert metric_gaps["benchmark_return"] == ["no_source"]


def test_c_fifo_partial_close_excludes_unclosed_quantity() -> None:
    rows = [
        _trade(
            31,
            side="buy",
            quantity="10",
            net_amount="-100",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        ),
        _trade(
            32,
            side="buy",
            quantity="10",
            net_amount="-120",
            traded_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        ),
        _trade(
            33,
            side="sell",
            quantity="15",
            net_amount="180",
            traded_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC),
        ),
    ]
    holding, _, _, _, _, has_open_positions = service._observations(
        rows,
        dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
    )
    assert holding == [Decimal(20), Decimal(0)]
    assert has_open_positions


def test_c_fifo_return_uses_net_amount_including_fees() -> None:
    rows = [
        _trade(
            41,
            side="buy",
            quantity="10",
            net_amount="-1010",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        ),
        _trade(
            42,
            side="sell",
            quantity="10",
            net_amount="1090",
            traded_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        ),
    ]
    holding, _, _, _, _, _ = service._observations(
        rows,
        dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
    )
    assert holding == [(Decimal(109) / Decimal(101) - Decimal(1)) * Decimal(100)]


def test_c_voided_execution_is_excluded() -> None:
    rows = [
        _trade(
            51,
            side="buy",
            quantity="10",
            net_amount="-100",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            voided_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        ),
        _trade(
            52,
            side="sell",
            quantity="10",
            net_amount="110",
            traded_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        ),
    ]
    holding, _, _, evidence_ids, _, _ = service._observations(
        rows,
        dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
    )
    assert holding == []
    assert evidence_ids == ["trade:" + str(rows[1].id)]


def test_c_trade_after_calculation_as_of_is_excluded() -> None:
    rows = [
        _trade(
            61,
            side="buy",
            quantity="10",
            net_amount="-100",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        ),
        _trade(
            62,
            side="sell",
            quantity="10",
            net_amount="110",
            traded_at=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
        ),
    ]
    holding, _, _, evidence_ids, _, _ = service._observations(
        rows,
        dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 10),
    )
    assert holding == []
    assert evidence_ids == ["trade:" + str(rows[0].id)]


def test_c_trade_imported_after_calculation_as_of_is_excluded() -> None:
    rows = [
        _trade(
            63,
            side="buy",
            quantity="10",
            net_amount="-100",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        ),
        _trade(
            64,
            side="sell",
            quantity="10",
            net_amount="110",
            traded_at=dt.datetime(2026, 1, 2, 1, tzinfo=dt.UTC),
            created_at=dt.datetime(2026, 1, 6, tzinfo=dt.UTC),
        ),
    ]
    holding, _, _, evidence_ids, data_as_of, _ = service._observations(
        rows,
        dt.datetime(2026, 1, 5, tzinfo=dt.UTC),
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 10),
    )
    assert holding == []
    assert evidence_ids == ["trade:" + str(rows[0].id)]
    assert data_as_of == rows[0].created_at


def test_d_evidence_is_written_for_plan_and_trade_snapshots() -> None:
    plan_id = uuid.UUID(int=10)
    trade_id = uuid.UUID(int=11)
    trade = _trade(
        trade_id.int,
        side="buy",
        quantity="10",
        net_amount="-100",
        traded_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
    )

    class SnapshotConnection:
        def execute(self, statement: object) -> SimpleNamespace:
            text = str(statement)
            if "trading_calendar" in text:
                return SimpleNamespace(
                    first=lambda: SimpleNamespace(
                        date=dt.date(2026, 1, 2), is_open=True
                    )
                )
            if "plan_versions" in text:
                return SimpleNamespace(
                    all=lambda: [
                        SimpleNamespace(
                            id=plan_id,
                            created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                        )
                    ]
                )
            if "trades" in text:
                return SimpleNamespace(all=lambda: [trade])
            if "daily_bars" in text:
                return SimpleNamespace(all=list)
            raise AssertionError(text)

    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        None,
        [],
        [],
        True,
        conn=SnapshotConnection(),
        owner=OWNER,
        plan_version_ids=[plan_id],
        trade_ids=[trade_id],
    )
    assert {item["id"] for item in snapshot["evidence"]} >= {
        f"plan:{plan_id}",
        f"trade:{trade_id}",
    }
    assert snapshot["attribution"]["execution"][0]["evidence_ids"]
    for item in snapshot["evidence"]:
        assert {
            "unit",
            "provider",
            "endpoint",
            "data_as_of",
            "fetched_at",
            "epistemic_type",
        } <= set(item)


def test_d_full_timeline_evidence_ids_resolve_across_history(
    monkeypatch: Any,
) -> None:
    old_snapshot = uuid.UUID(int=70)
    current_snapshot = uuid.UUID(int=71)
    old_trade = uuid.UUID(int=72)
    current_trade = uuid.UUID(int=73)
    versions = [
        SimpleNamespace(
            id=uuid.UUID(int=74),
            version_no=1,
            snapshot_id=old_snapshot,
            created_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            plan_version_ids=[],
            trade_ids=[],
        ),
        SimpleNamespace(
            id=uuid.UUID(int=75),
            version_no=2,
            snapshot_id=current_snapshot,
            created_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
            plan_version_ids=[],
            trade_ids=[current_trade],
        ),
    ]
    snapshots = {
        old_snapshot: {"evidence": [{"id": f"trade:{old_trade}"}]},
        current_snapshot: {"evidence": [{"id": f"trade:{current_trade}"}]},
    }

    class TimelineConnection:
        def execute(self, statement: object) -> SimpleNamespace:
            text = str(statement)
            if "review_versions" in text:
                return SimpleNamespace(all=lambda: versions)
            if "trades" in text:
                return SimpleNamespace(all=list)
            raise AssertionError(text)

    monkeypatch.setattr(
        service,
        "_snapshot",
        lambda _conn, _owner, snapshot_id: snapshots[snapshot_id],
    )
    timeline, evidence = service._timeline_data(
        TimelineConnection(),
        OWNER,
        uuid.UUID(int=76),
        versions[-1],
    )
    evidence_ids = {item["id"] for item in evidence}
    assert evidence_ids == {f"trade:{old_trade}", f"trade:{current_trade}"}
    assert all(
        evidence_id in evidence_ids
        for item in timeline
        for evidence_id in item["evidence_ids"]
    )


def test_e_plan_and_outcome_are_separate_frozen_sections() -> None:
    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1), dt.date(2026, 1, 2), "lesson", [], [], False
    )
    assert snapshot["period_start"] == "2026-01-01"
    assert snapshot["period_end"] == "2026-01-02"
    assert set(snapshot["plan_snapshot"]) == {
        "plan_version_ids",
        "judgement",
        "lessons",
        "tags",
    }
    assert set(snapshot["outcome_snapshot"]) == {"trade_ids", "metrics", "evidence"}


def test_f_summary_allows_missing_current_version_without_nested_version() -> None:
    row = SimpleNamespace(
        id=uuid.UUID(int=12),
        user_id=OWNER,
        plan_id=None,
        security_code="600000.SH",
        period_start=dt.date(2026, 1, 1),
        period_end=dt.date(2026, 1, 2),
        current_version_id=None,
        created_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
    )

    class Connection:
        def execute(self, _statement: object) -> SimpleNamespace:
            return SimpleNamespace(first=lambda: None, scalar=lambda: None)

    result = service.summary(Connection(), row)
    assert result["current_version_no"] is None
    assert "current_version" not in result

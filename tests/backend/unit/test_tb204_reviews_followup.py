"""T-B204 offline regression tests using only synthetic rows and connections."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace

from app.reviews import service
from app.reviews.metrics import project_metrics

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")


def test_a_unfinished_metric_contract_hides_old_values() -> None:
    projected = project_metrics(
        {"holding_return": {"value": "12", "n": 10, "small_sample": True}},
        period_end=dt.date(2026, 1, 12),
        now=dt.datetime(2026, 1, 12, 2, tzinfo=dt.UTC),
    )
    for metric in projected.values():
        assert metric["value"] is None
        assert metric["n"] == 0
        assert metric["small_sample"] is True
        assert metric["gaps"] == ["no_source"]


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
        return SimpleNamespace(all=lambda: self.rows)


def _trade(
    number: int,
    *,
    side: str,
    quantity: str,
    net_amount: str,
    traded_at: dt.datetime,
    voided_at: dt.datetime | None = None,
    epistemic_type: str = "execution",
) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=number),
        security_code="600000.SH",
        side=side,
        quantity=Decimal(quantity),
        net_amount=Decimal(net_amount),
        traded_at=traded_at,
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
    metrics, _, _ = service._compute_outcome_metrics(
        TradeConnection(rows),
        OWNER,
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 5),
        [r.id for r in rows],
        at,
    )
    assert metrics["holding_return"]["value"] is None
    assert metrics["holding_return"]["n"] == 0
    assert metrics["holding_return"]["small_sample"] is True
    assert metrics["holding_return"]["gaps"] == ["no_source"]
    assert metrics["benchmark_return"]["value"] is None
    assert metrics["benchmark_return"]["gaps"] == ["no_source"]


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


def test_d_evidence_is_written_for_plan_and_trade_snapshots() -> None:
    plan_id = uuid.UUID(int=10)
    trade_id = uuid.UUID(int=11)
    snapshot = service._snapshot_items(
        dt.date(2026, 1, 1),
        dt.date(2026, 1, 2),
        None,
        [],
        [],
        True,
        plan_version_ids=[plan_id],
        trade_ids=[trade_id],
    )
    assert {item["id"] for item in snapshot["evidence"]} >= {
        f"plan:{plan_id}",
        f"trade:{trade_id}",
    }
    assert snapshot["attribution"]["execution"][0]["evidence_ids"]


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


def test_g_project_metrics_excludes_simulated_tracking_and_merges_gaps() -> None:
    metrics = {
        "holding_return": {
            "value": "9",
            "n": 10,
            "source": "simulated_tracking",
            "gaps": ["no_source"],
        },
        "benchmark_return": {"value": None, "gaps": {"reason": "no_source"}},
    }
    projected = project_metrics(
        metrics,
        period_end=dt.date(2026, 1, 2),
        now=dt.datetime(2026, 1, 10, tzinfo=dt.UTC),
    )
    assert projected["holding_return"]["value"] is None
    assert projected["holding_return"]["gaps"] == ["no_source"]
    assert "source" not in projected["holding_return"]
    assert projected["benchmark_return"]["gaps"] == ["no_source"]


def test_g_fifo_groups_security_codes_and_ignores_malformed_rows() -> None:
    rows = [
        _trade(
            71,
            side="buy",
            quantity="2",
            net_amount="-20",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
        ),
        _trade(
            72,
            side="sell",
            quantity="1",
            net_amount="12",
            traded_at=dt.datetime(2026, 1, 3, tzinfo=dt.UTC),
        ),
        _trade(
            73,
            side="sell",
            quantity="1",
            net_amount="12",
            traded_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC),
        ),
        SimpleNamespace(
            id=uuid.UUID(int=74),
            security_code="000001.SZ",
            side="buy",
            quantity="bad",
            net_amount="-1",
            traded_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            voided_at=None,
            epistemic_type="execution",
        ),
    ]
    holding, open_positions = service._fifo_holding(rows)
    assert holding == [Decimal(20), Decimal(20)]
    assert not open_positions


def test_g_status_for_preserves_top_level_and_metric_gaps() -> None:
    snap = {
        "data_status": "partial",
        "data_as_of": None,
        "gaps": [{"key": "outcome_metrics", "reason": "no_source"}],
        "outcome_metrics": {"holding_return": {"gaps": ["user_input_missing"]}},
    }
    status = service._status_for(snap, dt.date(2026, 1, 2))
    assert {
        (gap["key"], gap["reason"])
        for gap in status["gaps"]
    } == {
        (f"outcome_metrics.{name}", "no_source")
        for name in service.METRIC_NAMES
    }
    metric_status = service._status_for({**snap, "gaps": []}, dt.date(2026, 1, 2))
    assert [gap["reason"] for gap in metric_status["gaps"]] == ["user_input_missing"]

"""T-B199 offline G6 history and F21 evidence-shape checks."""

from __future__ import annotations

import datetime as dt

import pytest
from app.strategy.g6 import Overlap, missing_history_gate
from app.strategy.g6_history import _remove_overlapping_events, build_report


# fmt: off
def _days(count: int = 120) -> list[str]:
    start = dt.date(2026, 1, 1)
    return [(start + dt.timedelta(days=index)).isoformat() for index in range(count)]
class Rows:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = [{"adjust": "qfq", "list_days": 120, **row} for row in rows]

    def fetch(self, query: object) -> list[dict[str, object]]:
        return self.rows

def _report(rows: list[dict[str, object]], **kwargs: object) -> dict[str, object]:
    return build_report(
        provider=Rows(rows), card_key=str(kwargs.pop("card_key", "S-01")), card_version="cv-1",
        spec={"min_list_days": 30, **kwargs.pop("spec", {})}, **kwargs,
    )

def test_default_history_is_explicitly_empty() -> None:
    report = build_report(card_key="W-01", card_version="cv-1")
    assert report["history_status"] == "no_history"
    assert report["max_jaccard"] is None
    assert report["max_jaccard_null_reason"] == "no_history"
    assert report["trigger_rate"]["value"] is None
    assert report["quota_estimate"]["cost_proof"] is False

def test_history_deduplicates_and_keeps_synthetic_separate() -> None:
    day = _days(1)[0]
    rows = [
        {"card_version": "cv-1", "period": "swing", "security": "SYNTH-001", "trading_day": day,
         "evaluation_at": "2026-01-02T09:30:00+08:00", "evaluable": True, "triggered": True,
         "source_kind": "real", "available_at": "2026-01-02T09:00:00+08:00"},
        {"card_version": "cv-1", "period": "swing", "security": "SYNTH-001", "trading_day": day,
         "evaluation_at": "2026-01-02T09:30:00+08:00", "evaluable": True, "triggered": False,
         "source_kind": "real"},
        {"security": "FIXTURE-001", "trading_day": day, "evaluable": True, "triggered": True,
         "source_kind": "synthetic"},
    ]
    report = _report(rows, card_key="W-01", spec={"horizons": ["swing"]})
    section = report["horizons"]["swing"]
    assert section["real_history"]["N"] == 1
    assert section["real_history"]["H"] == 1
    assert section["synthetic_fixtures"]["N"] == 1
    assert report["input_visible_at"] == ["2026-01-02T09:00:00+08:00"]

def test_zero_denominators_are_null_and_short_history_is_preserved() -> None:
    report = _report([{"trading_day": _days(3)[0], "evaluable": False}])
    assert report["history_status"] == "no_history"
    assert report["trigger_rate"]["value"] is None
    assert report["coverage"]["value"] is None
    assert report["coverage"]["small_sample"] is True

def test_trigger_and_jaccard_are_warnings_only() -> None:
    rows = [{"trading_day": day, "security": "SYNTH-001", "evaluable": True, "triggered": True,
             "comparable_sets": [["SYNTH-001"]]} for day in _days()]
    report = _report(rows)
    assert report["history_status"] == "available"
    assert "trigger_rate_out_of_expected_range" in report["warnings"]
    assert "jaccard_above_0.9" in report["warnings"]
    gate = missing_history_gate(True, Overlap(max_jaccard=report["max_jaccard"], max_jaccard_null_reason=None),
                                warnings=report["warnings"], history_status=report["history_status"])
    assert gate["result"] == "warn"

def test_full_history_without_comparable_set_has_explicit_reason() -> None:
    rows = [{"trading_day": day, "security": f"SYNTH-{index:03d}", "evaluable": True,
             "triggered": False} for index, day in enumerate(_days())]
    report = _report(rows, card_key="W-01")
    assert report["history_status"] == "no_comparable_set"
    assert report["max_jaccard"] is None
    assert report["max_jaccard_null_reason"] == "no_comparable_set"

def test_h_card_windows_use_security_and_rule_group_for_overlap() -> None:
    rows = [
        {"event_id": "same", "event_date": "2026-01-01", "trading_day": "2026-01-01",
         "security": "SYNTH-001", "rule_group": "r1", "evaluable": True, "triggered": True},
        {"event_id": "same", "event_date": "2026-01-02", "trading_day": "2026-01-02",
         "security": "SYNTH-001", "rule_group": "r1", "evaluable": True, "triggered": True},
        {"event_id": "same", "event_date": "2026-01-02", "trading_day": "2026-01-02",
         "security": "SYNTH-001", "rule_group": "r2", "evaluable": True, "triggered": True},
    ]
    report = _report(rows, card_key="hold_risk_monitor", card_id="H-01")
    assert set(report["horizons"]) == {"1", "5", "20"}
    assert report["horizons"]["1"]["real_history"]["N"] == 3
    assert report["horizons"]["5"]["real_history"]["N"] == 2
    assert report["horizons"]["20"]["real_history"]["N"] == 2

def test_h_event_overlap_uses_trading_days_across_weekend() -> None:
    rows = [{"security": "S", "rule_group": "r", "trading_day": day}
            for day in ("2026-01-02", "2026-01-12")]
    assert len(_remove_overlapping_events(rows, "h5")) == 1

def test_as_of_filters_future_rows_before_statistics() -> None:
    rows = [
        {"trading_day": "2026-01-14", "evaluable": True, "triggered": True},
        {"trading_day": "2026-02-01", "available_at": "2026-02-01T16:00:00+08:00",
         "evaluable": True, "triggered": True},
    ]
    cutoff = dt.datetime(2026, 1, 15, 23, tzinfo=dt.timezone(dt.timedelta(hours=8)))
    report = _report(rows, as_of=cutoff)
    section = report["horizons"]["default"]["real_history"]
    assert section["N"] == 1
    assert section["H"] == 1
    assert section["window_end"] == "2026-01-14"
    assert "available_at_missing" in report["warnings"]

@pytest.mark.parametrize(
    ("row", "reason"),
    [({"adjust": "none"}, "adjustment_not_qfq"), ({"adjust": None}, "adjustment_missing"),
     ({"is_suspended": True}, "suspended"), ({"list_days": 10}, "new_stock")],
)
def test_card_eligibility_filters_invalid_rows(row: dict[str, object], reason: str) -> None:
    report = _report([{"trading_day": "2026-01-05", "evaluable": True, "triggered": True, **row}])
    assert report["N"] == 0
    assert reason in report["missing_reasons"]

def test_missing_card_new_stock_threshold_is_unverified_gap() -> None:
    report = build_report(provider=Rows([{"trading_day": "2026-01-05", "evaluable": True}]),
                          card_key="S-01", card_version="cv-1", spec={"horizons": ["S-01"]})
    assert report["N"] == 0
    assert "list_days_threshold_missing" in report["missing_reasons"]
    assert "未验证" in report["warnings"]
# fmt: on

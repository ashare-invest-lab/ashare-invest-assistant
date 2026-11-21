"""T-B199 offline G6 history and F21 evidence-shape checks."""

from __future__ import annotations

import datetime as dt

from app.strategy.g6 import Overlap, missing_history_gate
from app.strategy.g6_history import build_report


def _days(count: int = 120) -> list[str]:
    start = dt.date(2026, 1, 1)
    return [(start + dt.timedelta(days=index)).isoformat() for index in range(count)]


class Rows:
    data_source_version = "synthetic-fixture-source-v1"

    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows

    def fetch(self, query: object) -> list[dict[str, object]]:
        return self.rows


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
        {
            "card_version": "cv-1",
            "period": "swing",
            "security": "SYNTH-001",
            "trading_day": day,
            "evaluation_at": "2026-01-02T09:30:00+08:00",
            "evaluable": True,
            "triggered": True,
            "source_kind": "real",
            "available_at": "2026-01-02T09:00:00+08:00",
        },
        {
            "card_version": "cv-1",
            "period": "swing",
            "security": "SYNTH-001",
            "trading_day": day,
            "evaluation_at": "2026-01-02T09:30:00+08:00",
            "evaluable": True,
            "triggered": False,
            "source_kind": "real",
        },
        {
            "security": "FIXTURE-001",
            "trading_day": day,
            "evaluable": True,
            "triggered": True,
            "source_kind": "synthetic",
        },
    ]
    report = build_report(
        provider=Rows(rows),
        card_key="W-01",
        card_version="cv-1",
        spec={"horizons": ["swing"]},
    )
    section = report["horizons"]["swing"]
    assert section["real_history"]["N"] == 1
    assert section["real_history"]["H"] == 1
    assert section["synthetic_fixtures"]["N"] == 1
    assert report["input_visible_at"] == ["2026-01-02T09:00:00+08:00"]


def test_zero_denominators_are_null_and_short_history_is_preserved() -> None:
    report = build_report(
        provider=Rows([{"trading_day": _days(3)[0], "evaluable": False}]),
        card_key="S-01",
        card_version="cv-1",
    )
    assert report["history_status"] == "no_history"
    assert report["trigger_rate"]["value"] is None
    assert report["coverage"]["value"] == 0
    assert "null_reason" not in report["coverage"]


def test_trigger_and_jaccard_are_warnings_only() -> None:
    rows = []
    for day in _days():
        rows.append(
            {
                "trading_day": day,
                "security": "SYNTH-001",
                "evaluable": True,
                "triggered": True,
                "comparable_sets": [["SYNTH-001"]],
            }
        )
    report = build_report(provider=Rows(rows), card_key="S-01", card_version="cv-1")
    assert report["history_status"] == "available"
    assert "trigger_rate_out_of_expected_range" in report["warnings"]
    assert "jaccard_above_0.9" in report["warnings"]
    gate = missing_history_gate(
        True,
        Overlap(max_jaccard=report["max_jaccard"], max_jaccard_null_reason=None),
        warnings=report["warnings"],
        history_status=report["history_status"],
    )
    assert gate["result"] == "warn"


def test_full_history_without_comparable_set_has_explicit_reason() -> None:
    rows = [
        {
            "trading_day": day,
            "security": f"SYNTH-{index:03d}",
            "evaluable": True,
            "triggered": False,
        }
        for index, day in enumerate(_days())
    ]
    report = build_report(provider=Rows(rows), card_key="W-01", card_version="cv-1")
    assert report["history_status"] == "no_comparable_set"
    assert report["max_jaccard"] is None
    assert report["max_jaccard_null_reason"] == "no_comparable_set"


def test_h_card_windows_are_separate_and_event_samples_do_not_overlap() -> None:
    rows = [
        {
            "event_id": "E1",
            "event_date": "2026-01-01",
            "trading_day": "2026-01-01",
            "security": "SYNTH-001",
            "evaluable": True,
            "triggered": True,
        },
        {
            "event_id": "E1",
            "event_date": "2026-01-02",
            "trading_day": "2026-01-02",
            "security": "SYNTH-001",
            "evaluable": True,
            "triggered": True,
        },
    ]
    report = build_report(
        provider=Rows(rows),
        card_key="hold_risk_monitor",
        card_id="H-01",
        card_version="cv-1",
    )
    assert set(report["horizons"]) == {"1", "5", "20"}
    assert report["horizons"]["1"]["real_history"]["N"] == 2
    assert report["horizons"]["5"]["real_history"]["N"] == 1
    assert report["horizons"]["20"]["real_history"]["N"] == 1

"""prepare 参数格式与保守缺口适配，无数据库或网络。"""

# ruff: noqa: S101
from datetime import UTC, date, datetime

import pytest

from app.features.horizon_adjustments import FactorBundle, FactorObservation, to_prepare_factors
from app.features.pipeline import prepare


@pytest.mark.parametrize("missing", [False, True])
def test_prepare_iso_time_and_missing_anchor(missing: bool) -> None:
    day = date(2026, 11, 15)
    at = datetime(2026, 11, 15, 9, tzinfo=UTC)
    factor = FactorObservation(day, "2", at, "synthetic-version")
    bundle = FactorBundle(
        (factor,),
        (factor.version_id,),
        "a" * 64,
        (day,),
        ("adjust_factor_missing:2026-11-16",) if missing else (),
    )
    assert to_prepare_factors(bundle) == (
        [] if missing else [{"date": str(day), "value": "2", "available_at": at.isoformat()}]
    )
    instrument = {
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "amount_unit": "CNY",
        "volume_unit": "share",
        "bars": [
            {
                "trade_date": str(day),
                "first_seen_at": at.isoformat(),
                "is_final": True,
                **dict.fromkeys(("open", "high", "low", "close", "amount"), "10"),
            }
        ],
    }
    prepared = prepare(
        instrument, [str(day)], as_of=at, factors=to_prepare_factors(bundle), registry={}
    )
    assert prepared["series"]["f.close_qfq"] == [None if missing else 10]
    assert (f"adjust_factor_missing:{day}" in prepared["gaps"]) is missing

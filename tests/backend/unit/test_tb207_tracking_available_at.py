from __future__ import annotations

import pytest
from app.tracking.engine import evaluate
from selfchecks.test_p2n03_tracking import sample


@pytest.mark.parametrize(
    "missing_factor",
    [
        {"date": "2031-01-03", "value": "1"},
        {"date": "2031-01-03", "value": "1", "available_at": None},
    ],
)
def test_tracking_missing_factor_available_at_is_unavailable(
    missing_factor: dict[str, object],
) -> None:
    args = sample()
    args["factors"] = [missing_factor]

    result = evaluate(**args)

    gap_keys = {item.key for item in result.gaps}
    assert "factor_available_at_missing" in gap_keys
    assert not any(item.key.startswith("tracking:factor:") for item in result.evidence)


def test_tracking_missing_factor_available_at_does_not_hide_normal_factor() -> None:
    args = sample()
    args["factors"].append({"date": "2031-01-03", "value": "2", "available_at": ""})

    result = evaluate(**args)

    gap_keys = {item.key for item in result.gaps}
    assert "factor_available_at_missing" in gap_keys
    assert sum(item.key == "factor:0" for item in result.evidence) == 1
    assert not any(item.key == "factor:1" for item in result.evidence)

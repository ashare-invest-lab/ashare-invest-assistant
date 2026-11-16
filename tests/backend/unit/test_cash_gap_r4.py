"""R4: cash_gap is ours minus broker; positive means we calculated more.

https://github.com/codeman840425-del/ashare-invest-assistant/blob/f0914c33f55b03eaa38b07adb7900c5f6e7967c9/docs/handover/team/reports/T-B46-47-rulings.md#L26-L29
"""

from decimal import Decimal

import pytest
from app.domain.portfolio import reconcile

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("ours", "broker", "expected_diff", "expected_ours", "expected_broker"),
    [
        ("10", "7", "3.00", "10.00", "7.00"),
        ("7", "10", "-3.00", "7.00", "10.00"),
        ("10.0051", "10", "0.01", "10.01", "10.00"),
        ("10", "10.0051", "-0.01", "10.00", "10.01"),
    ],
)
def test_cash_gap_uses_r4_ours_minus_broker(
    ours, broker, expected_diff, expected_ours, expected_broker
):
    items = reconcile({}, {}, ours_cash=Decimal(ours), broker_cash=Decimal(broker))

    assert len(items) == 1
    item = items[0]
    assert item.kind == "cash_gap"
    assert item.security_code is None
    assert item.ours == expected_ours
    assert item.broker == expected_broker
    assert item.diff == expected_diff


@pytest.mark.parametrize(
    ("ours", "broker"),
    [
        ("10", "10"),
        ("10.0049", "10"),
        ("10", "10.0049"),
        ("10.005", "10"),
        ("10", "10.005"),
    ],
)
def test_cash_gap_preserves_equal_and_within_tolerance(ours, broker):
    assert reconcile({}, {}, ours_cash=Decimal(ours), broker_cash=Decimal(broker)) == []


@pytest.mark.parametrize(
    ("ours", "broker"),
    [(None, Decimal(7)), (Decimal(10), None), (None, None)],
)
def test_cash_gap_requires_both_cash_balances(ours, broker):
    assert reconcile({}, {}, ours_cash=ours, broker_cash=broker) == []

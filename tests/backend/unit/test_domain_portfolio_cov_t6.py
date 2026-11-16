"""COV-T6: deterministic synthetic portfolio-domain contracts; no external resources."""

from __future__ import annotations

import socket
from decimal import Decimal

import pytest

from app.domain import portfolio as pf

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("portfolio domain test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def test_q4_uses_decimal_half_up_for_display_cost() -> None:
    assert pf.q4(Decimal("1.23445")) == Decimal("1.2345")
    assert pf.q4(Decimal("-1.23445")) == Decimal("-1.2345")


def test_optional_decimal_serialization_preserves_empty_and_fixed_precision() -> None:
    assert pf._s(None) is None
    assert pf._s(Decimal("10.5000")) == "10.5"
    assert pf._s(Decimal("10.5000"), pf.MONEY_DP) == "10.50"


@pytest.mark.parametrize(
    ("kind", "raw_qty", "expected"),
    [
        ("dividend", None, "0"),
        ("bonus_share", "-120", "120"),
        ("ipo_allot", "100", "100"),
        ("rights", "-30", "30"),
        ("transfer_in", "40", "40"),
        ("transfer_out", "-80", "-80"),
        ("transfer_out", "80", "-80"),
        ("other", "999", "0"),
    ],
)
def test_event_qty_uses_absolute_quantity_and_event_direction(
    kind: str, raw_qty: str | None, expected: str
) -> None:
    qty = None if raw_qty is None else Decimal(raw_qty)
    assert pf.event_qty(kind, qty) == Decimal(expected)


@pytest.mark.parametrize(
    ("broker_cost", "expected"),
    [("5", "0.01"), ("10", "0.01"), ("100", "0.1"), ("-100", "0.1")],
)
def test_cost_tolerance_is_greater_of_absolute_and_percentage(
    broker_cost: str, expected: str
) -> None:
    assert pf.cost_tolerance(Decimal(broker_cost)) == Decimal(expected)


def test_reconcile_reports_position_and_cost_differences_in_stable_order() -> None:
    ours = {
        "000004.SZ": pf.Lot(qty=Decimal(100), cost_total=Decimal(1000)),
        "000003.SZ": pf.Lot(qty=Decimal(80), cost_total=Decimal(800)),
        "000001.SZ": pf.Lot(qty=Decimal(100), cost_total=Decimal(1000)),
        "000005.SZ": pf.Lot(qty=Decimal(100), cost_total=Decimal(1000)),
    }
    broker = {
        "000006.SZ": (Decimal(0), Decimal(1)),
        "000005.SZ": (Decimal(100), None),
        "000003.SZ": (Decimal(100), Decimal(10)),
        "000002.SZ": (Decimal(50), Decimal(10)),
        "000001.SZ": (Decimal(100), Decimal("10.02")),
    }

    items = pf.reconcile(ours, broker, ours_cash=None, broker_cash=None)

    assert [item.kind for item in items] == [
        "cost_differs",
        "missing_in_ours",
        "quantity_mismatch",
        "missing_in_broker",
    ]
    assert [item.security_code for item in items] == [
        "000001.SZ",
        "000002.SZ",
        "000003.SZ",
        "000004.SZ",
    ]
    cost, missing_ours, mismatch, missing_broker = items
    assert (cost.ours, cost.broker, cost.diff) == ("10.0000", "10.0200", "-0.0200")
    assert (missing_ours.ours, missing_ours.broker, missing_ours.diff) == (
        None,
        "50",
        "-50",
    )
    assert (mismatch.ours, mismatch.broker, mismatch.diff) == ("80", "100", "-20")
    assert (missing_broker.ours, missing_broker.broker, missing_broker.diff) == (
        "100",
        None,
        "100",
    )
    for item in items:
        assert item.note == pf.NOTES[item.kind]
        assert item.actions == (pf.ACTIONS[item.kind],)


@pytest.mark.parametrize(
    ("cost_total", "broker_cost"),
    [("501", "5"), ("10010", "100")],
    ids=["absolute_tolerance_boundary", "percentage_tolerance_boundary"],
)
def test_reconcile_does_not_report_cost_at_tolerance_boundary(
    cost_total: str, broker_cost: str
) -> None:
    ours = {"000001.SZ": pf.Lot(qty=Decimal(100), cost_total=Decimal(cost_total))}
    broker = {"000001.SZ": (Decimal(100), Decimal(broker_cost))}
    assert pf.reconcile(ours, broker, ours_cash=None, broker_cash=None) == []


def test_reconcile_reports_cash_chain_break_without_cash_snapshot() -> None:
    items = pf.reconcile({}, {}, ours_cash=None, broker_cash=None, chain_breaks=3)
    assert len(items) == 1
    item = items[0]
    assert item.kind == "cash_chain_break"
    assert (item.security_code, item.ours, item.broker, item.diff) == (
        None,
        None,
        None,
        "3",
    )
    assert item.note == pf.NOTES["cash_chain_break"]
    assert item.actions == (pf.ACTIONS["cash_chain_break"],)


@pytest.mark.parametrize(
    ("ours_cash", "broker_cash"),
    [(None, Decimal("100")), (Decimal("100"), None), (None, None)],
)
def test_reconcile_does_not_invent_cash_gap_when_a_side_is_missing(
    ours_cash: Decimal | None, broker_cash: Decimal | None
) -> None:
    assert pf.reconcile({}, {}, ours_cash=ours_cash, broker_cash=broker_cash) == []


@pytest.mark.parametrize("security_type", ["stock", "cdr", "etf"])
def test_instrument_kind_preserves_supported_master_type(security_type: str) -> None:
    assert pf.instrument_kind("000001.SZ", security_type) == security_type


def test_instrument_kind_distinguishes_unknown_and_convertible_bond() -> None:
    assert pf.instrument_kind("110000.SH", None) == "convertible_bond"
    assert pf.instrument_kind("000001.SZ", None) == "unknown"
    assert pf.instrument_kind("110000.SH", "bond") == "unknown"

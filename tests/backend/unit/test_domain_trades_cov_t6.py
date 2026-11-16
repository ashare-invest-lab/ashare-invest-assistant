"""COV-T6: deterministic synthetic trade-domain contracts; no external resources."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from decimal import Decimal

import pytest

from app.common.errors import AppError, ErrorCode
from app.domain import trades

pytestmark = pytest.mark.unit

CORRECTS = uuid.UUID("00000000-0000-0000-0000-000000000001")
UTC = dt.UTC


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject(*args: object, **kwargs: object) -> None:
        pytest.fail("trade domain test attempted a network connection")

    monkeypatch.setattr(socket.socket, "connect", reject)
    monkeypatch.setattr(socket, "create_connection", reject)


def assert_reason_error(caught: pytest.ExceptionInfo[AppError], issue: str) -> None:
    assert caught.value.code == ErrorCode.VALIDATION_ERROR
    assert caught.value.details == {"fields": [{"field": "reason", "issue": issue}]}


@pytest.mark.parametrize("raw", [None, "", " \t\n"])
def test_validate_void_reason_rejects_blank(raw: str | None) -> None:
    with pytest.raises(AppError) as caught:
        trades.validate_void_reason(raw)
    assert_reason_error(caught, "required")


def test_validate_void_reason_rejects_more_than_200_characters() -> None:
    with pytest.raises(AppError) as caught:
        trades.validate_void_reason("x" * 201)
    assert_reason_error(caught, "too_long")


def test_validate_void_reason_trims_and_accepts_200_characters() -> None:
    assert trades.validate_void_reason("  synthetic reason  ") == "synthetic reason"
    assert trades.validate_void_reason("x" * 200) == "x" * 200


def test_validate_void_reason_rejects_reserved_batch_prefix() -> None:
    with pytest.raises(AppError) as caught:
        trades.validate_void_reason(f"  {trades.BATCH_REVERTED_PREFIX}synthetic")
    assert_reason_error(caught, "invalid")


def test_correction_reason_is_required_and_trimmed_for_replacement() -> None:
    with pytest.raises(AppError) as caught:
        trades.validate_correction_reason(CORRECTS, "  ")
    assert_reason_error(caught, "required")
    assert trades.validate_correction_reason(CORRECTS, "  corrected  ") == "corrected"


def test_correction_reason_is_optional_without_replacement() -> None:
    assert trades.validate_correction_reason(None, None) is None
    assert trades.validate_correction_reason(None, "  ") is None
    assert trades.validate_correction_reason(None, "  optional  ") == "optional"
    with pytest.raises(AppError) as caught:
        trades.validate_correction_reason(None, "x" * 201)
    assert_reason_error(caught, "too_long")


def test_batch_revert_void_reason_is_namespaced() -> None:
    batch_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
    assert trades.batch_revert_void_reason(batch_id) == f"batch_reverted:{batch_id}"


def test_ensure_voidable_accepts_new_and_rejects_voided_trade() -> None:
    trades.ensure_voidable(None)
    with pytest.raises(AppError) as caught:
        trades.ensure_voidable(dt.datetime(2026, 1, 2, tzinfo=UTC))
    assert caught.value.code == ErrorCode.INVALID_STATE_TRANSITION
    assert caught.value.status_code == 409


def test_trade_out_computes_amount_and_serializes_contract_fields() -> None:
    trade_id = uuid.UUID("00000000-0000-0000-0000-000000000003")
    account_id = uuid.UUID("00000000-0000-0000-0000-000000000004")
    batch_id = uuid.UUID("00000000-0000-0000-0000-000000000005")
    row = {
        "id": trade_id,
        "account_id": account_id,
        "trade_date": dt.date(2026, 1, 2),
        "traded_at": dt.datetime(2026, 1, 2, 1, 2, 3, 4, tzinfo=UTC),
        "security_code": "000001.SZ",
        "side": "buy",
        "quantity": Decimal("2"),
        "price": Decimal("3.50"),
        "amount": None,
        "commission": Decimal("1"),
        "stamp_tax": Decimal("2"),
        "transfer_fee": Decimal("0.3"),
        "other_fee": None,
        "net_amount": Decimal("3.70"),
        "source": "csv_template",
        "import_batch_id": batch_id,
        "voided_at": dt.datetime(2026, 1, 3, 4, 5, 6, tzinfo=UTC),
        "void_reason": "synthetic void",
        "replaces_trade_id": CORRECTS,
        "created_at": dt.datetime(2026, 1, 2, tzinfo=UTC),
    }

    assert trades.trade_out(row, name="合成证券") == {
        "id": str(trade_id),
        "account_id": str(account_id),
        "trade_date": "2026-01-02",
        "trade_time": "09:02:03",
        "security_code": "000001.SZ",
        "name": "合成证券",
        "side": "buy",
        "qty": "2",
        "price": "3.50",
        "amount": "7.00",
        "fee_total": "3.3",
        "net_amount": "3.70",
        "source": "import",
        "batch_id": str(batch_id),
        "voided": True,
        "void_reason": "synthetic void",
        "voided_at": "2026-01-03T04:05:06+00:00",
        "corrects_trade_id": str(CORRECTS),
        "created_at": "2026-01-02T00:00:00+00:00",
    }

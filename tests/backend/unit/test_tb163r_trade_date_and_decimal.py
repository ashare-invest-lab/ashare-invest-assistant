"""GOV-retro-1116 §2.8：公共模块日期格式与 Decimal 精度的纯单元回归。"""

from datetime import date
from decimal import Decimal, getcontext, localcontext

import pytest

from app import bj_offline_volume as gate


@pytest.fixture(autouse=True)
def isolated_confirmation(monkeypatch):
    """合成证据只在本例有效，不能向后续测试遗留进程许可。"""
    monkeypatch.setattr(gate, "_bj_offline_volume_codes", frozenset())
    monkeypatch.setattr(gate, "_bj_confirmation_pid", None)


def _pairs(*, lots="1", shares="100", tdx_date="20250421"):
    return [
        {
            "mairui": {
                "code": f"920{i:03d}.BJ", "t": "2025-04-21 00:00:00",
                "v": lots, "sf": 0,
            },
            "tdx_local": {
                "code": f"920{i:03d}.BJ", "trade_date": tdx_date,
                "volume": shares, "source": "tdx_local", "is_suspended": False,
            },
        }
        for i in range(20)
    ]


def _codes():
    return frozenset(f"920{i:03d}.BJ" for i in range(20))


@pytest.mark.parametrize("value", ["2025-04-21", "20250421", "2025-04-21 00:00:00"])
def test_trade_date_accepts_date_and_midnight(value):
    assert gate._trade_date(value) == date(2025, 4, 21)


@pytest.mark.parametrize("value", [
    "2025-04-21 10:00:00", "2025-04-21 00:00:01",
    "2025-02-30", "20250230", "2025-13-01",
])
def test_trade_date_rejects_nonzero_time_and_invalid_date(value):
    with pytest.raises(gate.RowReject, match="^trade_date_invalid$"):
        gate._trade_date(value)


@pytest.mark.parametrize("tdx_date", ["20250421", "2025-04-21"])
def test_confirm_accepts_mairui_midnight_and_tdx_date(tdx_date):
    assert gate.confirm_bj_offline_volume_units(_pairs(tdx_date=tdx_date)) == _codes()


@pytest.mark.parametrize("lots_text", [
    "12345678901234567890123456789",
    "9876543210987654321098765432109",
])
def test_confirm_rejects_mismatch_hidden_by_default_decimal_precision(lots_text):
    lots = Decimal(lots_text)
    assert len(lots.as_tuple().digits) > 28
    with localcontext() as context:
        context.prec = 28
        assert getcontext().prec == 28
        rounded_shares = lots * 100
        with localcontext() as exact_context:
            exact_context.prec = 100
            exact_shares = lots * 100
        assert exact_shares != rounded_shares
        assert lots * 100 == rounded_shares  # 旧乘法会把反例误认成相等。
        evidence = _pairs(lots=lots_text, shares=str(rounded_shares))
        assert gate.confirm_bj_offline_volume_units(_pairs()) == _codes()
        with pytest.raises(gate.RowReject, match="^bj_offline_volume_mismatch$"):
            gate.confirm_bj_offline_volume_units(evidence)
        assert gate._bj_write_unconfirmed({"code": "920999.BJ"})


@pytest.mark.parametrize("lots_text", [
    "12345678901234567890123456789",
    "98765432109876543210987654321.09",
])
@pytest.mark.parametrize("isolated", [False, True])
def test_confirm_accepts_exact_high_precision_volume_for_twenty_codes(lots_text, isolated, bj_isolated_list):
    if isolated:
        bj_isolated_list(_codes())
    lots = Decimal(lots_text)
    assert len(lots.as_tuple().digits) > 28
    # 独立高精度乘法构造股数，避免用默认上下文，也不复制被测 as_tuple 算法。
    with localcontext() as context:
        context.prec = 100
        shares = lots * 100
    assert shares == shares.to_integral_value()
    with localcontext() as context:
        context.prec = 28
        assert getcontext().prec == 28
        assert lots * 100 != shares
        assert gate.confirm_bj_offline_volume_units(
            _pairs(lots=lots_text, shares=str(shares))
        ) == _codes()
        assert gate._bj_write_unconfirmed({"code": "920000.BJ"}) is (not isolated)
        assert gate._bj_write_unconfirmed({"code": "920999.BJ"})

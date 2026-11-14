"""Deterministic synthetic regression for preview branches lost in full-suite coverage."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

from app.importing import findings as F
from app.importing.preview import (
    PreviewContext,
    RowResult,
    SecurityInfo,
    _choice,
    _market_for,
    _row_warnings,
)

TRADE_DATE = dt.date(2026, 11, 16)
UPLOADED_AT = dt.datetime(2026, 11, 16, 10, tzinfo=dt.UTC)


def context() -> PreviewContext:
    return PreviewContext(
        account_id="synthetic-coverage-repair",
        today=TRADE_DATE,
        uploaded_at=UPLOADED_AT,
        holder_hmac=lambda value: value,
    )


def security() -> SecurityInfo:
    return SecurityInfo(
        code="600000",
        name="合成主数据名称",
        exchange="SH",
        type="stock",
        board="main",
    )


def test_market_prefers_the_supplied_security_master() -> None:
    ctx = context()
    info = security()
    ctx.securities = {info.code: info}
    assert _market_for(info.code, ctx) == "SH"


def test_row_warnings_report_a_security_name_mismatch() -> None:
    ctx = context()
    info = security()
    ctx.securities = {info.code: info}
    row = RowResult(row_no=7, kind="trade", normalized={})
    parsed = {
        7: {
            "security_code": info.code,
            "name": "合成文件别名",
            "side": "sell",
            "net_amount": None,
            "holder_market": None,
            "trade_date": TRADE_DATE,
            "trade_time": None,
            "qty": Decimal(100),
        }
    }

    _row_warnings([row], parsed, ctx)

    assert [finding["code"] for finding in row.findings] == ["IMPORT_NAME_MISMATCH"]
    assert row.findings[0]["params"]["name_raw"] == "合成文件别名"
    assert row.findings[0]["params"]["name"] == info.name


def test_choice_returns_the_recorded_effective_resolution() -> None:
    finding = F.make("IMPORT_UNKNOWN_SECURITY", row_no=7, code="600000")
    finding["resolution"] = {"choice": "skip_row"}
    row = RowResult(row_no=7, kind="trade", normalized={}, findings=[finding])
    assert _choice(row, "IMPORT_UNKNOWN_SECURITY") == "skip_row"
    assert _choice(row, "IMPORT_NAME_MISMATCH") is None

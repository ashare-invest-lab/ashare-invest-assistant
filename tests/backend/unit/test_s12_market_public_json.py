"""JSON round-trip coverage for the four public market models."""

import json

import pytest
from app.aggregates.models import Account, MarketOverview, TodayMarket
from app.reports.models import Market
from pydantic import BaseModel

pytestmark = pytest.mark.unit

BASIS = {
    "snapshot_id": "00000000-0000-4000-8000-000000000187",
    "observed_date": "2031-01-07",
    "mode": "intraday",
    "scope": "沪深股票口径",
    "eligible": 9,
    "observed": 7,
    "trading": 5,
    "suspended": 2,
    "missing": 2,
    "source": "synthetic://market-public-json",
}
MARKET_FIELDS = {
    "basis": BASIS,
    "regime": "range",
    "regime_position_range": {"min_pct": "20.00", "max_pct": "50.00"},
    "data_status": "partial",
}
DATA_FIELDS = {
    "data_as_of": "2031-01-07T14:12:00+08:00",
    "gaps": [{"key": "market.partial", "reason": "no_source", "message": "合成缺口"}],
}
BREADTH = {"up": 2, "down": 1, "limit_up": 0, "limit_down": 0}


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        pytest.param(
            MarketOverview,
            {
                **MARKET_FIELDS,
                **DATA_FIELDS,
                "trade_date": "2031-01-07",
                "session": "afternoon",
                "indices": [
                    {
                        "security_code": "999991.SH",
                        "name": "合成指数",
                        "price": "12.34",
                        "change_pct": "0.00",
                        "amount": None,
                        "t": DATA_FIELDS["data_as_of"],
                    }
                ],
                "breadth": {**BREADTH, "flat": 2},
                "turnover_total": "1234.50",
            },
            id="market-overview",
        ),
        pytest.param(TodayMarket, MARKET_FIELDS, id="today-market"),
        pytest.param(
            Account,
            {
                **MARKET_FIELDS,
                "account_id": "00000000-0000-4000-8000-000000000201",
                "total_assets": "100.50",
                "cash_available": "40.00",
                "position_pct": "60.20",
                "pnl_day": None,
            },
            id="terminal-account",
        ),
        pytest.param(
            Market,
            {
                **MARKET_FIELDS,
                **DATA_FIELDS,
                "breadth": BREADTH,
                "summary": [{"text": "合成市场摘要", "expr": None, "evidence_ids": []}],
            },
            id="daily-report-market",
        ),
    ],
)
def test_public_market_model_preserves_every_json_field(
    model: type[BaseModel], payload: dict[str, object]
) -> None:
    parsed = model.model_validate_json(json.dumps(payload), strict=True)

    assert json.loads(parsed.model_dump_json()) == payload

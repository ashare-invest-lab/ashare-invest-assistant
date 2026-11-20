"""Offline projections for the T-A209 M1 market response proposals."""

from __future__ import annotations

import datetime as dt
import json
from collections.abc import Mapping

from pydantic import Field, JsonValue, model_validator

from app.aggregates.market_basis import MarketBasis
from app.aggregates.models import Account, DataBlock, Gap, MarketOverview, TodayMarket
from app.reports.models import DailyReport, Market
from app.schemas.enums import DataStatus, GapReason


class MarketOverviewWithBasis(MarketOverview):
    basis: MarketBasis = Field(default_factory=MarketBasis)


class AccountWithMarketBasis(Account):
    basis: MarketBasis = Field(default_factory=MarketBasis)


class TodayMarketWithBasis(TodayMarket):
    basis: MarketBasis = Field(default_factory=MarketBasis)


class ReportMarketWithBasis(Market, DataBlock):
    basis: MarketBasis = Field(default_factory=MarketBasis)

    data_status: DataStatus = DataStatus.UNAVAILABLE
    data_as_of: dt.datetime | None = None
    gaps: list[Gap] = Field(default_factory=list)

    @model_validator(mode="after")
    def project_legacy_fields(self) -> ReportMarketWithBasis:
        supplied = self.model_fields_set.copy()
        if "basis" in supplied:
            return self
        has_market_facts = any(
            value is not None
            for value in (self.regime, self.regime_position_range, self.breadth, self.data_as_of)
        )
        if "data_status" not in supplied and has_market_facts:
            self.data_status = DataStatus.PARTIAL
        if "gaps" not in supplied:
            self.gaps = [
                Gap(
                    key="market.basis",
                    reason=GapReason.NO_SOURCE,
                    message="旧日报未保存市场快照来源。",
                )
            ]
        return self


class DailyReportWithMarketBasis(DailyReport):
    market: ReportMarketWithBasis


def project_market_overview(body: Mapping[str, JsonValue]) -> MarketOverviewWithBasis:
    """Project a frozen JSON response without reading a current market snapshot."""
    return MarketOverviewWithBasis.model_validate_json(json.dumps(dict(body)))


def project_daily_report_market(body: Mapping[str, JsonValue]) -> ReportMarketWithBasis:
    """Project the archived market block while keeping its original facts and clock."""
    return ReportMarketWithBasis.model_validate_json(json.dumps(dict(body)))

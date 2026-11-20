"""Project frozen market JSON using the current public response models."""

from __future__ import annotations

import json
from collections.abc import Mapping

from pydantic import JsonValue

from app.aggregates.models import MarketOverview
from app.reports.models import Market


def project_market_overview(body: Mapping[str, JsonValue]) -> MarketOverview:
    return MarketOverview.model_validate_json(json.dumps(dict(body)))


def project_daily_report_market(body: Mapping[str, JsonValue]) -> Market:
    return Market.model_validate_json(json.dumps(dict(body)))

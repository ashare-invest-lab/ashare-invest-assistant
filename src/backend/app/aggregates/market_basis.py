"""Offline T-A209 M1 schema for market observations and report snapshot metadata."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, JsonValue, model_validator

from app.aggregates.models import Model

MarketCount = Annotated[int, Field(ge=0)]


class MarketBasis(Model):
    snapshot_id: uuid.UUID | None = None
    observed_date: dt.date | None = None
    mode: Literal["intraday", "close"] | None = None
    scope: Literal["沪深股票口径"] = "沪深股票口径"
    eligible: MarketCount | None = None
    observed: MarketCount | None = None
    trading: MarketCount | None = None
    suspended: MarketCount | None = None
    missing: MarketCount | None = None
    source: str | None = None

    @model_validator(mode="after")
    def validate_counts(self) -> MarketBasis:
        counts = (self.observed, self.trading, self.suspended, self.missing)
        if self.eligible is None:
            if any(count is not None for count in counts):
                raise ValueError("market_counts_without_eligibility")
            return self
        if (
            self.observed is not None
            and self.missing is not None
            and self.missing != self.eligible - self.observed
        ):
            raise ValueError("market_missing_count_mismatch")
        if any(count is not None and count > self.eligible for count in counts):
            raise ValueError("market_count_exceeds_eligibility")
        if self.observed is not None:
            explained = (self.trading or 0) + (self.suspended or 0)
            if explained > self.observed:
                raise ValueError("market_count_exceeds_observed")
        return self


class MarketSnapshotRecord(Model):
    """Report snapshot data for internal use. Readers must enforce owner and licence scope."""

    snapshot_id: uuid.UUID
    purpose: Literal["report"] = "report"
    user_id: uuid.UUID | None = None
    licence_id: uuid.UUID | None = None
    batch_id: uuid.UUID | None = None
    source_as_of: AwareDatetime | None = None
    fetched_at: AwareDatetime | None = None
    basis: MarketBasis = Field(default_factory=MarketBasis)
    eligibility_evidence: list[dict[str, JsonValue]] = Field(default_factory=list)
    f25_evidence: list[dict[str, JsonValue]] = Field(default_factory=list)

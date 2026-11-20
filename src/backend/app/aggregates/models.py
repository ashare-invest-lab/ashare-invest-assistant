"""Public field boilerplate reviewed locally from DeepSeek T-B77 draft.

Enums/nullability/required fields verified against api-contract §5.1/7.3.
Real owned products are typed; unbuilt plan event producers remain empty with gaps.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    PrivateAttr,
    model_validator,
)

from app.schemas import enums as e
from app.schemas.enums import (
    DataGapScope,
    DataStatus,
    GapReason,
    MarketRegime,
    MarketSession,
    ReconciliationStatus,
    RiskLevel,
    SecurityType,
)
from app.signals.models import Evidence, RiskFlag


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Gap(Model):
    key: str
    reason: GapReason
    message: str


class DataBlock(Model):
    data_status: DataStatus
    data_as_of: dt.datetime | None
    gaps: list[Gap]


class MarketClock(Model):
    """Must come from a reviewed calendar adapter; never guessed from weekday/code."""

    trade_date: dt.date
    session: MarketSession


class Range(Model):
    min_pct: str
    max_pct: str


class TerminalHolding(Model):
    qty: str
    sellable_qty: str
    cost_price: str
    weight_pct: str
    pnl: str | None
    pnl_pct: str | None
    security_type: SecurityType | None
    estimated: bool


class TerminalQuote(Model):
    price: str
    change_pct: str | None
    amount: str | None
    t: dt.datetime


class SummaryAction(Model):
    strategy_key: str
    strategy_name: str
    action: e.Action
    t_leg: e.TLeg | None
    lifecycle: e.Lifecycle


class SuggestionSummary(Model):
    id: uuid.UUID
    created_at: dt.datetime
    status: e.SuggestionStatus
    security_code: str
    name: str
    consensus: e.ConsensusStatus
    actions: list[SummaryAction]
    executability_status: e.ExecutabilityStatus
    divergent_dimensions: list[e.Dimension]
    top_score: int | None = Field(ge=0, le=100)


class TerminalRow(Model):
    security_code: str
    name: str
    in_watchlist: bool
    focus: bool
    quote: TerminalQuote | None
    holding: TerminalHolding | None
    suggestion: SuggestionSummary | None
    active_reason_count: int = Field(ge=0)
    max_risk_level: RiskLevel | None
    data_status: DataStatus
    data_as_of: dt.datetime | None


class TView(Model):
    vwap: str | None
    dev_pct: str | None
    volume_ratio: str | None
    base_qty: str | None
    sellable_qty: str | None
    # §3.7③：阈值未验证时缺省（不输出该键），而非 null。
    dev_pct_threshold: str | None = Field(default=None, exclude_if=lambda v: v is None)
    volume_ratio_threshold: str | None = Field(default=None, exclude_if=lambda v: v is None)
    data_status: DataStatus
    as_of: dt.datetime | None
    gaps: list[Gap]


class TodayRow(TerminalRow):
    t_view: TView | None


class MarketIndex(Model):
    security_code: str
    name: str
    price: str | None
    change_pct: str | None
    amount: str | None
    t: dt.datetime | None


class Breadth(Model):
    up: int = Field(ge=0)
    down: int = Field(ge=0)
    flat: int = Field(ge=0)
    limit_up: int = Field(ge=0)
    limit_down: int = Field(ge=0)


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
    """Internal report metadata. Snapshot reads must enforce owner and licence scope."""

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


class MarketOverview(DataBlock):
    basis: MarketBasis = Field(default_factory=MarketBasis)
    trade_date: dt.date
    session: MarketSession
    indices: list[MarketIndex]
    breadth: Breadth | None
    regime: MarketRegime | None
    regime_position_range: Range | None
    turnover_total: str | None


class Account(Model):
    basis: MarketBasis = Field(default_factory=MarketBasis)
    account_id: uuid.UUID
    total_assets: str
    cash_available: str
    position_pct: str | None
    pnl_day: str | None
    regime: MarketRegime | None
    regime_position_range: Range | None
    data_status: DataStatus


class Terminal(DataBlock):
    _focus_more: bool = PrivateAttr(default=False)
    account_id: uuid.UUID | None
    server_time: dt.datetime
    trade_date: dt.date
    session: MarketSession
    account: Account | None
    rows: list[TerminalRow] = Field(max_length=300)
    truncated: bool
    unread_notifications: int = Field(ge=0)


class ProductBlock[T](Model):
    items: list[T] = Field(max_length=50)
    more: bool


class PendingDraft(Model):
    id: uuid.UUID
    security_code: str
    name: str
    action: e.Action
    valid_until: dt.datetime
    status: e.PlanDraftStatus


class ReleasedReason(Model):
    reason_id: uuid.UUID
    signal_id: uuid.UUID
    code: e.ReasonCode
    security_code: str
    name: str
    released_at: dt.datetime


class TodayRiskFlag(RiskFlag):
    security_code: str | None
    name: str | None
    risk_event_id: uuid.UUID | None


class TodayAffectedPlan(Model):
    plan_id: uuid.UUID
    plan_version_no: int
    condition_id: uuid.UUID | None


class TodayAlert(Model):
    id: uuid.UUID
    rule_id: uuid.UUID
    origin: Literal["holding_event", "user_custom"]
    severity: e.Severity
    status: Literal["new", "read"]
    security_code: str | None
    name: str | None
    title: str
    triggered_at: dt.datetime
    data_as_of: dt.datetime | None
    affected_plans: list[TodayAffectedPlan]
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def account_name(self) -> TodayAlert:
        if self.security_code is None and self.name is not None:
            raise ValueError("account_alert_name_must_be_null")
        return self


class Invalidation(Model):
    suggestion_id: uuid.UUID
    security_code: str
    name: str
    strategy_key: str
    text: str
    at: dt.datetime


class EmptyBlock(Model):
    items: tuple[()]
    more: Literal[False]


class Focus(Model):
    items: list[TodayRow] = Field(max_length=50)
    more: bool


class Reconciliation(Model):
    status: ReconciliationStatus
    as_of: dt.datetime | None
    diff_count: int = Field(ge=0)
    important_count: int = Field(ge=0)


class Report(Model):
    date: dt.date
    status: Literal["ready", "generating", "not_yet"]


class TodayMarket(Model):
    basis: MarketBasis = Field(default_factory=MarketBasis)
    regime: MarketRegime | None
    regime_position_range: Range | None
    data_status: DataStatus


class GapSecurity(Model):
    security_code: str
    name: str


class TodayGap(Model):
    key: str
    reason: GapReason
    scope: DataGapScope
    dataset: str | None
    message: str
    security_count: int = Field(ge=0)
    securities: list[GapSecurity] = Field(max_length=10)
    since: dt.datetime | None
    route: str | None


class GapBlock(Model):
    items: list[TodayGap] = Field(max_length=50)
    more: Literal[False]


class Today(DataBlock):
    account_id: uuid.UUID | None
    server_time: dt.datetime
    trade_date: dt.date
    session: MarketSession
    market: TodayMarket
    focus: Focus
    pending_plan_drafts: ProductBlock[PendingDraft]
    released_reasons: ProductBlock[ReleasedReason]
    risk_flags: ProductBlock[TodayRiskFlag]
    invalidations_today: ProductBlock[Invalidation]
    daily_report: Report
    reconciliation: Reconciliation
    unread_notifications: int = Field(ge=0)
    alerts: ProductBlock[TodayAlert]
    plan_triggers: EmptyBlock
    data_gaps: GapBlock
    evidence: list[Evidence]

    @model_validator(mode="after")
    def resolves(self) -> Today:
        if not {i for alert in self.alerts.items for i in alert.evidence_ids} <= {
            item.id for item in self.evidence
        }:
            raise ValueError("unresolved_evidence")
        return self


class ReconciliationItem(Model):
    kind: e.ReconciliationItemKind
    security_code: str | None
    name: str | None
    ours: str | None
    broker: str | None
    diff: str | None
    important: bool
    note: str


class ReconciliationResult(Model):
    status: ReconciliationStatus
    as_of: dt.datetime | None
    items: list[ReconciliationItem]

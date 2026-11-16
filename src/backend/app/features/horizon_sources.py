"""Horizon A0 immutable evidence boundary; no database or acquisition side effects."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID


@dataclass(frozen=True, kw_only=True)
class SourceVersion:
    user_id: UUID
    licence_id: UUID | None
    scope: str
    source: str
    version_hash: str
    source_version: str
    first_seen_at: datetime | None
    available_at: datetime | None
    persisted_receipt: str
    version_id: str
    unit: str | None = None
    transform_version: str = "identity-v1"
    dependency_ids: tuple[str, ...] = ()


@dataclass(frozen=True, kw_only=True)
class DailyBarVersion(SourceVersion):
    code: str
    trade_date: date
    volume_unit: str | None = None
    amount_unit: str | None = None
    adj_type: str = "none"
    is_suspended: bool | None = None
    fetched_at: datetime | None = None
    conflicted: bool = False

    @property
    def valid_k(self) -> bool:
        return self.is_suspended is False


@dataclass(frozen=True, kw_only=True)
class CalendarVersion(SourceVersion):
    days: tuple[tuple[date, bool], ...]


@dataclass(frozen=True)
class CompletionProof:
    version: DailyBarVersion
    is_final: bool | None
    available_at: datetime | None
    source_final_receipt: str
    run_id: str | None = None


@dataclass(frozen=True)
class BatchReceipt:
    run_id: str
    owner_id: UUID | None
    licence_id: UUID | None
    run_date: date
    status: str
    finished_at: datetime
    available_at: datetime
    issues: tuple[str, ...] = ()
    members: tuple[tuple[UUID, str], ...] = ()
    kind: str = "daily_batch"
    step: str = "daily_bars.fetch"
    window_trading_days: int | None = None


@dataclass(frozen=True)
class BasisEvidence:
    calendar: CalendarVersion | None = None
    bars: tuple[DailyBarVersion, ...] = ()
    proofs: tuple[CompletionProof, ...] = ()
    batches: tuple[BatchReceipt, ...] = ()
    gaps: tuple[str, ...] = ()


@dataclass(frozen=True)
class VersionBundle:
    versions: tuple[SourceVersion, ...] = ()
    gaps: tuple[str, ...] = ()


class HorizonEvidenceProvider(Protocol):
    def read_basis(
        self, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
    ) -> BasisEvidence: ...

    def read_versions(
        self,
        *,
        user_id: UUID,
        licence_id: UUID | None,
        code: str,
        kind: str,
        dates: Sequence[date],
        as_of: datetime,
    ) -> VersionBundle: ...


def aware(as_of: datetime) -> datetime:
    if as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("as_of requires an aware instant")
    return as_of


def visible(at: datetime | None, as_of: datetime) -> bool:
    return at is not None and at.utcoffset() is not None and at <= as_of


def permitted(v: SourceVersion, user_id: UUID, licence_id: UUID | None, as_of: datetime) -> bool:
    scope_ok = (
        v.scope == "per_licence" and licence_id is not None and v.licence_id == licence_id
    ) or (v.scope in {"public", "synthetic"} and v.licence_id is None)
    return bool(
        v.user_id == user_id
        and scope_ok
        and v.source != "tdx_local"
        and (v.source != "fake" or v.scope == "synthetic")
        and (v.source != "mairui" or v.scope == "per_licence")
        and v.source
        and v.source_version
        and v.version_hash
        and v.persisted_receipt
        and visible(v.first_seen_at, as_of)
        and visible(v.available_at, as_of)
        and v.first_seen_at is not None
        and v.available_at is not None
        and v.first_seen_at <= v.available_at
    )


class EmptyEvidenceProvider:
    def read_basis(
        self, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
    ) -> BasisEvidence:
        aware(as_of)
        return BasisEvidence(gaps=("evidence_unavailable",))

    def read_versions(
        self,
        *,
        user_id: UUID,
        licence_id: UUID | None,
        code: str,
        kind: str,
        dates: Sequence[date],
        as_of: datetime,
    ) -> VersionBundle:
        aware(as_of)
        return VersionBundle(gaps=("evidence_unavailable",))


class FakeEvidenceProvider(EmptyEvidenceProvider):
    """Explicit synthetic fixtures only; A1b supplies real version/revision adapters."""

    def __init__(self, basis: BasisEvidence) -> None:
        versions: tuple[SourceVersion, ...] = (*basis.bars, *(p.version for p in basis.proofs))
        if basis.calendar is not None:
            versions = (*versions, basis.calendar)
        if any(v.scope != "synthetic" for v in versions):
            raise ValueError("fake provider requires synthetic evidence")
        self.basis = basis

    def read_basis(
        self, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
    ) -> BasisEvidence:
        aware(as_of)
        b = self.basis
        bars = tuple(
            v for v in b.bars if v.code == code and permitted(v, user_id, licence_id, as_of)
        )
        calendar = b.calendar
        if calendar is not None and not permitted(calendar, user_id, licence_id, as_of):
            calendar = None
        return BasisEvidence(
            calendar,
            bars,
            tuple(p for p in b.proofs if p.version in bars and visible(p.available_at, as_of)),
            b.batches,
            b.gaps,
        )

    def read_versions(
        self,
        *,
        user_id: UUID,
        licence_id: UUID | None,
        code: str,
        kind: str,
        dates: Sequence[date],
        as_of: datetime,
    ) -> VersionBundle:
        b = self.read_basis(user_id=user_id, licence_id=licence_id, code=code, as_of=as_of)
        versions = tuple(v for v in b.bars if v.trade_date in dates) if kind == "daily_bar" else ()
        if any(v.conflicted for v in versions) or any(
            sum(v.trade_date == d for v in versions) > 1 for d in dates
        ):
            return VersionBundle(gaps=("version_conflict",))
        missing = tuple(
            f"version_missing:{d}" for d in dates if not any(v.trade_date == d for v in versions)
        )
        return VersionBundle(versions, (*b.gaps, *missing))

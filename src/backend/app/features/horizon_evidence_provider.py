"""T-A202 §4：只读 PIT 适配器；完成声明与真实历史可见性仍未验证。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Connection, RowMapping, and_, or_, select

from app.db.tables.horizon import horizon_completion_evidence as completions
from app.db.tables.horizon import horizon_input_versions as versions
from app.features.horizon_evidence_store import EvidenceRejected, validate_batch
from app.features.horizon_sources import (
    BasisEvidence,
    BatchReceipt,
    CalendarVersion,
    CompletionProof,
    DailyBarVersion,
    HorizonEvidenceProvider,
    SourceVersion,
    VersionBundle,
    aware,
    permitted,
    visible,
)
from app.features.horizon_windows import BEIJING

Row = RowMapping


def _version(row: Row) -> SourceVersion:
    payload = row["payload"]
    fields = {
        key: row[key]
        for key in (
            "user_id",
            "licence_id",
            "scope",
            "source",
            "version_hash",
            "source_version",
            "first_seen_at",
            "available_at",
            "transform_version",
        )
    }
    fields.update(
        version_id=str(row["id"]),
        persisted_receipt=payload.get("persisted_receipt", ""),
        dependency_ids=tuple(str(v) for v in row["dependency_ids"]),
    )
    if row["kind"] == "daily_bar":
        return DailyBarVersion(
            **fields,
            code=row["code"],
            trade_date=row["data_date"],
            adj_type=payload["adj_type"],
            is_suspended=payload["is_suspended"],
            fetched_at=datetime.fromisoformat(payload["fetched_at"])
            if payload["fetched_at"]
            else None,
            unit=payload["price_unit"],
        )
    if row["kind"] == "calendar":
        day = row["data_date"]
        covered = (
            date.fromisoformat(payload["coverage_start"])
            <= day
            <= date.fromisoformat(payload["coverage_end"])
        )
        return CalendarVersion(**fields, days=((day, payload["is_open"]),) if covered else ())
    return SourceVersion(**fields)


class DatabaseHorizonEvidenceProvider:
    def __init__(self, conn: Connection) -> None:
        self.conn = conn

    def _read(
        self,
        *,
        user_id: UUID,
        licence_id: UUID | None,
        code: str,
        kind: str,
        dates: Sequence[date] | None,
        as_of: datetime,
    ) -> tuple[list[tuple[date, SourceVersion]], list[str]]:
        aware(as_of)
        if kind == "vendor_factor":  # 来源/披露映射未验证，b2a 亦拒绝登记。
            return [], ["vendor_factor_unavailable"]
        if dates is not None and not dates:
            return [], []
        c = versions.c
        public = and_(c.licence_id.is_(None), c.scope.in_(("public", "synthetic")))
        scope = (
            public
            if licence_id is None
            else or_(public, and_(c.licence_id == licence_id, c.scope == "per_licence"))
        )
        query = select(versions).where(
            c.user_id == user_id,
            scope,
            c.kind == kind,
            or_(c.code.is_(None), c.code == code) if kind == "calendar" else c.code == code,
            c.data_date <= as_of.astimezone(BEIJING).date(),
            c.first_seen_at.is_not(None),
            c.first_seen_at <= as_of,
            c.available_at.is_not(None),
            c.available_at <= as_of,
        )
        if dates is not None:
            query = query.where(c.data_date.in_(dates))
        rows = self.conn.execute(
            query.order_by(c.data_date, c.source, c.source_key, c.id)
        ).mappings()
        groups: dict[tuple[object, ...], list[tuple[Row, SourceVersion]]] = defaultdict(list)
        gaps: list[str] = []
        for row in rows:
            version = _version(row)
            # SQL 范围/PIT 与 A0 来源资格分别检查；不借空证书放行 mairui。
            if permitted(version, user_id, licence_id, as_of):
                key = tuple(
                    row[k]
                    for k in (
                        "user_id",
                        "licence_id",
                        "kind",
                        "source",
                        "code",
                        "data_date",
                        "source_key",
                    )
                )
                groups[key].append((row, version))
        selected: list[tuple[date, SourceVersion]] = []
        for key, group in groups.items():
            superseded = {r["supersedes_id"] for r, _ in group}
            tips = [(r, v) for r, v in group if r["id"] not in superseded]
            if len(tips) == 1:
                selected.append((tips[0][0]["data_date"], tips[0][1]))
            else:
                gaps.append(f"version_conflict:{kind}:{key[-2]}:{key[-1]}")
        return selected, gaps

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
        selected, gaps = self._read(
            user_id=user_id, licence_id=licence_id, code=code, kind=kind, dates=dates, as_of=as_of
        )
        covered = {d for d, v in selected if not isinstance(v, CalendarVersion) or v.days}
        gaps.extend(f"version_missing:{d}" for d in dict.fromkeys(dates) if d not in covered)
        return VersionBundle(tuple(v for _, v in selected), tuple(gaps))

    def read_basis(
        self, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
    ) -> BasisEvidence:
        calendars, gaps = self._read(
            user_id=user_id,
            licence_id=licence_id,
            code=code,
            as_of=aware(as_of),
            dates=None,
            kind="calendar",
        )
        daily, bar_gaps = self._read(
            user_id=user_id,
            licence_id=licence_id,
            code=code,
            as_of=as_of,
            dates=None,
            kind="daily_bar",
        )
        gaps.extend(bar_gaps)
        by_day: dict[date, list[CalendarVersion]] = defaultdict(list)
        for _, v in calendars:
            if isinstance(v, CalendarVersion):
                for day, _ in v.days:
                    by_day[day].append(v)
                if not v.days:
                    gaps.append(f"calendar_not_covered:{v.version_id}")
        days: list[tuple[date, bool]] = []
        members: list[CalendarVersion] = []
        for day, candidates in sorted(by_day.items()):
            if len(candidates) == 1:
                members.append(candidates[0])
                days.extend(candidates[0].days)
            else:
                gaps.append(f"calendar_conflict:{day}")
        calendar = None
        if members:
            known = {day for day, _ in days}
            start = days[0][0]
            for offset in range((as_of.astimezone(BEIJING).date() - start).days + 1):
                day = start + timedelta(days=offset)
                if day not in known:
                    gaps.append(f"calendar_not_covered:{day}")
            # 协议只有一个日历槽：末日行作锚，逐日不可变 ID 保留在组合视图的依赖中。
            calendar = replace(
                members[-1],
                days=tuple(days),
                first_seen_at=max(v.first_seen_at for v in members if v.first_seen_at is not None),
                available_at=max(v.available_at for v in members if v.available_at is not None),
                dependency_ids=tuple(
                    dict.fromkeys(
                        item for v in members for item in (*v.dependency_ids, v.version_id)
                    )
                ),
            )
        else:
            gaps.append("calendar_missing")
        bars = tuple(v for _, v in daily if isinstance(v, DailyBarVersion))
        if not bars:
            gaps.append("daily_bar_missing")
        indexed = {UUID(v.version_id): v for v in bars}
        proofs: dict[UUID, list[CompletionProof]] = defaultdict(list)
        batches: list[BatchReceipt] = []
        if indexed:
            c = completions.c
            rows = self.conn.execute(
                select(completions)
                .where(
                    c.bar_version_id.in_(indexed),
                    c.available_at.is_not(None),
                    c.available_at <= as_of,
                )
                .order_by(c.bar_version_id, c.id)
            ).mappings()
            for row in rows:
                payload = row["proof"]
                if not payload.get("persisted_receipt"):
                    continue
                bar = indexed[row["bar_version_id"]]
                # 真实供应商的完成声明/原始回执来源未验证；只透传已登记显式声明。
                proofs[row["bar_version_id"]].append(
                    CompletionProof(
                        bar,
                        row["is_final"],
                        row["available_at"],
                        payload.get("source_final_receipt", ""),
                        str(row["pipeline_run_id"]) if row["pipeline_run_id"] else None,
                    )
                )
                for raw in payload.get("batches", []):
                    try:
                        validate_batch(raw)
                        batch = BatchReceipt(
                            run_id=raw["run_id"],
                            owner_id=UUID(raw["owner_id"]) if raw["owner_id"] else None,
                            licence_id=UUID(raw["licence_id"]) if raw["licence_id"] else None,
                            run_date=date.fromisoformat(raw["run_date"]),
                            status=raw["status"],
                            finished_at=datetime.fromisoformat(raw["finished_at"]),
                            available_at=datetime.fromisoformat(raw["available_at"]),
                            issues=tuple(raw["issues"]),
                            members=tuple((UUID(u), s) for u, s in raw["members"]),
                            kind=raw["kind"],
                            step=raw["step"],
                            window_trading_days=raw.get("window_trading_days"),
                        )
                    except (EvidenceRejected, KeyError, TypeError, ValueError):
                        gaps.append(f"batch_invalid:{row['id']}")
                        continue
                    if (
                        batch.licence_id == licence_id
                        and (
                            batch.owner_id == user_id
                            or (batch.owner_id is None and (user_id, code) in batch.members)
                        )
                        and visible(batch.available_at, as_of)
                        and visible(batch.finished_at, as_of)
                    ):
                        batches.append(batch)
        final: list[CompletionProof] = []
        for bar_id, bar in indexed.items():
            found = proofs[bar_id]
            if {p.is_final for p in found} >= {True, False}:
                gaps.append(f"completion_conflict:{bar.trade_date}")
            else:
                final.extend(found)
                if not any(p.is_final is True and p.source_final_receipt for p in found):
                    gaps.append(f"completion_missing:{bar.trade_date}")
        return BasisEvidence(
            calendar, bars, tuple(final), tuple(dict.fromkeys(batches)), tuple(gaps)
        )


if TYPE_CHECKING:

    def _check_protocol(connection: Connection) -> HorizonEvidenceProvider:
        provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(connection)
        return provider

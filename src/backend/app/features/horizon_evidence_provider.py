"""T-A202 §4：只读 PIT 适配器；完成声明与真实历史可见性仍未验证。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
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


@dataclass
class _VersionRead:
    selected: list[tuple[date, SourceVersion]] = field(default_factory=list)
    history: list[SourceVersion] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: set[date] = field(default_factory=set)


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
            volume_unit=payload["volume_unit"],
            amount_unit=payload["amount_unit"],
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
    ) -> _VersionRead:
        aware(as_of)
        if kind == "vendor_factor":  # 来源/披露映射未验证，b2a 亦拒绝登记。
            return _VersionRead(gaps=["vendor_factor_unavailable"])
        if dates is not None and not dates:
            return _VersionRead()
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
        result = _VersionRead()
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
                result.history.append(version)
        for key, group in groups.items():
            superseded = {r["supersedes_id"] for r, _ in group}
            tips = [(r, v) for r, v in group if r["id"] not in superseded]
            if len(tips) == 1:
                result.selected.append((tips[0][0]["data_date"], tips[0][1]))
            else:
                result.gaps.append(f"version_conflict:{kind}:{key[-2]}:{key[-1]}")
                result.conflicts.add(group[0][0]["data_date"])
        return result

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
        result = self._read(
            user_id=user_id, licence_id=licence_id, code=code, kind=kind, dates=dates, as_of=as_of
        )
        covered = {d for d, v in result.selected if not isinstance(v, CalendarVersion) or v.days}
        result.gaps.extend(f"version_missing:{d}" for d in dict.fromkeys(dates) if d not in covered)
        return VersionBundle(tuple(v for _, v in result.selected), tuple(result.gaps))

    def read_basis(
        self, *, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime
    ) -> BasisEvidence:
        calendars = self._read(
            user_id=user_id,
            licence_id=licence_id,
            code=code,
            as_of=aware(as_of),
            dates=None,
            kind="calendar",
        )
        daily = self._read(
            user_id=user_id,
            licence_id=licence_id,
            code=code,
            as_of=as_of,
            dates=None,
            kind="daily_bar",
        )
        gaps = [*calendars.gaps, *daily.gaps]
        conflicts = calendars.conflicts | daily.conflicts
        by_day: dict[date, list[CalendarVersion]] = defaultdict(list)
        for day, v in calendars.selected:
            if isinstance(v, CalendarVersion):
                for day, _ in v.days:
                    by_day[day].append(v)
                if not v.days:
                    gaps.append(f"calendar_not_covered:{day}")
        days: list[tuple[date, bool]] = []
        members: list[CalendarVersion] = []
        for day, candidates in sorted(by_day.items()):
            if len(candidates) == 1 and day not in calendars.conflicts:
                members.append(candidates[0])
                days.extend(candidates[0].days)
            else:
                gaps.append(f"calendar_conflict:{day}")
                conflicts.add(day)
        calendar = None
        known = {day for day, _ in days}
        observed = {d for d, _ in calendars.selected} | calendars.conflicts
        if observed:
            start = min(observed)
            for offset in range((as_of.astimezone(BEIJING).date() - start).days + 1):
                day = start + timedelta(days=offset)
                if day not in known:
                    gaps.append(f"calendar_not_covered:{day}")
        if members:
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
        gaps.extend(f"version_conflict_day:{day}" for day in sorted(conflicts))
        bars = tuple(
            v
            for day, v in daily.selected
            if isinstance(v, DailyBarVersion) and day not in conflicts
        )
        if not bars:
            gaps.append("daily_bar_missing")
        # 完成门禁覆盖全日所有逻辑键及被修订旧版本，输出证明仍精确绑定已选版本。
        indexed = {
            UUID(v.version_id): v
            for v in daily.history
            if isinstance(v, DailyBarVersion) and v.trade_date not in conflicts
        }
        proofs: dict[date, list[CompletionProof]] = defaultdict(list)
        batches: dict[date, list[BatchReceipt]] = defaultdict(list)
        blocked: set[date] = set()
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
                proofs[bar.trade_date].append(
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
                        blocked.add(bar.trade_date)
                        continue
                    if not (
                        visible(batch.available_at, as_of) and visible(batch.finished_at, as_of)
                    ):
                        continue
                    if (
                        batch.run_date != bar.trade_date
                        or batch.licence_id not in {None, bar.licence_id}
                        or (batch.owner_id is not None and batch.owner_id != user_id)
                        or (batch.owner_id is None and (user_id, code) not in batch.members)
                    ):
                        gaps.append(f"batch_invalid:{row['id']}")
                        blocked.add(bar.trade_date)
                        continue
                    if batch.status != "ok":
                        blocked.add(bar.trade_date)
                    if batch.licence_id == licence_id:
                        batches[bar.trade_date].append(batch)
        final: list[CompletionProof] = []
        for day, found in proofs.items():
            if {p.is_final for p in found} >= {True, False}:
                gaps.append(f"completion_conflict:{day}")
                blocked.add(day)
        gaps.extend(f"completion_blocked:{day}" for day in sorted(blocked))
        for bar in bars:
            if bar.trade_date in blocked:
                continue
            found = [p for p in proofs[bar.trade_date] if p.version == bar]
            final.extend(found)
            if not any(p.is_final is True and p.source_final_receipt for p in found):
                gaps.append(f"completion_missing:{bar.trade_date}")
        return BasisEvidence(
            calendar,
            bars,
            tuple(final),
            tuple(
                dict.fromkeys(
                    b for day, receipts in batches.items() if day not in blocked for b in receipts
                )
            ),
            tuple(dict.fromkeys(gaps)),
        )


if TYPE_CHECKING:

    def _check_protocol(connection: Connection) -> HorizonEvidenceProvider:
        provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(connection)
        return provider

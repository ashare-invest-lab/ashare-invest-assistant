"""T-A202 §4：只读 PIT 适配器；完成声明与真实历史可见性仍未验证。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date, datetime
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Connection, RowMapping, and_, or_, select

from app.db.tables.horizon import horizon_input_versions as versions
from app.features.horizon_sources import (
    BasisEvidence,
    CalendarVersion,
    DailyBarVersion,
    HorizonEvidenceProvider,
    SourceVersion,
    VersionBundle,
    aware,
    permitted,
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
        aware(as_of)
        # b2b-2 实现；未提供基础证据时保守返回缺口。
        return BasisEvidence(gaps=("basis_unavailable",))


if TYPE_CHECKING:

    def _check_protocol(connection: Connection) -> HorizonEvidenceProvider:
        provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(connection)
        return provider

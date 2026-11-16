"""T-A202 §A1-3/§4：读取已有累计因子证据；真实 gbbq 连乘未验证，默认不生效。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, select

from app.db.tables.horizon import horizon_input_versions as versions
from app.features.horizon_evidence_provider import DatabaseHorizonEvidenceProvider
from app.features.horizon_evidence_store import EvidenceRejected, validate_payload
from app.features.horizon_sources import SourceVersion, aware
from app.features.horizon_windows import BEIJING


@dataclass(frozen=True)
class FactorObservation:
    date: date
    value: str
    available_at: datetime
    version_id: str


@dataclass(frozen=True)
class FactorBundle:
    factors: tuple[FactorObservation, ...]
    dependency_ids: tuple[str, ...]
    snapshot_sha256: str
    coverage: tuple[date, ...]  # 实际成功请求日期；不代表窗口完整或事件已全证。
    gaps: tuple[str, ...]


def read_adjustment_factors(
    conn: Connection,
    *,
    user_id: UUID,
    licence_id: UUID | None,
    code: str,
    dates: Sequence[date],
    as_of: datetime,
    snapshot_sha256: str,
) -> FactorBundle:
    """由 b2b 统一执行范围/PIT/修订选择；仅按选中 ID 读取原材料。

    coverage 为「实际成功请求日期」集合，不代表窗口完整或事件已全证；
    请求缺日或因子 issues 非空即 missing，不以 1 补齐。
    """
    anchor = aware(as_of).astimezone(BEIJING).date()
    targets = sorted(set(dates))
    provider = DatabaseHorizonEvidenceProvider(conn)
    identity: dict[str, Any] = {
        "user_id": user_id,
        "licence_id": licence_id,
        "code": code,
        "as_of": as_of,
    }
    c = versions.c
    # 只发现当前用户稀疏观测的日期目录，其余隔离或可见性判断交给 b2b。
    catalogue = (
        list(
            conn.scalars(
                select(c.data_date)
                .where(
                    c.user_id == user_id,
                    c.kind == "adjust_factor",
                    c.code == code,
                    c.data_date <= anchor,
                )
                .distinct()
            )
        )
        if targets
        else []
    )
    selected = provider.read_versions(**identity, kind="adjust_factor", dates=catalogue)
    # 稀疏累计观测不要求每日落库；目录上无可见版本不等于请求日缺因子。
    gaps = [g for g in selected.gaps if not g.startswith("version_missing:")]
    blocked = {
        date.fromisoformat(g.split(":", 3)[2])
        for g in gaps
        if g.startswith("version_conflict:adjust_factor:")
    }
    by_day: dict[date, list[tuple[SourceVersion, dict[str, Any]]]] = defaultdict(list)
    chosen = {UUID(v.version_id): v for v in selected.versions}

    def audits_verified(v: SourceVersion, p: dict[str, Any]) -> bool:
        # verified 键为本裁定读取门禁；槽内结构仍未验证。
        if all(p[slot].get("verified") is True for slot in ("algo_audit", "integrity_audit")):
            return True
        gaps.append(f"adjust_factor_unverified:{v.version_id}")
        return False

    for row in conn.execute(
        select(c.id, c.data_date, c.payload).where(c.id.in_(chosen))
    ).mappings():
        v = chosen[row["id"]]
        p = row["payload"]
        try:
            # §3.4 槽内结构仍未验证；先沿 b2a 校验非空证据槽，再应用读取门禁。
            validate_payload(
                "adjust_factor",
                p,
                dependency_ids=[UUID(d) for d in v.dependency_ids],
                transform_version=v.transform_version,
                available_at=v.available_at,
            )
            if p["date"] != str(row["data_date"]):
                raise EvidenceRejected("adjust_factor:date_mismatch")
        except EvidenceRejected as exc:
            gaps.append(f"adjust_factor_invalid:{v.version_id}:{exc.reason}")
            blocked.add(row["data_date"])
            continue
        if not audits_verified(v, p):
            blocked.add(row["data_date"])
            continue
        if p["snapshot_sha256"] != snapshot_sha256:
            gaps.append(f"adjust_factor_snapshot_mismatch:{v.version_id}")
            continue
        by_day[row["data_date"]].append((v, p))

    checked: dict[str, tuple[str, ...] | None] = {}

    def dependencies(v: SourceVersion) -> tuple[str, ...] | None:
        if v.version_id in checked:
            return checked[v.version_id]
        checked[v.version_id] = None  # 同时拒绝损坏材料中的依赖环。
        used: list[str] = []
        reference_days: list[date] = []
        ex_days: list[date] = []
        for dep_id in v.dependency_ids:
            # 引用 ID 的类型/日期目录仅用于调用 b2b；未经其选择不读取 payload。
            meta = (
                conn.execute(select(c.kind, c.code, c.data_date).where(c.id == UUID(dep_id)))
                .mappings()
                .first()
            )
            if meta is None:
                return None
            try:
                bundle = provider.read_versions(
                    **{**identity, "code": meta["code"] or code},
                    kind=meta["kind"],
                    dates=[meta["data_date"]],
                )
            except KeyError:
                # 历史材料缺字段可能在 b2b 投影时失败；拒绝依赖，不绕过其选择。
                return None
            dep = next((d for d in bundle.versions if d.version_id == dep_id), None)
            if dep is None or bundle.gaps:
                return None
            p = conn.scalar(select(c.payload).where(c.id == UUID(dep_id)))
            if p is None:
                return None
            try:
                validate_payload(
                    meta["kind"],
                    p,
                    dependency_ids=[UUID(d) for d in dep.dependency_ids],
                    transform_version=dep.transform_version,
                    available_at=dep.available_at,
                )
                if meta["kind"] == "ex_rights" and (
                    date.fromisoformat(p["ex_date"]) > anchor
                    or p["snapshot_sha256"] != snapshot_sha256
                ):
                    return None
                if meta["kind"] == "adjust_factor" and p["snapshot_sha256"] != snapshot_sha256:
                    return None
                if meta["kind"] == "adjust_factor" and not audits_verified(dep, p):
                    return None
                # 参考价 daily_bar 的字段/日期/单位口径仍未验证；仅作保守读取门禁。
                if meta["kind"] == "daily_bar":
                    if (
                        p["close"] is None
                        or p.get("price_unit") is None
                        or dep.available_at is None
                        or dep.available_at > as_of
                    ):
                        return None
                    reference_days.append(date.fromisoformat(p["trade_date"]))
                if meta["kind"] == "ex_rights":
                    ex_days.append(date.fromisoformat(p["ex_date"]))
            except EvidenceRejected:
                return None
            nested = dependencies(dep)
            if nested is None:
                return None
            used.extend((dep_id, *nested))
        # 多依赖配对口径未验证；保守要求每个参考日都早于每个依赖除权日。
        if reference_days and ex_days and max(reference_days) >= min(ex_days):
            return None
        checked[v.version_id] = tuple(dict.fromkeys(used))
        return checked[v.version_id]

    factors: list[FactorObservation] = []
    used_ids: list[str] = []
    observation_days = sorted(set(by_day) | blocked)
    for target in targets:
        prior = [d for d in observation_days if d <= target]
        day = prior[-1] if prior and target <= anchor else None
        candidates = by_day.get(day, []) if day is not None else []
        valid = day not in blocked and len(candidates) == 1
        if valid:
            v, p = candidates[0]
            deps = dependencies(v)
            if deps is None:
                gaps.append(f"adjust_factor_dependency_unavailable:{v.version_id}")
            valid = (
                deps is not None
                and not p["issues"]
                and p["coverage_start"] <= str(target) <= p["coverage_end"]
                and str(target) in p["trade_dates"]
            )
            if valid and v.available_at is not None and deps is not None:
                # 按 prepare 的最近观测规则解析到请求日，保留原版本/可见时点。
                factors.append(FactorObservation(target, p["value"], v.available_at, v.version_id))
                used_ids.extend((v.version_id, *deps))
                continue
        gaps.append(f"adjust_factor_missing:{target}")
    return FactorBundle(
        tuple(factors),
        tuple(dict.fromkeys(used_ids)),
        snapshot_sha256,
        tuple(f.date for f in factors),
        tuple(dict.fromkeys(gaps)),
    )


def to_prepare_factors(bundle: FactorBundle) -> list[dict[str, Any]]:
    """只转换参数，qfq 比值由 prepare 计算；缺口时不让其沿用旧观测填洞。"""
    if any(g.startswith("adjust_factor_missing:") for g in bundle.gaps):
        return []
    return [
        {"date": f.date.isoformat(), "value": f.value, "available_at": f.available_at.isoformat()}
        for f in bundle.factors
    ]

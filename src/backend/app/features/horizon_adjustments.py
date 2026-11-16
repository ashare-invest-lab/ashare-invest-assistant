"""T-A202 §A1-3/§4：读取已有累计因子证据；真实 gbbq 连乘未验证，默认不生效。"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, RowMapping, and_, or_, select

from app.db.tables.horizon import horizon_input_versions as versions
from app.features.horizon_evidence_provider import DatabaseHorizonEvidenceProvider
from app.features.horizon_evidence_store import EvidenceRejected, validate_payload
from app.features.horizon_sources import aware
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
    """先限定快照再选择修订；复用 b2b 资格门禁，整个依赖闭包保守校验。"""
    anchor = aware(as_of).astimezone(BEIJING).date()
    targets = sorted(set(dates))
    provider = DatabaseHorizonEvidenceProvider(conn)
    identity: dict[str, Any] = {"user_id": user_id, "licence_id": licence_id}
    identity.update(code=code, as_of=as_of)
    c = versions.c
    gaps: list[str] = []
    blocked: set[date] = set()
    unknown_events: set[date] = set()
    groups: dict[tuple[object, ...], list[RowMapping]] = defaultdict(list)
    # 目录保留未知/晚可见材料；其他快照不参与审计或修订图，避免误挡与回退。
    scope = and_(c.licence_id.is_(None), c.scope.in_(("public", "synthetic")))
    for row in conn.execute(
        select(versions).where(
            c.user_id == user_id,
            or_(scope, and_(c.scope == "per_licence", c.licence_id == licence_id))
            if licence_id is not None
            else scope,
            c.code == code,
            c.kind.in_(("adjust_factor", "ex_rights")),
            c.data_date <= anchor,
        )
    ).mappings():
        groups[
            tuple(row[k] for k in ("kind", "source", "data_date", "source_key", "licence_id"))
        ].append(row)
    selected: dict[UUID, RowMapping] = {}
    for group in groups.values():
        foreign = {
            r["id"]
            for r in group
            if r["payload"].get("snapshot_sha256") not in (None, snapshot_sha256)
        }
        group = [r for r in group if r["id"] not in foreign]
        if not group:
            continue
        invalid = [r for r in group if provider._qualified(r, user_id, licence_id, as_of) is None]
        parents = {
            r["id"]: None if r["supersedes_id"] in foreign else r["supersedes_id"] for r in group
        }
        tips = [r for r in group if r["id"] not in parents.values()]
        current = tips[0]["id"] if len(tips) == 1 else None
        seen = set()
        while current in parents and current not in seen:
            seen.add(current)
            current = parents[current]
        if invalid or len(seen) != len(group) or current is not None:
            for r in invalid or group:
                reason = (
                    "visibility_or_qualification"
                    if invalid
                    else f"version_conflict:{r['kind']}:{r['data_date']}"
                )
                gaps.append(f"adjust_factor_invalid:{r['id']}:{reason}")
                (blocked if r["kind"] == "adjust_factor" else unknown_events).add(r["data_date"])
        else:
            selected[tips[0]["id"]] = tips[0]
    by_day: dict[date, list[RowMapping]] = defaultdict(list)
    for row in selected.values():
        if row["kind"] == "adjust_factor":
            by_day[row["data_date"]].append(row)

    def closure(root: RowMapping) -> tuple[str, ...] | None:
        # 后序迭代：缓存携带整个子树的类型、业务日期和最大可见时刻。
        summaries: dict[UUID, tuple[set[date], set[date], datetime]] = {}
        active: set[UUID] = set()
        rows = {root["id"]: root}
        pending = [(root["id"], 0, False)]
        try:
            while pending:
                item, depth, exiting = pending.pop()
                if depth > 128 or len(rows) > 1024 or len(pending) > 2048:
                    raise EvidenceRejected("closure_limit:depth=128:nodes=1024")
                if item in summaries:
                    continue
                r = rows.get(item)
                if r is None:
                    r = conn.execute(select(versions).where(c.id == item)).mappings().first()
                    if r is None:
                        raise EvidenceRejected("dependency_missing")
                    rows[item] = r
                p, kind, deps = r["payload"], r["kind"], r["dependency_ids"]
                if not exiting:
                    if item in active:
                        raise EvidenceRejected("dependency_cycle")
                    if r["code"] != code:
                        raise EvidenceRejected("code_mismatch")
                    if kind in ("adjust_factor", "ex_rights"):
                        if item not in selected:
                            raise EvidenceRejected("snapshot_or_revision_unavailable")
                    else:
                        bundle = provider.read_versions(
                            **identity, kind=kind, dates=[r["data_date"]]
                        )
                        if bundle.gaps or str(item) not in {v.version_id for v in bundle.versions}:
                            raise EvidenceRejected(";".join(bundle.gaps) or "revision_not_selected")
                    validate_payload(
                        kind,
                        p,
                        dependency_ids=deps,
                        transform_version=r["transform_version"],
                        available_at=r["available_at"],
                    )
                    key = {
                        "daily_bar": "trade_date",
                        "ex_rights": "ex_date",
                        "adjust_factor": "date",
                    }[kind]
                    if p.get("code", code) != code or p[key] != str(r["data_date"]):
                        raise EvidenceRejected("payload_outer_mismatch:code/date")
                    if (
                        kind in ("adjust_factor", "ex_rights")
                        and p["snapshot_sha256"] != snapshot_sha256
                    ):
                        raise EvidenceRejected("snapshot_mismatch")
                    if kind == "adjust_factor":
                        if not all(
                            p[s].get("verified") is True for s in ("algo_audit", "integrity_audit")
                        ):
                            gaps.append(f"adjust_factor_unverified:{item}")
                            raise EvidenceRejected("unverified")
                        if p["issues"]:
                            raise EvidenceRejected(f"issues:{p['issues']}")
                        if (
                            not deps
                            or str(r["data_date"]) not in p["trade_dates"]
                            or not all(
                                p["coverage_start"] <= d <= p["coverage_end"]
                                for d in p["trade_dates"]
                            )
                        ):
                            raise EvidenceRejected("factor_coverage_or_dependencies")
                    if kind == "daily_bar" and (p["close"] is None or p.get("price_unit") is None):
                        raise EvidenceRejected("reference_price_or_unit_missing")
                    active.add(item)
                    pending.append((item, depth, True))
                    pending.extend((d, depth + 1, False) for d in reversed(deps))
                    continue
                refs: set[date] = set()
                events: set[date] = set()
                latest = r["computed_at"] if kind == "adjust_factor" else r["available_at"]
                if latest is None:
                    raise EvidenceRejected("computed_at_or_visibility_missing")
                for dep in deps:
                    ref, ex, at = summaries[dep]
                    refs.update(ref)
                    events.update(ex)
                    latest = max(latest, at)
                if kind == "daily_bar":
                    refs.add(r["data_date"])
                if kind == "ex_rights":
                    events.add(r["data_date"])
                if refs and events and max(refs) >= min(events):
                    raise EvidenceRejected("reference_date_not_before_ex_date")
                if kind == "adjust_factor":
                    if not {"ex_rights", "daily_bar"} <= {rows[d]["kind"] for d in deps}:
                        raise EvidenceRejected("dependency_required:ex_rights/daily_bar")
                    if latest != r["available_at"]:
                        raise EvidenceRejected("closure_available_at_mismatch")
                summaries[item] = refs, events, latest
                active.remove(item)
        except (EvidenceRejected, KeyError, TypeError, ValueError) as exc:
            reason = exc.reason if isinstance(exc, EvidenceRejected) else str(exc)
            gaps.append(f"adjust_factor_dependency_unavailable:{root['id']}:{item}:{reason}")
            return None
        return tuple(str(i) for i in summaries if i != root["id"])

    factors: list[FactorObservation] = []
    used_ids: list[str] = []
    observation_days = sorted(set(by_day) | blocked)
    for target in targets:
        prior = [d for d in observation_days if d <= target]
        day = prior[-1] if prior and target <= anchor else None
        candidates = by_day.get(day, []) if day is not None else []
        if (
            day not in blocked
            and len(candidates) == 1
            and not any(d <= target for d in unknown_events)
        ):
            row = candidates[0]
            deps = closure(row)
            p = row["payload"]
            if (
                deps is not None
                and p["coverage_start"] <= str(target) <= p["coverage_end"]
                and str(target) in p["trade_dates"]
            ):
                factors.append(
                    FactorObservation(target, p["value"], row["available_at"], str(row["id"]))
                )
                used_ids.extend((str(row["id"]), *deps))
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
    if bundle.gaps:
        return []
    return [
        {
            "date": f.date.isoformat(),
            "value": f.value,
            "available_at": f.available_at.isoformat(),
        }
        for f in bundle.factors
    ]

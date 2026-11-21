"""Offline, point-in-time G6 history collection and reporting."""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol, cast

from app.strategy.g6 import compare

WINDOW_DAYS = 120
CODE_VERSION = "g6-history-v1"
RULE_VERSION = "g6-rules-v1"


@dataclass(frozen=True)
class HistoryQuery:
    card_version: str
    card_key: str
    horizon: str
    limit: int = WINDOW_DAYS
    as_of: dt.datetime | None = None


class HistoryProvider(Protocol):
    """A read-only provider returning mapping-like daily history rows."""

    def fetch(self, query: HistoryQuery) -> Iterable[Mapping[str, Any]]: ...


class EmptyHistoryProvider:
    """Production-safe default when no real historical adapter is configured."""

    data_source_version = "empty-history-v1"

    def fetch(self, query: HistoryQuery) -> tuple[Mapping[str, Any], ...]:
        return ()


def _text(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value.isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    return str(value)


def _date(value: object) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _instant(value: object) -> dt.datetime | None:
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.UTC)
    if isinstance(value, str):
        try:
            parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.UTC)
    return None


def _as_of_visible(row: Mapping[str, Any], as_of: dt.datetime | None) -> tuple[bool, list[str]]:
    if as_of is None:
        return True, []
    cutoff = _instant(as_of)
    day = _date(_row_value(row, "trading_day", "date", "day"))
    if cutoff is None or day is None:
        return False, ["未验证", "trading_day_unverified"]
    if day > cutoff.astimezone(dt.timezone(dt.timedelta(hours=8))).date():
        return False, ["trading_day_after_as_of"]
    available = _instant(_row_value(row, "available_at", "input_visible_at", "visible_at"))
    if available is not None:
        return (available <= cutoff, [] if available <= cutoff else ["available_at_after_as_of"])
    close = dt.datetime.combine(day, dt.time(15), dt.timezone(dt.timedelta(hours=8)))
    gaps = ["未验证", "available_at_missing"]
    return close <= cutoff, gaps


def _adjustment(row: Mapping[str, Any]) -> str | None:
    value = _row_value(row, "adjust", "adjustment", "bar_adjust", "adj_type", "price_adjust")
    return str(value).lower() if value is not None else None


def _list_days_threshold(spec: Mapping[str, Any]) -> int | None:
    raw: object = spec.get("min_list_days")
    params = spec.get("params_schema")
    if raw is None and isinstance(params, Mapping):
        raw = params.get("min_list_days")
    if isinstance(raw, Mapping):
        raw = raw.get("default", raw.get("value"))
    try:
        return int(raw) if isinstance(raw, (int, str)) else None
    except (TypeError, ValueError):
        return None


def _qualify(row: Mapping[str, Any], spec: Mapping[str, Any]) -> tuple[bool, list[str]]:
    gaps: list[str] = []
    adjustment = _adjustment(row)
    if adjustment != "qfq":
        gaps.extend(
            ["未验证", "adjustment_missing" if adjustment is None else "adjustment_not_qfq"]
        )
        return False, gaps
    if row.get("is_suspended") is True:
        return False, ["suspended"]
    threshold = _list_days_threshold(spec)
    if threshold is None:
        gaps.extend(["未验证", "list_days_threshold_missing"])
        return False, gaps
    raw_list_days = row.get("list_days")
    try:
        list_days = int(raw_list_days) if isinstance(raw_list_days, (int, str)) else None
    except (TypeError, ValueError):
        return False, ["未验证", "list_days_missing"]
    if list_days is None:
        return False, ["未验证", "list_days_missing"]
    return (True, gaps) if list_days >= threshold else (False, ["new_stock"])


def _prepare_rows(
    rows: Iterable[Mapping[str, Any]], as_of: dt.datetime | None, spec: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], list[str]]:
    accepted: list[dict[str, Any]] = []
    gaps: list[str] = []
    for raw in rows:
        row = dict(raw)
        visible, visibility_gaps = _as_of_visible(row, as_of)
        if not visible:
            gaps.extend(visibility_gaps)
            continue
        valid, validity_gaps = _qualify(row, spec)
        if not valid:
            gaps.extend(visibility_gaps + validity_gaps)
            continue
        row["_gaps"] = visibility_gaps
        accepted.append(row)
        gaps.extend(visibility_gaps)
    return accepted, gaps


def _is_h_card(card_key: str, card_id: str | None = None) -> bool:
    return (
        card_key.upper().startswith("H-")
        or card_key.lower()
        in {
            "hold_risk_monitor",
            "h-01",
        }
        or (card_id or "").upper() == "H-01"
    )


def _horizons(
    card_key: str, spec: Mapping[str, Any], card_id: str | None = None
) -> tuple[str, ...]:
    raw = spec.get("horizons")
    if isinstance(raw, (list, tuple)) and raw:
        values = tuple(str(item) for item in raw)
    elif raw is not None:
        values = (str(raw),)
    elif _is_h_card(card_key, card_id):
        values = ("1", "5", "20")
    else:
        values = (str(spec.get("horizon", "default")),)
    if _is_h_card(card_key, card_id):
        # H-01 keeps three non-overlapping holding windows even though its
        # card declaration also contains display horizons.
        return ("1", "5", "20")
    return values


def _fetch(provider: object, query: HistoryQuery) -> Iterable[Mapping[str, Any]]:
    if provider is None:
        return ()
    if callable(provider):
        result = provider(query)
    else:
        fetch = getattr(provider, "fetch", None)
        if fetch is None:
            fetch = getattr(provider, "load", None)
        if fetch is None:
            fetch = getattr(provider, "get_history", None)
        if fetch is None:
            raise TypeError("history_provider_requires_fetch_or_load")
        try:
            result = fetch(query)
        except TypeError as first_error:
            try:
                result = fetch(
                    card_version=query.card_version,
                    card_key=query.card_key,
                    horizon=query.horizon,
                    limit=query.limit,
                    as_of=query.as_of,
                )
            except TypeError:
                raise first_error from None
    if result is None:
        return ()
    return cast(Iterable[Mapping[str, Any]], result)


def _row_value(row: Mapping[str, Any], *keys: str) -> object:
    for key in keys:
        if key in row:
            return row[key]
    return None


def _stat(
    value: Decimal | None, denominator: int, window: str, reason: str | None
) -> dict[str, Any]:
    reported = value if denominator >= 5 else None
    return {
        "value": str(reported) if reported is not None else None,
        "n": denominator,
        "window": window,
        "small_sample": denominator < 30,
        **({"null_reason": reason} if reason else {}),
    }


def _section(
    rows: Sequence[Mapping[str, Any]], *, trading_days: set[dt.date], window: str
) -> dict[str, Any]:
    pool = len(rows)

    def evaluable(row: Mapping[str, Any]) -> bool:
        if not bool(row.get("evaluable", not row.get("missing_reason"))):
            return False
        evaluation = _instant(_row_value(row, "evaluation_at", "evaluated_at", "as_of"))
        visible = _instant(_row_value(row, "input_visible_at", "available_at", "visible_at"))
        return evaluation is None or visible is None or visible <= evaluation

    evaluable_rows = [row for row in rows if evaluable(row)]
    triggered_rows = [
        row for row in evaluable_rows if bool(_row_value(row, "triggered", "hit", "is_triggered"))
    ]
    missing: Counter[str] = Counter()
    visibility: list[str] = []
    own_by_day: dict[dt.date, set[str]] = defaultdict(set)
    comparable: list[set[str]] = []
    for row in rows:
        missing.update(str(item) for item in row.get("_gaps", ()) if item)
        reason = _row_value(row, "missing_reason", "missing", "missing_reasons")
        evaluation = _instant(_row_value(row, "evaluation_at", "evaluated_at", "as_of"))
        visible_at = _instant(_row_value(row, "input_visible_at", "available_at", "visible_at"))
        if evaluation is not None and visible_at is not None and visible_at > evaluation:
            reason = (
                [reason, "input_not_visible_at_evaluation"]
                if reason
                else ["input_not_visible_at_evaluation"]
            )
        if reason:
            reasons = reason if isinstance(reason, (list, tuple, set)) else (reason,)
            missing.update(str(item) for item in reasons if item is not None)
        visible = _row_value(row, "input_visible_at", "available_at", "visible_at")
        visible_values = [visible] if visible is not None else []
        inputs = row.get("inputs")
        if isinstance(inputs, Mapping):
            visible_values.extend(
                value
                for item in inputs.values()
                if isinstance(item, Mapping)
                for value in [item.get("available_at", item.get("input_visible_at"))]
                if value is not None
            )
        visibility.extend(text for value in visible_values if (text := _text(value)))
        day = _date(_row_value(row, "trading_day", "date", "day"))
        security = _text(_row_value(row, "security", "code", "symbol"))
        if (
            day is not None
            and security
            and evaluable(row)
            and bool(_row_value(row, "triggered", "hit", "is_triggered"))
        ):
            own_by_day[day].add(security)
        raw_sets = (
            _row_value(row, "comparable_sets", "comparable_set", "other_hits", "template_hits")
            or ()
        )
        if isinstance(raw_sets, set):
            comparable.append({str(item) for item in raw_sets})
        elif isinstance(raw_sets, (list, tuple)):
            if raw_sets and all(isinstance(item, str) for item in raw_sets):
                comparable.append(set(raw_sets))
            else:
                comparable.extend(
                    {str(item) for item in item_set}
                    for item_set in raw_sets
                    if isinstance(item_set, (list, tuple, set))
                )
    history_days = len(trading_days)
    own = set().union(*own_by_day.values()) if own_by_day else set()
    overlap = compare(history_days, own, comparable)
    trigger_reason = "zero_evaluable_denominator" if not evaluable_rows else None
    coverage_reason = "zero_pool_denominator" if not rows else None
    trigger = (
        Decimal(len(triggered_rows)) / Decimal(len(evaluable_rows)) if evaluable_rows else None
    )
    coverage = Decimal(len(evaluable_rows)) / Decimal(pool) if pool else None
    warnings: list[str] = []
    if trigger is not None and (trigger == 0 or trigger > Decimal("0.3")):
        warnings.append("trigger_rate_out_of_expected_range")
    if overlap.duplicate:
        warnings.append("jaccard_above_0.9")
    return {
        "N": pool,
        "E": len(evaluable_rows),
        "H": len(triggered_rows),
        "n": pool,
        "e": len(evaluable_rows),
        "h": len(triggered_rows),
        "trading_days": history_days,
        "missing_reasons": dict(sorted(missing.items())),
        "input_visible_at": sorted(set(visibility)),
        "trigger_rate": _stat(trigger, len(evaluable_rows), window, trigger_reason),
        "coverage": _stat(coverage, pool, window, coverage_reason),
        "max_jaccard": overlap.max_jaccard,
        "max_jaccard_null_reason": overlap.max_jaccard_null_reason,
        "warnings": warnings,
    }


def _deduplicate(rows: Iterable[Mapping[str, Any]], horizon: str) -> list[dict[str, Any]]:
    unique: dict[tuple[str | None, ...], dict[str, Any]] = {}
    for raw in rows:
        row = dict(raw)
        day = _text(_row_value(row, "trading_day", "date", "day"))
        security = _text(_row_value(row, "security", "code", "symbol"))
        period = _text(_row_value(row, "period", "cycle", "horizon")) or horizon
        evaluation = _text(_row_value(row, "evaluation_at", "evaluated_at", "as_of"))
        card = _text(_row_value(row, "card_version", "card_version_id", "version"))
        rule_group = _text(_row_value(row, "rule_group", "rule", "rule_id", "group"))
        key = (card, period, security, day, evaluation, rule_group)
        unique.setdefault(key, row)
    return list(unique.values())


def _remove_overlapping_events(rows: list[dict[str, Any]], horizon: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    trading_days = sorted(
        day for row in rows if (day := _date(_row_value(row, "trading_day", "date", "day")))
    )
    day_index = {day: index for index, day in enumerate(trading_days)}
    starts: dict[tuple[str, str], list[int]] = defaultdict(list)
    try:
        length = int(horizon.removeprefix("h"))
    except ValueError:
        length = 0
    length = max(length, 0)
    for row in sorted(
        rows,
        key=lambda item: (
            _text(_row_value(item, "trading_day", "date", "day")) or "",
            _text(_row_value(item, "security", "code", "symbol")) or "",
            _text(_row_value(item, "rule_group", "rule", "rule_id", "group")) or "",
        ),
    ):
        start = _date(_row_value(row, "trading_day", "date", "day"))
        security = _text(_row_value(row, "security", "code", "symbol")) or ""
        rule_group = _text(_row_value(row, "rule_group", "rule", "rule_id", "group")) or ""
        key = (security, rule_group)
        index = day_index.get(start) if start is not None else None
        if index is not None and length:
            if any(index - old_index < length for old_index in starts[key]):
                continue
            starts[key].append(index)
        accepted.append(row)
    return accepted


def build_report(
    *,
    provider: object = None,
    card_key: str = "",
    card_id: str | None = None,
    card_version: str = "",
    card_version_no: int | None = None,
    content_sha256: str | None = None,
    spec: Mapping[str, Any] | None = None,
    as_of: dt.datetime | None = None,
    code_version: str = CODE_VERSION,
    rule_version: str = RULE_VERSION,
    data_source_version: str | None = None,
) -> dict[str, Any]:
    """Build a deterministic G6 report from injected, read-only rows."""
    actual_provider = provider if provider is not None else EmptyHistoryProvider()
    horizons = _horizons(card_key, spec or {}, card_id)
    all_rows: dict[str, list[dict[str, Any]]] = {}
    filter_gaps_by_horizon: dict[str, list[str]] = {}
    filter_gaps: list[str] = []
    for horizon in horizons:
        query = HistoryQuery(
            card_version=card_version, card_key=card_key, horizon=horizon, as_of=as_of
        )
        prepared, gaps = _prepare_rows(_fetch(actual_provider, query), as_of, spec or {})
        filter_gaps_by_horizon[horizon] = gaps
        filter_gaps.extend(gaps)
        rows = _deduplicate(prepared, horizon)
        all_rows[horizon] = (
            _remove_overlapping_events(rows, horizon) if _is_h_card(card_key, card_id) else rows
        )
    sections: dict[str, Any] = {}
    all_warnings: list[str] = []
    for horizon, rows in all_rows.items():
        real = [
            row
            for row in rows
            if str(row.get("source_kind", row.get("source", "real"))).lower()
            not in {"synthetic", "fixture"}
        ]
        synthetic = [row for row in rows if row not in real]
        real_days_for_section = {
            day
            for day in (_date(_row_value(row, "trading_day", "date", "day")) for row in real)
            if day is not None
        }
        synthetic_days_for_section = {
            day
            for day in (_date(_row_value(row, "trading_day", "date", "day")) for row in synthetic)
            if day is not None
        }
        window = f"{WINDOW_DAYS} trading days"
        sections[horizon] = {
            "real_history": _section(real, trading_days=real_days_for_section, window=window),
            "synthetic_fixtures": _section(
                synthetic, trading_days=synthetic_days_for_section, window=window
            ),
        }
        real_section = sections[horizon]["real_history"]
        section_filter_gaps = filter_gaps_by_horizon[horizon]
        if section_filter_gaps:
            section_gaps = Counter(section_filter_gaps)
            real_section["missing_reasons"] = dict(
                sorted((Counter(real_section["missing_reasons"]) | section_gaps).items())
            )
            real_section["warnings"] = sorted(set(real_section["warnings"]) | set(section_gaps))
        real_section["history_status"] = (
            "no_history"
            if len(real_days_for_section) < WINDOW_DAYS
            else "no_comparable_set"
            if real_section["max_jaccard"] is None
            else "available"
        )
        real_section["window_start"] = (
            _text(min(real_days_for_section)) if real_days_for_section else None
        )
        real_section["window_end"] = (
            _text(max(real_days_for_section)) if real_days_for_section else None
        )
        all_warnings.extend(sections[horizon]["real_history"]["warnings"])
    if all_rows:
        flattened = [
            row
            for rows in all_rows.values()
            for row in rows
            if str(row.get("source_kind", row.get("source", "real"))).lower()
            not in {"synthetic", "fixture"}
        ]
    else:
        flattened = []
    real_days = {
        day
        for day in (_date(_row_value(row, "trading_day", "date", "day")) for row in flattened)
        if day is not None
    }
    real_sections = [section["real_history"] for section in sections.values()]
    section_statuses = {section["history_status"] for section in real_sections}
    history_status = (
        "no_history"
        if "no_history" in section_statuses
        else "no_comparable_set"
        if "no_comparable_set" in section_statuses
        else "available"
    )
    overlap = max(
        (section for section in real_sections if section["max_jaccard"] is not None),
        key=lambda section: Decimal(section["max_jaccard"]),
        default=real_sections[0] if real_sections else None,
    )
    first_day = min(real_days) if real_days else None
    last_day = max(real_days) if real_days else None
    source_version = data_source_version or getattr(
        actual_provider, "data_source_version", "unknown-history-source"
    )
    feature_requests = (spec or {}).get("feature_requests")
    quota_unknown = bool(feature_requests)
    report: dict[str, Any] = {
        "card_version": {"id": card_version, "version_no": card_version_no},
        "content_sha256": content_sha256,
        "code_version": code_version,
        "rule_version": rule_version,
        "data_source_version": source_version,
        "window": {"days": WINDOW_DAYS, "start": _text(first_day), "end": _text(last_day)},
        "history_status": history_status,
        "horizons": sections,
        "real_history": {horizon: section["real_history"] for horizon, section in sections.items()},
        "synthetic_fixtures": {
            horizon: section["synthetic_fixtures"] for horizon, section in sections.items()
        },
        "warnings": sorted(set(all_warnings)),
        "trigger_rate": real_sections[0]["trigger_rate"]
        if real_sections
        else _stat(None, 0, f"{WINDOW_DAYS} trading days", "no_history"),
        "coverage": real_sections[0]["coverage"]
        if real_sections
        else _stat(None, 0, f"{WINDOW_DAYS} trading days", "no_history"),
        "max_jaccard": overlap["max_jaccard"] if overlap else None,
        "max_jaccard_null_reason": (
            None
            if overlap and overlap["max_jaccard"] is not None
            else "no_history"
            if history_status == "no_history"
            else "no_comparable_set"
            if history_status == "no_comparable_set"
            else None
        ),
        "quota_delta_per_min": None if quota_unknown else 0,
        "quota_estimate": {
            "value": None if quota_unknown else 0,
            "source": "feature_requests",
            "cost_proof": False,
            "reason": "feature_requests_empty_not_cost_proof"
            if not quota_unknown
            else "unimplemented_feature_request",
        },
        "missing_reasons": {},
        "input_visible_at": [],
    }
    report["N"] = sum(section["N"] for section in real_sections)
    report["E"] = sum(section["E"] for section in real_sections)
    report["H"] = sum(section["H"] for section in real_sections)
    if real_sections:
        reasons: Counter[str] = Counter()
        for section in real_sections:
            reasons.update(section["missing_reasons"])
        report["missing_reasons"] = dict(sorted(reasons.items()))
        report["input_visible_at"] = sorted(
            {value for section in real_sections for value in section["input_visible_at"]}
        )
    if filter_gaps:
        report["warnings"] = sorted(set(report["warnings"]) | set(filter_gaps))
        report["missing_reasons"] = dict(
            sorted((Counter(report["missing_reasons"]) | Counter(filter_gaps)).items())
        )
    return report


def history_gate_warnings(report: Mapping[str, Any]) -> list[str]:
    return list(report.get("warnings") or [])

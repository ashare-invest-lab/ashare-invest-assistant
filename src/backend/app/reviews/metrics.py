"""复盘指标的冻结与读取投影口径。"""
# ruff: noqa: ANN401

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

# fmt: off

METRIC_NAMES = ("holding_return", "benchmark_return", "excess_return", "max_drawdown")
GAP_REASONS = {"no_source", "not_yet_published", "user_input_missing"}
SHANGHAI = ZoneInfo("Asia/Shanghai")


def _stat(window: str, *, value: Decimal | None = None, n: int = 0) -> dict[str, Any]:
    return {
        "value": format(value, "f") if value is not None and n >= 5 else None,
        "n": n,
        "window": window,
        "small_sample": n < 30,
    }


def _gap(key: str, reason: str, message: str | None = None) -> dict[str, str]:
    messages = {
        "no_source": "来源缺失，指标未验证（待回测）",
        "not_yet_published": "复盘周期尚未结束",
        "user_input_missing": "未关联实际成交，无法计算结果指标",
    }
    return {"key": key, "reason": reason, "message": message or messages.get(reason, "未验证")}


def normalise_gaps(value: Any, key: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    values = [value] if isinstance(value, (str, dict)) else list(value)
    result: list[dict[str, Any]] = []
    for gap in values:
        if isinstance(gap, dict) and {"key", "reason", "message"} <= set(gap):
            result.append(dict(gap))
        elif isinstance(gap, dict) and "reason" in gap:
            result.append(_gap(str(gap.get("key", key)), str(gap["reason"]), gap.get("message")))
        else:
            result.append(_gap(key, str(gap)))
    return result


def normalise_metric_gaps(value: Any) -> list[str]:
    """Return the §7.8 metric representation, which stores reasons only."""
    if value is None:
        return []
    values = [value] if isinstance(value, (str, dict)) else list(value)
    result: list[str] = []
    for gap in values:
        reason = gap.get("reason") if isinstance(gap, dict) else gap
        if isinstance(reason, str) and reason in GAP_REASONS and reason not in result:
            result.append(reason)
    return result


def empty_metrics(period_start: dt.date, period_end: dt.date) -> dict[str, Any]:
    window = f"{period_start.isoformat()}/{period_end.isoformat()}"
    return {name: _stat(window) for name in METRIC_NAMES}


def status_block(
    *, has_observation: bool = False, reason: str = "no_source", message: str | None = None
) -> dict[str, Any]:
    if has_observation:
        return {"data_status": "partial", "data_as_of": None, "gaps": []}
    return {
        "data_status": "pending" if reason == "not_yet_published" else "unavailable",
        "data_as_of": None,
        "gaps": [_gap("outcome_metrics", reason, message)],
    }


def period_pending(period_end: dt.date | None, *, now: dt.datetime | None = None) -> bool:
    """Return whether the endpoint is still open at the supplied Beijing time.

    Weekends are only a workday approximation. A Friday endpoint is complete on
    Saturday. Future endpoints remain pending until their date.
    """
    if period_end is None:
        return False
    current = now or dt.datetime.now(dt.UTC)
    if current.tzinfo is None or current.utcoffset() is None:
        current = current.replace(tzinfo=dt.UTC)
    current = current.astimezone(SHANGHAI)
    if period_end > current.date():
        return True
    if period_end < current.date():
        return False
    return current.weekday() < 5 and current.time() < dt.time(15)


def pending_message() -> str:
    return "复盘周期尚未结束；未验证：未接交易日历"


def project_metrics(
    metrics: dict[str, Any] | None,
    *,
    period_end: dt.date | None = None,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Project frozen values, applying only the not-yet-ended period gate."""
    source = metrics or {}
    pending = period_pending(period_end, now=now)
    result: dict[str, Any] = {}
    for name in METRIC_NAMES:
        item = dict(source.get(name) or {})
        item["gaps"] = normalise_metric_gaps(item.get("gaps"))
        if item.get("source") == "simulated_tracking":
            item.pop("source", None)
            item["value"] = None
            item["gaps"] = [reason for reason in item["gaps"] if reason != "no_source"]
            item["gaps"].append("no_source")
        if pending:
            item["value"] = None
            item["gaps"] = ["not_yet_published"]
        elif item.get("value") is not None and item.get("n", 0) < 5:
            item["value"] = None
            item["label"] = "未验证"
        result[name] = item
    return result


def metric_gap(name: str, reason: str = "no_source", message: str | None = None) -> dict[str, Any]:
    return {"gaps": [reason]}

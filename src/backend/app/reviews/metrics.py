"""复盘统计的统一展示口径。"""
# ruff: noqa: E501

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

# fmt: off

def _stat(window: str, *, value: Decimal | None = None, n: int = 0) -> dict[str, Any]:
    return {
        "value": format(value, "f") if value is not None and n >= 5 else None,
        "n": n,
        "window": window,
        "small_sample": n < 30,
    }

def empty_metrics(period_start: dt.date, period_end: dt.date) -> dict[str, Any]:
    window = f"{period_start.isoformat()}/{period_end.isoformat()}"
    return {name: _stat(window) for name in ("holding_return", "benchmark_return", "excess_return", "max_drawdown")}

def status_block(*, has_observation: bool = False, reason: str = "no_source") -> dict[str, Any]:
    if has_observation:
        return {"data_status": "partial", "data_as_of": None, "gaps": []}
    if reason == "not_yet_published":
        return {
            "data_status": "pending",
            "data_as_of": None,
            "gaps": [{"key": "outcome_metrics", "reason": reason, "message": "复盘周期尚未结束"}],
        }
    message = "未关联实际成交，无法计算结果指标" if reason == "user_input_missing" else "实际成交结果或基准价格缺失，指标未验证（待回测）"
    return {
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [{"key": "outcome_metrics", "reason": reason, "message": message}],
    }


def period_pending(period_end: dt.date | None, *, now: dt.datetime | None = None) -> bool:
    if period_end is None:
        return False
    current = (now or dt.datetime.now(dt.UTC)).astimezone(ZoneInfo("Asia/Shanghai"))
    trading_day = current.date() - dt.timedelta(days=max(current.weekday() - 4, 0)) if current.weekday() >= 5 else current.date()
    return period_end > trading_day or (period_end == trading_day and current.time() < dt.time(15))


def project_metrics(
    metrics: dict[str, Any] | None,
    *,
    period_end: dt.date | None = None,
) -> dict[str, Any]:
    """Project stored values without treating simulated or unverified values as facts."""
    source = metrics or {}
    pending = period_pending(period_end)
    result: dict[str, Any] = {}
    for name in ("holding_return", "benchmark_return", "excess_return", "max_drawdown"):
        item = dict(source.get(name) or {})
        gaps = item.get("gaps", [])
        item["gaps"] = [gaps] if isinstance(gaps, str) else list(gaps)
        if item.get("source") == "simulated_tracking":
            item.pop("source", None)
            item["value"] = None
            if "no_source" not in item["gaps"]:
                item["gaps"].append("no_source")
        if pending:
            item["value"] = None
            item["gaps"] = ["not_yet_published"]
        elif item.get("value") is not None and item.get("n", 0) < 5:
            item["label"] = "未验证"
        result[name] = item
    return result

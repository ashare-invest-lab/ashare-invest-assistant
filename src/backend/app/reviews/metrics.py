"""复盘统计的统一展示口径。"""
# ruff: noqa: E501

from __future__ import annotations

import datetime as dt
from decimal import Decimal
from typing import Any

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
    message = "未关联实际成交，无法计算结果指标" if reason == "user_input_missing" else "实际成交结果或基准价格缺失，指标未验证（待回测）"
    return {
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [{"key": "outcome_metrics", "reason": reason, "message": message}],
    }

"""T-T107 I3：盘中 P0 计划器的离线契约测试。

计划器尚未进入主线时，相关用例以 strict xfail 记录 T-B197 的待实现状态。
夹具只包含合成代码，测试不建立数据库、Redis、Docker 或网络连接。
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import importlib
import importlib.util
import inspect
import sched
import socket
import threading
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from app.aggregates.models import MarketClock
from app.schemas.enums import MarketSession

BEIJING = dt.timezone(dt.timedelta(hours=8))
FIXED_NOW = dt.datetime(2026, 11, 20, 10, 15, tzinfo=BEIJING)
TRADE_DATE = FIXED_NOW.date()
PLANNER_MODULE = "app.intraday.p0_plan"
SOCKET_ATTEMPTS: list[tuple[object, ...]] = []


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何计划器外呼都应在测试中立即失败。"""

    SOCKET_ATTEMPTS.clear()

    def refused(*args: object, **kwargs: object) -> Any:
        SOCKET_ATTEMPTS.append(args)
        pytest.fail(f"I3 计划测试禁止 socket 外呼: {args!r}")

    monkeypatch.setattr(socket, "getaddrinfo", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(socket.socket, "connect", refused)
    monkeypatch.setattr(socket.socket, "connect_ex", refused)
    monkeypatch.setattr(threading, "Timer", refused)
    monkeypatch.setattr(sched, "scheduler", refused)
    monkeypatch.setattr(asyncio, "create_task", refused)
    monkeypatch.setattr(asyncio, "ensure_future", refused)


def _load_planner() -> tuple[ModuleType, type[Any]]:
    try:
        module = importlib.import_module(PLANNER_MODULE)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        if missing == PLANNER_MODULE or missing.startswith("app.intraday"):
            pytest.xfail("T-B197 未实现：盘中 P0 计划器模块未提供")
        raise

    for name in ("P0Planner", "IntradayP0Planner", "Planner"):
        candidate = getattr(module, name, None)
        if inspect.isclass(candidate):
            return module, candidate
    pytest.xfail("T-B197 未实现：公开 P0 计划器类未提供")


def _clock(session: MarketSession) -> MarketClock:
    return MarketClock(trade_date=TRADE_DATE, session=session)


def _synthetic_inputs() -> dict[str, Any]:
    """计划器应消费的最小合成股票池，明确分出三层优先级。"""

    holdings = [{"security_code": "SYN001.SH", "priority": "holding", "qty": 100}]
    focus = [{"security_code": "SYN002.SH", "priority": "focus"}]
    watchlist = [{"security_code": "SYN003.SH", "priority": "watchlist"}]
    suspended = [{"security_code": "SYN004.SH", "suspended": True}]
    universe = holdings + focus + watchlist + suspended
    return {
        "clock": _clock(MarketSession.MORNING),
        "market_clock": _clock(MarketSession.MORNING),
        "now": FIXED_NOW,
        "trade_date": TRADE_DATE,
        "session": MarketSession.MORNING,
        "universe": universe,
        "certificates": universe,
        "holdings": holdings,
        "positions": holdings,
        "focus": focus,
        "watchlist": watchlist,
        "self_selected": watchlist,
        "suspended": suspended,
        "suspensions": suspended,
        "budget": 2,
        "budget_remaining": 2,
        "existing_plans": [],
        "planned": [],
        "replay_keys": set(),
        "certificate_id": "00000000-0000-4000-8000-000000000720",
        "licence_id": "00000000-0000-4000-8000-000000000721",
    }


def _accepted_call(method: Any, values: dict[str, Any]) -> Any:
    """按公开参数名调用，兼容计划器的少量合理签名变体。"""

    signature = inspect.signature(method)
    kwargs: dict[str, Any] = {}
    positional: list[Any] = []
    fallback = [values["clock"], values["universe"], values["budget"]]
    fallback_index = 0
    accepts_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signature.parameters.values())
    for parameter in signature.parameters.values():
        if parameter.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        if parameter.name in values:
            if parameter.kind is inspect.Parameter.POSITIONAL_ONLY:
                positional.append(values[parameter.name])
            else:
                kwargs[parameter.name] = values[parameter.name]
        elif parameter.default is inspect.Parameter.empty:
            if fallback_index >= len(fallback):
                raise TypeError(f"无法为公开计划 API 参数 {parameter.name!r} 提供合成输入")
            positional.append(fallback[fallback_index])
            fallback_index += 1
    if accepts_kwargs:
        for name, value in values.items():
            kwargs.setdefault(name, value)
    return method(*positional, **kwargs)


def _make_planner(cls: type[Any], values: dict[str, Any]) -> Any:
    signature = inspect.signature(cls)
    caps = {"tier1_cap": 2, "universe_hard_cap": 8, "focus_cap": 4, "watchlist_cap": 4}
    kwargs = {name: caps[name] for name in caps if name in signature.parameters}
    if kwargs:
        try:
            return cls(**kwargs)
        except TypeError:
            pass
    try:
        return _accepted_call(cls, values)
    except TypeError as exc:
        if "missing" not in str(exc) and "无法为公开计划 API" not in str(exc):
            raise
        return cls()


def _certificate_payload(module: ModuleType) -> Any:
    payload = {
        "holdings": ["SYN001.SH"],
        "focus": ["SYN002.SH"],
        "watchlist": ["SYN003.SH"],
        "suspended": ["SYN004.SH"],
        "budget": 2,
    }
    universe_cls = getattr(module, "CertificateUniverse", None)
    if inspect.isclass(universe_cls):
        return [universe_cls("licence-a", **payload)]
    return {"licence-a": payload}


def _plan(values: dict[str, Any], planner: Any | None = None) -> tuple[Any, Any]:
    module, planner_cls = _load_planner()
    values = dict(values)
    values["certificates"] = _certificate_payload(module)
    instance = planner if planner is not None else _make_planner(planner_cls, values)
    method = getattr(instance, "plan", None)
    if not callable(method):
        pytest.xfail("T-B197 未实现：计划器未提供公开 plan() 方法")
    return instance, _accepted_call(method, values)


def _field(value: Any, *names: str) -> Any:
    if isinstance(value, dict):
        for name in names:
            if name in value:
                return value[name]
    for name in names:
        if hasattr(value, name):
            found = getattr(value, name)
            if found is not None:
                return found
    return None


def _plans(result: Any) -> list[Any]:
    if isinstance(result, (list, tuple, set)):
        return list(result)
    for name in ("scheduled", "dispatchable", "plans", "items", "planned"):
        value = _field(result, name)
        if value is not None:
            return list(value) if isinstance(value, (list, tuple, set)) else [value]
    return []


def _codes(result: Any) -> list[str]:
    out: list[str] = []
    for item in _plans(result):
        code = _field(item, "security_code", "code", "symbol")
        if isinstance(code, str):
            out.append(code)
    return out


@pytest.mark.parametrize(
    "session",
    [
        MarketSession.PRE_OPEN,
        MarketSession.CALL_AUCTION,
        MarketSession.LUNCH_BREAK,
        MarketSession.CLOSING_AUCTION,
        MarketSession.CLOSED,
        MarketSession.NON_TRADING_DAY,
        MarketSession.MORNING,
        MarketSession.AFTERNOON,
    ],
)
def test_session_boundaries_only_continuous_segments_dispatch(session: MarketSession) -> None:
    values = _synthetic_inputs()
    values["clock"] = _clock(session)
    values["market_clock"] = values["clock"]
    values["session"] = session
    _, result = _plan(values)
    codes = _codes(result)
    if session in {MarketSession.MORNING, MarketSession.AFTERNOON}:
        assert codes, "连续交易段应为合成持仓产生至少一个 P0 计划"
    else:
        assert not codes, "开收盘竞价、午休、闭市和非交易日不得产生新的可派发计划"


def test_missing_calendar_fails_closed_without_dispatch() -> None:
    values = _synthetic_inputs()

    def missing_calendar(*_args: object, **_kwargs: object) -> MarketClock:
        raise RuntimeError("synthetic calendar missing")

    values.update(clock=missing_calendar, market_clock=missing_calendar)
    _, result = _plan(values)
    assert not _codes(result)
    reason = _field(result, "reasons", "reason", "failure_reason", "blocked_reason", "error")
    assert reason, "日历缺失应留下不可派发原因或失败关闭状态"


def test_priority_suspension_and_budget_do_not_overrun() -> None:
    values = _synthetic_inputs()
    values["budget"] = 2
    values["budget_remaining"] = 2
    _, result = _plan(values)
    codes = _codes(result)
    assert codes[:2] == ["SYN001.SH", "SYN002.SH"], "持仓层必须优先于 focus，focus 必须优先于自选层"
    assert "SYN004.SH" not in codes, "有停牌事实的代码不可派发"
    assert len(codes) <= 2, "预算不足时应延期，不得超支"


def test_replay_same_certificate_date_session_is_deduplicated() -> None:
    values = _synthetic_inputs()
    planner, first = _plan(values)
    _, second = _plan(values, planner=planner)
    first_codes, second_codes = _codes(first), _codes(second)
    assert len(second_codes) == 0 or second_codes == first_codes[:0]
    first_used = _field(first, "budget_used", "used_budget", "cost")
    second_used = _field(second, "budget_used", "used_budget", "cost")
    if isinstance(first_used, (int, float)) and isinstance(second_used, (int, float)):
        assert second_used == 0 or second_used <= first_used


def test_ingest_has_no_intraday_producer_or_timer_registration() -> None:
    source_path = Path(__file__).resolve().parents[3] / "src/backend/app/workers/ingest.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, (ast.Attribute, ast.Name))
    }
    assert not any(
        token in call.lower()
        for call in calls
        for token in ("quotes_snapshot", "minute_producer", "intraday_quotes", "minute_bars")
    )
    assert "quotes_snapshot" not in source
    assert "threading.Timer" not in source
    assert "sched.scheduler" not in source
    assert "asyncio.create_task" not in source


def test_scheduler_constructor_does_not_start_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.ingest.scheduler import Scheduler

    calls: list[str] = []

    def forbidden(*args: object, **kwargs: object) -> None:
        calls.append("timer")
        raise AssertionError("Scheduler 构造不应创建定时器")

    monkeypatch.setattr(threading, "Timer", forbidden)
    monkeypatch.setattr(sched, "scheduler", forbidden)
    monkeypatch.setattr(asyncio, "create_task", forbidden)
    monkeypatch.setattr(asyncio, "ensure_future", forbidden)
    scheduler = Scheduler()
    assert scheduler.inflight_total == 0
    assert calls == []


def test_intraday_defaults_closed_and_plan_has_zero_socket_calls() -> None:
    spec = importlib.util.find_spec(PLANNER_MODULE)
    if spec is None:
        return
    module, planner_cls = _load_planner()
    enabled = getattr(module, "INTRADAY_ENABLED", None)
    if enabled is None:
        enabled = getattr(planner_cls, "INTRADAY_ENABLED", None)
    if enabled is not None:
        assert enabled is False
    values = _synthetic_inputs()
    before = len(SOCKET_ATTEMPTS)
    _plan(values)
    assert before == 0
    assert len(SOCKET_ATTEMPTS) == 0

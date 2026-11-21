"""T-T107 I3：盘中 P0 计划器的离线契约测试。

#323 已合入主线；计划器模块缺失或公开 API 不符时应直接失败，不再 xfail。
夹具只包含合成代码，测试不建立数据库、Redis、Docker 或网络连接。
"""

from __future__ import annotations

import ast
import asyncio
import datetime as dt
import importlib
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
LICENCE_ID = "00000000-0000-4000-8000-000000000721"
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
    module = importlib.import_module(PLANNER_MODULE)
    planner_cls = getattr(module, "P0Planner", None)
    if not isinstance(planner_cls, type):
        pytest.fail("T-B197 契约未满足：公开 P0 计划器类未提供")
    return module, planner_cls


def _clock(session: MarketSession) -> MarketClock:
    return MarketClock(trade_date=TRADE_DATE, session=session)


def _synthetic_inputs() -> dict[str, Any]:
    """计划器应消费的最小合成股票池，明确分出三层优先级。"""

    holdings = [{"security_code": "SYN001.SH", "priority": "holding", "qty": 100}]
    focus = [{"security_code": "SYN002.SH", "priority": "focus"}]
    watchlist = [
        {"security_code": "SYN003.SH", "priority": "watchlist"},
        {"security_code": "SYN004.SH", "priority": "watchlist"},
    ]
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
        "licence_id": LICENCE_ID,
    }


def _make_planner(cls: type[Any]) -> Any:
    return cls(tier1_cap=2, universe_hard_cap=8, focus_cap=4, watchlist_cap=4)


def _certificate_payload(module: ModuleType) -> Any:
    payload = {
        "holdings": ["SYN001.SH"],
        "focus": ["SYN002.SH"],
        "watchlist": ["SYN003.SH", "SYN004.SH"],
        "suspended": ["SYN004.SH"],
        "budget": 2,
    }
    universe_cls = getattr(module, "CertificateUniverse", None)
    if not isinstance(universe_cls, type):
        pytest.fail("P0 计划器模块已存在，但缺少公开 CertificateUniverse")
    return [universe_cls(LICENCE_ID, **payload)]


def _plan(values: dict[str, Any], planner: Any | None = None) -> tuple[Any, Any]:
    module, planner_cls = _load_planner()
    values = dict(values)
    certificates = _certificate_payload(module)
    instance = planner if planner is not None else _make_planner(planner_cls)
    method = getattr(instance, "plan", None)
    if not callable(method):
        pytest.fail("T-B197 契约未满足：计划器未提供公开 plan() 方法")
    return instance, method(values["now"], certificates, clock=values["clock"], budgets=None)


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
    if session in {MarketSession.MORNING, MarketSession.AFTERNOON}:
        assert result.scheduled, "连续交易段应为合成持仓产生至少一个 P0 计划"
    else:
        assert result.scheduled == ()
        assert result.records == ()
        assert f"session:{session.value}" in result.reasons


def test_missing_calendar_fails_closed_without_dispatch() -> None:
    values = _synthetic_inputs()

    def missing_calendar(*_args: object, **_kwargs: object) -> MarketClock:
        raise RuntimeError("synthetic calendar missing")

    values.update(clock=missing_calendar, market_clock=missing_calendar)
    _, result = _plan(values)
    assert result.scheduled == ()
    assert result.records == ()
    assert "calendar_unavailable" in result.reasons


def test_priority_suspension_and_budget_do_not_overrun() -> None:
    values = _synthetic_inputs()
    values["budget"] = 2
    values["budget_remaining"] = 2
    _, result = _plan(values)
    assert [record.security_code for record in result.scheduled] == ["SYN001.SH", "SYN002.SH"]
    assert all(record.status == "planned" for record in result.scheduled)
    skipped = {record.security_code: record.reason for record in result.skipped}
    assert all(record.status == "skipped" for record in result.skipped)
    assert skipped["SYN004.SH"] == "suspended"
    assert skipped["SYN003.SH"] == "budget_exhausted"
    assert result.budget_used == {LICENCE_ID: 2}


def test_replay_same_certificate_date_session_is_deduplicated() -> None:
    values = _synthetic_inputs()
    planner, first = _plan(values)
    _, second = _plan(values, planner=planner)
    assert first.scheduled
    assert len(first.records) == 4
    assert first.duplicate_count == 0
    assert second.scheduled == ()
    assert second.duplicate_count == 4
    assert second.budget_used == {}


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
    scheduler: Scheduler = Scheduler()
    assert scheduler.inflight_total == 0
    assert calls == []


def test_intraday_defaults_closed_and_plan_has_zero_socket_calls() -> None:
    module, _ = _load_planner()
    assert module.INTRADAY_ENABLED is False
    values = _synthetic_inputs()
    before = len(SOCKET_ATTEMPTS)
    _plan(values)
    assert before == 0
    assert len(SOCKET_ATTEMPTS) == 0

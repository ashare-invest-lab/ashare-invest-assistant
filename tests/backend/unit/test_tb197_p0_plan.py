import datetime as dt
import socket

import pytest
from app.aggregates.models import MarketClock
from app.ingest.scheduler import Scheduler
from app.intraday.p0_plan import CertificateUniverse, P0Planner
from app.schemas.enums import MarketSession

NOW = dt.datetime(2026, 11, 20, 10, tzinfo=dt.UTC)
DAY = dt.date(2026, 11, 20)


def planner() -> P0Planner:
    return P0Planner(tier1_cap=2, universe_hard_cap=4, focus_cap=2, watchlist_cap=3)


@pytest.mark.parametrize(
    "session",
    [
        MarketSession.PRE_OPEN,
        MarketSession.LUNCH_BREAK,
        MarketSession.CLOSING_AUCTION,
        MarketSession.CLOSED,
        MarketSession.NON_TRADING_DAY,
        MarketSession.CALL_AUCTION,
    ],
)
def test_only_continuous_sessions_plan(session: MarketSession) -> None:
    result = planner().plan(
        NOW,
        [CertificateUniverse("licence-a", holdings=["SYN001"])],
        clock=MarketClock(trade_date=DAY, session=session),
    )
    assert result.records == ()
    assert result.reasons == (f"session:{session.value}",)


def test_missing_calendar_fails_closed() -> None:
    result = planner().plan(
        NOW,
        {"licence-a": {"holdings": ["SYN001"]}},
        clock=lambda _: (_ for _ in ()).throw(RuntimeError()),
    )
    assert result.records == () and result.reasons == ("calendar_unavailable",)


def test_layers_suspension_budget_and_replay() -> None:
    p = planner()
    cert = CertificateUniverse(
        "licence-a",
        holdings=["SYN001", "SYN002"],
        focus=["SYN002", "SYN003"],
        watchlist=["SYN003", "SYN004", "SYN005"],
        suspended=["SYN002"],
        budget=2,
    )
    first = p.plan(
        NOW, [cert], clock=MarketClock(trade_date=DAY, session=MarketSession.MORNING)
    )
    assert [(r.code, r.layer, r.tier, r.status) for r in first.records] == [
        ("SYN001", "holding", 1, "planned"),
        ("SYN002", "holding", 1, "skipped"),
        ("SYN003", "focus", 2, "planned"),
        ("SYN004", "watchlist", 2, "deferred"),
    ]
    assert first.budget_used == {"licence-a": 2}
    replay = p.plan(
        NOW, [cert], clock=MarketClock(trade_date=DAY, session=MarketSession.MORNING)
    )
    assert replay.records == () and replay.duplicate_count == 4
    assert len(p.records) == 4


def test_scheduler_receives_records_idempotently_without_io(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = socket.socket

    def counted(*args: object, **kwargs: object) -> socket.socket:
        nonlocal calls
        calls += 1
        return original(*args, **kwargs)

    monkeypatch.setattr(socket, "socket", counted)
    record = (
        planner()
        .plan(
            NOW,
            {"licence-a": {"holdings": ["SYN001"]}},
            clock=MarketClock(trade_date=DAY, session=MarketSession.AFTERNOON),
        )
        .records[0]
    )
    scheduler: Scheduler[object] = Scheduler()
    assert scheduler.record_plan(record)
    assert not scheduler.record_plan(record)
    assert scheduler.plan_records == (record,)
    assert calls == 0

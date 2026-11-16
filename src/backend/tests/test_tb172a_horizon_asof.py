"""T-B172 A0: fictional symbols and synthetic evidence; no services."""

# ruff: noqa: S101
from __future__ import annotations

import datetime as dt
import inspect
import socket
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest

from app.features.horizon_sources import (
    BasisEvidence,
    BatchReceipt,
    CalendarVersion,
    CompletionProof,
    DailyBarVersion,
    EmptyEvidenceProvider,
    FakeEvidenceProvider,
)
from app.features.horizon_windows import DaySelection, daily_cutoff, intraday, select_day, window
from app.strategy.horizon import inputs

BJ = ZoneInfo("Asia/Shanghai")
T = dt.date(2031, 1, 3)  # Entire calendar is synthetic, including closures.
P = T - dt.timedelta(days=1)
USER, LIC = UUID(int=1), UUID(int=2)
CODE = "SYNTH.SH"
SCOPE = {"user_id": USER, "licence_id": None, "code": CODE}


def at(hour: int = 17, minute: int = 30, day: dt.date = T) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(hour, minute), BJ)


@pytest.fixture(autouse=True)
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    def deny(*args: object, **kwargs: object) -> None:
        pytest.fail("external call forbidden")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    monkeypatch.setattr(socket, "getaddrinfo", deny)


def basis(source: str = "fake", scope: str = "synthetic") -> BasisEvidence:
    identity = {
        "user_id": USER,
        "licence_id": LIC if scope == "per_licence" else None,
        "source": source,
        "scope": scope,
        "first_seen_at": at(day=P),
        "available_at": at(day=P),
        "source_version": "fixture-v1",
        "persisted_receipt": "synthetic-commit",
    }
    bars = tuple(
        DailyBarVersion(
            **identity, version_id=str(day), version_hash=str(day), code=CODE, trade_date=day
        )
        for day in (P, T)
    )
    calendar = CalendarVersion(
        **{**identity, "source": "fake", "scope": "synthetic", "licence_id": None},
        version_id="calendar-v1",
        version_hash="calendar-v1",
        days=(
            (P, True),
            (T, True),
            (T + dt.timedelta(days=1), False),
            (T + dt.timedelta(days=2), False),
            (T + dt.timedelta(days=3), False),
        ),
    )
    proofs = tuple(
        CompletionProof(b, True, at(17, 10, b.trade_date), "synthetic-final") for b in bars
    )
    return BasisEvidence(calendar, bars, proofs)


def selected(b: BasisEvidence, as_of: dt.datetime | None = None, **scope: object) -> DaySelection:
    return select_day(b, **{**SCOPE, **scope}, as_of=as_of or at())


def test_a192_finality_requires_visible_symbol_proof() -> None:
    b = basis()
    assert selected(b).d == T
    late = replace(b.proofs[-1], available_at=at() + dt.timedelta(microseconds=1))
    b = replace(b, proofs=(b.proofs[0], late))
    assert selected(b).d == P
    assert selected(b, late.available_at).d == T
    assert selected(b).d == P
    b = basis()
    for change in (
        {"first_seen_at": at() + dt.timedelta(microseconds=1)},
        {"available_at": None},
        {"persisted_receipt": ""},
        {"adj_type": "qfq"},
        {"conflicted": True},
    ):
        bar = replace(b.bars[-1], **change)
        proof = replace(b.proofs[-1], version=bar)
        broken = replace(b, bars=(b.bars[0], bar), proofs=(b.proofs[0], proof))
        assert selected(broken).d == P
    for change in (
        {"is_final": False},
        {"source_final_receipt": ""},
        {"version": replace(b.bars[-1], version_hash="another")},
        {"version": replace(b.bars[-1], code="OTHER.SH")},
        {"version": replace(b.bars[-1], user_id=UUID(int=3))},
        {"version": replace(b.bars[-1], licence_id=LIC)},
    ):
        assert selected(replace(b, proofs=(b.proofs[0], replace(b.proofs[-1], **change)))).d == P


@pytest.mark.parametrize("status", ["ok", "partial"])
def test_a192_ready_partial_not_symbol_final(status: str) -> None:
    b = basis("mairui", "per_licence")
    receipt = BatchReceipt("run", USER, LIC, T, status, at(17, 10), at(17, 10))
    proof = replace(b.proofs[-1], run_id="run")
    b = replace(b, proofs=(b.proofs[0], proof), batches=(receipt,))
    assert selected(b, licence_id=LIC).d == T
    assert selected(replace(b, proofs=()), licence_id=LIC).d is None
    assert selected(replace(b, batches=()), licence_id=LIC).d == P
    assert (
        selected(replace(b, batches=(replace(receipt, issues=("OTHER.SH",)),)), licence_id=LIC).d
        == T
    )
    for change in (
        {"issues": (CODE,)},
        {"status": "failed"},
        {"window_trading_days": 1},
        {"kind": "backfill"},
        {"step": "other"},
        {"owner_id": None},
        {"finished_at": at() + dt.timedelta(microseconds=1)},
        {"available_at": at() + dt.timedelta(microseconds=1)},
    ):
        assert selected(replace(b, batches=(replace(receipt, **change),)), licence_id=LIC).d == P
    public_batch = replace(receipt, owner_id=None, members=((USER, CODE),))
    assert selected(replace(b, batches=(public_batch,)), licence_id=LIC).d == T
    failed = replace(receipt, run_id="later", status="failed", available_at=at(), finished_at=at())
    assert selected(replace(b, batches=(receipt, failed)), licence_id=LIC).d == P


def test_a192_no_proof_falls_back_or_null() -> None:
    b = basis()
    assert selected(replace(b, proofs=b.proofs[:1])).d == P
    for delta in (-1, 0, 1):
        instant = at() + dt.timedelta(microseconds=delta)
        bars = tuple(replace(bar, fetched_at=instant) for bar in b.bars)
        result = selected(replace(b, bars=bars, proofs=()), instant)
        assert result.d is None
        assert result.gaps
        proofs = tuple(replace(p, version=v) for p, v in zip(b.proofs, bars, strict=True))
        assert selected(replace(b, bars=bars, proofs=proofs), instant).d == T
    empty = EmptyEvidenceProvider().read_basis(**SCOPE, as_of=at())
    assert selected(empty).d is None


@pytest.mark.parametrize(
    ("hour", "minute", "during"),
    [
        (9, 15, False),
        (9, 25, False),
        (9, 30, True),
        (11, 30, True),
        (12, 0, True),
        (13, 0, True),
        (14, 57, True),
        (15, 0, False),
        (17, 10, False),
        (17, 30, False),
    ],
)
def test_a192_session_edges_lunch_close_and_finality(hour: int, minute: int, during: bool) -> None:
    instant = at(hour, minute)
    assert intraday(instant, is_open=True) is during
    b = basis()
    b = replace(b, proofs=(b.proofs[0], replace(b.proofs[-1], available_at=at(day=P))))
    assert selected(b, instant).d == (T if (hour, minute) >= (17, 10) else P)


def test_a188_asof_finality_intraday_close_weekend() -> None:
    b = basis()
    for offset in (1, 2, 3):
        instant = at(day=T + dt.timedelta(days=offset))
        assert selected(b, instant).d == T
        assert not intraday(instant, is_open=False)
    assert selected(b, at().astimezone(dt.UTC)) == selected(b)
    assert selected(b, at(9, 15) - dt.timedelta(microseconds=1)).d == P


def test_a188_calendar_gap_and_suspension_window() -> None:
    b = basis()
    suspended = replace(b.bars[-1], is_suspended=True)
    b = replace(
        b,
        bars=(b.bars[0], suspended),
        proofs=(b.proofs[0], replace(b.proofs[-1], version=suspended)),
    )
    result = window(b, d=T, n=2, **SCOPE, as_of=at())
    assert result.dates == (P, T)
    assert result.bars[-1] == suspended
    assert not suspended.valid_k
    missing = window(replace(b, proofs=b.proofs[1:]), d=T, n=2, **SCOPE, as_of=at())
    assert missing.dates == (P, T)
    assert missing.bars[0] is None
    assert missing.gaps
    hole = replace(b, calendar=replace(b.calendar, days=((P, True),)))
    assert selected(hole).d is None
    assert selected(hole).gaps
    assert window(hole, d=T, n=2, **SCOPE, as_of=at()).gaps
    assert window(b, d=T, n=3, **SCOPE, as_of=at()).gaps


@pytest.mark.parametrize(
    ("source", "scope", "owner", "licence", "requested", "allowed"),
    [
        ("fake", "synthetic", USER, None, None, True),
        ("exchange", "public", USER, None, None, True),
        ("fake", "public", USER, None, None, False),
        ("tdx_local", "public", USER, None, None, False),
        ("mairui", "per_licence", USER, LIC, None, False),
        ("mairui", "per_licence", USER, LIC, UUID(int=3), False),
        ("mairui", "per_licence", USER, None, None, False),
        ("fake", "synthetic", UUID(int=3), None, None, False),
    ],
)
def test_source_scope_isolation(
    source: str,
    scope: str,
    owner: UUID,
    licence: UUID | None,
    requested: UUID | None,
    allowed: bool,
) -> None:
    b = basis()
    bars = tuple(
        replace(v, source=source, scope=scope, user_id=owner, licence_id=licence) for v in b.bars
    )
    b = replace(
        b,
        bars=bars,
        proofs=tuple(replace(p, version=v) for p, v in zip(b.proofs, bars, strict=True)),
    )
    assert (selected(b, licence_id=requested).d is not None) is allowed
    if source != "fake" or scope != "synthetic":
        with pytest.raises(ValueError, match="synthetic"):
            FakeEvidenceProvider(b)


def test_a192_collect_explicit_asof_no_clock_or_clamp(monkeypatch: pytest.MonkeyPatch) -> None:
    params = inspect.signature(inputs.collect).parameters
    assert "as_of" in params
    assert "evidence_provider" in params
    assert params["as_of"].default is inspect.Parameter.empty
    conn = MagicMock()
    conn.execute.return_value.first.return_value = None
    later = at() + dt.timedelta(microseconds=2)
    conn.execute.return_value.one.side_effect = [(0, None), (later, 0)] * 2
    clock = MagicMock(side_effect=AssertionError("clock consulted"))
    monkeypatch.setattr(inputs, "now_utc", clock, raising=False)
    monkeypatch.setattr(inputs, "dt", SimpleNamespace(datetime=clock))
    b = basis()
    late = replace(b.proofs[-1], available_at=at() + dt.timedelta(microseconds=1))
    provider = FakeEvidenceProvider(replace(b, proofs=(b.proofs[0], late)))
    kwargs = {"as_of": at() + dt.timedelta(microseconds=1), "evidence_provider": provider}
    result = inputs.collect(conn, USER, CODE, ["user.has_position"], **kwargs)
    assert result.d == T
    assert result.values == {"user.has_position": None}
    assert (
        inputs.collect(
            conn,
            USER,
            CODE,
            ["user.has_position"],
            **{**kwargs, "as_of": kwargs["as_of"].astimezone(dt.UTC)},
        )
        == result
    )
    sql = "\n".join(str(c.args[0]) for c in conn.execute.call_args_list)
    assert "user_profiles.created_at <=" in sql
    assert "user_profiles.confirmed_at <=" in sql
    assert "trades.created_at <=" in sql
    with pytest.raises(ValueError, match="aware"):
        inputs.collect(conn, USER, CODE, [], **{**kwargs, "as_of": at().replace(tzinfo=None)})
    with pytest.raises(TypeError):
        inputs.collect(conn, USER, CODE, [])
    clock.assert_not_called()


def test_a192_daily_cutoff_http_request_time_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.api.v1 import horizon

    assert daily_cutoff(T) == at()
    assert str(daily_cutoff(T).tzinfo) == "Asia/Shanghai"
    instant = at() + dt.timedelta(microseconds=1)
    clock = MagicMock(return_value=instant)
    collect = MagicMock(return_value=inputs.Inputs())
    monkeypatch.setattr(horizon, "now_utc", clock)
    monkeypatch.setattr(horizon.hz_inputs, "collect", collect)
    monkeypatch.setattr(horizon, "normalize_code", lambda *_: CODE)
    monkeypatch.setattr(
        horizon.classifier,
        "classify",
        lambda *_: SimpleNamespace(
            reasons=[],
            suitable=[],
            scores={},
            inputs_missing=[],
            caps=[],
            hints=[],
            classifier_version="synthetic",
        ),
    )
    settings = SimpleNamespace(
        business=SimpleNamespace(horizon_classifier=SimpleNamespace(features=[]))
    )
    horizon.get_horizon_assessment(SimpleNamespace(user_id=USER), settings, MagicMock(), CODE)
    clock.assert_called_once_with()
    assert collect.call_args.kwargs["as_of"] == instant
    assert isinstance(collect.call_args.kwargs["evidence_provider"], EmptyEvidenceProvider)
    b = basis()
    late = replace(b, proofs=(b.proofs[0], replace(b.proofs[-1], available_at=instant)))
    assert selected(late, daily_cutoff(T)).d == P
    assert selected(late, instant).d == T
    from app.research import content

    monkeypatch.setattr(content, "latest_profile", lambda *_a, **_k: object())
    settings.business.risk_controls = SimpleNamespace(
        rc2_position_cap=SimpleNamespace(enabled=False)
    )
    content._fit(MagicMock(), settings, USER, CODE, content._Ev(instant), as_of=instant)
    assert collect.call_args.kwargs["as_of"] == instant


@pytest.mark.parametrize(
    ("rebuilt", "count", "expected"),
    [
        (None, 0, False),
        (at(), 1, True),
        (at(), 0, False),
        (at() + dt.timedelta(microseconds=1), 1, None),
    ],
)
def test_position_requires_visible_rebuild(
    rebuilt: dt.datetime | None, count: int, expected: bool | None
) -> None:
    conn = MagicMock()
    conn.execute.return_value.first.return_value = None
    conn.execute.return_value.one.side_effect = [(0, None), (rebuilt, count)]
    got = inputs.collect(
        conn,
        USER,
        CODE,
        ["user.has_position"],
        as_of=at(),
        evidence_provider=EmptyEvidenceProvider(),
    )
    assert got.values["user.has_position"] is expected


def test_versions_late_conflict_and_calendar_visibility() -> None:
    b = basis()
    later = at() + dt.timedelta(microseconds=1)
    revised = replace(b.bars[-1], version_hash="revision", available_at=later)
    b = replace(b, bars=(*b.bars, revised))
    provider = FakeEvidenceProvider(b)
    kwargs = {**SCOPE, "kind": "daily_bar", "dates": (P, T)}
    assert provider.read_versions(**kwargs, as_of=at()).versions == b.bars[:2]
    assert provider.read_versions(**kwargs, as_of=later).gaps == ("version_conflict",)
    assert selected(b).d == T
    assert selected(b, later).d == P
    assert selected(replace(b, calendar=replace(b.calendar, available_at=later))).d is None
    assert provider.read_basis(**{**SCOPE, "user_id": UUID(int=3)}, as_of=at()).bars == ()
    assert EmptyEvidenceProvider().read_versions(**kwargs, as_of=at()).gaps

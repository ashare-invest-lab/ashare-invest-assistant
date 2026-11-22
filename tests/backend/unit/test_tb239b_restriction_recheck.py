"""T-B239b regression coverage for restriction rechecks with synthetic rows."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.signals import service
from app.signals.models import MarketFacts, SignalInput
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import Select

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
INSTANCE_ID = uuid.UUID("00000000-0000-4000-8000-000000000103")
BASE = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one_or_none(self) -> Any | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class _RecheckConnection:
    def __init__(self, *, candidate: Any, remaining: list[Any], strategy_rows: list[Any] | None = None,
                 signal: Any | None = None, active_reason: Any | None = None) -> None:
        self.candidate, self.remaining = candidate, remaining
        self.strategy_rows, self.signal = strategy_rows or [], signal
        self.active_reason, self.select_number = active_reason, 0
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        self.statements.append(statement)
        if isinstance(statement, TextClause) or not isinstance(statement, Select):
            return _Result([])
        self.select_number += 1
        n = self.select_number
        if n == 1:
            return _Result([self.candidate])
        if n == 2:
            return _Result([_reason(self.candidate)])
        if self.candidate.strategy_version_id is not None and n == 3:
            return _Result(self.strategy_rows)
        remaining_number = 4 if self.candidate.strategy_version_id is not None else 3
        if n == remaining_number:
            return _Result(self.remaining)
        if n == remaining_number + 1:
            return _Result([self.signal] if self.signal is not None else [])
        if n == remaining_number + 2:
            return _Result([self.active_reason] if self.active_reason is not None else [])
        return _Result([])


def _restriction(*, target_type: str = "security", target_id: str = "600000.SH",
                 created_at: dt.datetime = BASE - dt.timedelta(hours=2),
                 until: dt.datetime | None = None, kind: str = "blocklist") -> Any:
    return SimpleNamespace(id=uuid.uuid4(), user_id=USER_ID, kind=kind, target_type=target_type,
                           target_id=target_id, created_at=created_at, until=until, removed_at=None)


def _candidate(*, candidate_at: dt.datetime = BASE, instance_id: uuid.UUID | None = None,
               strategy_version_id: uuid.UUID | None = None) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), user_id=USER_ID, security_code="600000.SH",
                           instance_id=instance_id, strategy_version_id=strategy_version_id,
                           created_at=candidate_at)


def _reason(candidate: Any) -> Any:
    return SimpleNamespace(id=uuid.uuid4(), signal_id=candidate.id)


def _signal(candidate: Any, *, state: str = "blocked") -> Any:
    return SimpleNamespace(id=candidate.id, user_id=USER_ID, state=state, created_at=candidate.created_at)


def _run(restriction: Any, *, candidate: Any, remaining: list[Any],
         at: dt.datetime = BASE + dt.timedelta(hours=2), strategy_rows: list[Any] | None = None,
         signal: Any | None = None, active_reason: Any | None = None) -> tuple[list[uuid.UUID], list[uuid.UUID], list[dict[str, Any]]]:
    connection = _RecheckConnection(candidate=candidate, remaining=remaining, strategy_rows=strategy_rows,
                                    signal=signal if signal is not None else _signal(candidate),
                                    active_reason=active_reason)
    return service.recheck_restriction(connection, user_id=USER_ID, restriction=restriction, at=at)


def _assert_until(until: dt.datetime, kept: bool) -> None:
    candidate = _candidate()
    released, remaining, gaps = _run(_restriction(), candidate=candidate,
                                     remaining=[_restriction(until=until)])
    assert (len(released), len(remaining), gaps) == ((0, 1, []) if kept else (1, 0, []))


def test_recheck_until_early_than_candidate_created_at_releases_reason() -> None:
    _assert_until(BASE - dt.timedelta(minutes=1), False)


def test_recheck_until_equal_to_candidate_created_at_releases_reason() -> None:
    _assert_until(BASE, False)


def test_recheck_until_late_than_candidate_created_at_keeps_reason() -> None:
    _assert_until(BASE + dt.timedelta(hours=1), True)


def test_recheck_honors_restriction_until_and_instance_target() -> None:
    candidate = _candidate(instance_id=INSTANCE_ID)
    restriction = _restriction(target_type="instance", target_id=str(INSTANCE_ID),
                               until=BASE + dt.timedelta(hours=1))
    released, remaining, gaps = _run(restriction, candidate=candidate, remaining=[])
    assert len(released) == 1
    assert remaining == []
    assert gaps == []


def test_recheck_unknown_target_type_returns_gap_without_query() -> None:
    released, remaining, gaps = _run(_restriction(target_type="portfolio"),
                                     candidate=_candidate(), remaining=[])
    assert released == []
    assert remaining == []
    assert gaps[0]["reason"] == "no_source"


class _WriteResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self.rows, self.scalar = rows or [], scalar

    def all(self) -> list[Any]:
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def one(self) -> Any:
        assert self.rows
        return self.rows[0]

    def one_or_none(self) -> Any | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.scalar

    def scalar_one_or_none(self) -> Any:
        return self.scalar

    def scalars(self) -> _WriteResult:
        return self


class _WriteConnection:
    def __init__(self, responses: list[_WriteResult]) -> None:
        self.responses = list(responses)

    def execute(self, _statement: Any, *_args: Any, **_kwargs: Any) -> _WriteResult:
        return self.responses.pop(0) if self.responses else _WriteResult()


def _write_content(snapshot_id: uuid.UUID) -> tuple[SignalInput, MarketFacts]:
    at = BASE
    evidence_id = "synthetic-evidence"
    content = SignalInput.model_validate({
        "security_code": "600000.SH", "proposed_action": "buy", "t_leg": None, "score": None,
        "confidence": {"level": "high", "value": "0.8"},
        "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
        "rule_refs": [{"rule_id": "R1", "snippet_id": None, "snippet_version": None,
                       "role": "entry", "dimension": "technical", "passed": True, "value": None,
                       "threshold": "f.close_qfq > 0", "evidence_ids": [evidence_id]}],
        "evidence": [{"id": evidence_id, "key": "f.close_qfq", "value": 12.5, "unit": None,
                      "provider": "system", "endpoint": None, "data_as_of": at, "fetched_at": at,
                      "epistemic_type": "fact"}],
        "counter_evidence": [{"text": "synthetic counter evidence", "expr": None,
                              "evidence_ids": [evidence_id]}],
        "invalidation": [{"text": "synthetic invalidation", "expr": None,
                           "evidence_ids": [evidence_id]}],
        "model_refs": [], "risk_flags": [], "valid_until": None, "snapshot_id": str(snapshot_id),
        "feature_set_version": "synthetic", "created_at": at, "data_status": "fresh",
        "data_as_of": at, "gaps": [],
    })
    facts = MarketFacts(price=Decimal("12.5"), required_cash=Decimal(1250), is_suspended=False,
                        list_days=600, limit_locked_up=False, limit_locked_down=False)
    return content, facts


def test_write_candidate_applies_restriction_interval_at_candidate_time(monkeypatch: Any) -> None:
    snapshot_id, account_id, instance_id, version_id, strategy_id = (uuid.uuid4() for _ in range(5))
    content, facts = _write_content(snapshot_id)
    expired, active = _restriction(until=BASE - dt.timedelta(minutes=1)), _restriction(until=None)
    instance = SimpleNamespace(id=instance_id, user_id=USER_ID, status="active",
                               derived_strategy_version_id=None, strategy_version_id=version_id,
                               scope="account", security_code=None, account_id=account_id, horizon="short")
    version = SimpleNamespace(id=version_id, strategy_id=strategy_id, lifecycle="published",
                              config={"universe": {"pool": "持仓 ∪ 自选", "security_types": ["stock"],
                                                   "boards": {"main": True}},
                                     "spec": {"rules": [{"id": "R1", "role": "entry",
                                                           "dimension": "technical",
                                                           "expr": "f.close_qfq > 0"}]}},
                              card_version_id=None)
    account, snapshot = SimpleNamespace(id=account_id), SimpleNamespace(
        id=snapshot_id, licence_id=None, created_at=BASE - dt.timedelta(minutes=1),
        items=service.snapshot_items(content, facts))
    portfolio = SimpleNamespace(positions={}, cash=Decimal(10000))
    master, segment = SimpleNamespace(type="stock", board="main", risk_flag=None), SimpleNamespace()
    market_rules = SimpleNamespace(segment_for=lambda _day: segment)
    responses = [_WriteResult(scalar="approved"), _WriteResult(), _WriteResult([instance]),
                 _WriteResult([version]), _WriteResult(scalar=USER_ID), _WriteResult(scalar="user"),
                 _WriteResult([account]), _WriteResult([snapshot]), _WriteResult([uuid.uuid4()]),
                 _WriteResult(scalar=None), _WriteResult([master]), _WriteResult(),
                 _WriteResult([expired, active]), _WriteResult(), _WriteResult()]
    connection = _WriteConnection(responses)
    monkeypatch.setattr(service, "run_with_master_guard",
                        lambda _conn, **kwargs: (None, kwargs["operation"](_conn)))
    monkeypatch.setattr("app.strategy.runtime.runnable", lambda _lifecycle, _role: True)
    monkeypatch.setattr("app.api.v1.portfolio._account", lambda _conn, _id, _day: portfolio)
    monkeypatch.setattr(service, "lot_spec", lambda *_args, **_kwargs: SimpleNamespace(min_buy=100))
    monkeypatch.setattr(service, "board_in_universe", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "calendar_state", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(service, "assess", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "live_snapshots", lambda _id: SimpleNamespace(
        order_by=lambda _order: SimpleNamespace(limit=lambda _limit: object())))
    result = service.write_candidate(connection, user_id=USER_ID, instance_id=instance_id,
                                     content=content, facts=facts, market_rules=market_rules)
    assert result["diagnostic"] == "blocked"

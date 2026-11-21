"""T-T112 R5/R6 contracts with synthetic offline fixtures only."""

from __future__ import annotations

import datetime as dt
import importlib.util
import inspect
import socket
import uuid
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import BinaryExpression, BindParameter, BooleanClauseList, Grouping, Null

from app.signals import service

_RESTRICTIONS_MODULE = "app.api.v1.restrictions"
if importlib.util.find_spec(_RESTRICTIONS_MODULE) is not None:
    from app.api.v1 import restrictions
else:
    restrictions = None  # type: ignore[assignment]

USER = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER = uuid.UUID("00000000-0000-4000-8000-000000000002")
STRATEGY = uuid.UUID("00000000-0000-4000-8000-000000000101")
INSTANCE = uuid.UUID("00000000-0000-4000-8000-000000000102")
NOW = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("T-T112 tests must not use the network")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)


def _require_restrictions() -> None:
    if restrictions is None:
        pytest.xfail("app.api.v1.restrictions endpoint is absent on this tree")


def _require_recheck() -> None:
    if not callable(getattr(service, "recheck_restriction", None)):
        pytest.xfail("service.recheck_restriction is absent on this tree")


def _require_candidate_pit() -> None:
    write_candidate = getattr(service, "write_candidate", None)
    if not callable(write_candidate):
        pytest.xfail("service.write_candidate is absent on this tree")
    source = inspect.getsource(write_candidate)
    if "user_restrictions.c.created_at" not in source or "user_restrictions.c.removed_at" not in source:
        pytest.xfail("#348 write_candidate PIT window is absent on this tree")


def auth(user_id: uuid.UUID = USER) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id)


def row(
    *,
    owner: uuid.UUID = USER,
    identifier: uuid.UUID | None = None,
    kind: str = "blocklist",
    target_type: str = "security",
    target_id: str = "SYN001.SH",
    until: dt.datetime | None = None,
    created_at: dt.datetime = NOW - dt.timedelta(hours=1),
    removed_at: dt.datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier or uuid.uuid4(),
        user_id=owner,
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        until=until,
        reason="synthetic fixture",
        created_at=created_at,
        removed_at=removed_at,
    )


class Result:
    def __init__(self, rows: list[Any] | tuple[Any, ...] = ()) -> None:
        self.rows = list(rows)

    def all(self) -> list[Any]:
        return list(self.rows)

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def one_or_none(self) -> Any | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.one()

    def scalar_one_or_none(self) -> Any | None:
        return self.one_or_none()

    def scalars(self) -> Result:
        return self

    def mappings(self) -> Result:
        return self

    def __iter__(self):
        return iter(self.rows)


class Engine:
    def __init__(self, connection: Any) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Any:
        yield self.connection

    @contextmanager
    def begin(self) -> Any:
        yield self.connection


def _unwrap(expression: Any) -> Any:
    while isinstance(expression, Grouping):
        expression = expression.element
    return expression


def _literal(expression: Any) -> Any:
    expression = _unwrap(expression)
    if isinstance(expression, BindParameter):
        return expression.value
    if isinstance(expression, Null):
        return None
    return expression


def _value(expression: Any, item: Any) -> Any:
    expression = _unwrap(expression)
    if isinstance(expression, (BindParameter, Null)):
        return _literal(expression)
    key = getattr(expression, "key", None)
    if key is not None and hasattr(item, key):
        return getattr(item, key)
    raise AssertionError(f"unexpected SQL value {expression!r}")


def _matches(expression: Any, item: Any) -> bool:
    expression = _unwrap(expression)
    if isinstance(expression, BooleanClauseList):
        clauses = list(expression.clauses)
        if expression.operator is operators.and_:
            return all(_matches(clause, item) for clause in clauses)
        if expression.operator is operators.or_:
            return any(_matches(clause, item) for clause in clauses)
        raise AssertionError(f"unexpected boolean operator {expression.operator!r}")
    if not isinstance(expression, BinaryExpression):
        raise AssertionError(f"unexpected SQL predicate {expression!r}")
    left = _value(expression.left, item)
    right = _value(expression.right, item)
    operator = expression.operator
    if operator is operators.eq:
        return left == right
    if operator is operators.ne:
        return left != right
    if operator is operators.le:
        return left <= right
    if operator is operators.lt:
        return left < right
    if operator is operators.ge:
        return left >= right
    if operator is operators.gt:
        return left > right
    if operator is operators.is_:
        return left is right
    if operator is operators.in_op:
        return left in right
    raise AssertionError(f"unexpected SQL comparison {operator!r}")


def _expressions(expression: Any) -> list[Any]:
    expression = _unwrap(expression)
    values = [expression]
    values.extend(child for child in expression.get_children())
    return values + [nested for child in expression.get_children() for nested in _expressions(child)]


_MISSING = object()

def _has_comparison(expression: Any, column: str, operator: Any, expected: Any = _MISSING) -> bool:
    for candidate in _expressions(expression):
        if not isinstance(candidate, BinaryExpression):
            continue
        left = _unwrap(candidate.left)
        if getattr(left, "key", None) != column or candidate.operator is not operator:
            continue
        if expected is _MISSING or _literal(candidate.right) == expected:
            return True
    return False


class RecheckConnection:
    """Synthetic connection that evaluates the actual recheck predicates."""

    def __init__(self, rows: list[Any], candidate: Any, reason: Any, signal: Any) -> None:
        self.rows = rows
        self.candidate = candidate
        self.reason = reason
        self.signal = signal
        self.reason_status = "active"
        self.current_restriction: Any | None = None
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        text = str(statement)
        whereclause = getattr(statement, "whereclause", None)
        if isinstance(statement, Update):
            params = statement.compile().params
            if "user_restrictions" in text:
                assert whereclause is not None
                assert _has_comparison(whereclause, "id", operators.eq)
                assert _has_comparison(whereclause, "user_id", operators.eq, USER)
                assert _has_comparison(whereclause, "removed_at", operators.is_, None)
                identifier = params.get("id") or params.get("id_1")
                for item in self.rows:
                    if item.id == identifier:
                        self.current_restriction = item
                        item.removed_at = params["removed_at"]
                return Result()
            if "non_executable_reasons" in text:
                assert whereclause is not None
                assert _has_comparison(whereclause, "id", operators.eq, self.reason.id)
                assert _has_comparison(whereclause, "status", operators.eq, "active")
                assert params.get("status") == "released"
                self.reason_status = "released"
                self.reason.status = "released"
                return Result()
            if "candidate_signals" in text:
                assert whereclause is not None
                assert _has_comparison(whereclause, "id", operators.eq, self.signal.id)
                assert _has_comparison(
                    whereclause, "created_at", operators.eq, self.signal.created_at
                )
                assert params.get("state") == "released"
                return Result()
            raise AssertionError(f"unexpected recheck update: {statement!s}")
        if isinstance(statement, Insert):
            params = statement.compile().params
            if "reason_status_events" in text:
                assert params["reason_id"] == self.reason.id
                assert params["from_status"] == "active"
                assert params["to_status"] == "released"
                assert params["at"] in (NOW, NOW + dt.timedelta(hours=1))
                return Result()
            if "candidate_signal_events" in text:
                assert params["signal_id"] == self.signal.id
                assert params["from_state"] == "blocked"
                assert params["to_state"] == "released"
                assert params["cause"] == "reason_released"
                return Result()
            raise AssertionError(f"unexpected recheck insert: {statement!s}")
        if "pg_advisory_xact_lock" in text:
            return Result()
        if "user_restrictions" in text:
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            if _has_comparison(whereclause, "id", operators.ne):
                assert _has_comparison(whereclause, "removed_at", operators.is_, None)
                current = next(
                    _literal(candidate.right)
                    for candidate in _expressions(whereclause)
                    if isinstance(candidate, BinaryExpression)
                    and getattr(_unwrap(candidate.left), "key", None) == "id"
                    and candidate.operator is operators.ne
                )
                return Result(
                    [
                        item
                        for item in self.rows
                        if item.user_id == USER
                        and item.id != current
                        and item.removed_at is None
                        and _matches(whereclause, item)
                    ]
                )
            assert _has_comparison(whereclause, "id", operators.eq)
            return Result(
                [item for item in self.rows if item.user_id == USER and _matches(whereclause, item)]
            )
        if "candidate_signals" in text:
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            if _has_comparison(whereclause, "security_code", operators.eq, "SYN001.SH"):
                assert _has_comparison(whereclause, "created_at", operators.lt)
                assert _has_comparison(whereclause, "created_at", operators.ge)
                if self.current_restriction and self.current_restriction.until is not None:
                    assert _has_comparison(
                        whereclause, "created_at", operators.lt, self.current_restriction.until
                    )
                matches = _matches(whereclause, self.candidate)
                return Result([self.candidate] if matches else [])
            assert _has_comparison(whereclause, "id", operators.eq, self.signal.id)
            return Result([self.signal] if _matches(whereclause, self.signal) else [])
        if "non_executable_reasons" in text:
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            assert _has_comparison(whereclause, "status", operators.eq, "active")
            if _has_comparison(whereclause, "code", operators.eq, "BLOCKLISTED"):
                assert _has_comparison(whereclause, "signal_id", operators.in_op)
                return Result(
                    [self.reason]
                    if self.reason_status == "active" and _matches(whereclause, self.reason)
                    else []
                )
            assert _has_comparison(whereclause, "signal_id", operators.eq, self.signal.id)
            assert self.reason_status == "released"
            return Result()
        if "securities" in text:
            assert whereclause is not None
            assert _has_comparison(whereclause, "code", operators.eq, "SYN001.SH")
            return Result()
        raise AssertionError(f"unexpected recheck statement: {statement!s}")


def test_recheck_keeps_reason_until_last_same_target_restriction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _require_restrictions()
    _require_recheck()
    clock = iter((NOW, NOW + dt.timedelta(hours=1)))
    monkeypatch.setattr(restrictions, "_now", lambda: next(clock))
    first = row(
        identifier=uuid.UUID("00000000-0000-4000-8000-000000000201"),
        until=NOW + dt.timedelta(hours=2),
    )
    second = row(
        identifier=uuid.UUID("00000000-0000-4000-8000-000000000202"),
        until=NOW + dt.timedelta(hours=2),
    )
    signal_id = uuid.UUID("00000000-0000-4000-8000-000000000301")
    reason_id = uuid.UUID("00000000-0000-4000-8000-000000000401")
    candidate = SimpleNamespace(
        id=signal_id,
        user_id=USER,
        security_code="SYN001.SH",
        instance_id=str(INSTANCE),
        strategy_version_id=None,
        created_at=NOW - dt.timedelta(minutes=30),
    )
    reason = SimpleNamespace(
        id=reason_id,
        signal_id=signal_id,
        user_id=USER,
        code="BLOCKLISTED",
        status="active",
    )
    signal = SimpleNamespace(
        id=signal_id,
        user_id=USER,
        state="blocked",
        created_at=candidate.created_at,
    )
    connection = RecheckConnection([first, second], candidate, reason, signal)
    first_result = restrictions.delete_restriction(first.id, auth(), Engine(connection))
    assert first_result.recheck.released_reason_ids == []
    assert first_result.recheck.remaining_reason_ids == [reason_id]
    second_result = restrictions.delete_restriction(second.id, auth(), Engine(connection))
    assert second_result.recheck.released_reason_ids == [reason_id]
    assert second_result.recheck.remaining_reason_ids == []


class CandidateContent:
    security_code = "SYN001.SH"
    proposed_action = "buy"
    t_leg = None
    score = None
    rule_refs = [SimpleNamespace(rule_id="synthetic-rule", role="entry", dimension="technical", threshold="x")]
    evidence = [{"id": "synthetic-evidence", "provider": "local", "epistemic_type": "fact", "data_as_of": NOW, "fetched_at": NOW}]
    risk_flags: list[Any] = []
    risk_details: list[Any] = []
    gaps: list[Any] = []
    valid_until = None
    feature_set_version = "synthetic"
    data_status = SimpleNamespace(value="fresh")
    data_as_of = NOW
    created_at = NOW
    snapshot_id = uuid.UUID("00000000-0000-4000-8000-000000000501")

    def model_dump(self, *, mode: str = "python") -> dict[str, Any]:
        return {
            "security_code": self.security_code,
            "proposed_action": self.proposed_action,
            "t_leg": None,
            "score": None,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": [{"rule_id": "synthetic-rule", "role": "entry", "dimension": "technical", "threshold": "x", "evidence_ids": []}],
            "evidence": self.evidence,
            "counter_evidence": [{"text": "synthetic counter", "expr": "x", "evidence_ids": ["synthetic-evidence"]}],
            "invalidation": [{"text": "synthetic invalidation", "expr": "x", "evidence_ids": ["synthetic-evidence"]}],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "feature_set_version": self.feature_set_version,
            "gaps": [],
            "created_at": self.created_at,
            "snapshot_id": self.snapshot_id,
            "data_status": self.data_status.value,
            "data_as_of": self.data_as_of,
        }


class SyntheticSecurity(SimpleNamespace):
    def __iter__(self):
        yield "code", self.code
        yield "type", self.type
        yield "board", self.board
        yield "risk_flag", self.risk_flag
        yield "listing_status", self.listing_status
        yield "delist_date", self.delist_date


class SnapshotQuery:
    def __init__(self, snapshot: Any) -> None:
        self.snapshot = snapshot

    def order_by(self, *_args: Any, **_kwargs: Any) -> SnapshotQuery:
        return self

    def limit(self, *_args: Any, **_kwargs: Any) -> SnapshotQuery:
        return self

    def one_or_none(self) -> Any:
        return self.snapshot


def _restriction_matches(expression: Any, item: Any) -> bool:
    return _matches(expression, item)


class CandidateConnection:
    def __init__(
        self,
        restrictions_: list[Any],
        content: CandidateContent,
        snapshot: Any,
        *,
        strategy_version_id: uuid.UUID,
        account_id: uuid.UUID,
    ) -> None:
        self.restriction_rows = restrictions_
        self.content = content
        self.snapshot = snapshot
        self.strategy_version_id = strategy_version_id
        self.account_id = account_id
        self.inserted_states: list[str] = []
        self.inserted_signal_id: uuid.UUID | None = None

    @contextmanager
    def begin_nested(self) -> Any:
        yield self

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        if isinstance(statement, SnapshotQuery):
            return Result([self.snapshot])
        text = str(statement)
        if isinstance(statement, Insert):
            params = statement.compile().params
            if "candidate_signals" in text:
                assert params["user_id"] == USER
                assert params["instance_id"] == INSTANCE
                assert params["strategy_version_id"] == self.strategy_version_id
                assert params["security_code"] == self.content.security_code
                assert params["snapshot_id"] == self.content.snapshot_id
                assert params["created_at"] == self.content.created_at
                assert params["proposed_action"] == self.content.proposed_action
                assert params["state"] in {"open", "blocked"}
                self.inserted_signal_id = params["id"]
                self.inserted_states.append(params["state"])
                return Result()
            if "candidate_signal_events" in text:
                assert self.inserted_signal_id is not None
                assert params["signal_id"] == self.inserted_signal_id
                assert params["from_state"] is None
                assert params["to_state"] == self.inserted_states[-1]
                assert params["cause"] == "executability_check"
                assert params["at"] == self.content.created_at
                return Result()
            if "non_executable_reasons" in text:
                assert self.inserted_signal_id is not None
                assert params["signal_id"] == self.inserted_signal_id
                assert params["user_id"] == USER
                assert params["code"] == "BLOCKLISTED"
                assert params["status"] == "active"
                assert params["snapshot_id"] == self.content.snapshot_id
                return Result()
            if "reason_status_events" in text:
                assert params["reason_id"] == uuid.uuid5(
                    self.inserted_signal_id, "BLOCKLISTED"
                )
                assert params["from_status"] is None
                assert params["to_status"] == "active"
                assert params["at"] == self.content.created_at
                return Result()
            raise AssertionError(f"unexpected candidate insert: {statement!s}")
        if "watchlist_items" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            assert _has_comparison(
                whereclause, "security_code", operators.eq, self.content.security_code
            )
            assert _has_comparison(whereclause, "removed_at", operators.is_, None)
            return Result()
        if "user_restrictions" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            assert _has_comparison(whereclause, "created_at", operators.le, self.content.created_at)
            assert _has_comparison(whereclause, "removed_at", operators.is_, None)
            assert _has_comparison(whereclause, "removed_at", operators.gt, self.content.created_at)
            assert _has_comparison(whereclause, "target_type", operators.eq, "security")
            assert _has_comparison(whereclause, "target_id", operators.eq, self.content.security_code)
            return Result(
                [
                    item
                    for item in self.restriction_rows
                    if _restriction_matches(whereclause, item)
                    and (item.until is None or self.content.created_at < item.until)
                ]
            )
        if "candidate_signals" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            if _has_comparison(whereclause, "cooldown_key", operators.eq):
                assert _has_comparison(whereclause, "instance_id", operators.eq, INSTANCE)
                return Result()
            assert _has_comparison(whereclause, "security_code", operators.eq, self.content.security_code)
            assert _has_comparison(whereclause, "instance_id", operators.ne, INSTANCE)
            assert _has_comparison(whereclause, "state", operators.in_op)
            assert _has_comparison(whereclause, "proposed_action", operators.in_op)
            return Result()
        if "non_executable_reasons" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq)
            return Result()
        if "data_snapshots" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq, self.content.snapshot_id)
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            return Result([self.snapshot] if _matches(whereclause, self.snapshot) else [])
        if "action_plans" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            assert _has_comparison(
                whereclause, "security_code", operators.eq, self.content.security_code
            )
            assert _has_comparison(whereclause, "status", operators.in_op)
            return Result()
        if "strategy_versions" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq, self.strategy_version_id)
            return Result(
                [
                    SimpleNamespace(
                        id=self.strategy_version_id,
                        strategy_id=STRATEGY,
                        config={
                            "rules": [
                                {
                                    "id": "synthetic-rule",
                                    "role": "entry",
                                    "dimension": "technical",
                                    "expr": "x",
                                }
                            ]
                        },
                        lifecycle="published",
                        card_version_id=None,
                    )
                ]
            )
        if "owner_user_id" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq, STRATEGY)
            return Result([USER])
        if "securities" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(
                whereclause, "code", operators.eq, self.content.security_code
            )
            return Result(
                [
                    SyntheticSecurity(
                        code=self.content.security_code,
                        type="stock",
                        board="main",
                        risk_flag=None,
                        listing_status="listed",
                        delist_date=None,
                    )
                ]
            )
        if "app.users" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq, USER)
            return Result(["approved"] if "status" in text else ["user"])
        if "accounts" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_comparison(whereclause, "id", operators.eq, self.account_id)
            assert _has_comparison(whereclause, "user_id", operators.eq, USER)
            assert _has_comparison(whereclause, "archived_at", operators.is_, None)
            return Result([SimpleNamespace(id=self.account_id)])
        if "pg_advisory_xact_lock" in text:
            return Result()
        raise AssertionError(f"unexpected candidate statement: {statement!s}")


@pytest.mark.parametrize(
    ("label", "restriction"),
    [
        ("active", row()),
        ("until", row(until=NOW + dt.timedelta(hours=1))),
        ("until_equal", row(until=NOW)),
        ("expired", row(until=NOW - dt.timedelta(seconds=1))),
        ("removed", row(removed_at=NOW - dt.timedelta(seconds=1))),
        ("future_created", row(created_at=NOW + dt.timedelta(seconds=1))),
        ("other_user", row(owner=OTHER)),
    ],
)
def test_write_candidate_restriction_point_in_time(label: str, restriction: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    _require_candidate_pit()
    content = CandidateContent()
    facts = SimpleNamespace(model_dump=lambda mode="python": {})
    instance = SimpleNamespace(
        derived_strategy_version_id=None,
        strategy_version_id=uuid.UUID("00000000-0000-4000-8000-000000000601"),
        scope="security",
        security_code="SYN001.SH",
        status="active",
        account_id=uuid.UUID("00000000-0000-4000-8000-000000000602"),
        horizon="swing",
    )
    snapshot = SimpleNamespace(
        id=content.snapshot_id,
        user_id=USER,
        licence_id=None,
        created_at=NOW - dt.timedelta(days=1),
        cash_available=Decimal("100000"),
        items={
            "signal_input": content.model_dump(mode="json"),
            "market_facts": facts.model_dump(mode="json"),
            "data_status_block": {"data_status": "fresh", "data_as_of": NOW.isoformat(), "gaps": []},
        },
    )
    connection = CandidateConnection(
        [restriction],
        content,
        snapshot,
        strategy_version_id=instance.strategy_version_id,
        account_id=instance.account_id,
    )
    monkeypatch.setattr(service, "owned", lambda *_args, **_kwargs: instance)
    monkeypatch.setattr(service, "normalize_universe", lambda *_args, **_kwargs: {"security_types": ["stock"], "boards": {"main": True}})
    monkeypatch.setattr(service, "screen_membership", lambda **_kwargs: None)
    monkeypatch.setattr(service, "lot_spec", lambda *_args, **_kwargs: SimpleNamespace(min_buy=1))
    monkeypatch.setattr(service, "calendar_state", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(service, "assess", lambda *_args, **_kwargs: [])
    from app.api.v1 import portfolio
    from app.strategy import runtime

    monkeypatch.setattr(runtime, "runnable", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(portfolio, "_account", lambda *_args, **_kwargs: SimpleNamespace(positions={}, cash=Decimal("100000")))
    monkeypatch.setattr(service, "live_snapshots", lambda *_args, **_kwargs: SnapshotQuery(snapshot))
    monkeypatch.setattr(service, "snapshot_items", lambda *_args, **_kwargs: snapshot.items)
    result = service.write_candidate(
        connection,
        user_id=USER,
        instance_id=INSTANCE,
        content=content,
        facts=facts,
        market_rules=SimpleNamespace(segment_for=lambda _day: SimpleNamespace()),
    )
    expected_blocked = label in {"active", "until"}
    assert (result["diagnostic"] == "blocked") is expected_blocked
    if expected_blocked:
        assert connection.inserted_states == ["blocked"]
    else:
        assert result["diagnostic"] == "open"

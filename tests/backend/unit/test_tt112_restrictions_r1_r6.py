"""T-T112 API-level restriction contracts using synthetic offline fixtures only."""

from __future__ import annotations

import datetime as dt
import socket
import uuid
from contextlib import contextmanager
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.sql import operators
from sqlalchemy.sql.dml import Insert, Update
from sqlalchemy.sql.elements import (
    BinaryExpression,
    BindParameter,
    BooleanClauseList,
    Grouping,
    Null,
)

try:
    from app.api.v1 import restrictions
    from app.common.errors import AppError, ErrorCode
    from app.common.pagination import PageParams
    from app.db.tables.signals import user_restrictions
    from app.schemas.enums import RestrictionKind
    from app.signals import service
except (ImportError, ModuleNotFoundError):  # pragma: no cover - compatibility with pre-merge trees
    restrictions = None  # type: ignore[assignment]
    service = None  # type: ignore[assignment]
    user_restrictions = None  # type: ignore[assignment]
    RestrictionKind = SimpleNamespace(  # type: ignore[assignment,misc]
        BLOCKLIST="blocklist", COOLING_OFF="cooling_off", MUTE="mute"
    )
    AppError = Exception  # type: ignore[assignment,misc]
    ErrorCode = SimpleNamespace(NOT_FOUND="NOT_FOUND", VALIDATION_ERROR="VALIDATION_ERROR")
    PageParams = SimpleNamespace  # type: ignore[assignment,misc]
    pytestmark = pytest.mark.xfail(
        reason="主线未合入 #330+#341+#348", strict=False
    )


USER = uuid.UUID("00000000-0000-4000-8000-000000000001")
OTHER = uuid.UUID("00000000-0000-4000-8000-000000000002")
STRATEGY = uuid.UUID("00000000-0000-4000-8000-000000000101")
INSTANCE = uuid.UUID("00000000-0000-4000-8000-000000000102")
NOW = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract suite is offline and must fail on any socket attempt."""

    def fail_socket(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("T-T112 tests must not use the network")

    monkeypatch.setattr(socket, "socket", fail_socket)
    monkeypatch.setattr(socket, "create_connection", fail_socket)


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


class Redis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def set(self, key: str, value: str, *, nx: bool = False, ex: int) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def delete(self, key: str) -> None:
        self.values.pop(key, None)


class Settings:
    app_env = "test"
    app_master_key = None
    cursor_ttl_s = 86_400
    page_limit_max = 200


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


def target_id(target_type: str) -> str:
    return {
        "security": "SYN001.SH",
        "strategy": str(STRATEGY),
        "instance": str(INSTANCE),
    }[target_type]


def body(
    *,
    kind: RestrictionKind = RestrictionKind.BLOCKLIST,
    target_type: str = "security",
    target: str | None = None,
    until: dt.datetime | None = None,
) -> Any:
    return restrictions.RestrictionCreate(
        kind=kind,
        target_type=target_type,
        target_id=target or target_id(target_type),
        until=until,
        reason="synthetic fixture",
    )


class RestrictionConnection:
    def __init__(
        self,
        rows: list[Any] | None = None,
        *,
        target_exists: bool = True,
        foreign_target: bool = False,
        names: bool = True,
    ) -> None:
        self.rows = rows or []
        self.target_exists = target_exists
        self.foreign_target = foreign_target
        self.names = names
        self.query_user = USER
        self.statements: list[Any] = []
        self.inserted = 0

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Insert):
            params = statement.compile().params
            if "user_id" in params and "target_id" in params:
                created = row(
                    owner=params["user_id"],
                    identifier=params["id"],
                    kind=params["kind"],
                    target_type=params["target_type"],
                    target_id=params["target_id"],
                    until=params.get("until"),
                    created_at=NOW,
                )
                self.rows.append(created)
                self.inserted += 1
            return Result()
        if isinstance(statement, Update):
            params = statement.compile().params
            identifier = params.get("id") or params.get("id_1")
            for item in self.rows:
                if item.id == identifier:
                    item.removed_at = params["removed_at"]
            return Result()
        text = str(statement)
        if "user_restrictions" in text:
            params = statement.compile().params
            if " != " in text:
                return Result([item for item in self.rows if item.user_id == self.query_user])
            identifier = params.get("id_1") or params.get("id")
            if identifier is not None:
                return Result([item for item in self.rows if item.id == identifier and item.user_id == self.query_user])
            return Result([item for item in self.rows if item.user_id == self.query_user and item.removed_at is None])
        if any(name in text for name in ("securities", "strategies", "strategy_instances")):
            if self.foreign_target:
                assert "owner_user_id" in text or "strategy_instances.user_id" in text
                return Result()
            return Result([SimpleNamespace(name="Synthetic target")] if self.target_exists and self.names else [])
        if "pg_advisory_xact_lock" in text:
            return Result()
        return Result()


class RestrictionEngine:
    def __init__(self, connection: RestrictionConnection) -> None:
        self.connection = connection

    @contextmanager
    def connect(self) -> Any:
        yield self.connection

    @contextmanager
    def begin(self) -> Any:
        yield self.connection


def test_owner_can_create_each_target_and_list_is_private(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    created: list[Any] = []
    for kind_target in ("security", "strategy", "instance"):
        connection = RestrictionConnection()
        result = restrictions.create_restriction(
            body(target_type=kind_target), auth(), RestrictionEngine(connection), None
        )
        assert result.target_type == kind_target
        assert result.target_id == target_id(kind_target)
        created.append(connection.rows[-1])

    expired = row(until=NOW - dt.timedelta(seconds=1))
    removed = row(removed_at=NOW - dt.timedelta(seconds=1))
    foreign = row(owner=OTHER)
    connection = RestrictionConnection(created + [expired, removed, foreign])
    listed = restrictions.list_restrictions(
        auth(), RestrictionEngine(connection), Settings(), PageParams(50, None)
    )
    ids = {item["id"] for item in listed.items}
    assert ids == {item.id for item in created} | {expired.id}
    assert removed.id not in ids
    assert foreign.id not in ids
    assert next(item for item in listed.items if item["id"] == expired.id)["status"] == "expired"


@pytest.mark.parametrize("target_type", ["security", "strategy", "instance"])
def test_unknown_and_foreign_targets_are_indistinguishable_404(target_type: str) -> None:
    cases = (
        (target_id(target_type), target_type != "security"),
        ("SYN999.SH" if target_type == "security" else str(uuid.uuid4()), False),
    )
    for target, foreign_target in cases:
        known_security = target_type == "security" and target == target_id(target_type)
        connection = RestrictionConnection(
            target_exists=foreign_target or known_security,
            foreign_target=foreign_target,
        )
        if known_security:
            result = restrictions.create_restriction(
                body(target_type=target_type, target=target),
                auth(),
                RestrictionEngine(connection),
                None,
            )
            assert result.target_id == target
            continue
        with pytest.raises(AppError) as caught:
            restrictions.create_restriction(
                body(target_type=target_type, target=target),
                auth(),
                RestrictionEngine(connection),
                None,
            )
        assert caught.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    ("until", "issue"),
    [
        (None, "required_for_kind"),
        (NOW - dt.timedelta(seconds=1), "must_be_future"),
        (dt.datetime(2026, 11, 21, 13), None),
        (NOW + dt.timedelta(hours=1), None),
    ],
)
def test_cooling_off_until_validation_and_future_creation(
    monkeypatch: pytest.MonkeyPatch, until: dt.datetime | None, issue: str | None
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    request = body(kind=RestrictionKind.COOLING_OFF, until=until)
    if until is not None and until.tzinfo is None:
        with pytest.raises(AppError) as caught:
            restrictions.create_restriction(
                request, auth(), RestrictionEngine(RestrictionConnection()), None
            )
    elif issue is not None:
        with pytest.raises(AppError) as caught:
            restrictions.create_restriction(
                request, auth(), RestrictionEngine(RestrictionConnection()), None
            )
    else:
        result = restrictions.create_restriction(
            request, auth(), RestrictionEngine(RestrictionConnection()), None
        )
        assert result.until == until
        return
    assert caught.value.code == ErrorCode.VALIDATION_ERROR
    fields = caught.value.details["fields"]
    assert any(item["field"] == "until" for item in fields)
    if issue is not None:
        assert any(item["issue"] == issue for item in fields)


def test_invalid_kind_and_target_type_are_validation_errors() -> None:
    for field, value in (("kind", "invented"), ("target_type", "portfolio")):
        payload = {
            "kind": "blocklist",
            "target_type": "security",
            "target_id": "SYN001.SH",
            field: value,
        }
        with pytest.raises(ValidationError) as caught:
            restrictions.RestrictionCreate.model_validate(payload)
        assert any(error["loc"] == (field,) for error in caught.value.errors())


def test_idempotency_is_per_user_and_does_not_insert_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    request = body()
    redis = Redis()
    connection = RestrictionConnection()
    engine = RestrictionEngine(connection)
    first = restrictions.create_restriction(request, auth(), engine, redis, "synthetic-key")
    replay = restrictions.create_restriction(request, auth(), engine, redis, "synthetic-key")
    assert replay == first
    assert connection.inserted == 1
    changed = request.model_copy(update={"reason": "different synthetic reason"})
    with pytest.raises(AppError) as conflict:
        restrictions.create_restriction(changed, auth(), engine, redis, "synthetic-key")
    assert conflict.value.code == ErrorCode.IDEMPOTENCY_CONFLICT

    other_connection = RestrictionConnection()
    other_connection.query_user = OTHER
    other = restrictions.create_restriction(
        request, auth(OTHER), RestrictionEngine(other_connection), redis, "synthetic-key"
    )
    assert other.id != first.id


def test_blocklist_and_mute_null_or_expired_until_keep_status_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    active = row(kind="blocklist", until=None)
    active_mute = row(kind="mute", until=None)
    expired = row(kind="mute", until=NOW - dt.timedelta(minutes=1))
    removed_expired = row(
        kind="mute",
        until=NOW - dt.timedelta(minutes=1),
        removed_at=NOW - dt.timedelta(seconds=1),
    )
    assert restrictions._status(removed_expired, NOW) == "removed"
    connection = RestrictionConnection([active, active_mute, expired])
    listed = restrictions.list_restrictions(
        auth(), RestrictionEngine(connection), Settings(), PageParams(50, None)
    )
    statuses = {item["id"]: item["status"] for item in listed.items}
    assert statuses[active.id] == "active"
    assert statuses[active_mute.id] == "active"
    assert statuses[expired.id] == "expired"
    assert {item["id"] for item in listed.items} == {active.id, active_mute.id, expired.id}


@pytest.mark.parametrize("kind", [RestrictionKind.BLOCKLIST, RestrictionKind.MUTE])
def test_blocklist_and_mute_past_until_create_projects_expired(
    monkeypatch: pytest.MonkeyPatch, kind: RestrictionKind
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    connection = RestrictionConnection()
    result = restrictions.create_restriction(
        body(kind=kind, until=NOW - dt.timedelta(minutes=1)),
        auth(),
        RestrictionEngine(connection),
        None,
    )
    assert result.until == NOW - dt.timedelta(minutes=1)
    assert result.status == "expired"


def test_delete_repeat_uses_original_removed_at_and_no_recheck_on_repeat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    item = row()
    foreign = row(owner=OTHER, identifier=uuid.UUID("00000000-0000-4000-8000-000000000777"))
    connection = RestrictionConnection([item, foreign])
    calls: list[Any] = []
    real_recheck = restrictions.signal_service.recheck_restriction

    def spy(*args: Any, **kwargs: Any) -> Any:
        calls.append(1)
        return real_recheck(*args, **kwargs)

    monkeypatch.setattr(restrictions.signal_service, "recheck_restriction", spy)
    first = restrictions.delete_restriction(item.id, auth(), RestrictionEngine(connection))
    second = restrictions.delete_restriction(item.id, auth(), RestrictionEngine(connection))
    assert first.status == second.status == "removed"
    assert first.removed_at == second.removed_at
    assert second.recheck.released_reason_ids == []
    assert second.recheck.remaining_reason_ids == []
    assert len(calls) == 1
    for identifier in (uuid.uuid4(), foreign.id):
        with pytest.raises(AppError) as caught:
            restrictions.delete_restriction(identifier, auth(), RestrictionEngine(connection))
        assert caught.value.code == ErrorCode.NOT_FOUND


class RecheckConnection(RestrictionConnection):
    def __init__(self, rows: list[Any], candidate: Any, reason: Any, signal: Any) -> None:
        super().__init__(rows)
        self.candidate = candidate
        self.reason = reason
        self.signal = signal
        self.reason_status: str = "active"

    def execute(self, statement: Any, *_args: Any, **kwargs: Any) -> Result:
        if isinstance(statement, Update):
            params = statement.compile().params
            if "status" in params:
                self.reason_status = params["status"]
            return super().execute(statement, *_args, **kwargs)
        text = str(statement)
        if "candidate_signals" in text:
            if "created_at <" in text:
                return Result([self.candidate])
            return Result([self.signal])
        if "non_executable_reasons" in text:
            return Result([self.reason] if self.reason_status == "active" else [])
        if "user_restrictions" in text:
            params = statement.compile().params
            if " != " in text:
                current = params.get("id_1") or params.get("id")
                return Result([item for item in self.rows if item.user_id == USER and item.id != current])
            identifier = params.get("id_1") or params.get("id")
            if identifier is not None:
                return Result([item for item in self.rows if item.id == identifier and item.user_id == USER])
            return Result([item for item in self.rows if item.user_id == USER])
        if "SELECT" in text and "candidate_signals" not in text and "user_restrictions" not in text:
            if "strategy_versions" in text:
                return Result()
            if "securities" in text:
                return Result([SimpleNamespace(name="Synthetic target")])
            if "signals" in text:
                return Result([self.signal])
        return super().execute(statement, *_args, **kwargs)


def test_recheck_keeps_reason_until_last_same_target_restriction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clock = iter((NOW, NOW + dt.timedelta(hours=1)))
    monkeypatch.setattr(restrictions, "_now", lambda: next(clock))
    first = row(identifier=uuid.UUID("00000000-0000-4000-8000-000000000201"))
    second = row(identifier=uuid.UUID("00000000-0000-4000-8000-000000000202"))
    signal_id = uuid.UUID("00000000-0000-4000-8000-000000000301")
    reason_id = uuid.UUID("00000000-0000-4000-8000-000000000401")
    candidate = SimpleNamespace(
        id=signal_id,
        user_id=USER,
        security_code="SYN001.SH",
        instance_id=str(INSTANCE),
        strategy_version_id=None,
        created_at=NOW + dt.timedelta(minutes=30),
    )
    reason = SimpleNamespace(id=reason_id, signal_id=signal_id)
    signal = SimpleNamespace(
        id=signal_id,
        user_id=USER,
        state="blocked",
        created_at=candidate.created_at,
    )
    connection = RecheckConnection([first, second], candidate, reason, signal)
    first_result = restrictions.delete_restriction(first.id, auth(), RestrictionEngine(connection))
    assert first_result.recheck.released_reason_ids == []
    assert first_result.recheck.remaining_reason_ids == [reason_id]
    second_result = restrictions.delete_restriction(second.id, auth(), RestrictionEngine(connection))
    assert second_result.recheck.released_reason_ids == [reason_id]
    assert second_result.recheck.remaining_reason_ids == []


class CandidateContent:
    security_code = "SYN001.SH"
    proposed_action = "buy"
    t_leg = None
    score = None
    rule_refs = [SimpleNamespace(rule_id="synthetic-rule", role="entry", dimension="technical", threshold="x")]
    evidence = [
        {
            "id": "synthetic-evidence",
            "provider": "local",
            "epistemic_type": "fact",
            "data_as_of": NOW,
            "fetched_at": NOW,
        }
    ]
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


def _unwrap_grouping(expression: Any) -> Any:
    while isinstance(expression, Grouping):
        expression = expression.element
    return expression


def _literal(expression: Any) -> Any:
    if isinstance(expression, BindParameter):
        return expression.value
    if isinstance(expression, Null):
        return None
    raise AssertionError(f"unexpected restriction predicate value: {expression!r}")


def _column_value(expression: Any, item: Any) -> Any:
    assert getattr(expression, "table", None) is user_restrictions
    return getattr(item, expression.key)


def _restriction_predicate_matches(expression: Any, item: Any) -> bool:
    expression = _unwrap_grouping(expression)
    if isinstance(expression, BooleanClauseList):
        clauses = list(expression.clauses)
        if expression.operator is operators.and_:
            return all(_restriction_predicate_matches(clause, item) for clause in clauses)
        if expression.operator is operators.or_:
            return any(_restriction_predicate_matches(clause, item) for clause in clauses)
        raise AssertionError(f"unexpected boolean operator: {expression.operator!r}")
    if not isinstance(expression, BinaryExpression):
        raise AssertionError(f"unexpected restriction predicate: {expression!r}")
    left = _unwrap_grouping(expression.left)
    right = _unwrap_grouping(expression.right)
    left_value = _column_value(left, item)
    right_value = _literal(right)
    if expression.operator is operators.eq:
        return left_value == right_value
    if expression.operator is operators.le:
        return left_value <= right_value
    if expression.operator is operators.gt:
        return left_value > right_value
    if expression.operator is operators.is_:
        return left_value is right_value
    raise AssertionError(f"unexpected restriction comparison: {expression.operator!r}")


def _restriction_expressions(expression: Any) -> list[Any]:
    expression = _unwrap_grouping(expression)
    expressions = [expression]
    for child in expression.get_children():
        expressions.extend(_restriction_expressions(child))
    return expressions


def _has_restriction_comparison(
    expression: Any, column: str, operator: Any, expected: Any
) -> bool:
    for candidate in _restriction_expressions(expression):
        if not isinstance(candidate, BinaryExpression):
            continue
        left = _unwrap_grouping(candidate.left)
        if getattr(left, "table", None) is not user_restrictions:
            continue
        if left.key != column or candidate.operator is not operator:
            continue
        if isinstance(candidate.right, Null):
            value = None
        else:
            value = _literal(candidate.right)
        if value == expected:
            return True
    return False


def _has_removed_window(expression: Any, candidate_created_at: dt.datetime) -> bool:
    expression = _unwrap_grouping(expression)
    if isinstance(expression, BooleanClauseList) and expression.operator is operators.or_:
        has_removed_null = _has_restriction_comparison(
            expression, "removed_at", operators.is_, None
        )
        has_removed_after = _has_restriction_comparison(
            expression, "removed_at", operators.gt, candidate_created_at
        )
        if has_removed_null and has_removed_after:
            return True
    return any(
        _has_removed_window(child, candidate_created_at)
        for child in expression.get_children()
    )


def _has_target_pair(expression: Any, target_type: str, target_id: str) -> bool:
    expression = _unwrap_grouping(expression)
    if isinstance(expression, BooleanClauseList):
        if expression.operator is operators.and_:
            return _has_restriction_comparison(
                expression, "target_type", operators.eq, target_type
            ) and _has_restriction_comparison(
                expression, "target_id", operators.eq, target_id
            )
        if expression.operator is operators.or_:
            return any(
                _has_target_pair(child, target_type, target_id)
                for child in expression.clauses
            )
    return False


class CandidateConnection(RestrictionConnection):
    def __init__(self, restrictions_: list[Any], content: CandidateContent) -> None:
        super().__init__()
        self.restriction_rows = restrictions_
        self.content = content
        self.inserted_states: list[str] = []
        self.snapshot: Any = None

    @contextmanager
    def begin_nested(self) -> Any:
        yield self

    def execute(self, statement: Any, *_args: Any, **kwargs: Any) -> Result:
        if isinstance(statement, Insert):
            params = statement.compile().params
            if "state" in params:
                self.inserted_states.append(params["state"])
            return Result()
        text = str(statement)
        if "user_restrictions" in text:
            whereclause = getattr(statement, "whereclause", None)
            assert whereclause is not None
            assert _has_restriction_comparison(
                whereclause, "user_id", operators.eq, USER
            )
            assert _has_restriction_comparison(
                whereclause, "created_at", operators.le, self.content.created_at
            )
            assert _has_removed_window(whereclause, self.content.created_at)
            assert _has_target_pair(whereclause, "security", self.content.security_code)
            return Result(
                [
                    item
                    for item in self.restriction_rows
                    if _restriction_predicate_matches(whereclause, item)
                ]
            )
        if "candidate_signals" in text:
            return Result()
        if "data_snapshots" in text:
            return Result([self.snapshot or SimpleNamespace(licence_id=None, created_at=NOW - dt.timedelta(days=1), items={})])
        if "strategy_versions" in text:
            return Result([SimpleNamespace(id=uuid.uuid4(), strategy_id=STRATEGY, config={"rules": [{"id": "synthetic-rule", "role": "entry", "dimension": "technical", "expr": "x"}]}, lifecycle="published", card_version_id=None)])
        if "owner_user_id" in text:
            return Result([USER])
        if "securities" in text:
            if "FOR UPDATE" in text:
                return Result([{"type": "stock", "listing_status": "listed", "delist_date": None}])
            return Result([SimpleNamespace(type="stock", board="main", risk_flag=None)])
        if "app.users" in text:
            return Result(["approved"] if "status" in text else ["user"])
        if "accounts" in text:
            return Result([SimpleNamespace(id=uuid.uuid4())])
        return super().execute(statement, *_args, **kwargs)


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
    version = SimpleNamespace(
        id=instance.strategy_version_id,
        strategy_id=STRATEGY,
        config={"rules": [{"id": "synthetic-rule", "role": "entry", "dimension": "technical", "expr": "x"}]},
        lifecycle="published",
        card_version_id=None,
    )
    account = SimpleNamespace(id=instance.account_id)
    snapshot = SimpleNamespace(
        licence_id=None,
        created_at=NOW - dt.timedelta(days=1),
        items={
            "signal_input": content.model_dump(mode="json"),
            "market_facts": facts.model_dump(mode="json"),
            "data_status_block": {"data_status": "fresh", "data_as_of": NOW.isoformat(), "gaps": []},
        },
    )
    connection = CandidateConnection([restriction], content)
    connection.snapshot = snapshot
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
    monkeypatch.setattr(service, "live_snapshots", lambda *_args, **_kwargs: SimpleNamespace(order_by=lambda *_a, **_k: SimpleNamespace(limit=lambda *_a, **_k: object())))
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

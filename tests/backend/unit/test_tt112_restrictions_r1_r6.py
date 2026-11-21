"""T-T112 API-level restriction contracts using synthetic offline fixtures only."""

from __future__ import annotations

import datetime as dt
import importlib.util
import socket
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.sql.dml import Insert, Update

from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams
from app.schemas.enums import RestrictionKind

_RESTRICTIONS_MODULE = "app.api.v1.restrictions"
if importlib.util.find_spec(_RESTRICTIONS_MODULE) is not None:
    from app.api.v1 import restrictions
else:
    restrictions = None  # type: ignore[assignment]


def _require_restrictions() -> None:
    if restrictions is None:
        pytest.xfail("app.api.v1.restrictions endpoint is absent on this tree")


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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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
    _require_restrictions()
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

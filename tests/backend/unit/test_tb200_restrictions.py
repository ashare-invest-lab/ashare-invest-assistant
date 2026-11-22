"""T-B200 restrictions API checks using synthetic rows and no external services."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import restrictions
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams
from app.schemas.enums import RestrictionKind
from app.signals import service
from sqlalchemy.sql.dml import Delete, Insert, Update
from sqlalchemy.sql.selectable import Select

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
NOW = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


def row(
    *,
    owner: uuid.UUID = USER_ID,
    identifier: uuid.UUID | None = None,
    kind: str = "cooling_off",
    until: dt.datetime | None = None,
    removed_at: dt.datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier or uuid.uuid4(),
        user_id=owner,
        kind=kind,
        target_type="security",
        target_id="600000.SH",
        until=until,
        reason="synthetic test",
        created_at=NOW,
        removed_at=removed_at,
    )


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        assert len(self.rows) == 1
        return self.rows[0]

    def one_or_none(self) -> Any | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.names = [SimpleNamespace(name="Synthetic target")]
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Update):
            self.rows[0].removed_at = statement.compile().params["removed_at"]
            return Result([])
        if isinstance(statement, (Insert, Delete)):
            return Result([])
        statement_text = str(statement)
        if (
            "candidate_signals" in statement_text
            or "non_executable_reasons" in statement_text
        ):
            return Result([])
        if "user_restrictions" in statement_text:
            return Result(self.rows)
        return Result([self.names.pop(0)]) if self.names else Result([])


class Engine:
    def __init__(self, rows: list[Any]) -> None:
        self.connection = Connection(rows)

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def begin(self):
        yield self.connection


class RecheckConnection(Connection):
    def __init__(
        self,
        restriction: Any,
        candidates: list[Any],
        remaining_restrictions: list[Any],
        signal: Any,
    ) -> None:
        super().__init__([restriction])
        reason_rows = [
            SimpleNamespace(id=item.reason_id, signal_id=item.signal_id)
            for item in candidates
        ]
        signal_rows = [
            SimpleNamespace(
                id=item.signal_row_id,
                user_id=USER_ID,
                instance_id=item.instance_id,
                security_code=item.security_code,
                strategy_version_id=item.strategy_version_id,
                created_at=restriction.created_at + dt.timedelta(minutes=1),
            )
            for item in candidates
            if item.signal_row_id is not None
        ]
        self.select_results = [
            [restriction],
            signal_rows,
            reason_rows,
            remaining_restrictions,
            [signal],
            [],
            [SimpleNamespace(name="Synthetic target")],
        ]
        self.reason_updates: list[dict[str, Any]] = []
        self.reason_events: list[dict[str, Any]] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Update):
            params = statement.compile().params
            if "removed_at" in params:
                self.rows[0].removed_at = params["removed_at"]
            elif params.get("status") == "released":
                self.reason_updates.append(params)
            elif params.get("state") == "released":
                self.signal_state = "released"
            return Result([])
        if isinstance(statement, Insert):
            params = statement.compile().params
            if params.get("to_status") == "released":
                self.reason_events.append(params)
            return Result([])
        if isinstance(statement, Select):
            return Result(self.select_results.pop(0))
        return Result([])


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


def auth(user_id: uuid.UUID = USER_ID) -> SimpleNamespace:
    return SimpleNamespace(user_id=user_id)


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        app_master_key=None,
        cursor_ttl_s=86_400,
        page_limit_max=200,
    )


def test_get_lists_expired_rows_and_uses_cursor_shape() -> None:
    expired = row(until=NOW - dt.timedelta(seconds=1))
    engine = Engine([expired])

    result = restrictions.list_restrictions(
        auth(),
        engine,
        settings(),
        PageParams(limit=50, cursor=None),
    )

    assert [item["id"] for item in result.items] == [expired.id]
    assert result.items[0]["until"] == "2026-11-21T19:59:59+08:00"
    assert result.next_cursor is None
    statement = str(engine.connection.statements[0])
    assert "removed_at" in statement
    assert "user_id" in statement


def test_post_creates_only_the_authenticated_owner_record() -> None:
    created = row(kind="blocklist")
    engine = Engine([created])
    body = restrictions.RestrictionCreate(
        kind=RestrictionKind.BLOCKLIST,
        target_type="security",
        target_id="600000.SH",
        until=None,
        reason="synthetic",
    )

    result = restrictions.create_restriction(body, auth(), engine, None)

    assert result.id == created.id
    assert result.kind == RestrictionKind.BLOCKLIST
    insert_statement = next(
        statement
        for statement in engine.connection.statements
        if isinstance(statement, Insert)
    )
    assert isinstance(insert_statement, Insert)
    assert insert_statement.compile().params["user_id"] == USER_ID


def test_post_idempotency_replays_conflicts_and_isolates_users() -> None:
    body = restrictions.RestrictionCreate(
        kind=RestrictionKind.BLOCKLIST,
        target_type="security",
        target_id="600000.SH",
        until=None,
        reason="synthetic",
    )
    rds = Redis()
    first_engine = Engine([row(kind="blocklist")])
    first = restrictions.create_restriction(body, auth(), first_engine, rds, "same-key")
    replay = restrictions.create_restriction(
        body, auth(), first_engine, rds, "same-key"
    )
    assert replay == first
    assert (
        sum(isinstance(item, Insert) for item in first_engine.connection.statements)
        == 1
    )

    changed = body.model_copy(update={"reason": "different"})
    with pytest.raises(AppError) as conflict:
        restrictions.create_restriction(changed, auth(), first_engine, rds, "same-key")
    assert conflict.value.code == ErrorCode.IDEMPOTENCY_CONFLICT

    other_user = uuid.UUID("00000000-0000-4000-8000-000000000002")
    other_engine = Engine([row(owner=other_user, kind="blocklist")])
    other = restrictions.create_restriction(
        body, auth(other_user), other_engine, rds, "same-key"
    )
    assert other.id != first.id


def test_delete_soft_deletes_and_repeat_or_foreign_is_not_found() -> None:
    identifier = uuid.uuid4()
    owned = row(identifier=identifier)
    engine = Engine([owned])

    result = restrictions.delete_restriction(identifier, auth(), engine)

    assert result.id == identifier
    assert result.removed_at.tzinfo is not None
    assert result.recheck.released_reason_ids == []
    assert owned.removed_at == result.removed_at
    repeated = restrictions.delete_restriction(identifier, auth(), engine)
    assert repeated.id == identifier
    assert repeated.removed_at == result.removed_at
    assert repeated.status == "removed"
    assert repeated.recheck.released_reason_ids == []
    assert repeated.recheck.remaining_reason_ids == []
    assert repeated.gaps == result.gaps

    foreign_engine = Engine([])
    with pytest.raises(AppError) as foreign:
        restrictions.delete_restriction(identifier, auth(), foreign_engine)
    assert foreign.value.code == ErrorCode.NOT_FOUND


def test_delete_rechecks_only_associated_reason_and_releases_signal() -> None:
    restriction = row(kind="blocklist")
    restriction.created_at = NOW - dt.timedelta(hours=1)
    reason_id = uuid.uuid4()
    unrelated_id = uuid.uuid4()
    signal = SimpleNamespace(
        id=uuid.uuid4(), user_id=USER_ID, state="blocked", created_at=NOW
    )
    candidates = [
        SimpleNamespace(
            reason_id=reason_id,
            signal_id=signal.id,
            signal_row_id=signal.id,
            instance_id=uuid.uuid4(),
            security_code=restriction.target_id,
            strategy_version_id=None,
        ),
        SimpleNamespace(
            reason_id=unrelated_id,
            signal_id=unrelated_id,
            signal_row_id=unrelated_id,
            instance_id=uuid.uuid4(),
            security_code="000001.SZ",
            strategy_version_id=None,
        ),
    ]
    connection = RecheckConnection(restriction, candidates, [], signal)
    engine = Engine([])
    engine.connection = connection

    result = restrictions.delete_restriction(restriction.id, auth(), engine)

    assert result.recheck.released_reason_ids == [reason_id]
    assert result.recheck.remaining_reason_ids == []
    assert result.gaps == []
    assert connection.reason_updates[0]["released_by"] == "system"
    assert connection.reason_events[0]["to_status"] == "released"
    assert connection.signal_state == "released"


def test_delete_keeps_reason_when_another_valid_restriction_remains() -> None:
    restriction = row(kind="blocklist")
    restriction.created_at = NOW - dt.timedelta(hours=1)
    other = row(kind="blocklist")
    other.created_at = restriction.created_at - dt.timedelta(minutes=1)
    other.target_id = restriction.target_id
    reason_id = uuid.uuid4()
    signal = SimpleNamespace(
        id=uuid.uuid4(), user_id=USER_ID, state="blocked", created_at=NOW
    )
    candidate = SimpleNamespace(
        reason_id=reason_id,
        signal_id=signal.id,
        signal_row_id=signal.id,
        instance_id=uuid.uuid4(),
        security_code=restriction.target_id,
        strategy_version_id=None,
    )
    connection = RecheckConnection(restriction, [candidate], [other], signal)
    engine = Engine([])
    engine.connection = connection

    result = restrictions.delete_restriction(restriction.id, auth(), engine)

    assert result.recheck.released_reason_ids == []
    assert result.recheck.remaining_reason_ids == [reason_id]
    assert connection.reason_updates == []
    assert not hasattr(connection, "signal_state")


def test_write_candidate_restriction_read_filters_removed_and_matches_type() -> None:
    source = inspect.getsource(service.write_candidate)
    restriction_read = source[source.index("select(user_restrictions)") :]
    assert "user_restrictions.c.removed_at.is_(None)" in restriction_read
    assert 'user_restrictions.c.target_type == "security"' in restriction_read
    assert 'user_restrictions.c.target_type == "instance"' in restriction_read
    assert 'user_restrictions.c.target_type == "strategy"' in restriction_read

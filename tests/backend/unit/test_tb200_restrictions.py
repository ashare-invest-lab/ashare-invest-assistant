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


class Connection:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Update):
            self.rows[0].removed_at = statement.compile().params["removed_at"]
            return Result([])
        if isinstance(statement, (Insert, Delete)):
            return Result([])
        return Result(self.rows)


class Engine:
    def __init__(self, rows: list[Any]) -> None:
        self.connection = Connection(rows)

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def begin(self):
        yield self.connection


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
    assert result.items[0]["until"] == expired.until
    assert result.next_cursor is None
    statement = str(engine.connection.statements[-1])
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

    result = restrictions.create_restriction(body, auth(), engine)

    assert result.id == created.id
    assert result.kind == RestrictionKind.BLOCKLIST
    insert_statement = engine.connection.statements[0]
    assert isinstance(insert_statement, Insert)
    assert insert_statement.compile().params["user_id"] == USER_ID


def test_delete_soft_deletes_and_repeat_or_foreign_is_not_found() -> None:
    identifier = uuid.uuid4()
    owned = row(identifier=identifier)
    engine = Engine([owned])

    result = restrictions.delete_restriction(identifier, auth(), engine)

    assert result.id == identifier
    assert result.removed_at.tzinfo is not None
    assert result.recheck.released_reason_ids == []
    assert owned.removed_at == result.removed_at
    with pytest.raises(AppError) as repeated:
        restrictions.delete_restriction(identifier, auth(), engine)
    assert repeated.value.code == ErrorCode.NOT_FOUND

    foreign_engine = Engine([])
    with pytest.raises(AppError) as foreign:
        restrictions.delete_restriction(identifier, auth(), foreign_engine)
    assert foreign.value.code == ErrorCode.NOT_FOUND


def test_write_candidate_restriction_read_filters_removed_and_matches_type() -> None:
    source = inspect.getsource(service.write_candidate)
    restriction_read = source[source.index("select(user_restrictions)") :]
    assert "user_restrictions.c.removed_at.is_(None)" in restriction_read
    assert 'user_restrictions.c.target_type == "security"' in restriction_read
    assert 'user_restrictions.c.target_type == "instance"' in restriction_read
    assert 'user_restrictions.c.target_type == "strategy"' in restriction_read

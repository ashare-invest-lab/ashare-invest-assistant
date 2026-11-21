"""T-B202 PIT and restriction-concurrency checks with synthetic rows only."""

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from typing import Any

from app.api.v1 import restrictions
from app.signals import service
from sqlalchemy.sql.elements import TextClause
from sqlalchemy.sql.selectable import Select

USER_ID = uuid.UUID("00000000-0000-4000-8000-000000000001")
BASE = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


def _effective_at(
    *,
    created_at: dt.datetime,
    removed_at: dt.datetime | None,
    until: dt.datetime | None,
    candidate_at: dt.datetime,
) -> bool:
    """Evaluate the persisted restriction interval for the PIT boundary table."""
    return (
        created_at <= candidate_at
        and (removed_at is None or removed_at > candidate_at)
        and (until is None or until > candidate_at)
    )


def test_pit_boundaries_keep_history_at_candidate_time() -> None:
    created_at = BASE
    assert not _effective_at(
        created_at=created_at,
        removed_at=None,
        until=None,
        candidate_at=BASE - dt.timedelta(seconds=1),
    )
    assert _effective_at(
        created_at=created_at,
        removed_at=BASE + dt.timedelta(hours=1),
        until=None,
        candidate_at=BASE + dt.timedelta(minutes=1),
    )
    assert not _effective_at(
        created_at=created_at,
        removed_at=BASE + dt.timedelta(minutes=1),
        until=None,
        candidate_at=BASE + dt.timedelta(minutes=1),
    )
    assert not _effective_at(
        created_at=created_at,
        removed_at=None,
        until=BASE + dt.timedelta(minutes=1),
        candidate_at=BASE + dt.timedelta(minutes=1),
    )

    source = inspect.getsource(service.write_candidate)
    assert "user_restrictions.c.created_at <= content.created_at" in source
    assert "user_restrictions.c.removed_at > content.created_at" in source
    assert "restriction.until <= content.created_at" in source


def test_delete_and_recheck_paths_use_row_locks() -> None:
    delete_source = inspect.getsource(restrictions.delete_restriction)
    assert ".with_for_update()" in delete_source
    lock_call = 'text("SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))")'
    assert lock_call in delete_source
    assert delete_source.index(lock_call) < delete_source.index(
        "select(user_restrictions)"
    )

    recheck_source = inspect.getsource(service.recheck_restriction)
    remaining_query = recheck_source[recheck_source.index("remaining_restrictions") :]
    assert ".with_for_update()" in remaining_query


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows


class _Connection:
    def __init__(self, scripted: list[list[Any]]) -> None:
        self.scripted = list(scripted)
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        self.statements.append(statement)
        if isinstance(statement, TextClause):
            assert (
                statement.text
                == "SELECT pg_advisory_xact_lock(hashtextextended(:owner,74))"
            )
            assert _args == ({"owner": str(USER_ID)},)
            return _Result([])
        assert isinstance(statement, Select)
        return _Result(self.scripted.pop(0))


def test_no_matching_candidate_leaves_other_reasons_untouched() -> None:
    restriction = SimpleNamespace(
        id=uuid.uuid4(),
        kind="blocklist",
        target_type="security",
        target_id="600000.SH",
        created_at=BASE - dt.timedelta(hours=1),
        until=None,
    )
    connection = _Connection([[]])

    released, remaining, gaps = service.recheck_restriction(
        connection,
        user_id=USER_ID,
        restriction=restriction,
        at=BASE,
    )

    assert released == []
    assert remaining == []
    assert gaps == []
    assert len(connection.statements) == 1
    assert connection.statements[0]._for_update_arg is not None

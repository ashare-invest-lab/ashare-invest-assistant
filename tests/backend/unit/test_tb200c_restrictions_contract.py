"""T-B200c restrictions contract checks with synthetic rows only."""

from __future__ import annotations

import datetime as dt
import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import restrictions
from app.common.errors import AppError, ErrorCode
from app.common.pagination import PageParams
from app.schemas.enums import RestrictionKind
from sqlalchemy.sql.dml import Insert, Update

USER = uuid.UUID("00000000-0000-4000-8000-000000000001")
NOW = dt.datetime(2026, 11, 21, 12, tzinfo=dt.UTC)


def restriction_row(**changes: Any) -> SimpleNamespace:
    values = {
        "id": uuid.UUID("00000000-0000-4000-8000-000000000101"),
        "user_id": USER,
        "kind": "blocklist",
        "target_type": "security",
        "target_id": "600000.SH",
        "until": None,
        "reason": "synthetic",
        "created_at": NOW - dt.timedelta(hours=1),
        "removed_at": None,
    }
    values.update(changes)
    return SimpleNamespace(**values)


class Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one(self) -> Any:
        return self.rows[0]


class Conn:
    def __init__(self, rows: list[Any], names: list[Any] | None = None) -> None:
        self.rows = rows
        self.names = list(names or [])
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        if isinstance(statement, Update):
            self.rows[0].removed_at = statement.compile().params["removed_at"]
            return Result([])
        if isinstance(statement, Insert):
            return Result([])
        text = str(statement)
        if "user_restrictions" in text:
            return Result(self.rows)
        if self.names:
            return Result([self.names.pop(0)])
        return Result([])


class Engine:
    def __init__(self, connection: Conn) -> None:
        self.connection = connection

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def begin(self):
        yield self.connection


def auth() -> SimpleNamespace:
    return SimpleNamespace(user_id=USER)


def settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test", app_master_key=None, cursor_ttl_s=86400, page_limit_max=200
    )


def body(
    *,
    kind: RestrictionKind = RestrictionKind.BLOCKLIST,
    target_type: restrictions.RestrictionTargetType = "security",
    target_id: str = "600000.SH",
    until: dt.datetime | None = None,
) -> restrictions.RestrictionCreate:
    return restrictions.RestrictionCreate(
        kind=kind,
        target_type=target_type,
        target_id=target_id,
        until=until,
        reason="synthetic",
    )


@pytest.mark.parametrize("target_type", ["security", "strategy", "instance"])
def test_target_existing_is_accepted(
    target_type: restrictions.RestrictionTargetType,
) -> None:
    target_id = "600000.SH" if target_type == "security" else str(uuid.uuid4())
    conn = Conn([], [SimpleNamespace(name="示例目标")])
    assert restrictions._validate_target(
        conn, body(target_type=target_type, target_id=target_id), USER
    )


@pytest.mark.parametrize("target_type", ["security", "strategy", "instance"])
def test_target_missing_or_foreign_is_not_found(
    target_type: restrictions.RestrictionTargetType,
) -> None:
    target_id = "missing" if target_type == "security" else str(uuid.uuid4())
    with pytest.raises(AppError) as exc:
        restrictions._validate_target(
            Conn([], []), body(target_type=target_type, target_id=target_id), USER
        )
    assert exc.value.code == ErrorCode.NOT_FOUND


@pytest.mark.parametrize(
    ("until", "valid"),
    [
        (None, False),
        (NOW - dt.timedelta(seconds=1), False),
        (NOW, False),
        (NOW + dt.timedelta(seconds=1), True),
    ],
)
def test_cooling_off_until_requires_aware_future(
    until: dt.datetime | None, valid: bool
) -> None:
    if valid:
        restrictions._validate_until(
            body(kind=RestrictionKind.COOLING_OFF, until=until), NOW
        )
    else:
        with pytest.raises(AppError) as exc:
            restrictions._validate_until(
                body(kind=RestrictionKind.COOLING_OFF, until=until), NOW
            )
        assert exc.value.code == ErrorCode.VALIDATION_ERROR
        assert exc.value.details == {
            "fields": [
                {
                    "field": "until",
                    "issue": "required_for_kind" if until is None else "must_be_future",
                }
            ]
        }


def test_blocklist_past_and_null_until_derive_expired_and_active() -> None:
    assert restrictions._status(restriction_row(until=None), NOW) == "active"
    assert (
        restrictions._status(restriction_row(until=NOW - dt.timedelta(seconds=1)), NOW)
        == "expired"
    )
    assert restrictions._status(restriction_row(removed_at=NOW), NOW) == "removed"


def test_projection_has_name_gap_and_complete_fields() -> None:
    row = restriction_row(until=NOW - dt.timedelta(seconds=1))
    item, gaps = restrictions._project_row(Conn([], [None]), row, USER, NOW)
    assert set(item) == {
        "id",
        "kind",
        "target_type",
        "target_id",
        "name",
        "until",
        "reason",
        "created_at",
        "removed_at",
        "status",
    }
    assert item["status"] == "expired"
    assert gaps and gaps[0]["key"] == "no_source"


def test_post_returns_projection_and_top_level_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    row = restriction_row()
    engine = Engine(
        Conn(
            [row], [SimpleNamespace(name="示例证券"), SimpleNamespace(name="示例证券")]
        )
    )
    result = restrictions.create_restriction(body(), auth(), engine, None)  # type: ignore[arg-type]
    assert result.name == "示例证券"
    assert result.status == "active"
    assert result.removed_at is None
    assert result.gaps == []


def test_delete_returns_removed_projection_and_recheck(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    monkeypatch.setattr(
        restrictions.signal_service,
        "recheck_restriction",
        lambda *args, **kwargs: ([], [], []),
    )
    row = restriction_row()
    engine = Engine(Conn([row], [SimpleNamespace(name="示例证券")]))
    result = restrictions.delete_restriction(row.id, auth(), engine)  # type: ignore[arg-type]
    assert result.status == "removed"
    assert result.removed_at == NOW
    assert result.name == "示例证券"
    assert result.recheck.released_reason_ids == []
    assert result.gaps == []


def test_get_has_gaps_and_excludes_removed_in_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(restrictions, "_now", lambda: NOW)
    row = restriction_row(until=NOW - dt.timedelta(seconds=1))
    conn = Conn([row], [None])
    list_fn: Any = restrictions.list_restrictions
    result = list_fn(auth(), Engine(conn), settings(), PageParams(50, None))
    assert result.items[0]["status"] == "expired"
    assert result.gaps[0]["key"] == "no_source"
    assert "removed_at" in str(conn.statements[0])

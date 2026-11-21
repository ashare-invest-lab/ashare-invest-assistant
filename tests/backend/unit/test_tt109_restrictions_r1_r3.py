"""T-T109：/restrictions R1--R3 的离线契约测试。

路由尚未落地主线时，相关例子以严格动态 xfail 标记。夹具只保存虚构限制，
通过内存连接记录 SQLAlchemy 语句，不连接 PostgreSQL、Redis 或任何外部服务。
"""

from __future__ import annotations

import datetime as dt
import importlib
import importlib.util
import inspect
import socket
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, get_type_hints

import pytest
from app.common.errors import AppError
from app.common.pagination import PageParams
from fastapi import HTTPException
from pydantic import ValidationError

pytestmark = pytest.mark.unit

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
OTHER = uuid.UUID("22222222-2222-4222-8222-222222222222")
RID = uuid.UUID("33333333-3333-4333-8333-333333333333")
RID_2 = uuid.UUID("44444444-4444-4444-8444-444444444444")
UNKNOWN = uuid.UUID("66666666-6666-4666-8666-666666666666")
NOW = dt.datetime(2026, 11, 20, 12, tzinfo=dt.UTC)
FUTURE = NOW + dt.timedelta(days=30)
PAST = NOW - dt.timedelta(days=1)
TARGET_IDS = {
    "security": "SYN001.SH",
    "strategy": str(RID),
    "instance": str(RID_2),
}


@pytest.fixture(autouse=True)
def offline_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """阻断所有 socket 出口，保证本文件永远使用合成连接。"""

    def denied(*_args: Any, **_kwargs: Any) -> None:
        pytest.fail("T-T109：restrictions 测试禁止网络访问")

    for name in ("getaddrinfo", "create_connection"):
        monkeypatch.setattr(socket, name, denied)
    for name in ("connect", "connect_ex", "sendto"):
        monkeypatch.setattr(socket.socket, name, denied)


def _module() -> Any | None:
    if importlib.util.find_spec("app.api.v1.restrictions") is None:
        return None
    return importlib.import_module("app.api.v1.restrictions")


def _route(module: Any | None, path: str, method: str) -> Any | None:
    router = getattr(module, "router", None)
    for route in getattr(router, "routes", ()):
        if route.path == path and method.upper() in {m.upper() for m in route.methods or ()}:
            return route.endpoint
    return None


RESTRICTIONS = _module()
LIST_ENDPOINT = _route(RESTRICTIONS, "/restrictions", "GET")
CREATE_ENDPOINT = _route(RESTRICTIONS, "/restrictions", "POST")
DELETE_ENDPOINT = _route(RESTRICTIONS, "/restrictions/{restriction_id}", "DELETE")
ROUTES_READY = all((LIST_ENDPOINT, CREATE_ENDPOINT, DELETE_ENDPOINT))


@dataclass
class RestrictionRow:
    id: uuid.UUID
    user_id: uuid.UUID
    kind: str
    target_type: str
    target_id: str
    until: dt.datetime | None
    reason: str
    created_at: dt.datetime
    removed_at: dt.datetime | None = None


class Result:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None):
        self.rows = rows or []
        self.scalar = scalar

    def all(self) -> list[Any]:
        return list(self.rows)

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def one_or_none(self) -> Any | None:
        if len(self.rows) > 1:
            raise AssertionError("合成查询预期至多一行")
        return self.first()

    def one(self) -> Any:
        value = self.one_or_none()
        if value is None:
            raise AssertionError("合成查询没有返回行")
        return value

    def scalar_one_or_none(self) -> Any | None:
        return self.scalar if self.scalar is not None else (self.first() if self.rows else None)

    def scalar_one(self) -> Any:
        value = self.scalar_one_or_none()
        if value is None:
            raise AssertionError("合成查询没有标量")
        return value

    def scalars(self) -> Result:
        return self


def _params(statement: Any) -> dict[str, Any]:
    try:
        return dict(statement.compile().params)
    except (AttributeError, TypeError, ValueError):
        return {}


def _as_uuid(value: Any) -> uuid.UUID | None:
    try:
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


class MemoryConnection:
    """最小 SQLAlchemy Connection 替身，记录语句并维护虚构限制行。"""

    def __init__(
        self,
        rows: list[RestrictionRow],
        reasons: list[Any] | None = None,
        signals: list[Any] | None = None,
    ):
        self.rows = rows
        self.reasons = reasons or []
        self.signals = signals or []
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> Result:
        self.statements.append(statement)
        text = str(statement).lower()
        params = _params(statement)
        row_ids: set[uuid.UUID] = set()
        user_ids: set[uuid.UUID] = set()
        cursor_time: dt.datetime | None = None
        for key, value in params.items():
            key_l = str(key).lower()
            ident = _as_uuid(value)
            if ident is not None and "user_id" in key_l:
                user_ids.add(ident)
            elif ident is not None and "id" in key_l:
                row_ids.add(ident)
            if isinstance(value, dt.datetime):
                cursor_time = value
        if "non_executable_reasons" in text and getattr(statement, "is_select", False):
            rows = list(self.reasons)
            if user_ids:
                rows = [row for row in rows if row.user_id in user_ids]
            if row_ids:
                rows = [row for row in rows if row.id in row_ids]
            return Result(rows)
        if "candidate_signals" in text and getattr(statement, "is_select", False):
            rows = list(self.signals)
            if row_ids:
                rows = [row for row in rows if row.id in row_ids]
            if user_ids:
                rows = [row for row in rows if row.user_id in user_ids]
            return Result(rows)
        if "user_restrictions" in text and getattr(statement, "is_select", False):
            rows = list(self.rows)
            if user_ids:
                rows = [row for row in rows if row.user_id in user_ids]
            # 用 ".id =" 避免误匹配 user_id。
            sql_neq = any(token in text for token in (".id !=", ".id <>"))
            sql_eq = (".id =" in text) and not sql_neq
            if row_ids and sql_neq:
                rows = [row for row in rows if row.id not in row_ids]
            elif row_ids and sql_eq:
                rows = [row for row in rows if row.id in row_ids]
            if "removed_at" in text and "is null" in text:
                rows = [row for row in rows if row.removed_at is None]
            if cursor_time is not None and row_ids and (" < " in text or "<" in text):
                cursor_id = next(iter(row_ids))
                rows = [
                    row
                    for row in rows
                    if row.created_at < cursor_time or (row.created_at == cursor_time and row.id < cursor_id)
                ]
            return Result(rows)
        if "user_restrictions" in text and getattr(statement, "is_update", False):
            removed = params.get("removed_at") or NOW
            targets = row_ids or set()
            for row in self.rows:
                if row.id in targets and row.removed_at is None:
                    row.removed_at = removed
            return Result([row for row in self.rows if row.id in targets])
        if "user_restrictions" in text and getattr(statement, "is_insert", False):
            self.rows.append(
                RestrictionRow(
                    id=uuid.UUID(str(params.get("id", uuid.uuid4()))),
                    user_id=uuid.UUID(str(params.get("user_id", OWNER))),
                    kind=str(params.get("kind", "blocklist")),
                    target_type=str(params.get("target_type", "security")),
                    target_id=str(params.get("target_id", "SYN001.SH")),
                    until=params.get("until"),
                    reason=str(params.get("reason", "虚构原因")),
                    created_at=params.get("created_at", NOW),
                )
            )
            return Result([self.rows[-1]])
        if "securities" in text or "strategies" in text or "strategy_instances" in text:
            target_id = next(iter(row_ids), RID)
            return Result(
                [
                    SimpleNamespace(
                        id=target_id,
                        code="SYN001.SH",
                        name="虚构证券",
                        owner_user_id=OWNER,
                        user_id=OWNER,
                    )
                ]
            )
        return Result([])


class MemoryEngine:
    def __init__(
        self,
        rows: list[RestrictionRow],
        *,
        reasons: list[Any] | None = None,
        signals: list[Any] | None = None,
    ):
        self.conn = MemoryConnection(rows, reasons=reasons, signals=signals)

    @contextmanager
    def connect(self):
        yield self.conn

    @contextmanager
    def begin(self):
        yield self.conn


def _row(identifier: uuid.UUID, user_id: uuid.UUID = OWNER, **changes: Any) -> RestrictionRow:
    values: dict[str, Any] = {
        "id": identifier,
        "user_id": user_id,
        "kind": "blocklist",
        "target_type": "security",
        "target_id": "SYN001.SH",
        "until": None,
        "reason": "虚构原因",
        "created_at": NOW,
        "removed_at": None,
    }
    values.update(changes)
    return RestrictionRow(**values)


def _auth(user_id: uuid.UUID = OWNER) -> Any:
    return SimpleNamespace(user_id=user_id)


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        app_env="test",
        app_master_key=None,
        cursor_ttl_s=86_400,
        page_limit_max=200,
    )


def _get(obj: Any, name: str, default: Any = ...) -> Any:
    if isinstance(obj, dict):
        if default is not ...:
            return obj.get(name, default)
        return obj[name]
    if default is not ...:
        return getattr(obj, name, default)
    return getattr(obj, name)


def _items(result: Any) -> list[Any]:
    return list(_get(result, "items"))


def _body(endpoint: Any, payload: dict[str, Any]) -> Any:
    hints = get_type_hints(endpoint)
    for name, parameter in inspect.signature(endpoint).parameters.items():
        if name not in {"body", "payload", "data"}:
            continue
        candidate = hints.get(name, parameter.annotation)
        if getattr(candidate, "__origin__", None) is not None:
            candidate = next(
                (arg for arg in getattr(candidate, "__args__", ()) if inspect.isclass(arg)),
                candidate,
            )
        if inspect.isclass(candidate) and hasattr(candidate, "model_validate"):
            return candidate.model_validate(payload)
    return SimpleNamespace(**payload)


def _invoke(
    endpoint: Any,
    engine: MemoryEngine,
    *,
    user_id: uuid.UUID = OWNER,
    payload: dict[str, Any] | None = None,
    restriction_id: uuid.UUID = RID,
    kind: Any = None,
    target_type: Any = None,
    limit: int = 50,
    cursor: str | None = None,
) -> Any:
    kwargs: dict[str, Any] = {}
    for name in inspect.signature(endpoint).parameters:
        if name in {"auth", "current_user", "user"}:
            kwargs[name] = _auth(user_id)
        elif name in {"engine", "db"}:
            kwargs[name] = engine
        elif name in {"rds", "redis"}:
            kwargs[name] = SimpleNamespace()
        elif name in {"settings", "config"}:
            kwargs[name] = _settings()
        elif name in {"page", "params"}:
            kwargs[name] = PageParams(limit=limit, cursor=cursor)
        elif name == "kind":
            kwargs[name] = kind
        elif name == "target_type":
            kwargs[name] = target_type
        elif name in {"restriction_id", "id"}:
            kwargs[name] = restriction_id
        elif name in {"body", "payload", "data"}:
            kwargs[name] = _body(endpoint, payload or {})
    result = endpoint(**kwargs)
    if inspect.isawaitable(result):
        import asyncio

        return asyncio.run(result)
    return result


def _recheck(result: Any) -> Any:
    return _get(result, "recheck")


def _recheck_is_stubbed() -> bool:
    if DELETE_ENDPOINT is None:
        return True
    source = inspect.getsource(DELETE_ENDPOINT)
    return "released_reason_ids=[]" in source and "remaining_reason_ids=[]" in source


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：/restrictions R1 路由不存在")
def test_r1_list_is_owner_scoped_and_excludes_removed() -> None:
    expired = _row(RID, created_at=NOW, until=PAST)
    removed = _row(RID_2, created_at=NOW - dt.timedelta(minutes=1), removed_at=NOW)
    foreign = _row(uuid.UUID("55555555-5555-4555-8555-555555555555"), OTHER)
    engine = MemoryEngine([expired, removed, foreign])
    result = _invoke(LIST_ENDPOINT, engine)
    items = _items(result)
    assert [_get(item, "id") for item in items] == [RID]
    assert _get(items[0], "until") == PAST
    cursor = _get(result, "next_cursor")
    assert cursor is None or isinstance(cursor, str)
    other_ids = [_get(item, "id") for item in _items(_invoke(LIST_ENDPOINT, engine, user_id=OTHER))]
    assert RID not in other_ids
    assert RID_2 not in other_ids
    assert foreign.id in other_ids


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：/restrictions R1 分页路由不存在")
def test_r1_list_pagination_uses_cursor() -> None:
    engine = MemoryEngine([
        _row(RID, created_at=NOW),
        _row(RID_2, created_at=NOW - dt.timedelta(minutes=1)),
    ])
    first = _invoke(LIST_ENDPOINT, engine, limit=1)
    assert [_get(item, "id") for item in _items(first)] == [RID]
    cursor = _get(first, "next_cursor")
    assert isinstance(cursor, str) and cursor
    second = _invoke(LIST_ENDPOINT, engine, limit=1, cursor=cursor)
    assert [_get(item, "id") for item in _items(second)] == [RID_2]


@pytest.mark.parametrize("kind", ["blocklist", "cooling_off", "mute"])
@pytest.mark.parametrize("target_type", ["security", "strategy", "instance"])
@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：/restrictions POST R1 路由不存在")
def test_r1_all_kind_target_combinations_are_accepted(kind: str, target_type: str) -> None:
    engine = MemoryEngine([])
    until = FUTURE if kind == "cooling_off" else None
    target_id = TARGET_IDS[target_type]
    result = _invoke(
        CREATE_ENDPOINT,
        engine,
        payload={
            "kind": kind,
            "target_type": target_type,
            "target_id": target_id,
            "until": until,
            "reason": "虚构原因",
        },
    )
    assert _get(result, "kind") == kind
    assert _get(result, "target_type") == target_type
    assert _get(result, "target_id") == target_id
    insert = next(
        statement
        for statement in engine.conn.statements
        if "user_restrictions" in str(statement).lower()
        and getattr(statement, "is_insert", False)
    )
    assert _params(insert)["user_id"] == OWNER


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：R1 POST 校验路由不存在")
def test_r1_cooling_off_requires_future_until_and_post_is_strict() -> None:
    model = next(
        (
            getattr(RESTRICTIONS, name, None)
            for name in ("RestrictionCreate", "RestrictionIn", "RestrictionBody")
            if getattr(RESTRICTIONS, name, None)
        ),
        None,
    )
    if model is None:
        pytest.fail("P0：restrictions 路由已存在，但未公开创建模型")
    assert {"kind", "target_type", "target_id", "until", "reason"} <= set(model.model_fields)
    assert "user_id" not in model.model_fields
    assert getattr(model, "model_config", {}).get("extra") == "forbid"
    with pytest.raises(ValidationError):
        model.model_validate({
            "kind": "mute",
            "target_type": "security",
            "target_id": "SYN001.SH",
            "until": None,
            "reason": "虚构原因",
            "user_id": str(OWNER),
        })
    engine = MemoryEngine([])
    payload = {
        "kind": "cooling_off",
        "target_type": "security",
        "target_id": "SYN001.SH",
        "until": PAST,
        "reason": "虚构原因",
    }
    try:
        _invoke(CREATE_ENDPOINT, engine, payload=payload)
    except (AppError, HTTPException, ValueError, ValidationError) as error:
        code = getattr(error, "code", None)
        status = getattr(error, "status_code", None)
        assert str(code) == "VALIDATION_ERROR" or status == 400
    else:
        pytest.xfail("T-B200 未实现：cooling_off 缺少未来 until 应返回 400 VALIDATION_ERROR")


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：/restrictions DELETE R2 路由不存在")
def test_r2_delete_is_soft_delete_and_repeat_returns_404() -> None:
    engine = MemoryEngine([_row(RID), _row(RID_2, target_type="security", target_id="SYN001.SH")])
    first = _invoke(DELETE_ENDPOINT, engine)
    assert _get(first, "id") == RID
    removed_at = _get(first, "removed_at")
    assert removed_at is not None and getattr(removed_at, "tzinfo", None) is not None
    recheck = _recheck(first)
    released = list(_get(recheck, "released_reason_ids"))
    remaining = list(_get(recheck, "remaining_reason_ids"))
    assert all(isinstance(item, uuid.UUID) for item in released + remaining)
    assert isinstance(_get(first, "gaps", []), list)
    assert "已解除" not in str(first)
    owned = next(row for row in engine.conn.rows if row.id == RID)
    leftover = next(row for row in engine.conn.rows if row.id == RID_2)
    assert owned.removed_at == removed_at
    assert leftover.removed_at is None
    with pytest.raises((AppError, HTTPException, ValueError)) as error:
        _invoke(DELETE_ENDPOINT, engine)
    code = getattr(error.value, "code", None)
    status = getattr(error.value, "status_code", None)
    assert str(code) == "NOT_FOUND" or status == 404


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：R2 所有权删除路由不存在")
@pytest.mark.parametrize("user_id,restriction_id", [(OTHER, RID), (OWNER, UNKNOWN)])
def test_r2_other_user_or_unknown_id_is_not_leaked(user_id: uuid.UUID, restriction_id: uuid.UUID) -> None:
    engine = MemoryEngine([_row(RID)])
    with pytest.raises((AppError, HTTPException, ValueError)) as error:
        _invoke(DELETE_ENDPOINT, engine, user_id=user_id, restriction_id=restriction_id)
    code = getattr(error.value, "code", None)
    status = getattr(error.value, "status_code", None)
    assert str(code) == "NOT_FOUND" or status == 404


@pytest.mark.xfail(not ROUTES_READY, strict=True, reason="T-B200 未实现：R3 重查路由不存在")
def test_r3_multiple_restrictions_release_only_after_last_one() -> None:
    reason_id = uuid.UUID("77777777-7777-4777-8777-777777777777")
    signal_id = uuid.UUID("88888888-8888-4888-8888-888888888888")
    reason = SimpleNamespace(
        id=reason_id,
        signal_id=signal_id,
        user_id=OWNER,
        code="BLOCKLISTED",
        status="active",
    )
    signal = SimpleNamespace(
        id=signal_id,
        user_id=OWNER,
        security_code="SYN001.SH",
        instance_id=None,
        strategy_version_id=None,
        state="blocked",
        created_at=NOW,
    )
    engine = MemoryEngine([_row(RID), _row(RID_2)], reasons=[reason], signals=[signal])
    first = _invoke(DELETE_ENDPOINT, engine)
    leftover = next(row for row in engine.conn.rows if row.id == RID_2)
    assert leftover.removed_at is None
    assert list(_get(_recheck(first), "released_reason_ids")) == []
    assert "已解除" not in str(first)
    if _recheck_is_stubbed():
        pytest.xfail("T-B200 未实现：R3 重查仍为占位，未按同目标剩余限制计算 released/remaining_reason_ids")
    assert list(_get(_recheck(first), "remaining_reason_ids")) == [reason_id]
    second = _invoke(DELETE_ENDPOINT, engine, restriction_id=RID_2)
    assert list(_get(_recheck(second), "released_reason_ids")) == [reason_id]
    assert list(_get(_recheck(second), "remaining_reason_ids")) == []


def test_r3_machine_reasons_remain_non_manually_releasable() -> None:
    candidate_signals = importlib.import_module("app.api.v1.candidate_signals")
    release = getattr(candidate_signals, "release_reason", None)
    assert release is not None
    source = inspect.getsource(release)
    assert "REASON_NOT_MANUALLY_RELEASABLE" in source
    assert any(
        route.path == "/non-executable-reasons/{reason_id}/release"
        and "POST" in {method.upper() for method in route.methods or ()}
        for route in candidate_signals.router.routes
    )


def _write_candidate_has_restriction_filters() -> bool:
    service = importlib.import_module("app.signals.service")
    source = inspect.getsource(service.write_candidate)
    return (
        "user_restrictions.c.removed_at.is_(None)" in source
        and 'user_restrictions.c.target_type == "security"' in source
        and 'user_restrictions.c.target_type == "instance"' in source
        and 'user_restrictions.c.target_type == "strategy"' in source
    )


@pytest.mark.xfail(
    not _write_candidate_has_restriction_filters(),
    strict=True,
    reason="T-B200 未实现：write_candidate 尚未按 removed_at/target_type 过滤",
)
def test_write_candidate_filters_removed_at_and_target_type() -> None:
    service = importlib.import_module("app.signals.service")
    source = inspect.getsource(service.write_candidate)
    restriction_read = source[source.index("select(user_restrictions)") :]
    assert "user_restrictions.c.removed_at.is_(None)" in restriction_read
    assert 'user_restrictions.c.target_type == "security"' in restriction_read
    assert 'user_restrictions.c.target_type == "instance"' in restriction_read
    assert 'user_restrictions.c.target_type == "strategy"' in restriction_read

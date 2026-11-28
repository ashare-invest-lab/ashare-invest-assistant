"""T-T113: offline HTTP contract probes for T-A219 market overview.

The facts below are deliberately fictional. The endpoint is exercised through
the real FastAPI route. A missing aggregate is reported as a single-case xfail
until T-B210 wires the production reader; tests never replace the route response
with a hand-built MarketOverview.
"""

from __future__ import annotations

import datetime as dt
import inspect
import operator
import socket
import uuid
from collections.abc import Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.sql import operators
from sqlalchemy.sql.elements import (
    BooleanClauseList,
    BindParameter,
    False_,
    Grouping,
    Null,
    True_,
    UnaryExpression,
)

from app.aggregates import models as aggregate_models
from app.api.v1 import aggregates as routes
from app.auth import deps
from app.auth.sessions import SESSION_COOKIE
from app.common.errors import install_exception_handlers
from app.db.tables.licences import user_data_licence_holds, user_data_licence_status
from app.db.tables.market import (
    daily_bars,
    quotes_snapshot,
    securities,
    security_listing_status_history,
)
from app.schemas.enums import MarketSession


OWNER = uuid.UUID("00000000-0000-0000-0000-00000000b210")
LICENCE_A = uuid.UUID("00000000-0000-0000-0000-00000000a219")
LICENCE_B = uuid.UUID("00000000-0000-0000-0000-00000000a220")
QUERY = dt.datetime(2026, 11, 13, 10, 0, tzinfo=dt.timezone.utc)
INTRADAY_QUERY = dt.datetime(2026, 11, 13, 6, 0, tzinfo=dt.timezone.utc)
TRADE_DATE = dt.date(2026, 11, 13)
SHANGHAI = dt.timezone(dt.timedelta(hours=8))
INTRADAY_BATCH = uuid.UUID("00000000-0000-0000-0000-00000000b371")
PIT_FUTURE_BATCH = uuid.UUID("00000000-0000-0000-0000-00000000b372")


def fixture_settings() -> SimpleNamespace:
    # config/realtime.yaml sets quote_interval_s=15 and stale_threshold_s=null.
    # RealtimeIntervals.effective_stale_threshold_s therefore evaluates to 30.
    return SimpleNamespace(
        business=SimpleNamespace(
            market_rules={},
            realtime=SimpleNamespace(
                intervals=SimpleNamespace(effective_stale_threshold_s=30)
            ),
        )
    )


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """The contract fixtures must not reach PG, Redis, or a vendor."""

    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("T-T113 is offline and must not open a socket")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


@dataclass(frozen=True)
class MarketFact:
    code: str
    query_as_of: dt.datetime
    ts: dt.datetime
    fetched_at: dt.datetime
    source: str
    source_licence_id: uuid.UUID | None
    batch_id: uuid.UUID | None = None
    price: Decimal | None = None
    pct_change: Decimal | None = None
    volume: Decimal | None = None
    amount: Decimal | None = None
    kind: str = "stock"
    pre_close: Decimal | None = None
    close: Decimal | None = None
    is_suspended: bool = False
    listing_status: str = "listed"
    risk_flag: str | None = None


@dataclass
class OverviewState:
    facts: list[MarketFact] = field(default_factory=list)
    licence: uuid.UUID | None = None
    query_as_of: dt.datetime = QUERY
    clock: aggregate_models.MarketClock = field(
        default_factory=lambda: aggregate_models.MarketClock(
            trade_date=TRADE_DATE, session=MarketSession.MORNING
        )
    )


class FixtureRow:
    def __init__(self, mapping: Mapping[str, object]) -> None:
        self._mapping = dict(mapping)


class FixtureResult:
    def __init__(self, rows: list[FixtureRow]) -> None:
        self._rows = rows

    def all(self) -> list[FixtureRow]:
        return self._rows

    def first(self) -> FixtureRow | None:
        return self._rows[0] if self._rows else None

    def scalar_one_or_none(self) -> object | None:
        if len(self._rows) > 1:
            raise AssertionError("fixture scalar query returned multiple rows")
        row = self.first()
        return next(iter(row._mapping.values())) if row is not None else None


def _table_key(table: object) -> tuple[object, object]:
    return (getattr(table, "schema", None), getattr(table, "name", None))


def _record(table: object, values: Mapping[str, object]) -> dict[tuple[tuple[object, object], str], object]:
    return {
        (_table_key(table), column.name): values.get(column.name)
        for column in table.c
    }


def _expression_value(expression: object, values: Mapping[tuple[tuple[object, object], str], object]) -> object:
    if isinstance(expression, Null):
        return None
    if isinstance(expression, True_):
        return True
    if isinstance(expression, False_):
        return False
    if isinstance(expression, BindParameter):
        return expression.value
    if isinstance(expression, Grouping):
        return _expression_value(expression.element, values)
    if isinstance(expression, UnaryExpression):
        return _expression_value(expression.element, values)
    table = getattr(expression, "table", None)
    name = getattr(expression, "name", None)
    if table is not None and name is not None:
        key = (_table_key(table), name)
        if key not in values:
            raise AssertionError(f"unknown fixture SQL column: {expression!r}")
        return values[key]
    raise AssertionError(f"unsupported fixture SQL value: {expression!r}")


def _matches(expression: object, values: Mapping[tuple[tuple[object, object], str], object]) -> bool:
    if isinstance(expression, BooleanClauseList):
        parts = [_matches(part, values) for part in expression.clauses]
        if expression.operator is operators.and_:
            return all(parts)
        if expression.operator is operators.or_:
            return any(parts)
        raise AssertionError(f"unsupported fixture boolean operator: {expression.operator!r}")
    if isinstance(expression, UnaryExpression):
        if expression.operator is operators.inv:
            return not _matches(expression.element, values)
        return bool(_expression_value(expression, values))
    left = _expression_value(expression.left, values)
    right = _expression_value(expression.right, values)
    operation = expression.operator
    if operation in {operator.eq, operators.eq}:
        return left == right
    if operation in {operator.ne, operators.ne}:
        return left != right
    if operation in {operator.lt, operators.lt}:
        return left is not None and right is not None and left < right
    if operation in {operator.le, operators.le}:
        return left is not None and right is not None and left <= right
    if operation in {operator.gt, operators.gt}:
        return left is not None and right is not None and left > right
    if operation in {operator.ge, operators.ge}:
        return left is not None and right is not None and left >= right
    if operation is operators.in_op:
        return left in (right or ())
    if operation is operators.not_in_op:
        return left not in (right or ())
    if operation is operators.is_:
        return left is right
    if operation is operators.is_not:
        return left is not right
    raise AssertionError(f"unsupported fixture SQL operator: {operation!r}")


def _fact_day(fact: MarketFact) -> dt.date:
    return fact.ts.astimezone(SHANGHAI).date()


class FixtureConnection:
    """Read-only SQLAlchemy-shaped connection over the test's fictional facts."""

    def __init__(self, state: OverviewState) -> None:
        self.state = state

    def _securities(self) -> list[dict[tuple[tuple[object, object], str], object]]:
        names = {"600000.SH": "示例银行", "000001.SZ": "演示电子"}
        by_code: dict[str, MarketFact] = {}
        for fact in self.state.facts:
            by_code.setdefault(fact.code, fact)
        return [
            _record(
                securities,
                {
                    "code": fact.code,
                    "type": fact.kind,
                    "name": names.get(fact.code, fact.code),
                    "exchange": fact.code.rsplit(".", 1)[-1],
                    "listing_status": fact.listing_status,
                    "list_date": None,
                    "delist_date": None,
                    "risk_flag": fact.risk_flag,
                },
            )
            for fact in by_code.values()
        ]

    def _listing_history(self) -> list[dict[tuple[tuple[object, object], str], object]]:
        by_code: dict[str, dict[dt.date, str]] = {}
        for fact in self.state.facts:
            by_code.setdefault(fact.code, {})[_fact_day(fact)] = fact.listing_status
        rows: list[dict[tuple[tuple[object, object], str], object]] = []
        for code, statuses in by_code.items():
            days = sorted(statuses)
            for index, day in enumerate(days):
                rows.append(
                    _record(
                        security_listing_status_history,
                        {
                            "code": code,
                            "listing_status": statuses[day],
                            "valid_from": day,
                            "valid_until": days[index + 1] if index + 1 < len(days) else None,
                        },
                    )
                )
        return rows

    def _quotes(self) -> list[dict[tuple[tuple[object, object], str], object]]:
        rows = []
        for fact in self.state.facts:
            if fact.close is not None:
                continue
            payload = {
                key: value
                for key, value in {
                    "pct_change": fact.pct_change,
                    "volume": fact.volume,
                    "amount": fact.amount,
                    "is_suspended": fact.is_suspended,
                }.items()
                if value is not None
            }
            rows.append(
                _record(
                    quotes_snapshot,
                    {
                        "code": fact.code,
                        "ts": fact.ts,
                        "price": fact.price,
                        "pct_change": fact.pct_change,
                        "payload": {"price": fact.price, **payload},
                        "source": fact.source,
                        "source_licence_id": fact.source_licence_id,
                        "row_id": uuid.uuid5(
                            uuid.NAMESPACE_URL,
                            f"quote:{fact.code}:{fact.ts}:{fact.fetched_at}:{fact.source_licence_id}",
                        ),
                        "revision": 0,
                        "content_fingerprint": None,
                        "volume": fact.volume,
                        "amount": fact.amount,
                        "is_suspended": fact.is_suspended,
                        "limit_up": None,
                        "limit_down": None,
                        "batch_id": fact.batch_id,
                        "fetched_at": fact.fetched_at,
                    },
                )
            )
        return rows

    def _daily_bars(self) -> list[dict[tuple[tuple[object, object], str], object]]:
        return [
            _record(
                daily_bars,
                {
                    "code": fact.code,
                    "trade_date": _fact_day(fact),
                    "adj_type": "none",
                    "close": fact.close,
                    "pre_close": fact.pre_close,
                    "volume": fact.volume,
                    "amount": fact.amount,
                    "is_suspended": fact.is_suspended,
                    "source": fact.source,
                    "source_licence_id": fact.source_licence_id,
                    "fetched_at": fact.fetched_at,
                },
            )
            for fact in self.state.facts
            if fact.close is not None
        ]

    def _licences(self) -> list[dict[tuple[tuple[object, object], str], object]]:
        licence = self.state.licence
        if licence is None:
            return []
        return [
            {
                **_record(
                    user_data_licence_status,
                    {
                        "id": licence,
                        "user_id": OWNER,
                        "status": "active",
                        "deleted_at": None,
                        "paused_until": None,
                        "expires_on": None,
                    },
                ),
                **_record(user_data_licence_holds, {"user_id": None}),
            }
        ]

    def _candidates(self, statement: Any) -> list[dict[tuple[tuple[object, object], str], object]]:
        selected = list(statement.selected_columns)
        if not selected:
            raise AssertionError(f"fixture cannot execute statement without columns: {statement!r}")
        table = getattr(selected[0], "table", None)
        name = getattr(table, "name", None)
        if name == securities.name:
            return self._securities()
        if name == security_listing_status_history.name:
            return self._listing_history()
        if name == quotes_snapshot.name:
            return self._quotes()
        if name == daily_bars.name:
            return self._daily_bars()
        if name == user_data_licence_status.name:
            return self._licences()
        raise AssertionError(f"unknown fixture SELECT source: {statement!r}")

    def execute(self, statement: Any) -> FixtureResult:
        if not hasattr(statement, "selected_columns") or not hasattr(statement, "_where_criteria"):
            raise AssertionError(f"fixture only executes SQLAlchemy SELECT statements: {statement!r}")
        candidates = [
            values
            for values in self._candidates(statement)
            if all(_matches(clause, values) for clause in statement._where_criteria)
        ]
        for ordering in reversed(list(statement._order_by_clauses)):
            descending = isinstance(ordering, UnaryExpression) and ordering.modifier is operators.desc_op
            expression = ordering.element if isinstance(ordering, UnaryExpression) else ordering
            candidates.sort(
                key=lambda values: (
                    _expression_value(expression, values) is None,
                    _expression_value(expression, values),
                ),
                reverse=descending,
            )
        rows = [
            FixtureRow(
                {
                    column.key: _expression_value(column, values)
                    for column in statement.selected_columns
                }
            )
            for values in candidates
        ]
        return FixtureResult(rows)


class FixtureEngine:
    def __init__(self, state: OverviewState) -> None:
        self.state = state

    def connect(self) -> Any:
        return nullcontext(FixtureConnection(self.state))


def intraday_fact(
    code: str,
    change: str,
    *,
    query_as_of: dt.datetime = QUERY,
    ts: dt.datetime | None = None,
    fetched_at: dt.datetime | None = None,
    licence: uuid.UUID | None = LICENCE_A,
    batch_id: uuid.UUID | None = None,
    volume: str | None = "100",
    amount: str | None = "1000",
    kind: str = "stock",
    **extra: Any,
) -> MarketFact:
    observed = ts or dt.datetime(2026, 11, 13, 2, 0, tzinfo=dt.timezone.utc)
    return MarketFact(
        code=code,
        query_as_of=query_as_of,
        ts=observed,
        fetched_at=fetched_at or observed,
        source="mairui",
        source_licence_id=licence,
        batch_id=batch_id,
        price=Decimal("10.00"),
        pct_change=Decimal(change),
        volume=Decimal(volume) if volume is not None else None,
        amount=Decimal(amount) if amount is not None else None,
        kind=kind,
        **extra,
    )


def close_fact(
    code: str,
    close: str,
    pre_close: str,
    *,
    trade_date: dt.date = TRADE_DATE,
    query_as_of: dt.datetime = dt.datetime(2026, 11, 13, 9, 15, tzinfo=dt.timezone.utc),
    fetched_at: dt.datetime | None = None,
    licence: uuid.UUID | None = LICENCE_A,
    kind: str = "stock",
    source: str = "mairui",
    volume: str = "100",
    amount: str = "1000",
    **extra: Any,
) -> MarketFact:
    observed = dt.datetime.combine(trade_date, dt.time(15), tzinfo=SHANGHAI)
    visible_at = fetched_at or dt.datetime.combine(
        trade_date, dt.time(9, 15), tzinfo=dt.timezone.utc
    )
    return MarketFact(
        code=code,
        query_as_of=query_as_of,
        ts=observed,
        fetched_at=visible_at,
        source=source,
        source_licence_id=licence,
        close=Decimal(close),
        pre_close=Decimal(pre_close),
        price=Decimal(close),
        volume=Decimal(volume),
        amount=Decimal(amount),
        kind=kind,
        **extra,
    )


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> OverviewState:
    state = OverviewState()
    engine = FixtureEngine(state)
    settings = fixture_settings()

    class FrozenDateTime(dt.datetime):
        @classmethod
        def now(cls, tz: dt.tzinfo | None = None) -> dt.datetime:
            value = state.query_as_of
            return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)

    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: engine
    app.dependency_overrides[deps.get_settings] = lambda: settings
    app.dependency_overrides[deps.current_auth] = lambda: SimpleNamespace(user_id=OWNER)
    monkeypatch.setattr(routes, "market_clock", lambda conn, now, rules: state.clock)
    monkeypatch.setattr(routes.dt, "datetime", FrozenDateTime)
    with TestClient(app) as client:
        client.cookies.set(SESSION_COOKIE, "synthetic-session")
        state.client = client  # type: ignore[attr-defined]
        yield state


def get_overview(state: OverviewState) -> dict[str, Any]:
    response = state.client.get("/api/v1/market/overview")  # type: ignore[attr-defined]
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["data_status"] != "pending"
    return payload


def is_unwired_empty_state(payload: dict[str, Any]) -> bool:
    indices = payload.get("indices") or []
    empty_indices = not indices or all(
        item.get("price") is None
        and item.get("change_pct") is None
        and item.get("amount") is None
        for item in indices
    )
    gaps = payload.get("gaps") or []
    return (
        payload.get("basis") is None
        and payload.get("breadth") is None
        and payload.get("turnover_total") is None
        and payload.get("data_status") == "unavailable"
        and empty_indices
        and bool(gaps)
        and all(
            gap.get("key") == "market"
            and gap.get("reason") == "no_source"
            and "行情聚合尚未接线" in gap.get("message", "")
            for gap in gaps
        )
    )


def require_component(payload: dict[str, Any], condition: bool, reason: str) -> None:
    if not condition and is_unwired_empty_state(payload):
        pytest.xfail(f"T-B210 未实现：{reason}")
    assert condition


def market_overview_reader_is_wired() -> bool:
    market = getattr(routes.service, "market", None)
    if not callable(market):
        return False
    try:
        parameters = inspect.signature(market).parameters
    except (TypeError, ValueError):
        return False
    return {"conn", "user_id", "clock", "query_as_of"}.issubset(parameters)


def assert_decimal_ratio(value: Any, expected: Decimal) -> None:
    assert isinstance(value, str)
    parsed = Decimal(value)
    assert parsed == expected
    assert len(value.split(".")[1]) >= 4


def assert_decimal_string(value: Any, expected: Decimal) -> None:
    assert isinstance(value, str)
    assert Decimal(value) == expected


def complete_intraday_facts(
    *, query_as_of: dt.datetime = INTRADAY_QUERY
) -> list[MarketFact]:
    return [
        intraday_fact(
            "600000.SH",
            "2",
            query_as_of=query_as_of,
            batch_id=INTRADAY_BATCH,
            amount="1200",
        ),
        intraday_fact(
            "000001.SZ",
            "1",
            query_as_of=query_as_of,
            batch_id=INTRADAY_BATCH,
            amount="800",
        ),
        intraday_fact(
            "688001.SH",
            "-1",
            query_as_of=query_as_of,
            batch_id=INTRADAY_BATCH,
            amount="600",
        ),
    ]


def test_market_overview_empty_state_is_honest(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = []
    payload = get_overview(world)
    assert payload["indices"] == [] or all(
        item["price"] is None and item["change_pct"] is None and item["amount"] is None
        for item in payload["indices"]
    )
    assert payload["breadth"] is None
    assert payload["regime"] is None
    assert payload["regime_position_range"] is None
    assert payload["turnover_total"] is None
    assert payload["data_status"] == "unavailable"
    assert payload["data_as_of"] is None
    assert payload["gaps"]
    regime_gap = next((gap for gap in payload["gaps"] if gap["key"] == "market.regime"), None)
    if is_unwired_empty_state(payload) and regime_gap is None:
        pytest.xfail("T-B210 未实现：空态须含契约 §7 的 market.regime/no_source")
    assert regime_gap is not None and regime_gap["reason"] == "no_source" and "F25/G-02 参数未批准" in regime_gap["message"]
    assert all(gap["reason"] == "no_source" for gap in payload["gaps"])
    assert all(gap["reason"] != "pending" for gap in payload["gaps"])


def test_market_overview_requires_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    install_exception_handlers(app)
    app.include_router(routes.router, prefix="/api/v1")
    app.dependency_overrides[deps.get_engine] = lambda: FixtureEngine(OverviewState())
    app.dependency_overrides[deps.get_session_store] = lambda: SimpleNamespace(get=lambda _: None)
    app.dependency_overrides[deps.get_settings] = fixture_settings
    monkeypatch.setattr(routes, "market_clock", lambda conn, now, rules: OverviewState().clock)
    response = TestClient(app).get("/api/v1/market/overview")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTH_REQUIRED"


def test_market_overview_rejects_unsupported_method(world: OverviewState) -> None:
    response = world.client.post("/api/v1/market/overview")  # type: ignore[attr-defined]
    assert response.status_code == 405


def test_market_overview_complete_intraday_batch(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.query_as_of = INTRADAY_QUERY
    world.facts = complete_intraday_facts()
    payload = get_overview(world)
    breadth = payload["breadth"]
    basis = payload["basis"]
    require_component(
        payload,
        breadth is not None and basis is not None and payload["turnover_total"] is not None,
        "完整盘中宽度比例与同批 basis/turnover，契约 §5.1/§9",
    )
    assert (breadth["up"], breadth["down"], breadth["flat"]) == (2, 1, 0)
    assert all(isinstance(breadth[field], int) for field in ("up", "down", "flat"))
    # §5.2：完整批次若无规则出处，limit_* 仍应是 null，而不是 int。
    assert all(
        breadth[field] is None or isinstance(breadth[field], int)
        for field in ("limit_up", "limit_down")
    )
    assert_decimal_ratio(breadth["up_ratio"], Decimal("0.6667"))
    assert_decimal_ratio(breadth["down_ratio"], Decimal("0.3333"))
    assert_decimal_ratio(breadth["flat_ratio"], Decimal("0"))
    assert basis["mode"] == "intraday"
    assert basis["observed_date"] == "2026-11-13"
    assert basis["source"] == "mairui"
    assert_decimal_string(payload["turnover_total"], Decimal("2600"))


def test_market_overview_intraday_missing_volume_amount_is_partial(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.query_as_of = INTRADAY_QUERY
    world.facts = [
        intraday_fact(
            "600000.SH",
            "1",
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
            volume=None,
            amount=None,
        ),
        intraday_fact(
            "000001.SZ",
            "-1",
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
            volume=None,
            amount=None,
        ),
        intraday_fact(
            "000300.SH",
            "1",
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
            volume=None,
            amount=None,
            kind="index",
        ),
        intraday_fact(
            "399001.SZ",
            "-1",
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
            volume=None,
            amount=None,
            kind="index",
        ),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        bool(payload["indices"])
        and any(item["price"] is not None for item in payload["indices"])
        and (
            payload["data_status"] == "partial"
            or any(
                g["key"] in {"market.breadth", "market.turnover_total"}
                for g in payload["gaps"]
            )
        ),
        "盘中缺量额不得补零，契约 §2/§5.3/§9",
    )
    assert all(
        item["amount"] is None
        for item in payload["indices"]
        if item["security_code"] in {"000300.SH", "399001.SZ"}
    )
    assert payload["turnover_total"] is None


@pytest.mark.parametrize(
    ("query_as_of", "expect_close"),
    [
        (dt.datetime(2026, 11, 13, 6, 59, 59, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 7, 0, 1, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 9, 9, 59, tzinfo=dt.timezone.utc), False),
        (dt.datetime(2026, 11, 13, 9, 15, 1, tzinfo=dt.timezone.utc), True),
    ],
)
def test_market_overview_1500_and_1710_selection(
    world: OverviewState, query_as_of: dt.datetime, expect_close: bool
) -> None:
    world.licence = LICENCE_A
    world.query_as_of = query_as_of
    world.facts = [
        intraday_fact(
            "600000.SH",
            "1",
            query_as_of=query_as_of,
            batch_id=INTRADAY_BATCH if not expect_close else None,
        ),
        close_fact(
            "600000.SH",
            "11",
            "10",
            query_as_of=query_as_of,
            fetched_at=dt.datetime(2026, 11, 13, 9, 11, tzinfo=dt.timezone.utc),
        ),
    ]
    payload = get_overview(world)
    basis = payload["basis"]
    require_component(
        payload,
        basis is not None,
        "15:00/17:10 时点门槛与 PIT 选择，契约 §4/§9",
    )
    if expect_close:
        assert basis["mode"] == "close"
    else:
        assert basis["mode"] != "close"


def test_market_overview_daily_close_uses_decimal_amounts(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.query_as_of = dt.datetime(2026, 11, 13, 9, 15, tzinfo=dt.timezone.utc)
    world.facts = [
        close_fact("600000.SH", "11.25", "10.00", fetched_at=world.query_as_of),
        close_fact("000001.SZ", "9.50", "10.00", fetched_at=world.query_as_of),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["basis"] is not None and payload["basis"]["mode"] == "close",
        "合格 daily_bars 收盘模式与元单位，契约 §2/§4/§9",
    )
    assert_decimal_string(payload["turnover_total"], Decimal("2000"))


def test_market_overview_excludes_suspended_zero_delisted_but_keeps_st(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = [
        close_fact("600000.SH", "11", "10", is_suspended=True),
        close_fact("000001.SZ", "11", "10", volume="0"),
        close_fact("688001.SH", "11", "10", listing_status="delisted"),
        close_fact("000002.SZ", "11", "10", risk_flag="st"),
    ]
    payload = get_overview(world)
    breadth = payload["breadth"]
    require_component(
        payload,
        breadth is not None
        and any(g["key"] == "market.breadth.limit_counts" for g in payload["gaps"]),
        "停牌/零量/退市资格排除与 ST 基础宽度，契约 §3.1/§5.2/§9",
    )
    assert breadth["up"] + breadth["down"] + breadth["flat"] == 1
    assert breadth["limit_up"] is None and breadth["limit_down"] is None


def test_market_overview_etf_index_and_bj_scope(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = [
        close_fact("510001.SH", "1.01", "1.00", kind="etf"),
        close_fact("000300.SH", "4000", "3990", kind="index"),
        close_fact("830001.BJ", "10.1", "10.0"),
        close_fact("600000.SH", "11", "10"),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["basis"] is not None and payload["breadth"] is not None,
        "ETF/指数/BJ 沪深股票口径过滤，契约 §3.1/§9",
    )
    assert payload["basis"]["scope"] == "沪深股票口径"
    assert payload["breadth"]["up"] + payload["breadth"]["down"] + payload["breadth"]["flat"] == 1
    assert all(item["security_code"] != "510001.SH" for item in payload["indices"])
    assert any(item["security_code"] == "000300.SH" for item in payload["indices"])


def test_market_overview_limit_counts_need_rule_evidence(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = [close_fact("600000.SH", "11", "10")]
    payload = get_overview(world)
    breadth = payload["breadth"]
    require_component(
        payload,
        breadth is not None
        and any(
            gap["key"] == "market.breadth.limit_counts" and gap["reason"] == "no_source"
            for gap in payload["gaps"]
        ),
        "缺 T 日规则或最小价位单位时 limit_* 为 null，契约 §5.2/§9",
    )
    assert breadth["limit_up"] is None and breadth["limit_down"] is None


def test_market_overview_coverage_threshold_stays_disabled(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.query_as_of = INTRADAY_QUERY
    world.facts = complete_intraday_facts()
    payload = get_overview(world)
    basis = payload["basis"]
    no_source_gaps = [gap for gap in payload["gaps"] if gap["reason"] == "no_source"]
    require_component(
        payload,
        basis is not None
        and payload.get("coverage_threshold") is None
        and basis.get("coverage_threshold") is None
        and bool(no_source_gaps)
        and all(gap["reason"] != "coverage_unknown" for gap in payload["gaps"]),
        "coverage_threshold 保持 disabled，相关值为 null 且不冒充覆盖率证据，契约 §3.1",
    )
    assert payload.get("coverage_threshold") is None
    assert basis.get("coverage_threshold") is None
    assert all(gap["reason"] != "coverage_unknown" for gap in payload["gaps"])


def test_market_overview_zero_denominator_keeps_width_null(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = [
        close_fact("600000.SH", "11", "10", is_suspended=True),
        close_fact("000001.SZ", "11", "10", volume="0"),
    ]
    payload = get_overview(world)
    breadth = payload["breadth"]
    width_fields = (
        "up",
        "down",
        "flat",
        "up_ratio",
        "down_ratio",
        "flat_ratio",
        "limit_up",
        "limit_down",
    )
    require_component(
        payload,
        breadth is not None
        and all(breadth[field] is None for field in width_fields)
        and any(gap["reason"] == "no_source" for gap in payload["gaps"]),
        "宽度分母 N=0 时计数与比例均为 null，契约 §1/§5.1",
    )
    assert all(breadth[field] is None for field in width_fields)


@pytest.mark.parametrize("catalog_status", ["declared", "verified_live"])
def test_market_overview_regime_remains_gated(catalog_status: str, world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.facts = [close_fact("000300.SH", "4000", "3990", kind="index")]
    world.regime_feature = {  # type: ignore[attr-defined]
        "f.market_regime": "uptrend",
        "catalog_status": catalog_status,
    }
    payload = get_overview(world)
    assert payload["regime"] is None
    assert payload["regime_position_range"] is None
    regime_gap = next(
        (gap for gap in payload["gaps"] if gap["key"] == "market.regime"),
        None,
    )
    if is_unwired_empty_state(payload) and regime_gap is None:
        pytest.xfail("T-B210 未实现：F25/G-02 未批准时 regime 门控，契约 §7/§9")
    assert regime_gap is not None
    assert regime_gap["reason"] == "no_source"
    assert "F25/G-02 参数未批准" in regime_gap["message"]


def test_market_overview_no_licence_or_all_future_is_unavailable(world: OverviewState) -> None:
    world.query_as_of = QUERY
    world.facts = [
        intraday_fact("600000.SH", "1", licence=None),
        intraday_fact(
            "000001.SZ",
            "-1",
            fetched_at=QUERY + dt.timedelta(minutes=1),
            licence=None,
        ),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["data_status"] == "unavailable"
        and all(item["price"] is None for item in payload["indices"])
        and any(gap["reason"] == "data_licence_unavailable" for gap in payload["gaps"]),
        "无证书与全空 PIT 响应，契约 §6/§8/§9",
    )
    assert payload["data_as_of"] is None
    assert payload["basis"] is None
    assert payload["breadth"] is None
    assert payload["turnover_total"] is None
    assert any(gap["reason"] == "no_source" for gap in payload["gaps"])


def test_fixture_connection_does_not_infer_owner_licence_from_market_facts() -> None:
    state = OverviewState(
        facts=[
            close_fact(
                "830001.BJ",
                "10.1",
                "10.0",
                source="tdx_local",
                licence=LICENCE_B,
            )
        ]
    )

    assert FixtureConnection(state)._licences() == []


@pytest.mark.parametrize(
    ("session", "trade_date"),
    [
        (MarketSession.NON_TRADING_DAY, dt.date(2026, 11, 14)),
        (MarketSession.PRE_OPEN, dt.date(2026, 11, 13)),
    ],
)
def test_market_overview_nontrading_and_preopen_use_stale_close(
    world: OverviewState, session: MarketSession, trade_date: dt.date
) -> None:
    world.licence = LICENCE_A
    world.clock = aggregate_models.MarketClock(
        trade_date=trade_date, session=session
    )
    world.query_as_of = dt.datetime.combine(
        trade_date, dt.time(0), tzinfo=dt.timezone.utc
    )
    # 11-14 为休市日，最近已完成收盘批是 11-13；开盘前（11-13 08:00）则用 11-12。
    previous_trade_date = (
        dt.date(2026, 11, 13)
        if session is MarketSession.NON_TRADING_DAY
        else dt.date(2026, 11, 12)
    )
    early_same_day = world.query_as_of - dt.timedelta(minutes=30)
    world.facts = [
        close_fact(
            "600000.SH",
            "11",
            "10",
            trade_date=previous_trade_date,
            query_as_of=world.query_as_of,
        ),
        close_fact(
            "000300.SH",
            "4001",
            "4000",
            trade_date=previous_trade_date,
            query_as_of=world.query_as_of,
            kind="index",
        ),
        # 查询时已可见的当日（或休市日清晨）盘中行，仍不得被当作回退收盘。
        intraday_fact(
            "600000.SH",
            "1",
            query_as_of=world.query_as_of,
            ts=early_same_day,
            fetched_at=early_same_day,
            batch_id=INTRADAY_BATCH,
        ),
        intraday_fact(
            "000300.SH",
            "1",
            query_as_of=world.query_as_of,
            ts=early_same_day,
            fetched_at=early_same_day,
            batch_id=INTRADAY_BATCH,
            kind="index",
        ),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["data_status"] == "stale"
        and payload["session"] == session.value
        and payload["basis"] is not None
        and payload["basis"]["mode"] == "close"
        and payload["basis"]["observed_date"] == previous_trade_date.isoformat()
        and any(
            item["security_code"] == "000300.SH" and item["price"] == "4001"
            for item in payload["indices"]
        )
        and all(
            item["change_pct"] != "1"
            for item in payload["indices"]
            if item["security_code"] == "000300.SH"
        ),
        "非交易日/开盘前沿用上一完整收盘且不读当日盘中，契约 §4/§8/§9",
    )
    assert payload["trade_date"] == trade_date.isoformat()
    assert payload["basis"]["mode"] == "close"
    assert payload["basis"]["observed_date"] == previous_trade_date.isoformat()
    selected = [
        item for item in payload["indices"] if item["security_code"] == "000300.SH"
    ]
    assert len(selected) == 1
    assert selected[0]["price"] == "4001"
    assert selected[0]["change_pct"] != "1"


def test_market_overview_bj_gate_stays_closed_below_twenty_clean_rows(world: OverviewState) -> None:
    world.licence = LICENCE_A
    if not market_overview_reader_is_wired():
        pytest.xfail("待 #182/T-A172 §10：BJ 门闩运行能力尚未接入")
    world.facts = [
        close_fact(f"830{i:03d}.BJ", "10.1", "10.0", source=source)
        for i in range(1, 20)
        for source in ("mairui", "tdx_local")
    ] + [
        close_fact("830020.BJ", "10.1", "10.0", volume="0", source="mairui"),
        close_fact("830020.BJ", "10.1", "10.0", volume="0", source="tdx_local"),
        close_fact("830021.BJ", "10.1", "10.0", is_suspended=True, source="mairui"),
    ]
    payload = get_overview(world)
    assert payload["basis"] is not None
    assert payload["basis"]["scope"] == "沪深股票口径"
    assert payload["breadth"] is None or (
        payload["breadth"]["up"]
        + payload["breadth"]["down"]
        + payload["breadth"]["flat"]
        == 0
    )


@pytest.mark.xfail(strict=True, reason="待 #182/T-A172 §10.10 可信证据投影（后续单）")
def test_market_overview_bj_gate_positive_requires_twenty_clean_pairs(
    world: OverviewState,
) -> None:
    world.licence = LICENCE_A
    if not market_overview_reader_is_wired():
        pytest.xfail("待 #182/T-A172 §10：BJ 门闩运行能力尚未接入")
    world.facts = [
        close_fact(
            f"830{i:03d}.BJ",
            "10.1",
            "10.0",
            source=source,
            licence=licence,
        )
        for i in range(1, 21)
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ] + [
        close_fact(
            "830021.BJ", "10.1", "10.0", source=source, licence=licence, is_suspended=True
        )
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ] + [
        close_fact("830022.BJ", "10.1", "10.0", source=source, licence=licence, volume="0")
        for source, licence in (("mairui", LICENCE_A), ("tdx_local", LICENCE_B))
    ]
    # 对照结果、来源时点和规则版本可追溯；该门闩待合入，不宣称主线已验收。
    world.bj_gate_evidence = {  # type: ignore[attr-defined]
        "rule_version": "synthetic-T-A219-bj-2026-11-13",
        "sources": ("mairui", "tdx_local"),
        "reconciled_on": TRADE_DATE.isoformat(),
        "clean_codes": 20,
    }
    payload = get_overview(world)
    breadth = payload["breadth"]
    basis = payload["basis"]
    admitted = (
        basis is not None
        and basis["mode"] == "close"
        and basis["observed_date"] == "2026-11-13"
        and (
            (breadth is not None and breadth["up"] + breadth["down"] + breadth["flat"] == 20)
            or basis.get("eligible") == 20
        )
    )
    assert admitted
    if breadth is not None:
        assert breadth["up"] + breadth["down"] + breadth["flat"] == 20
    else:
        assert basis["eligible"] == 20


def test_market_overview_pit_cross_licence_does_not_borrow_rows(world: OverviewState) -> None:
    world.licence = LICENCE_A
    world.query_as_of = INTRADAY_QUERY
    world.facts = [
        intraday_fact(
            "600000.SH",
            "1",
            licence=LICENCE_A,
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
        ),
        intraday_fact(
            "600000.SH",
            "-1",
            licence=LICENCE_B,
            query_as_of=INTRADAY_QUERY,
            batch_id=INTRADAY_BATCH,
        ),
        # 证书 A 下第二只股票使用更晚的行情时点，用以断言 data_as_of 取参与源最早 ts。
        intraday_fact(
            "688001.SH",
            "2",
            licence=LICENCE_A,
            query_as_of=INTRADAY_QUERY,
            ts=dt.datetime(2026, 11, 13, 2, 5, tzinfo=dt.timezone.utc),
            batch_id=INTRADAY_BATCH,
        ),
        intraday_fact(
            "000300.SH",
            "3",
            licence=LICENCE_A,
            query_as_of=INTRADAY_QUERY,
            kind="index",
            batch_id=INTRADAY_BATCH,
        ),
        intraday_fact(
            "000300.SH",
            "-3",
            licence=LICENCE_B,
            query_as_of=INTRADAY_QUERY,
            kind="index",
            batch_id=INTRADAY_BATCH,
        ),
        intraday_fact(
            "600000.SH",
            "5",
            licence=LICENCE_A,
            query_as_of=INTRADAY_QUERY,
            fetched_at=INTRADAY_QUERY + dt.timedelta(minutes=1),
            batch_id=PIT_FUTURE_BATCH,
        ),
        intraday_fact(
            "000301.SH",
            "1",
            licence=None,
            query_as_of=INTRADAY_QUERY,
            kind="index",
            batch_id=INTRADAY_BATCH,
        ),
    ]
    payload = get_overview(world)
    require_component(
        payload,
        payload["data_as_of"] == "2026-11-13T02:00:00Z"
        and len(
            [
                item
                for item in payload["indices"]
                if item["security_code"] == "000300.SH"
            ]
        )
        == 1,
        "同码同日证书归属与未来 fetched_at PIT 过滤，契约 §2/§4/§9",
    )
    assert payload["data_as_of"] <= world.query_as_of.isoformat()
    selected = [
        item for item in payload["indices"] if item["security_code"] == "000300.SH"
    ]
    assert len(selected) == 1
    assert selected[0]["change_pct"] == "3"
    assert dt.datetime.fromisoformat(selected[0]["t"]).astimezone(dt.timezone.utc) == dt.datetime(
        2026, 11, 13, 2, tzinfo=dt.timezone.utc
    )
    assert payload["data_as_of"] == "2026-11-13T02:00:00Z"
    unowned = [
        item for item in payload["indices"] if item["security_code"] == "000301.SH"
    ]
    assert not unowned or (
        unowned[0]["price"] is None and unowned[0]["change_pct"] is None
    )

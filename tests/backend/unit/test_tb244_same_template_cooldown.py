"""T-B244 same-template cooldown contract tests with synthetic calendar rows."""

# Synthetic fakes intentionally use broad SQLAlchemy-compatible signatures.
# ruff: noqa: UP017

from __future__ import annotations

import datetime as dt
import inspect
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import candidate_signals
from app.common.errors import AppError, ErrorCode
from app.schemas.enums import REASON_CODE_TABLE, Action, DataStatus
from app.signals import service
from app.signals.models import MarketFacts, SignalInput
from app.workers import assembly
from sqlalchemy.sql.selectable import Select

USER = uuid.UUID("00000000-0000-4000-8000-000000000244")
VERSION = uuid.UUID("00000000-0000-4000-8000-000000000245")
BASE = dt.datetime(2026, 11, 2, 10, tzinfo=dt.timezone.utc)


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self) -> list[Any]:
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def one_or_none(self) -> Any | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None


class _CooldownConnection:
    def __init__(self, previous: dt.datetime | None, calendar: list[Any]) -> None:
        self.previous = previous
        self.calendar = calendar

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        if "candidate_signals" in str(statement):
            rows = [] if self.previous is None else [SimpleNamespace(created_at=self.previous)]
            return _Result(rows)
        return _Result(self.calendar)


def _calendar(*days: tuple[str, bool]) -> list[Any]:
    return [SimpleNamespace(date=dt.date.fromisoformat(day), is_open=open_) for day, open_ in days]


def _decision(
    previous: dt.datetime | None,
    candidate: dt.datetime,
    calendar: list[Any],
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    return service.same_template_cooldown(
        _CooldownConnection(previous, calendar),
        user_id=USER,
        security_code="600000.SH",
        strategy_version_id=VERSION,
        created_at=candidate,
        cooldown_days=3,
    )


def test_same_template_hit_has_beijing_expiry_and_release_shape() -> None:
    release, gap = _decision(
        BASE,
        dt.datetime(2026, 11, 3, 10, tzinfo=dt.timezone.utc),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", True),
            ("2026-11-04", True),
            ("2026-11-05", True),
        ),
    )
    assert gap is None
    assert release == {
        "kind": "time",
        "expr": None,
        "at": "2026-11-05T15:00:00+08:00",
        "event": None,
        "action": None,
        "check_on": ["schedule"],
        "human_text": "同模板同证券冷却至到期交易日15:00（北京时间）",
        "machine_checkable": True,
    }


def test_closed_calendar_days_do_not_consume_trading_day_quota() -> None:
    release, gap = _decision(
        BASE,
        dt.datetime(2026, 11, 5, 10, tzinfo=dt.UTC),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", False),
            ("2026-11-04", False),
            ("2026-11-05", True),
            ("2026-11-06", True),
            ("2026-11-07", True),
        ),
    )
    assert gap is None
    assert release is not None and release["at"] == "2026-11-07T15:00:00+08:00"


@pytest.mark.parametrize(
    "calendar",
    [
        [],
        _calendar(("2026-11-02", True), ("2026-11-03", True)),
    ],
)
def test_missing_or_insufficient_calendar_is_a_no_source_gap(calendar: list[Any]) -> None:
    release, gap = _decision(BASE, BASE + dt.timedelta(days=1), calendar)
    assert release is None
    assert gap is not None and gap["reason"] == "no_source"


def test_expired_window_does_not_block() -> None:
    release, gap = _decision(
        BASE,
        dt.datetime(2026, 11, 5, 7, tzinfo=dt.timezone.utc),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", True),
            ("2026-11-04", True),
            ("2026-11-05", True),
        ),
    )
    assert release is None and gap is None


def test_post_close_starts_from_next_open_day() -> None:
    release, gap = _decision(
        dt.datetime(2026, 11, 2, 8, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 3, 2, tzinfo=dt.UTC),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", True),
            ("2026-11-04", True),
            ("2026-11-05", True),
        ),
    )
    assert gap is None
    assert release is not None and release["at"] == "2026-11-05T15:00:00+08:00"


def test_intraday_starts_on_the_same_open_day() -> None:
    release, gap = _decision(
        dt.datetime(2026, 11, 2, 2, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 3, 2, tzinfo=dt.UTC),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", True),
            ("2026-11-04", True),
        ),
    )
    assert gap is None
    assert release is not None and release["at"] == "2026-11-04T15:00:00+08:00"


def test_pre_open_starts_on_the_same_open_day() -> None:
    release, gap = _decision(
        dt.datetime(2026, 11, 2, 0, tzinfo=dt.UTC),
        dt.datetime(2026, 11, 3, 2, tzinfo=dt.UTC),
        _calendar(
            ("2026-11-02", True),
            ("2026-11-03", True),
            ("2026-11-04", True),
        ),
    )
    assert gap is None
    assert release is not None and release["at"] == "2026-11-04T15:00:00+08:00"


def test_no_source_gap_is_in_snapshot_projection_once() -> None:
    content = SignalInput.model_construct(
        security_code="600000.SH",
        proposed_action=Action.BUY,
        snapshot_id=uuid.uuid4(),
        created_at=BASE,
        data_as_of=BASE,
        data_status=DataStatus.FRESH,
        gaps=[],
    )
    _, gap = _decision(BASE, BASE + dt.timedelta(days=1), [])
    assert gap is not None and gap["reason"] == "no_source"
    prepared = service.add_same_template_gap(content, gap)
    assert prepared.data_status == DataStatus.PARTIAL
    block = service.snapshot_items(prepared, MarketFacts(price=12.5))["data_status_block"]
    assert block["data_status"] == DataStatus.PARTIAL.value
    assert block["gaps"] == [gap]
    assert service.add_same_template_gap(prepared, gap).gaps == prepared.gaps

    source = inspect.getsource(assembly.conclusion)
    assert source.index("add_same_template_gap") < source.index("persist(conn, owner")


class _ScheduleConnection:
    def __init__(self, reason: Any, signal: Any) -> None:
        self.reason = reason
        self.signal = signal
        self.statements: list[Any] = []

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        self.statements.append(statement)
        sql = str(statement)
        if isinstance(statement, Select):
            if "candidate_signals" in sql:
                return _Result([self.signal])
            if "non_executable_reasons" in sql and statement._for_update_arg is None:
                return _Result([SimpleNamespace(signal_id=self.signal.id)])
            if "non_executable_reasons" in sql:
                return _Result([self.reason])
            return _Result([])
        return _Result([])


def test_schedule_release_locks_candidate_before_reason() -> None:
    signal = SimpleNamespace(id=uuid.uuid4(), user_id=USER, state="blocked")
    reason = SimpleNamespace(
        id=uuid.uuid4(),
        signal_id=signal.id,
        user_id=USER,
        release_condition={
            "kind": "time",
            "at": "2026-11-22T15:00:00+08:00",
            "check_on": ["schedule"],
        },
    )
    connection = _ScheduleConnection(reason, signal)
    assert service.release_due_schedule_reasons(
        connection, user_id=USER, at=dt.datetime(2026, 11, 23, tzinfo=dt.UTC)
    ) == [reason.id]
    locked = [
        statement
        for statement in connection.statements
        if isinstance(statement, Select) and statement._for_update_arg is not None
    ]
    assert "candidate_signals" in str(locked[0])
    assert "non_executable_reasons" in str(locked[1])


def test_different_template_or_security_has_no_predecessor() -> None:
    release, gap = _decision(None, BASE + dt.timedelta(days=1), [])
    assert release is None and gap is None


def test_reason_is_machine_checkable_and_not_manually_releasable() -> None:
    spec = next(item for item in REASON_CODE_TABLE if item.code.value == "SAME_TEMPLATE_COOLDOWN")
    assert spec.manually_releasable is False
    assert service.same_template_release(BASE + dt.timedelta(days=1))["machine_checkable"] is True
    reason = SimpleNamespace(
        id=uuid.uuid4(),
        signal_id=uuid.uuid4(),
        user_id=USER,
        status="active",
        machine_checkable=True,
        release_condition={"kind": "time", "at": "2099-01-01T15:00:00+08:00", "check_on": ["schedule"]},
    )
    signal = SimpleNamespace(id=reason.signal_id, state="blocked")

    class _ReleaseConnection:
        def __init__(self) -> None:
            self.selects = 0

        def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
            if not isinstance(statement, Select):
                return _Result([])
            sql = str(statement)
            if "candidate_signals" in sql:
                return _Result([signal])
            if "non_executable_reasons" in sql:
                self.selects += 1
                if "signal_id" in sql and self.selects == 1:
                    return _Result([SimpleNamespace(signal_id=reason.signal_id)])
                return _Result([reason])
            return _Result([])

    class _Engine:
        def begin(self) -> Any:
            connection = _ReleaseConnection()

            class _Context:
                def __enter__(self) -> _ReleaseConnection:
                    return connection

                def __exit__(self, *_args: object) -> None:
                    return None

            return _Context()

    with pytest.raises(AppError) as caught:
        candidate_signals.release_reason(
            reason.id,
            SimpleNamespace(confirm=True, note=None),
            SimpleNamespace(user_id=USER),
            _Engine(),
        )
    assert caught.value.code == ErrorCode.REASON_NOT_MANUALLY_RELEASABLE


def test_restriction_recheck_does_not_include_same_template_cooldown() -> None:
    assert "SAME_TEMPLATE_COOLDOWN" not in service.RESTRICTION_REASON_CODES.values()


def test_write_candidate_persists_same_template_reason(monkeypatch: Any) -> None:
    snapshot_id, account_id, instance_id, version_id, strategy_id = (uuid.uuid4() for _ in range(5))
    content = SignalInput.model_validate(
        {
            "security_code": "600000.SH",
            "proposed_action": "buy",
            "t_leg": None,
            "score": 80,
            "confidence": {"level": "high", "value": "0.8"},
            "stops": {"stop_loss": None, "take_profit": None, "time_stop_days": None},
            "rule_refs": [
                {
                    "rule_id": "R1",
                    "snippet_id": None,
                    "snippet_version": None,
                    "role": "entry",
                    "dimension": "technical",
                    "passed": True,
                    "value": None,
                    "threshold": "f.close_qfq > 0",
                    "evidence_ids": ["e1"],
                }
            ],
            "evidence": [
                {
                    "id": "e1",
                    "key": "f.close_qfq",
                    "value": 12.5,
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "data_as_of": BASE,
                    "fetched_at": BASE,
                    "epistemic_type": "fact",
                }
            ],
            "counter_evidence": [{"text": "counter", "expr": None, "evidence_ids": ["e1"]}],
            "invalidation": [{"text": "invalid", "expr": None, "evidence_ids": ["e1"]}],
            "model_refs": [],
            "risk_flags": [],
            "valid_until": None,
            "snapshot_id": snapshot_id,
            "feature_set_version": "synthetic",
            "created_at": BASE,
            "data_status": "fresh",
            "data_as_of": BASE,
            "gaps": [],
        }
    )
    instance = SimpleNamespace(
        id=instance_id,
        user_id=USER,
        status="active",
        derived_strategy_version_id=None,
        strategy_version_id=version_id,
        scope="account",
        security_code=None,
        account_id=account_id,
        horizon="short",
    )
    version = SimpleNamespace(
        id=version_id,
        strategy_id=strategy_id,
        lifecycle="published",
        config={
            "universe": {"pool": "持仓 ∪ 自选", "security_types": ["stock"], "boards": {"main": True}},
            "spec": {"rules": [{"id": "R1", "role": "entry", "dimension": "technical", "expr": "f.close_qfq > 0"}]},
        },
        card_version_id=None,
    )
    snapshot = SimpleNamespace(
        id=snapshot_id,
        licence_id=None,
        created_at=BASE - dt.timedelta(minutes=1),
        items=service.snapshot_items(content, MarketFacts(price=12.5)),
    )
    responses = [
        _WriteResult(scalar="approved"),
        _WriteResult(),
        _WriteResult([instance]),
        _WriteResult([version]),
        _WriteResult(scalar=USER),
        _WriteResult(scalar="user"),
        _WriteResult([SimpleNamespace(id=account_id)]),
        _WriteResult([snapshot]),
        _WriteResult([uuid.uuid4()]),
        _WriteResult(scalar=None),
        _WriteResult([SimpleNamespace(type="stock", board="main", risk_flag=None)]),
        _WriteResult(),
        _WriteResult(),
        _WriteResult(),
        _WriteResult(),
    ]
    connection = _WriteConnection(responses)
    captured: list[str] = []
    cooldown_days: list[int] = []
    monkeypatch.setattr(service, "run_with_master_guard", lambda _conn, **kwargs: (None, kwargs["operation"](_conn)))
    monkeypatch.setattr("app.strategy.runtime.runnable", lambda _lifecycle, _role: True)
    monkeypatch.setattr("app.api.v1.portfolio._account", lambda *_args: SimpleNamespace(positions={}, cash=10000))
    monkeypatch.setattr(service, "lot_spec", lambda *_args, **_kwargs: SimpleNamespace(min_buy=100))
    monkeypatch.setattr(service, "board_in_universe", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(service, "calendar_state", lambda *_args, **_kwargs: (True, None))
    monkeypatch.setattr(service, "assess", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(service, "live_snapshots", lambda _id: SimpleNamespace(order_by=lambda _order: SimpleNamespace(limit=lambda _limit: object())))
    monkeypatch.setattr(
        service,
        "same_template_cooldown",
        lambda *_args, **kwargs: (
            cooldown_days.append(kwargs["cooldown_days"])
            or service.same_template_release(BASE + dt.timedelta(days=1)),
            None,
        ),
    )
    monkeypatch.setattr(
        service,
        "get_settings",
        lambda: SimpleNamespace(business=SimpleNamespace(risk_controls=SimpleNamespace())),
    )
    monkeypatch.setattr(
        service,
        "effective_config",
        lambda *_args: SimpleNamespace(
            executability=SimpleNamespace(same_template_cooldown_days=5)
        ),
    )
    monkeypatch.setattr(service, "add_reason", lambda _conn, **kwargs: captured.append(kwargs["code"]))
    result = service.write_candidate(
        connection,
        user_id=USER,
        instance_id=instance_id,
        content=content,
        facts=MarketFacts(price=12.5),
        market_rules=SimpleNamespace(segment_for=lambda _day: SimpleNamespace()),
    )
    assert result["diagnostic"] == "blocked"
    assert "SAME_TEMPLATE_COOLDOWN" in captured
    assert cooldown_days == [5]


class _WriteResult:
    def __init__(self, rows: list[Any] | None = None, scalar: Any = None) -> None:
        self.rows, self.scalar = rows or [], scalar

    def all(self) -> list[Any]:
        return self.rows

    def __iter__(self):
        return iter(self.rows)

    def one(self) -> Any:
        return self.rows[0]

    def one_or_none(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def first(self) -> Any | None:
        return self.rows[0] if self.rows else None

    def scalar_one(self) -> Any:
        return self.scalar

    def scalar_one_or_none(self) -> Any | None:
        return self.scalar

    def scalars(self) -> _WriteResult:
        return self


class _WriteConnection:
    def __init__(self, responses: list[_WriteResult]) -> None:
        self.responses = responses

    def execute(self, _statement: Any, *_args: Any, **_kwargs: Any) -> _WriteResult:
        return self.responses.pop(0) if self.responses else _WriteResult()

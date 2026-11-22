"""T-B244 same-template cooldown contract tests with synthetic calendar rows."""

# Synthetic fakes intentionally use broad SQLAlchemy-compatible signatures.
# ruff: noqa: UP017

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1 import candidate_signals
from app.common.errors import AppError, ErrorCode
from app.schemas.enums import REASON_CODE_TABLE
from app.signals import service
from app.signals.models import MarketFacts, SignalInput
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
        _calendar(("2026-11-02", True), ("2026-11-03", True), ("2026-11-04", True)),
    )
    assert gap is None
    assert release == {
        "kind": "time",
        "expr": None,
        "at": "2026-11-04T15:00:00+08:00",
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
    assert release is not None and release["at"] == "2026-11-06T15:00:00+08:00"


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
        dt.datetime(2026, 11, 4, 7, tzinfo=dt.timezone.utc),
        _calendar(("2026-11-02", True), ("2026-11-03", True), ("2026-11-04", True)),
    )
    assert release is None and gap is None


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
            self.selects += 1
            return _Result([reason] if self.selects in {1, 2} else [signal])

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
        lambda *_args, **_kwargs: (service.same_template_release(BASE + dt.timedelta(days=1)), None),
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

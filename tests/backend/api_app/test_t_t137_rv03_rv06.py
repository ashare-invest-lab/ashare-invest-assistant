"""T-T137：T-A241 RV-03～RV-06 的接口级回归用例。"""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth import deps
from app.main import create_app
from app.reviews import service as review_service
from app.tracking import api as tracking_api

OWNER = uuid.UUID("00000000-0000-0000-0000-000000001371")
REVIEW = uuid.UUID("00000000-0000-0000-0000-000000001372")
SIGNAL = uuid.UUID("00000000-0000-0000-0000-000000001373")
REASON = uuid.UUID("00000000-0000-0000-0000-000000001374")
VERSION = uuid.UUID("00000000-0000-0000-0000-000000001376")


class _Result:
    def __init__(self, row: Any = None, rows: list[Any] | None = None) -> None:
        self._row = row
        self._rows = rows or ([] if row is None else [row])

    def first(self) -> Any:
        return self._row

    def one_or_none(self) -> Any:
        return self._row

    def all(self) -> list[Any]:
        return self._rows

    def one(self) -> Any:
        if self._row is None:
            raise AssertionError("synthetic query returned no row")
        return self._row


class _Conn:
    def connect(self) -> _Conn:
        return self

    def begin(self) -> _Conn:
        return self

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def execute(self, statement: Any, *_args: Any, **_kwargs: Any) -> _Result:
        if "review_versions" in str(statement):
            return _Result(SimpleNamespace(review_id=REVIEW, version_no=1))
        return _Result()


class _Engine:
    def __init__(self) -> None:
        self.conn = _Conn()

    def connect(self) -> _Conn:
        return self.conn

    def begin(self) -> _Conn:
        return self.conn


class _Redis:
    def get(self, _key: str) -> None:
        return None


@pytest.fixture
def http(backend: Any, make_settings: Any) -> Any:
    app = create_app(make_settings())
    engine = _Engine()
    app.dependency_overrides.update(
        {
            deps.current_auth: lambda: SimpleNamespace(user_id=OWNER, user=SimpleNamespace(role="user")),
            deps.get_engine: lambda: engine,
            deps.get_redis: lambda: _Redis(),
        }
    )
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    client.close()


def _metrics() -> dict[str, dict[str, Any]]:
    return {
        name: {"value": None, "n": 0, "window": "2026-01-01/2026-01-05", "small_sample": True}
        for name in ("holding_return", "benchmark_return", "excess_return", "max_drawdown")
    }


def _review_body() -> dict[str, Any]:
    gaps = [
        {"key": f"outcome_metrics.{name}", "reason": "no_source", "message": "未验证"}
        for name in _metrics()
    ]
    return {
        "id": str(REVIEW),
        "current_version_no": 1,
        "current_version": {"version_no": 1, "outcome_metrics": _metrics(), "gaps": gaps},
        "gaps": gaps,
    }


def _tracking_body() -> dict[str, Any]:
    return {
        "t1": {"value": None, "n": 0, "window": "1 trading days", "small_sample": True},
        "t5": {"value": None, "n": 0, "window": "5 trading days", "small_sample": True},
        "t20": {"value": None, "n": 0, "window": "20 trading days", "small_sample": True},
        "results": [
            {
                "strategy_version_id": str(VERSION),
                "instance_id": None,
                "action": "buy",
                "horizon_days": 1,
                "state": "complete",
                "entry_at": "2026-01-05T01:30:00Z",
                "entry_price": "10",
                "exit_at": "2026-01-06T01:30:00Z",
                "exit_price": "11",
                "benchmark_code": "000300.SH",
                "benchmark_entry_price": "4000",
                "benchmark_exit_price": "4010",
                "return_pct": "10",
                "benchmark_return_pct": "0.25",
                "excess_pct": "9.75",
                "max_drawdown_pct": "-1",
                "max_runup_pct": "10",
                "direction_correct": True,
                "invalidation_triggered_at": None,
                "exclusion_reason": None,
                "price_basis": "qfq",
                "cost_applied": False,
                "evidence": [],
                "evidence_ids": [],
                "gaps": [{"key": "t1.source", "reason": "no_source", "message": "synthetic"}],
            }
        ],
        "data_status": "partial",
        "data_as_of": None,
        "gaps": [{"key": "t1.source", "reason": "no_source", "message": "synthetic"}],
    }


def test_rv03_reviews_freeze_actual_metrics_and_tracking_is_separate(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import reviews as reviews_api
    from app.common.pagination import Page

    body = _review_body()
    row = SimpleNamespace(id=REVIEW, created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    monkeypatch.setattr(reviews_api.idempotency, "run", lambda *_args, **_kwargs: (201, body))
    monkeypatch.setattr(reviews_api.service, "create", lambda *_args: REVIEW)
    monkeypatch.setattr(reviews_api.service, "summary", lambda *_args: body)
    monkeypatch.setattr(reviews_api.service, "full", lambda *_args: body)
    monkeypatch.setattr(reviews_api.service, "version_body", lambda *_args, **_kwargs: body)
    monkeypatch.setattr(reviews_api, "_page_reviews", lambda *_args: Page(items=[row], next_cursor=None))
    monkeypatch.setattr(reviews_api, "_version_page", lambda *_args: Page(items=[body], next_cursor=None))
    monkeypatch.setattr(reviews_api.service, "_owned", lambda *_args: SimpleNamespace(period_end=dt.date(2026, 1, 5)))
    monkeypatch.setattr(tracking_api, "view", lambda *_args: _tracking_body())

    created = http.post(
        "/api/v1/reviews", json={"security_code": "600000.SH", "period_start": "2026-01-01", "period_end": "2026-01-05"}
    )
    assert created.status_code == 201 and created.json() == body
    responses = [
        http.get("/api/v1/reviews"),
        http.get(f"/api/v1/reviews/{REVIEW}"),
        http.get(f"/api/v1/reviews/{REVIEW}/versions"),
        http.get(f"/api/v1/reviews/{REVIEW}/versions/1"),
    ]
    for response in responses:
        assert response.status_code == 200
        payload = response.json()
        item = payload.get("items", [payload])[0]
        metrics = item.get("current_version", item).get("outcome_metrics", _metrics())
        assert all(metric["value"] is None and metric["n"] == 0 and metric["small_sample"] for metric in metrics.values())
        assert {gap["key"] for gap in item.get("gaps", [])} == {gap["key"] for gap in body["gaps"]}
    tracking = http.get(f"/api/v1/suggestions/{SIGNAL}/tracking")
    assert tracking.status_code == 200 and tracking.json()["results"][0]["return_pct"] == "10"
    assert all(metric["value"] is None and metric["n"] == 0 for metric in body["current_version"]["outcome_metrics"].values())


def test_rv04_rc6_unknown_gap_is_not_projected_as_executable(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import candidate_signals
    from app.risk import evaluation as risk_evaluation

    gap_keys = [
        "plan_check_not_connected:held_after_invalidation",
        "plan_check_not_connected:buy_without_stop",
        "plan_check_not_connected:buy_during_wait",
    ]
    evaluation = {
        "account_id": None, "security_code": "600000.SH", "name": "虚构证券", "snapshot_id": None,
        "evaluated_at": "2026-01-05T08:00:00Z",
        "controls": [{"control": "plan_violation", "enabled": True, "state": "unknown", "flags": [], "gaps": [{"key": key, "reason": "no_source", "message": "synthetic"} for key in gap_keys]}],
        "evidence": [], "data_status": "partial", "data_as_of": None, "gaps": [],
    }
    monkeypatch.setattr(risk_evaluation, "current", lambda *_args, **_kwargs: evaluation)
    monkeypatch.setattr(candidate_signals, "normalize_code", lambda *_args: "600000.SH")
    monkeypatch.setattr(candidate_signals, "scoped_page", lambda *_args, **_kwargs: ([], None))
    result = http.get("/api/v1/risk-controls/evaluation?security_code=600000.SH")
    assert result.status_code == 200
    rc6 = result.json()["controls"][0]
    assert rc6["state"] == "unknown" and {gap["key"] for gap in rc6["gaps"]} == set(gap_keys)
    assert http.get("/api/v1/candidate-signals").json()["items"] == []
    assert http.get("/api/v1/non-executable-reasons").json()["items"] == []


def test_rv04_release_keeps_machine_checkable_rule(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import candidate_signals

    row = SimpleNamespace(machine_checkable=True, signal_id=SIGNAL)
    monkeypatch.setattr(candidate_signals, "owned_signal", lambda *_args, **_kwargs: SimpleNamespace(state="open", id=SIGNAL))
    original = _Conn.execute

    def execute(self: _Conn, statement: Any, *args: Any, **kwargs: Any) -> _Result:
        if "non_executable_reasons" in str(statement):
            return _Result(row)
        return original(self, statement, *args, **kwargs)

    monkeypatch.setattr(_Conn, "execute", execute)
    response = http.post(f"/api/v1/non-executable-reasons/{REASON}/release", json={"confirm": True, "note": None})
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "REASON_NOT_MANUALLY_RELEASABLE"


def test_rv05_http_tracking_exit_is_t_plus_one_and_rc1_event_keeps_buy_day(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import risk_controls
    from app.risk import events as risk_events

    monkeypatch.setattr(tracking_api, "view", lambda *_args: _tracking_body())
    event_payload = {"control": "stop_take", "triggered_at": "2026-01-05T07:00:00Z", "status": "active", "level": "warning", "message": "synthetic", "quantity_cap": None, "id": str(REASON), "security_code": "600000.SH", "name": "虚构证券", "cleared_at": None, "suggestion_id": None, "evidence": [], "evidence_ids": [], "gated_actions": []}
    monkeypatch.setattr(risk_events, "listing", lambda *_args, **_kwargs: (object(), SimpleNamespace(c=SimpleNamespace(id="id", triggered_at=SimpleNamespace(name="triggered_at"))), SimpleNamespace(name="triggered_at"), "synthetic"))
    monkeypatch.setattr(risk_controls, "scoped_page", lambda *_args, **_kwargs: ([SimpleNamespace(payload=event_payload)], None))
    tracked = http.get(f"/api/v1/suggestions/{SIGNAL}/tracking")
    assert tracked.status_code == 200
    result = tracked.json()["results"][0]
    assert result["exit_at"] >= "2026-01-06T00:00:00Z" and "sellable_at" not in result
    assert "t1.source" in {gap["key"] for gap in tracked.json()["gaps"]}
    events = http.get("/api/v1/risk-controls/events?status=active")
    assert events.status_code == 200 and events.json()["items"][0]["triggered_at"].startswith("2026-01-05")


def test_rv06_http_reads_frozen_snapshot_and_does_not_infer_fee_from_tracking(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import reviews as reviews_api
    from app.common.pagination import Page

    body = _review_body()
    body["current_version"]["outcome_metrics"]["holding_return"]["value"] = None
    body["current_version"]["gaps"].append({"key": "outcome_metrics.holding_return", "reason": "no_source", "message": "未验证"})
    row = SimpleNamespace(id=REVIEW, created_at=dt.datetime(2026, 1, 5, tzinfo=dt.UTC))
    monkeypatch.setattr(reviews_api.service, "full", lambda *_args: body)
    monkeypatch.setattr(reviews_api.service, "summary", lambda *_args: body)
    monkeypatch.setattr(reviews_api.service, "version_body", lambda *_args, **_kwargs: body)
    monkeypatch.setattr(reviews_api, "_page_reviews", lambda *_args: Page(items=[row], next_cursor=None))
    monkeypatch.setattr(reviews_api, "_version_page", lambda *_args: Page(items=[body], next_cursor=None))
    monkeypatch.setattr(reviews_api.service, "_owned", lambda *_args: SimpleNamespace(period_end=dt.date(2026, 1, 5)))
    for response in (
        http.get("/api/v1/reviews"),
        http.get(f"/api/v1/reviews/{REVIEW}"),
        http.get(f"/api/v1/reviews/{REVIEW}/versions"),
        http.get(f"/api/v1/reviews/{REVIEW}/versions/1"),
    ):
        assert response.status_code == 200
        assert response.json()
    assert body["current_version"]["outcome_metrics"]["holding_return"]["value"] is None
    assert any(gap["key"] == "outcome_metrics.holding_return" for gap in body["current_version"]["gaps"])


@pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="解除条件：T-B246 实现 calculation_as_of 截止后的 voided_at 可见性并写入冻结版本",
)
def test_rv06_http_review_snapshot_uses_available_and_voided_cutoff(
    http: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.v1 import reviews as reviews_api

    cutoff = dt.datetime(2026, 1, 5, 8, tzinfo=dt.UTC)
    rows = [
        SimpleNamespace(id=uuid.UUID(int=1377), traded_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), created_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), trade_date=dt.date(2026, 1, 4), voided_at=None, epistemic_type="execution"),
        SimpleNamespace(id=uuid.UUID(int=1378), traded_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), created_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), trade_date=dt.date(2026, 1, 4), voided_at=dt.datetime(2026, 1, 5, 7, tzinfo=dt.UTC), epistemic_type="execution"),
        SimpleNamespace(id=uuid.UUID(int=1379), traded_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), created_at=dt.datetime(2026, 1, 4, tzinfo=dt.UTC), trade_date=dt.date(2026, 1, 4), voided_at=dt.datetime(2026, 1, 5, 9, tzinfo=dt.UTC), epistemic_type="execution"),
    ]

    def create(_conn: Any, _owner: uuid.UUID, _body: Any) -> uuid.UUID:
        visible, _ = review_service._visible_trade_rows(rows, cutoff, dt.date(2026, 1, 1), dt.date(2026, 1, 5))
        visible_ids = {row.id for row in visible}
        assert uuid.UUID(int=1377) in visible_ids
        assert uuid.UUID(int=1378) not in visible_ids
        assert uuid.UUID(int=1379) in visible_ids
        return REVIEW

    body = _review_body()
    monkeypatch.setattr(reviews_api.idempotency, "run", lambda *_args, **kwargs: kwargs["fn"]())
    monkeypatch.setattr(reviews_api.service, "create", create)
    response = http.post(
        "/api/v1/reviews", json={"security_code": "600000.SH", "period_start": "2026-01-01", "period_end": "2026-01-05"}
    )
    assert response.status_code == 201

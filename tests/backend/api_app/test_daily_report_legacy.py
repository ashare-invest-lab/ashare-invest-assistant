"""Offline coverage of the public read projection for archived daily reports."""

from __future__ import annotations

import datetime as dt
from contextlib import nullcontext
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import UUID

import pytest

pytestmark = pytest.mark.unit


def test_daily_report_projects_legacy_account_without_cash(backend, make_client, make_settings, monkeypatch):
    from app.auth import deps

    day = dt.date(2026, 10, 30)
    generated = dt.datetime(2026, 10, 30, 10, tzinfo=dt.UTC)
    existing_gap = {"key": "market", "reason": "no_source", "message": "Synthetic market gap"}
    archived = {
        "date": day.isoformat(),
        "generated_at": generated.isoformat(),
        "account_id": str(UUID(int=2)),
        "market": {"regime": None, "regime_position_range": None, "breadth": None, "summary": []},
        "account": {"total_assets": "125.00", "position_pct": None, "pnl_day": None, "position_vs_regime": None},
        "reconciliation": {"status": "not_imported", "as_of": None, "diff_count": 0, "important_count": 0},
        "stocks": [],
        "pending": {"plan_drafts": 0, "active_reasons": 0},
        "explanation": {"source": "template", "text": "Synthetic report", "llm_call_id": None},
        "evidence": [],
        "data_status": "unavailable",
        "data_as_of": None,
        "gaps": [existing_gap],
    }
    frozen = deepcopy(archived)
    row = SimpleNamespace(body=archived, generated_at=generated)
    execute = Mock(return_value=SimpleNamespace(first=lambda: row))
    connection = SimpleNamespace(execute=execute)

    app = backend.main.create_app(make_settings())
    monkeypatch.setitem(app.dependency_overrides, deps.current_auth, lambda: SimpleNamespace(user_id=UUID(int=1)))
    monkeypatch.setitem(app.dependency_overrides, deps.get_engine, lambda: SimpleNamespace(connect=lambda: nullcontext(connection)))
    response = make_client(app=app).get(f"/api/v1/daily-reports/{day.isoformat()}")

    assert response.status_code == 200, response.text
    report = response.json()
    assert report["date"] == day.isoformat()
    assert report["account_id"] == frozen["account_id"]
    assert report["account"] is None
    assert report["gaps"][:1] == frozen["gaps"]
    assert [(gap["key"], gap["reason"]) for gap in report["gaps"][1:]] == [("account", "no_source")]
    assert archived == frozen
    execute.assert_called_once()
    assert execute.call_args.args[0].is_select

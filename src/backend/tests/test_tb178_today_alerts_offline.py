"""Today alert evidence and pagination behavior without a PostgreSQL dependency."""

# ruff: noqa: S101
from __future__ import annotations

import datetime as dt
import json
import socket
import uuid
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, Mock

import pytest
from pydantic import ValidationError
from sqlalchemy import Connection, Select

from app.aggregates import models, products
from app.common.errors import AppError, ErrorCode
from app.db.tables.research import alerts
from app.strategy.reviews import COMPLIANCE_TERMS

OWNER = uuid.UUID(int=178)
AT = dt.datetime(2020, 1, 2, 8, tzinfo=dt.UTC)


@pytest.fixture(autouse=True)
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    denied = Mock(side_effect=AssertionError("Offline alerts must not connect to services"))
    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)


def alert(number: int, *, account: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.UUID(int=number),
        rule_id=uuid.UUID(int=1000 + number),
        user_id=OWNER,
        severity="attention",
        status="new",
        security_code=None if account else "999991.SH",
        triggered_at=AT,
        data_as_of=AT,
        affected=[],
        checklist=[],
        snapshot_id=None,
        handled_at=None,
        what_happened={
            "origin": "user_custom",
            "name": "合成提醒",
            "title": "已有事件的离线展示",
            "evidence_ids": ["local"],
            "evidence": [
                {
                    "id": "local",
                    "key": "synthetic.event",
                    "value": number,
                    "unit": None,
                    "provider": "system",
                    "endpoint": None,
                    "data_as_of": AT.isoformat(),
                    "fetched_at": AT.isoformat(),
                    "epistemic_type": "fact",
                }
            ],
        },
    )


def connection(rows: list[SimpleNamespace]) -> tuple[MagicMock, list[int]]:
    """Supply SQL-ordered pages; all other product sources are empty."""
    conn = MagicMock(spec=Connection)
    offsets: list[int] = []

    def execute(statement: Select[Any]) -> MagicMock:
        result = MagicMock()
        result.all.return_value = []
        result.scalar_one.return_value = 0
        if statement.get_final_froms()[0] is alerts:
            assert OWNER in statement.compile().params.values()
            offset = (
                int(statement._offset_clause.value) if statement._offset_clause is not None else 0
            )
            limit = (
                int(statement._limit_clause.value)
                if statement._limit_clause is not None
                else len(rows)
            )
            offsets.append(offset)
            page = rows[offset : offset + limit]
            result.all.return_value = page
            result.__iter__.side_effect = lambda: iter(page)
            result.__enter__.return_value = result
        return result

    conn.execute.side_effect = execute
    return conn, offsets


def today_payload(block: models.ProductBlock[models.TodayAlert], evidence: list[Any]) -> str:
    empty = {"items": [], "more": False}
    return json.dumps(
        {
            "data_status": "partial",
            "data_as_of": None,
            "gaps": [],
            "account_id": None,
            "server_time": AT.isoformat(),
            "trade_date": AT.date().isoformat(),
            "session": "non_trading_day",
            "market": {"regime": None, "regime_position_range": None, "data_status": "unavailable"},
            "focus": empty,
            "pending_plan_drafts": empty,
            "released_reasons": empty,
            "risk_flags": empty,
            "invalidations_today": empty,
            "daily_report": {"date": AT.date().isoformat(), "status": "not_yet"},
            "reconciliation": {
                "status": "not_imported",
                "as_of": None,
                "diff_count": 0,
                "important_count": 0,
            },
            "unread_notifications": 0,
            "alerts": block.model_dump(mode="json"),
            "plan_triggers": empty,
            "data_gaps": empty,
            "evidence": [item.model_dump(mode="json") for item in evidence],
        }
    )


@pytest.mark.parametrize("account", [False, True])
def test_shared_local_evidence_resolves_to_its_own_alert(account: bool) -> None:
    rows = [alert(1, account=account), alert(2, account=account)]
    rows[1].status = "read"
    conn, offsets = connection(rows)

    block, evidence, skipped = products.today_alerts(conn, OWNER)
    response = models.Today.model_validate_json(today_payload(block, evidence))

    assert offsets == [0]
    assert not skipped
    assert not block.more
    assert [item.id for item in response.alerts.items] == [row.id for row in rows]
    assert [item.status for item in response.alerts.items] == ["new", "read"]
    lookup = {item.id: item for item in response.evidence}
    assert len(lookup) == 2
    for number, item in enumerate(response.alerts.items, 1):
        assert len(item.evidence_ids) == 1
        assert lookup[item.evidence_ids[0]].value == number
        assert item.name == (None if account else "合成提醒")
        assert item.security_code == (None if account else "999991.SH")
    assert set(block.items[0].evidence_ids).isdisjoint(block.items[1].evidence_ids)
    assert all(row.what_happened["evidence_ids"] == ["local"] for row in rows)


@pytest.mark.parametrize(
    "fault", ["empty_ids", "unresolved", "missing_evidence", "invalid_evidence"]
)
def test_unrenderable_alert_does_not_hide_valid_alert_and_has_one_gap(fault: str) -> None:
    bad, good = alert(10), alert(11)
    if fault == "empty_ids":
        bad.what_happened["evidence_ids"] = []
    elif fault == "unresolved":
        bad.what_happened["evidence_ids"] = ["local", "absent"]
    elif fault == "missing_evidence":
        bad.what_happened["evidence"] = None
    else:
        bad.what_happened["evidence"] = [{"id": "local"}]
    conn, _ = connection([bad, good])

    result = products.blocks(conn, OWNER, None, AT, AT.date(), {}, {}, [])

    assert [item.id for item in result["alerts"].items] == [good.id]
    assert not result["alerts"].more
    assert len(result["evidence"]) == 1
    gaps = [(key, message) for key, message in result["gaps"] if key == "alerts"]
    assert len(gaps) == 1
    assert "证据" in gaps[0][1]
    assert result["alerts"].items[0].evidence_ids == [result["evidence"][0].id]


@pytest.mark.parametrize("valid_count", [50, 51])
def test_refill_uses_displayable_items_for_more_and_does_not_leak_hidden_evidence(
    valid_count: int,
) -> None:
    bad = alert(900)
    bad.what_happened["evidence_ids"] = []
    good = [alert(number) for number in range(1, valid_count + 1)]
    conn, offsets = connection([bad, *good])

    block, evidence, skipped = products.today_alerts(conn, OWNER)

    assert offsets == [0]
    assert conn.execute.call_count == 1
    assert skipped
    assert [item.id for item in block.items] == [row.id for row in good[:50]]
    assert block.more is (valid_count > 50)
    assert {item.value for item in evidence} == set(range(1, 51))
    assert {identifier for item in block.items for identifier in item.evidence_ids} == {
        item.id for item in evidence
    }


@pytest.mark.parametrize(
    ("fault", "message"),
    [
        ("account_name", "account_alert_name_must_be_null"),
        ("unresolved", "unresolved_evidence"),
        ("empty_ids", "at least 1 item"),
    ],
)
def test_today_response_rejects_inconsistent_alerts(fault: str, message: str) -> None:
    conn, _ = connection([alert(20)])
    block, evidence, _ = products.today_alerts(conn, OWNER)
    payload = json.loads(today_payload(block, evidence))
    if fault == "account_name":
        payload["alerts"]["items"][0]["security_code"] = None
    elif fault == "unresolved":
        payload["evidence"] = []
    else:
        payload["alerts"]["items"][0]["evidence_ids"] = []

    with pytest.raises(ValidationError, match=message):
        models.Today.model_validate_json(json.dumps(payload))


def test_no_alert_records_mean_no_alert_gap_or_evidence() -> None:
    conn, _ = connection([])

    result = products.blocks(conn, OWNER, None, AT, AT.date(), {}, {}, [])

    assert result["alerts"].model_dump(mode="json") == {"items": [], "more": False}
    assert result["evidence"] == []
    assert not any(key == "alerts" for key, _ in result["gaps"])


@pytest.mark.parametrize("term", COMPLIANCE_TERMS)
@pytest.mark.parametrize("template", ["发生{term}事件", "不{term}", "引用“{term}”"])
def test_today_alert_title_uses_real_compliance_lint(term: str, template: str) -> None:
    row = alert(1)
    row.what_happened["title"] = template.format(term=term)
    conn, _ = connection([row])

    with pytest.raises(AppError) as caught:
        products.today_alerts(conn, OWNER)

    assert caught.value.code is ErrorCode.COMPLIANCE_LINT_FAILED
    assert caught.value.details == {"terms": [term]}
    assert conn.execute.call_count == 1


@pytest.mark.parametrize("invalid_count", [0, 1, 51, 300])
@pytest.mark.parametrize("valid_count", [0, 50, 51])
def test_alert_select_count_independent_of_invalid_and_displayable_rows(
    invalid_count: int,
    valid_count: int,
) -> None:
    invalid = [alert(1000 + index) for index in range(invalid_count)]
    for row in invalid:
        row.what_happened["evidence_ids"] = []
    valid = [alert(index + 1) for index in range(valid_count)]
    conn, offsets = connection([*invalid, *valid])

    block, evidence, skipped = products.today_alerts(conn, OWNER)

    assert conn.execute.call_count == 1
    assert offsets == [0]
    assert skipped is bool(invalid_count)
    assert [item.id for item in block.items] == [row.id for row in valid[:50]]
    assert block.more is (valid_count > 50)
    assert len(evidence) == min(valid_count, 50)
    statement = conn.execute.call_args.args[0]
    assert statement.is_select
    assert statement._offset_clause is None
    assert statement.get_execution_options()["yield_per"] == 128


@pytest.mark.parametrize("invalid_count", [0, 51, 300])
def test_all_today_blocks_keep_fixed_select_count(invalid_count: int) -> None:
    rows = [alert(index + 1) for index in range(invalid_count + 51)]
    for row in rows[:invalid_count]:
        row.what_happened["evidence_ids"] = []
    conn, _ = connection(rows)

    result = products.blocks(conn, OWNER, None, AT, AT.date(), {}, {}, [])

    assert conn.execute.call_count == 5
    assert len(result["alerts"].items) == 50
    assert result["alerts"].more
    assert len(result["evidence"]) == 50


def test_stream_closes_on_compliance_rejection() -> None:
    row = alert(1)
    row.what_happened["title"] = COMPLIANCE_TERMS[0]
    result = MagicMock()
    result.__enter__.return_value = result
    result.__iter__.side_effect = lambda: iter([row])
    result.all.return_value = [row]
    conn = MagicMock(spec=Connection)
    conn.execute.return_value = result

    with pytest.raises(AppError, match="COMPLIANCE_LINT_FAILED"):
        products.today_alerts(conn, OWNER)

    result.__exit__.assert_called_once()
    assert result.__exit__.call_args.args[0] is AppError

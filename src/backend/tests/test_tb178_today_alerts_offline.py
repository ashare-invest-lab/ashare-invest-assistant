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
from app.db.tables.research import alerts

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
            offset = int(statement._offset_clause.value)
            limit = int(statement._limit_clause.value)
            offsets.append(offset)
            result.all.return_value = rows[offset : offset + limit]
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

    assert offsets == [0, 51]
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

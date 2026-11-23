"""T-B235 PIT filtering tests with synthetic rows and a fake connection."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

import pytest

from app.api.v1.reviews import ReviewCreate, ReviewVersionCreate
from app.reviews import service

OWNER = uuid.UUID("11111111-1111-4111-8111-111111111111")
ACCOUNT = uuid.UUID(int=900)
CODE = "600000.SH"
CREATED_AT = dt.datetime(2026, 1, 10, 8, tzinfo=dt.UTC)


def _trade(identifier: int, batch_id: uuid.UUID) -> SimpleNamespace:
    traded_at = dt.datetime(2026, 1, 2, 8, tzinfo=dt.UTC)
    return SimpleNamespace(
        id=uuid.UUID(int=identifier),
        user_id=OWNER,
        account_id=ACCOUNT,
        security_code=CODE,
        import_batch_id=batch_id,
        created_at=traded_at,
        traded_at=traded_at,
        trade_date=traded_at.date(),
        epistemic_type="execution",
        voided_at=None,
        source="import",
        side="buy",
        quantity=Decimal(10),
        net_amount=Decimal(-100),
    )


def _batch(identifier: uuid.UUID, committed_at: dt.datetime) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        user_id=OWNER,
        account_id=ACCOUNT,
        committed_at=committed_at,
    )


class ReviewConnection:
    def __init__(self, rows: list[Any], batches: list[Any]) -> None:
        self.rows = rows
        self.batches = batches
        self.versions: list[Any] = []
        self.version_trade_ids: list[list[uuid.UUID]] = []
        self.snapshot_items: list[dict[str, Any]] = []
        self.current = SimpleNamespace(
            id=uuid.UUID(int=500),
            version_no=1,
            trade_ids=[row.id for row in rows],
            plan_version_ids=[],
            snapshot_id=None,
            lessons=None,
            tags=[],
            attribution=None,
            outcome_metrics={},
            created_at=CREATED_AT,
        )

    def execute(self, statement: Any) -> SimpleNamespace:
        text = str(statement)
        upper = text.upper()
        if "APP.TRADES" in upper:
            return SimpleNamespace(all=lambda: self.rows)
        if "APP.IMPORT_BATCHES" in upper:
            return SimpleNamespace(all=lambda: self.batches)
        if "TRADING_CALENDAR" in upper:
            return SimpleNamespace(
                first=lambda: SimpleNamespace(date=dt.date(2026, 1, 5), is_open=True)
            )
        if "DAILY_BARS" in upper:
            return SimpleNamespace(all=list)
        if "INSERT INTO APP.DATA_SNAPSHOTS" in upper:
            self.snapshot_items.append(statement.compile().params["items"])
            return SimpleNamespace(first=lambda: None)
        if "INSERT INTO APP.REVIEW_VERSIONS" in upper:
            params = statement.compile().params
            version = SimpleNamespace(
                id=params["id"],
                version_no=params["version_no"],
                trade_ids=params["trade_ids"],
                plan_version_ids=params["plan_version_ids"],
                snapshot_id=params["snapshot_id"],
                lessons=params["lessons"],
                tags=params["tags"],
                attribution=params["attribution"],
                outcome_metrics=params["outcome_metrics"],
                created_at=params["created_at"],
            )
            self.versions.append(version)
            self.version_trade_ids.append(list(params["trade_ids"]))
            return SimpleNamespace(first=lambda: None)
        if "SELECT" in upper and "REVIEW_VERSIONS" in upper:
            latest = self.versions[-1] if self.versions else self.current
            return SimpleNamespace(
                first=lambda: latest,
                one=lambda: latest,
                all=lambda: self.versions or [self.current],
            )
        if "SELECT" in upper and "REVIEWS.CREATED_AT" in upper:
            return SimpleNamespace(first=lambda: SimpleNamespace(created_at=CREATED_AT))
        return SimpleNamespace(
            first=lambda: None,
            one=lambda: self.current,
            scalar=lambda: None,
            all=list,
        )


def _body(trade_ids: list[uuid.UUID]) -> ReviewCreate:
    return ReviewCreate.model_validate(
        {
            "security_code": CODE,
            "period_start": "2026-01-01",
            "period_end": "2026-01-05",
            "trade_ids": [str(identifier) for identifier in trade_ids],
        }
    )


def test_tb235_create_filters_late_import_batch_and_snapshot_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    early_batch_id = uuid.UUID(int=700)
    late_batch_id = uuid.UUID(int=701)
    early = _trade(702, early_batch_id)
    late = _trade(703, late_batch_id)
    conn = ReviewConnection(
        [early, late],
        [
            _batch(early_batch_id, dt.datetime(2026, 1, 9, 8, tzinfo=dt.UTC)),
            _batch(late_batch_id, dt.datetime(2026, 1, 11, 8, tzinfo=dt.UTC)),
        ],
    )

    monkeypatch.setattr(
        service, "_validate_links", lambda *_args, **_kwargs: (CODE, None)
    )
    review_id = service.create(conn, OWNER, _body([early.id, late.id]))

    assert review_id is not None
    assert conn.version_trade_ids == [[early.id]]
    assert conn.snapshot_items[0]["outcome_snapshot"]["trade_ids"] == [str(early.id)]
    assert conn.snapshot_items[0]["calculation_as_of"] == CREATED_AT.isoformat()


def test_tb235_revise_filters_new_version_and_keeps_old_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    early_batch_id = uuid.UUID(int=710)
    late_batch_id = uuid.UUID(int=711)
    early = _trade(712, early_batch_id)
    late = _trade(713, late_batch_id)
    conn = ReviewConnection(
        [early, late],
        [
            _batch(early_batch_id, dt.datetime(2026, 1, 9, 8, tzinfo=dt.UTC)),
            _batch(late_batch_id, dt.datetime(2026, 1, 11, 8, tzinfo=dt.UTC)),
        ],
    )
    old_trade_ids = [early.id, late.id]
    conn.current.trade_ids = old_trade_ids

    monkeypatch.setattr(
        service,
        "_owned",
        lambda *_args, **_kwargs: SimpleNamespace(current_version_id=conn.current.id),
    )
    monkeypatch.setattr(
        service, "_validate_links", lambda *_args, **_kwargs: (CODE, None)
    )
    monkeypatch.setattr(service, "_now", lambda: CREATED_AT)
    body = ReviewVersionCreate.model_validate(
        {
            "security_code": CODE,
            "period_start": "2026-01-01",
            "period_end": "2026-01-05",
            "trade_ids": [str(early.id), str(late.id)],
            "base_version_no": 1,
        }
    )

    service.revise(conn, OWNER, uuid.UUID(int=501), body)

    assert conn.current.trade_ids == old_trade_ids
    assert conn.version_trade_ids == [[early.id]]

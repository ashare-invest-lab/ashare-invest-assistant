"""复盘读写服务，版本内容由不可变快照投影。"""
# ruff: noqa: ANN401, E501

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import Connection, Row, insert, select, update

from app.common.errors import AppError, ErrorCode
from app.db.tables.accounts import import_batches, trades
from app.db.tables.market import daily_bars, securities
from app.db.tables.research import action_plans, plan_versions
from app.db.tables.reviews import data_snapshots, review_versions, reviews
from app.reviews.metrics import (
    METRIC_NAMES,
    SHANGHAI,
    _stat,
    empty_metrics,
    normalise_gaps,
    pending_message,
    period_pending_state,
    project_metrics,
    status_block,
)

OUTCOME_METRICS_ENABLED = False  # #349 §7.8.4 口径定稿前关闭

# fmt: off


def _bad(field: str, issue: str) -> AppError:
    return AppError(ErrorCode.VALIDATION_ERROR, details={"fields": [{"field": field, "issue": issue}]})


def _owned(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, *, lock: bool = False) -> Row[Any]:
    statement = select(reviews).where(reviews.c.id == identifier, reviews.c.user_id == owner)
    row = conn.execute(statement.with_for_update() if lock else statement).first()
    if row is None:
        raise AppError(ErrorCode.NOT_FOUND)
    return row


def _code(raw: str | None) -> str | None:
    if raw is None:
        return None
    value = raw.strip().upper()
    if len(value) == 6 and value.isdigit():
        value = f"{value}.SH" if value.startswith(("5", "6", "9")) else f"{value}.SZ"
    if len(value) != 9 or value[6] != "." or not value[:6].isdigit() or value[7:] not in {"SH", "SZ", "BJ"}:
        raise _bad("security_code", "invalid")
    return value


def _validate_links(
    conn: Connection,
    owner: uuid.UUID,
    *,
    plan_id: uuid.UUID | None,
    security_code: str | None,
    plan_version_ids: Sequence[uuid.UUID],
    trade_ids: Sequence[uuid.UUID],
) -> tuple[str | None, Row[Any] | None]:
    plan = None
    code = _code(security_code)
    if plan_id is None and code is None:
        raise _bad("plan_id", "plan_or_security_required")
    if plan_id is not None:
        plan = conn.execute(select(action_plans).where(action_plans.c.id == plan_id, action_plans.c.user_id == owner)).first()
        if plan is None:
            raise _bad("plan_id", "not_found")
        if code is not None and plan.security_code != code:
            raise _bad("security_code", "inconsistent_with_plan")
        code = str(plan.security_code)
    if plan_version_ids:
        rows = conn.execute(select(plan_versions.c.id, plan_versions.c.plan_id, action_plans.c.security_code).join(action_plans, action_plans.c.id == plan_versions.c.plan_id).where(plan_versions.c.id.in_(plan_version_ids), action_plans.c.user_id == owner)).all()
        if len(rows) != len(set(plan_version_ids)):
            raise _bad("plan_version_ids", "not_owned")
        if plan_id is not None and any(r.plan_id != plan_id for r in rows):
            raise _bad("plan_version_ids", "inconsistent_with_plan")
        if code is not None and any(r.security_code != code for r in rows):
            raise _bad("plan_version_ids", "inconsistent_with_security")
        if code is None:
            code = str(rows[0].security_code)
    if trade_ids:
        # source is deliberately not filtered here. The table's source enum has
        # only real-import values. Simulated rows are excluded in the metric
        # projection, where their epistemic type is visible.
        rows = conn.execute(select(trades.c.id, trades.c.security_code, trades.c.plan_version_id).where(trades.c.id.in_(trade_ids), trades.c.user_id == owner, trades.c.voided_at.is_(None))).all()
        if len(rows) != len(set(trade_ids)):
            raise _bad("trade_ids", "not_owned")
        if code is not None and any(r.security_code != code for r in rows):
            raise _bad("trade_ids", "inconsistent_with_security")
        if plan_version_ids and any(r.plan_version_id not in plan_version_ids for r in rows):
            raise _bad("trade_ids", "inconsistent_with_plan")
        if plan_id is not None and not plan_version_ids:
            valid = {r.id for r in conn.execute(select(plan_versions.c.id).where(plan_versions.c.plan_id == plan_id)).all()}
            if any(r.plan_version_id not in valid for r in rows):
                raise _bad("trade_ids", "inconsistent_with_plan")
        if code is None:
            code = str(rows[0].security_code)
    return code, plan


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _as_datetime(value: dt.datetime | None) -> dt.datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=dt.UTC)


def _executed_at(row: Any) -> dt.datetime | None:
    return _as_datetime(row.traded_at)


def _available_at(row: Any, *, committed_at: dt.datetime | None = None) -> dt.datetime | None:
    values = [_executed_at(row), _as_datetime(row.created_at)]
    if row.import_batch_id is not None:
        committed = _as_datetime(committed_at)
        if committed is None:
            return None
        values.append(committed)
    available = [value for value in values if value is not None]
    return max(available) if available else None


def _decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return number if number.is_finite() else None


def _trade_rows(conn: Connection, owner: uuid.UUID, trade_ids: Sequence[uuid.UUID]) -> list[Any]:
    if not trade_ids:
        return []
    return list(conn.execute(select(trades).where(trades.c.id.in_(trade_ids), trades.c.user_id == owner)).all())


def _batch_commitments(
    conn: Connection, owner: uuid.UUID, rows: Sequence[Any]
) -> tuple[dict[uuid.UUID, dt.datetime], set[uuid.UUID]]:
    batch_ids = {row.import_batch_id for row in rows if row.import_batch_id is not None}
    if not batch_ids:
        return {}, set()
    batch_rows = conn.execute(
        select(
            import_batches.c.id,
            import_batches.c.user_id,
            import_batches.c.account_id,
            import_batches.c.committed_at,
        ).where(
            import_batches.c.id.in_(batch_ids),
            import_batches.c.user_id == owner,
        )
    ).all()
    by_batch_account = {
        (batch.id, batch.account_id): _as_datetime(batch.committed_at)
        for batch in batch_rows
        if batch.user_id == owner
    }
    committed_at: dict[uuid.UUID, dt.datetime] = {}
    unproven: set[uuid.UUID] = set()
    for row in rows:
        if row.import_batch_id is None:
            continue
        stamp = by_batch_account.get((row.import_batch_id, row.account_id))
        if stamp is None:
            unproven.add(row.id)
        else:
            committed_at[row.id] = stamp
    return committed_at, unproven


def _trade_date(row: Any) -> dt.date | None:
    value = row.trade_date
    if isinstance(value, dt.date):
        return value
    return None


def _visible_trade_rows(
    rows: Sequence[Any],
    calculation_as_of: dt.datetime,
    period_start: dt.date,
    period_end: dt.date,
    knowledge: object | None = None,
    batch_committed_at: Mapping[uuid.UUID, dt.datetime] | None = None,
) -> tuple[list[Any], dt.datetime | None]:
    visible: list[Any] = []
    data_as_of: dt.datetime | None = None
    calculation_as_of_normalized = (
        calculation_as_of
        if calculation_as_of.tzinfo
        else calculation_as_of.replace(tzinfo=dt.UTC)
    )
    for row in rows:
        traded_at = _executed_at(row)
        if row.voided_at is not None or row.epistemic_type != "execution":
            continue
        row_date = _trade_date(row)
        if traded_at is None or row_date is None:
            continue
        committed_at = batch_committed_at.get(row.id) if batch_committed_at is not None else None
        available_at = _available_at(row, committed_at=committed_at)
        if available_at is None or available_at > calculation_as_of_normalized:
            continue
        if row_date < period_start or row_date > period_end:
            continue
        visible.append(row)
        data_as_of = max(data_as_of, available_at) if data_as_of else available_at
    return visible, data_as_of


def _fifo_holding(rows: Sequence[Any]) -> tuple[list[Decimal], bool]:
    """Pair execution cash flows FIFO and report returns for closed lots."""
    openings_by_code: dict[str, list[tuple[Decimal, Decimal]]] = {}
    holding: list[Decimal] = []
    for row in sorted(rows, key=lambda item: (_executed_at(item), str(item.id))):
        quantity = _decimal(row.quantity)
        net_amount = _decimal(row.net_amount)
        openings = openings_by_code.setdefault(str(row.security_code), [])
        if quantity is None or quantity <= 0 or net_amount is None:
            continue
        unit_cash = abs(net_amount) / quantity
        if unit_cash <= 0:
            continue
        if row.side == "buy":
            openings.append((unit_cash, quantity))
            continue
        if row.side != "sell":
            continue
        remaining = quantity
        while remaining > 0 and openings:
            buy_unit_cash, buy_quantity = openings[0]
            matched = min(remaining, buy_quantity)
            holding.append((unit_cash / buy_unit_cash - Decimal(1)) * Decimal(100))
            remaining -= matched
            buy_quantity -= matched
            if buy_quantity == 0:
                openings.pop(0)
            else:
                openings[0] = (buy_unit_cash, buy_quantity)
    return holding, any(openings_by_code.values())


def _closed_trade_observations(rows: Sequence[Any]) -> list[tuple[str, dt.date, dt.date, Decimal]]:
    """Return closed FIFO lots with their exact trade-date interval."""
    openings_by_code: dict[str, list[tuple[Decimal, Decimal, dt.date]]] = {}
    result: list[tuple[str, dt.date, dt.date, Decimal]] = []
    for row in sorted(rows, key=lambda item: (_executed_at(item), str(item.id))):
        quantity = _decimal(row.quantity)
        net_amount = _decimal(row.net_amount)
        row_date = _trade_date(row)
        if quantity is None or quantity <= 0 or net_amount is None or row_date is None:
            continue
        unit_cash = abs(net_amount) / quantity
        if unit_cash <= 0:
            continue
        code = str(row.security_code)
        openings = openings_by_code.setdefault(code, [])
        if row.side == "buy":
            openings.append((unit_cash, quantity, row_date))
            continue
        if row.side != "sell":
            continue
        remaining = quantity
        while remaining > 0 and openings:
            buy_unit_cash, buy_quantity, buy_date = openings[0]
            matched = min(remaining, buy_quantity)
            result.append(
                (
                    code,
                    buy_date,
                    row_date,
                    (unit_cash / buy_unit_cash - Decimal(1)) * Decimal(100),
                )
            )
            remaining -= matched
            buy_quantity -= matched
            if buy_quantity == 0:
                openings.pop(0)
            else:
                openings[0] = (buy_unit_cash, buy_quantity, buy_date)
    return result


def _close_time(trade_date: dt.date) -> dt.datetime:
    return dt.datetime.combine(trade_date, dt.time(15), tzinfo=SHANGHAI).astimezone(dt.UTC)


def _market_rows(
    conn: Connection,
    code: str,
    start: dt.date,
    end: dt.date,
    adj_type: str,
    calculation_as_of: dt.datetime,
) -> list[Any]:
    result = conn.execute(
        select(
            daily_bars.c.code,
            daily_bars.c.trade_date,
            daily_bars.c.adj_type,
            daily_bars.c.close,
            daily_bars.c.fetched_at,
            daily_bars.c.is_suspended,
        ).where(
            daily_bars.c.code == code,
            daily_bars.c.trade_date >= start,
            daily_bars.c.trade_date <= end,
            daily_bars.c.adj_type == adj_type,
            daily_bars.c.fetched_at <= calculation_as_of,
        )
    )
    visible: list[Any] = []
    for row in result.all():
        if row.code != code or row.adj_type != adj_type:
            continue
        trade_date = row.trade_date
        fetched_at = _as_datetime(row.fetched_at)
        close = _decimal(row.close)
        suspended = row.is_suspended
        if not isinstance(trade_date, dt.date) or fetched_at is None or close is None or close <= 0:
            continue
        if fetched_at > calculation_as_of or fetched_at < _close_time(trade_date):
            continue
        if suspended is True:
            continue
        visible.append(row)
    return visible


def _market_as_of(rows: Sequence[Any]) -> dt.datetime | None:
    values: list[dt.datetime] = []
    for row in rows:
        fetched_at = _as_datetime(row.fetched_at)
        if fetched_at is not None:
            values.append(fetched_at)
    return max(values) if values else None


def _benchmark_and_drawdowns(
    conn: Connection,
    pairs: Sequence[tuple[str, dt.date, dt.date, Decimal]],
    calculation_as_of: dt.datetime,
) -> tuple[list[Decimal], list[Decimal], list[Decimal], dt.datetime | None]:
    if not pairs:
        return [], [], [], None
    first = min(item[1] for item in pairs)
    last = max(item[2] for item in pairs)
    benchmark_rows = _market_rows(conn, "000300.SH", first, last, "none", calculation_as_of)
    benchmark = {
        row.trade_date: _decimal(row.close)
        for row in benchmark_rows
    }
    market_as_of = _market_as_of(benchmark_rows)
    by_code: dict[str, list[Any]] = {}
    ranges: dict[str, tuple[dt.date, dt.date]] = {}
    for code, entry, expiry, _ in pairs:
        previous = ranges.get(code)
        if previous is None or entry < previous[0] or expiry > previous[1]:
            first_date = entry if previous is None else min(previous[0], entry)
            last_date = expiry if previous is None else max(previous[1], expiry)
            by_code[code] = _market_rows(
                conn, code, first_date, last_date, "qfq", calculation_as_of
            )
            ranges[code] = first_date, last_date
    benchmark_values: list[Decimal] = []
    drawdowns: list[Decimal] = []
    excess_values: list[Decimal] = []
    for code, entry, expiry, holding_return in pairs:
        start_value = benchmark.get(entry)
        end_value = benchmark.get(expiry)
        if start_value is not None and end_value is not None and start_value > 0:
            benchmark_return = (end_value / start_value - Decimal(1)) * Decimal(100)
            benchmark_values.append(benchmark_return)
            excess_values.append(holding_return - benchmark_return)
        path = [
            (row.trade_date, _decimal(row.close))
            for row in by_code[code]
            if entry <= row.trade_date <= expiry
        ]
        path.sort(key=lambda item: item[0])
        if path and path[0][0] == entry and path[-1][0] == expiry:
            peak: Decimal | None = None
            drawdown: Decimal | None = None
            for _, value in path:
                if value is None or value <= 0:
                    continue
                peak = value if peak is None else max(peak, value)
                current = (value / peak - Decimal(1)) * Decimal(100)
                drawdown = current if drawdown is None else min(drawdown, current)
            if drawdown is not None:
                drawdowns.append(drawdown)
        stock_as_of = _market_as_of(by_code[code])
        if stock_as_of is not None:
            market_as_of = max(market_as_of, stock_as_of) if market_as_of else stock_as_of
    return benchmark_values, drawdowns, excess_values, market_as_of


def _observations(
    rows: Sequence[Any],
    calculation_as_of: dt.datetime,
    period_start: dt.date,
    period_end: dt.date,
    knowledge: object | None = None,
    batch_committed_at: Mapping[uuid.UUID, dt.datetime] | None = None,
) -> tuple[list[Decimal], list[Decimal], list[Decimal], list[str], dt.datetime | None, bool]:
    visible, data_as_of = _visible_trade_rows(
        rows,
        calculation_as_of,
        period_start,
        period_end,
        knowledge,
        batch_committed_at,
    )
    evidence_ids: list[str] = []
    for row in rows:
        if row in visible:
            evidence_ids.append("trade:" + str(row.id))
    holding, has_open_positions = _fifo_holding(visible)
    return holding, [], [], evidence_ids, data_as_of, has_open_positions


def _metric(name: str, window: str, values: Sequence[Decimal]) -> dict[str, Any]:
    value = sum(values, Decimal(0)) / Decimal(len(values)) if values else None
    result = _stat(window, value=value, n=len(values))
    if values and len(values) < 5:
        result["label"] = "未验证"
    return result


def _trade_provider(source: str) -> str:
    return "user_input" if source == "manual" else "user_import"


def _trade_evidence(
    row: Any, *, committed_at: dt.datetime | None = None
) -> dict[str, Any] | None:
    available_at = _available_at(row, committed_at=committed_at)
    if available_at is None:
        return None
    stamp = available_at.isoformat()
    return {
        "id": "trade:" + str(row.id),
        "key": "trade",
        "value": str(row.id),
        "unit": None,
        "provider": _trade_provider(row.source),
        "endpoint": None,
        "data_as_of": stamp,
        "fetched_at": stamp,
        "epistemic_type": row.epistemic_type,
    }


def _plan_evidence(
    conn: Connection | None, owner: uuid.UUID | None, identifiers: Sequence[uuid.UUID]
) -> list[dict[str, Any]]:
    if conn is None or owner is None or not identifiers:
        return []
    rows = conn.execute(select(plan_versions).where(plan_versions.c.id.in_(identifiers))).all()
    by_id = {row.id: row for row in rows}
    evidence: list[dict[str, Any]] = []
    for identifier in identifiers:
        row = by_id.get(identifier)
        if row is None:
            continue
        stamp = _as_datetime(row.created_at)
        if stamp is None:
            continue
        evidence.append(
            {
                "id": "plan:" + str(identifier),
                "key": "plan_version",
                "value": str(identifier),
                "unit": None,
                "provider": "user_input",
                "endpoint": None,
                "data_as_of": stamp.isoformat(),
                "fetched_at": stamp.isoformat(),
                "epistemic_type": "hypothesis",
            }
        )
    return evidence


def _compute_outcome_metrics(
    conn: Connection,
    owner: uuid.UUID,
    start: dt.date,
    end: dt.date,
    trade_ids: Sequence[uuid.UUID],
    calculation_as_of: dt.datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], dt.datetime | None, dict[str, list[str]]]:
    window = f"{start.isoformat()}/{end.isoformat()}"
    rows = _trade_rows(conn, owner, trade_ids)
    batch_committed_at, unproven_imports = _batch_commitments(conn, owner, rows)
    pending, calendar_available = period_pending_state(end, now=calculation_as_of, conn=conn)
    if pending:
        pending_gaps = ["not_yet_published"]
        if not calendar_available:
            pending_gaps.append("no_source")
        metric_reasons = dict.fromkeys(METRIC_NAMES, pending_gaps)
        if unproven_imports:
            metric_reasons["trades.import_commit_unproven"] = ["no_source"]
        return {name: _stat(window) for name in METRIC_NAMES}, [], None, metric_reasons
    holding, _, _, _, data_as_of, has_open_positions = _observations(
        rows,
        calculation_as_of,
        start,
        end,
        batch_committed_at=batch_committed_at,
    )
    visible_rows, _ = _visible_trade_rows(
        rows,
        calculation_as_of,
        start,
        end,
        batch_committed_at=batch_committed_at,
    )
    pairs = _closed_trade_observations(visible_rows)
    benchmark, drawdowns, excess, market_as_of = _benchmark_and_drawdowns(
        conn, pairs, calculation_as_of
    )
    if market_as_of is not None:
        data_as_of = max(data_as_of, market_as_of) if data_as_of else market_as_of
    metrics = {
        "holding_return": _metric("holding_return", window, holding),
        "benchmark_return": _metric("benchmark_return", window, benchmark),
        "max_drawdown": _metric("max_drawdown", window, drawdowns),
    }
    metric_gaps: dict[str, list[str]] = {}
    if not holding:
        metric_gaps["holding_return"] = [
            "user_input_missing" if has_open_positions else "no_source"
        ]
    if has_open_positions:
        metric_gaps["holding_return"] = ["user_input_missing"]
    if excess:
        metrics["excess_return"] = _metric("excess_return", window, excess)
    else:
        metrics["excess_return"] = _metric("excess_return", window, [])
        metric_gaps["excess_return"] = ["no_source"]
    evidence: list[dict[str, Any]] = []
    for row in visible_rows:
        item = _trade_evidence(row, committed_at=batch_committed_at.get(row.id))
        if item is not None:
            evidence.append(item)
    if not benchmark:
        metric_gaps["benchmark_return"] = ["no_source"]
    if not drawdowns:
        metric_gaps["max_drawdown"] = ["no_source"]
    if not OUTCOME_METRICS_ENABLED:
        for name in ("holding_return", "benchmark_return", "excess_return", "max_drawdown"):
            metrics[name]["value"] = None
            metric_gaps[name] = ["no_source"]
    if unproven_imports:
        metric_gaps["trades.import_commit_unproven"] = ["no_source"]
    return metrics, evidence, data_as_of, metric_gaps


def _snapshot_items(
    start: dt.date,
    end: dt.date,
    lessons: str | None,
    tags: list[str],
    judgement: list[dict[str, Any]],
    has_trades: bool,
    *,
    conn: Connection | None = None,
    owner: uuid.UUID | None = None,
    trade_ids: Sequence[uuid.UUID] = (),
    plan_version_ids: Sequence[uuid.UUID] = (),
    calculation_as_of: dt.datetime | None = None,
) -> dict[str, Any]:
    calculation_as_of = calculation_as_of or _now()
    if conn is not None and owner is not None:
        metrics, evidence, data_as_of, metric_reasons = _compute_outcome_metrics(
            conn, owner, start, end, trade_ids, calculation_as_of
        )
    else:
        metrics, evidence, data_as_of = empty_metrics(start, end), [], None
        reason = "no_source" if has_trades else "user_input_missing"
        metric_reasons = {name: [reason] for name in METRIC_NAMES}
    plan_evidence = _plan_evidence(conn, owner, plan_version_ids)
    evidence = plan_evidence + evidence
    pending_metrics = any("not_yet_published" in reasons for reasons in metric_reasons.values())
    block = status_block(
        has_observation=bool(evidence),
        reason=(
            "not_yet_published"
            if pending_metrics
            else "no_source"
            if has_trades
            else "user_input_missing"
        ),
    )
    metric_messages = {
        "holding_return": "未验证：按成交可见时点计算；未平仓部分未计入",
        "benchmark_return": "基准价格缺失，指标未验证（待回测）",
        "excess_return": "基准价格缺失，超额收益未验证（待回测）",
        "max_drawdown": "复权价格路径缺失，最大回撤未验证（待回测）",
    }
    metric_gaps = []
    for name, reasons in metric_reasons.items():
        for reason in reasons:
            message = (
                "导入批次提交时点不可证实"
                if name == "trades.import_commit_unproven"
                else metric_messages[name]
            )
            if reason == "no_source" and "not_yet_published" in reasons:
                message = "交易日历缺失，发布时点未验证"
            key = name if name == "trades.import_commit_unproven" else f"outcome_metrics.{name}"
            gap = {"key": key, "reason": reason, "message": message}
            if gap not in metric_gaps:
                metric_gaps.append(gap)
    if metric_gaps:
        block["gaps"] = metric_gaps
    plan_snapshot = {
        "plan_version_ids": [str(identifier) for identifier in plan_version_ids],
        "judgement": judgement,
        "lessons": lessons,
        "tags": tags,
    }
    outcome_snapshot = {"trade_ids": [str(identifier) for identifier in trade_ids], "metrics": metrics, "evidence": evidence}
    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "outcome_metrics": metrics,
        "attribution": {
            "judgement": judgement,
            "execution": (
                [
                    {
                        "text": "本人实际成交已冻结",
                        "evidence_ids": [item["id"] for item in evidence if item["key"] == "trade"],
                    }
                ]
                if any(item["key"] == "trade" for item in evidence)
                else []
            ),
            "market": [],
        },
        "lessons": lessons,
        "tags": tags,
        "plan_snapshot": plan_snapshot,
        "outcome_snapshot": outcome_snapshot,
        "plan": plan_snapshot,
        "outcome": outcome_snapshot,
        "calculation_as_of": calculation_as_of.isoformat(),
        "data_as_of": data_as_of.isoformat() if data_as_of else None,
        "evidence": evidence,
        **block,
    }


def _new_version(
    conn: Connection,
    owner: uuid.UUID,
    review_id: uuid.UUID,
    version_no: int,
    *,
    start: dt.date,
    end: dt.date,
    plan_version_ids: list[uuid.UUID],
    trade_ids: list[uuid.UUID],
    lessons: str | None,
    tags: list[str],
    judgement: list[dict[str, Any]],
) -> Row[Any]:
    snapshot_id, version_id = uuid.uuid4(), uuid.uuid4()
    calculation_as_of = _now()
    items = _snapshot_items(start, end, lessons, tags, judgement, bool(trade_ids), conn=conn, owner=owner, trade_ids=trade_ids, plan_version_ids=plan_version_ids, calculation_as_of=calculation_as_of)
    raw = json.dumps(items, sort_keys=True, default=str, ensure_ascii=False).encode()
    conn.execute(insert(data_snapshots).values(id=snapshot_id, user_id=owner, purpose="review", items=items, hash=hashlib.sha256(raw).hexdigest()))
    conn.execute(insert(review_versions).values(id=version_id, review_id=review_id, version_no=version_no, plan_version_ids=plan_version_ids, trade_ids=trade_ids, outcome_metrics=items["outcome_metrics"], attribution=items["attribution"], lessons=lessons, tags=tags, snapshot_id=snapshot_id))
    return conn.execute(select(review_versions).where(review_versions.c.id == version_id)).one()


def create(conn: Connection, owner: uuid.UUID, body: Any) -> uuid.UUID:
    if body.period_end < body.period_start:
        raise _bad("period_end", "before_period_start")
    code, _ = _validate_links(conn, owner, plan_id=body.plan_id, security_code=body.security_code, plan_version_ids=body.plan_version_ids, trade_ids=body.trade_ids)
    review_id = uuid.uuid4()
    conn.execute(insert(reviews).values(id=review_id, user_id=owner, plan_id=body.plan_id, security_code=code, period_start=body.period_start, period_end=body.period_end))
    version = _new_version(conn, owner, review_id, 1, start=body.period_start, end=body.period_end, plan_version_ids=list(body.plan_version_ids), trade_ids=list(body.trade_ids), lessons=body.lessons, tags=list(body.tags), judgement=[j.model_dump(mode="json") for j in body.judgement])
    conn.execute(update(reviews).where(reviews.c.id == review_id).values(current_version_id=version.id))
    return review_id


def revise(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, body: Any) -> uuid.UUID:
    review = _owned(conn, owner, identifier, lock=True)
    if review.current_version_id is None:
        raise AppError(ErrorCode.NOT_FOUND)
    current = conn.execute(select(review_versions).where(review_versions.c.id == review.current_version_id)).first()
    if current is None:
        raise AppError(ErrorCode.NOT_FOUND)
    if body.base_version_no != current.version_no:
        raise AppError(ErrorCode.VERSION_CONFLICT, details={"current_version_no": current.version_no})
    plan_id, code = body.plan_id, body.security_code
    start, end = body.period_start, body.period_end
    if end < start:
        raise _bad("period_end", "before_period_start")
    ids, tids = list(body.plan_version_ids), list(body.trade_ids)
    code, _ = _validate_links(conn, owner, plan_id=plan_id, security_code=code, plan_version_ids=ids, trade_ids=tids)
    _new_version(conn, owner, identifier, current.version_no + 1, start=start, end=end, plan_version_ids=ids, trade_ids=tids, lessons=body.lessons, tags=list(body.tags), judgement=[j.model_dump(mode="json") for j in body.judgement])
    # The parent row points only to the new immutable version. Existing versions
    # and their snapshots are never updated.
    newest = conn.execute(select(review_versions).where(review_versions.c.review_id == identifier).order_by(review_versions.c.version_no.desc())).first()
    conn.execute(update(reviews).where(reviews.c.id == identifier).values(plan_id=plan_id, security_code=code, period_start=start, period_end=end, current_version_id=newest.id if newest else current.id))
    return identifier


def _snapshot(conn: Connection, owner: uuid.UUID, snapshot_id: uuid.UUID | None) -> dict[str, Any]:
    if snapshot_id is None:
        return status_block()
    row = conn.execute(select(data_snapshots.c["items"]).where(data_snapshots.c.id == snapshot_id, data_snapshots.c.user_id == owner)).first()
    items = row.items if row is not None else None
    return dict(items) if items else status_block()


def _status_for(
    snap: dict[str, Any], period_end: dt.date | None, conn: Connection | None = None
) -> dict[str, Any]:
    pending, calendar_available = period_pending_state(period_end, conn=conn)
    current_day = dt.datetime.now(dt.UTC).astimezone(SHANGHAI).date()
    period_is_future = period_end is not None and period_end > current_day
    if pending and (
        period_is_future
        or snap.get("period_end") is not None
        or snap.get("outcome_metrics")
    ):
        block = status_block(reason="not_yet_published", message=pending_message())
        block["gaps"] = [
            {
                "key": f"outcome_metrics.{name}",
                "reason": "not_yet_published",
                "message": pending_message(),
            }
            for name in METRIC_NAMES
        ]
        if not calendar_available:
            block["gaps"].extend(
                {
                    "key": f"outcome_metrics.{name}",
                    "reason": "no_source",
                    "message": "交易日历缺失，发布时点未验证",
                }
                for name in METRIC_NAMES
            )
        for gap in normalise_gaps(snap.get("gaps"), "outcome_metrics"):
            if not str(gap.get("key", "")).startswith("outcome_metrics") and gap not in block["gaps"]:
                block["gaps"].append(gap)
        return block
    gaps: list[dict[str, Any]] = []
    for gap in normalise_gaps(snap.get("gaps"), "outcome_metrics"):
        if gap.get("key") == "outcome_metrics":
            gaps.extend({**gap, "key": f"outcome_metrics.{name}"} for name in METRIC_NAMES)
        else:
            gaps.append(gap)
    for name, metric in (snap.get("outcome_metrics") or {}).items():
        for gap in normalise_gaps(metric.get("gaps"), f"outcome_metrics.{name}"):
            if gap not in gaps:
                gaps.append(gap)
    return {"data_status": snap.get("data_status", "unavailable"), "data_as_of": snap.get("data_as_of"), "gaps": gaps}


def version_body(conn: Connection, owner: uuid.UUID, row: Row[Any], *, period_end: dt.date | None = None) -> dict[str, Any]:
    snap = _snapshot(conn, owner, row.snapshot_id)
    frozen_end = period_end
    if isinstance(snap.get("period_end"), str):
        with contextlib.suppress(ValueError):
            frozen_end = dt.date.fromisoformat(snap["period_end"])
    metrics = project_metrics(
        row.outcome_metrics or snap.get("outcome_metrics", {}),
        period_end=frozen_end,
        conn=conn,
    )
    status = _status_for(snap, frozen_end, conn)
    return {
        "id": str(row.id),
        "version_no": row.version_no,
        "plan_version_ids": [str(x) for x in row.plan_version_ids or []],
        "trade_ids": [str(x) for x in row.trade_ids or []],
        "snapshot_id": str(row.snapshot_id) if row.snapshot_id else None,
        "lessons": row.lessons,
        "tags": list(row.tags or []),
        "attribution": row.attribution or snap.get("attribution", {"judgement": [], "execution": [], "market": []}),
        "outcome_metrics": metrics,
        "evidence": list(snap.get("evidence", [])),
        "created_at": row.created_at.isoformat(),
        "data_status": status.get("data_status", "unavailable"),
        "data_as_of": status.get("data_as_of"),
        "gaps": status.get("gaps", []),
    }


def _timeline_data(
    conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, current: Row[Any] | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    result: list[dict[str, Any]] = []
    all_evidence: dict[str, dict[str, Any]] = {}
    versions = conn.execute(select(review_versions).where(review_versions.c.review_id == identifier).order_by(review_versions.c.version_no.asc())).all()
    for version in versions:
        snap = _snapshot(conn, owner, version.snapshot_id)
        for item in snap.get("evidence", []):
            if item.get("id"):
                all_evidence[str(item["id"])] = item
        ids = [str(item.get("id")) for item in snap.get("evidence", []) if item.get("id")]
        result.append({"kind": "review_version", "at": version.created_at.isoformat(), "resource_id": str(version.id), "version_no": version.version_no, "evidence_ids": ids})
    if current is not None and current.plan_version_ids:
        plan_rows = conn.execute(select(plan_versions).where(plan_versions.c.id.in_(current.plan_version_ids))).all()
        plan_evidence = {str(item.get("value")): str(item.get("id")) for item in _snapshot(conn, owner, current.snapshot_id).get("evidence", []) if item.get("key") == "plan_version"}
        result.extend({"kind": "plan_version", "at": r.created_at.isoformat(), "resource_id": str(r.id), "version_no": r.version_no, "evidence_ids": [plan_evidence[str(r.id)]] if str(r.id) in plan_evidence else []} for r in plan_rows)
    if current is not None and current.trade_ids:
        trade_rows = conn.execute(select(trades).where(trades.c.id.in_(current.trade_ids), trades.c.user_id == owner)).all()
        batch_committed_at, _ = _batch_commitments(conn, owner, trade_rows)
        current_snapshot = _snapshot(conn, owner, current.snapshot_id)
        calculation_as_of = _now()
        raw_calculation_as_of = current_snapshot.get("calculation_as_of")
        if isinstance(raw_calculation_as_of, str):
            with contextlib.suppress(ValueError):
                calculation_as_of = dt.datetime.fromisoformat(raw_calculation_as_of)
        calculation_as_of = _as_datetime(calculation_as_of) or _now()
        trade_evidence = {
            str(item.get("value")): str(item.get("id"))
            for item in current_snapshot.get("evidence", [])
            if item.get("key") == "trade"
        }
        for row in trade_rows:
            available_at = _available_at(row, committed_at=batch_committed_at.get(row.id))
            if available_at is None or available_at > calculation_as_of:
                continue
            result.append(
                {
                    "kind": "trade",
                    "at": available_at.isoformat(),
                    "resource_id": str(row.id),
                    "version_no": None,
                    "evidence_ids": [trade_evidence[str(row.id)]]
                    if str(row.id) in trade_evidence
                    else [],
                }
            )
    result.sort(key=lambda item: item["at"])
    return result, list(all_evidence.values())


def _timeline(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID, current: Row[Any] | None) -> list[dict[str, Any]]:
    return _timeline_data(conn, owner, identifier, current)[0]


def full(conn: Connection, owner: uuid.UUID, identifier: uuid.UUID) -> dict[str, Any]:
    review = _owned(conn, owner, identifier)
    current = None if review.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == review.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == review.security_code)).scalar()
    snap = _snapshot(conn, owner, current.snapshot_id) if current is not None else status_block()
    status = _status_for(snap, review.period_end, conn) if current is not None else snap
    timeline, timeline_evidence = _timeline_data(conn, owner, identifier, current)
    evidence = timeline_evidence
    return {
        "id": str(review.id),
        "plan_id": str(review.plan_id) if review.plan_id else None,
        "security_code": review.security_code,
        "name": sec or review.security_code,
        "period_start": review.period_start.isoformat(),
        "period_end": review.period_end.isoformat(),
        "current_version_no": current.version_no if current is not None else None,
        "created_at": review.created_at.isoformat(),
        "current_version": version_body(conn, owner, current, period_end=review.period_end) if current is not None else None,
        "timeline": timeline,
        "evidence": evidence,
        **status,
    }


def summary(conn: Connection, row: Row[Any]) -> dict[str, Any]:
    version = None if row.current_version_id is None else conn.execute(select(review_versions).where(review_versions.c.id == row.current_version_id)).first()
    sec = conn.execute(select(securities.c["name"]).where(securities.c.code == row.security_code)).scalar()
    snap = _snapshot(conn, row.user_id, version.snapshot_id) if version is not None else status_block()
    status = _status_for(snap, row.period_end, conn) if version is not None else snap
    return {
        "id": str(row.id),
        "plan_id": str(row.plan_id) if row.plan_id else None,
        "security_code": row.security_code,
        "name": sec or row.security_code,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "current_version_no": version.version_no if version is not None else None,
        "created_at": row.created_at.isoformat(),
        **status,
    }

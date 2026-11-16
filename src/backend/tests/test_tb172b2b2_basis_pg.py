"""T-A202 §2/§3.4/§4、T-A204 阻断1/2：仅隔离 PG 的合成登记材料。"""

# ruff: noqa: S101, F811
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, event, insert, select, text

from app.db.tables.horizon import horizon_input_versions as versions
from app.db.tables.realtime import pipeline_runs
from app.features import horizon_evidence_store as store
from app.features.horizon_evidence_provider import DatabaseHorizonEvidenceProvider
from app.features.horizon_windows import select_day
from app.strategy.horizon.inputs import collect
from tests.test_tb172b2a_evidence_store_offline import BATCH, U
from tests.test_tb172b2a_evidence_store_pg import (
    NOW,
    completion,
    conn,  # noqa: F401
    package,
    world,  # noqa: F401
)

DAY = NOW.date()
CUTOFF = NOW + timedelta(minutes=30)
SCOPE = {"user_id": UUID(U), "licence_id": None, "code": "SYN"}


def calendar(connection: Connection, **changes: Any) -> UUID:  # noqa: ANN401
    return store.register_version(connection, **package(code=None, **changes))


def bar(connection: Connection, **changes: Any) -> UUID:  # noqa: ANN401
    return store.register_version(connection, **package("daily_bar", source_key="none", **changes))


def receipt(connection: Connection, saved: UUID, **changes: Any) -> dict[str, Any]:  # noqa: ANN401
    c = completion(connection, saved, **changes)
    c["proof"]["source_version"] = connection.execute(
        select(versions.c.source_version).where(versions.c.id == saved)
    ).scalar_one()
    return c


def batch(connection: Connection, licence: UUID, status: str = "ok") -> dict[str, Any]:
    run = uuid4()
    connection.execute(
        insert(pipeline_runs).values(id=run, kind="daily_batch", run_date=DAY, status=status)
    )
    return {**BATCH, "run_id": str(run), "licence_id": str(licence), "status": status}


@pytest.mark.parametrize("status", ["failed", "running", "partial", "skipped"])
@pytest.mark.parametrize("attachment", ["superseded", "other_key", "unbound_batch"])
def test_completion_blocked_by_all_day_versions(
    conn: Connection, status: str, attachment: str
) -> None:
    licence = uuid4()
    scope = {**SCOPE, "licence_id": licence}
    origin = {"source": "mairui", "scope": "per_licence", "licence_id": licence}
    calendar(conn)
    old = bar(conn, **origin)
    if attachment == "other_key":
        p = package("daily_bar", source_key="other", **origin)
        old = store.register_version(conn, **p)
        saved = bar(conn, **origin)
    else:
        saved = bar(conn, **origin, source_version="v2", supersedes_id=old)
    ok, bad = batch(conn, licence), batch(conn, licence, status)
    if attachment == "unbound_batch":
        bad["licence_id"] = None
    bad.update(finished_at=CUTOFF.isoformat(), available_at=CUTOFF.isoformat())
    for version, raw, at in ((saved, ok, NOW), (old, bad, CUTOFF)):
        c = receipt(
            conn,
            version,
            pipeline_run_id=UUID(raw["run_id"]),
            available_at=at,
            proof_kind="source_final_receipt",
        )
        c["proof"]["batches"] = [raw]
        store.register_completion(conn, **c)
    provider = DatabaseHorizonEvidenceProvider(conn)
    before = provider.read_basis(**scope, as_of=NOW)
    if attachment != "other_key":
        assert select_day(before, **scope, as_of=CUTOFF).d == DAY
    b = provider.read_basis(**scope, as_of=CUTOFF)
    assert select_day(b, **scope, as_of=CUTOFF).d is None
    assert f"completion_blocked:{DAY}" in b.gaps
    assert not b.proofs
    assert not b.batches


@pytest.mark.parametrize("kind", ["daily_bar", "calendar"])
def test_version_conflict_blocks_entire_day(conn: Connection, kind: str) -> None:
    calendar(conn)
    saved = bar(conn)
    store.register_completion(conn, **receipt(conn, saved))
    p = package(kind, source_key="A", code=None if kind == "calendar" else "SYN")
    root = store.register_version(conn, **p)
    for revision in ("v2", "v3"):
        store.register_version(conn, **{**p, "source_version": revision, "supersedes_id": root})
    b = DatabaseHorizonEvidenceProvider(conn).read_basis(**SCOPE, as_of=CUTOFF)
    assert select_day(b, **SCOPE, as_of=CUTOFF).d is None
    assert f"version_conflict_day:{DAY}" in b.gaps
    assert not b.bars
    assert not b.proofs
    assert not b.batches


@pytest.mark.parametrize("state", [True, False, None, "late", "null", "conflict", "old_false"])
def test_completion_visibility_and_batches(conn: Connection, state: object) -> None:
    # 数据库以非 UTC 返回 timestamptz；时刻断言比较 datetime 瞬时。
    conn.execute(text("SET LOCAL TIME ZONE 'Asia/Shanghai'"))
    licence = uuid4()
    scope = {**SCOPE, "licence_id": licence}
    origin = {"source": "mairui", "scope": "per_licence", "licence_id": licence}
    old = bar(conn, **origin)
    saved = bar(conn, **origin, source_version="v2", supersedes_id=old)
    raw = batch(conn, licence)
    raw.update(issues=["OTHER"], window_trading_days=None)
    c = receipt(
        conn,
        saved,
        pipeline_run_id=UUID(raw["run_id"]),
        proof_kind="source_final_receipt",
        is_final=state if state is True or state is False or state is None else True,
        available_at=CUTOFF if state == "late" else None if state == "null" else NOW,
    )
    c["proof"]["batches"] = [raw]
    if state == "null":
        c["is_final"] = None
    store.register_completion(conn, **c)
    if state in {"conflict", "old_false"}:
        negative = receipt(
            conn,
            old if state == "old_false" else saved,
            is_final=False,
            proof_kind="source_final_receipt",
        )
        store.register_completion(conn, **negative)
    provider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**scope, as_of=NOW)
    assert len(b.proofs) == (1 if state is True or state is False or state is None else 0)
    if b.proofs:
        p, r = b.proofs[0], b.batches[0]
        assert (p.is_final, p.available_at, p.run_id, p.version.version_id) == (
            state,
            NOW,
            raw["run_id"],
            str(saved),
        )
        assert p.source_final_receipt == "synthetic fixture"
        assert (r.run_id, r.owner_id, r.licence_id, r.members, r.status, r.issues) == (
            raw["run_id"],
            None,
            licence,
            ((UUID(U), "SYN"),),
            "ok",
            ("OTHER",),
        )
        assert (
            r.finished_at,
            r.available_at,
            r.run_date,
            r.kind,
            r.step,
            r.window_trading_days,
        ) == (
            NOW,
            NOW,
            DAY,
            "daily_batch",
            "daily_bars.fetch",
            None,
        )
    if state in {"conflict", "old_false"}:
        assert f"completion_blocked:{DAY}" in b.gaps
        assert not b.batches
    if state == "late":
        assert provider.read_basis(**scope, as_of=CUTOFF).proofs[0].available_at == CUTOFF
    assert not provider.read_basis(**SCOPE, as_of=CUTOFF).proofs


@pytest.mark.parametrize("field", ["available_at", "finished_at"])
def test_future_batch_does_not_block(conn: Connection, field: str) -> None:
    licence = uuid4()
    scope = {**SCOPE, "licence_id": licence}
    calendar(conn)
    saved = bar(conn, source="mairui", scope="per_licence", licence_id=licence)
    good, late = batch(conn, licence), batch(conn, licence, "failed")
    late[field] = CUTOFF.isoformat()
    c = receipt(
        conn, saved, pipeline_run_id=UUID(good["run_id"]), proof_kind="source_final_receipt"
    )
    c["proof"]["batches"] = [good, late]
    store.register_completion(conn, **c)
    provider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**scope, as_of=NOW)
    assert len(b.batches) == 1
    assert select_day(b, **scope, as_of=CUTOFF).d == DAY
    assert f"completion_blocked:{DAY}" in provider.read_basis(**scope, as_of=CUTOFF).gaps


@pytest.mark.parametrize("bad", ["status", "step", "finished_at", "window_trading_days", "issues"])
def test_invalid_batch_writes_gap(
    conn: Connection, monkeypatch: pytest.MonkeyPatch, bad: str
) -> None:
    saved = bar(conn)
    raw = {**BATCH, bad: "invalid"}
    if bad == "issues":
        del raw[bad]
    c = receipt(conn, saved)
    c["proof"]["batches"] = [raw]
    # 模拟历史不合格材料：仍走登记 API，仅在造数期间关闭批字段校验。
    with monkeypatch.context() as seed:
        seed.setattr(store, "validate_batch", lambda raw: None)
        evidence = store.register_completion(conn, **c)
    b = DatabaseHorizonEvidenceProvider(conn).read_basis(**SCOPE, as_of=NOW)
    assert f"batch_invalid:{evidence}" in b.gaps
    assert f"completion_blocked:{DAY}" in b.gaps
    assert not b.proofs
    assert not b.batches


def test_calendar_mapping_collect_and_read_only(conn: Connection) -> None:
    ids = []
    for offset, opened in ((-1, False), (0, True)):
        day = DAY + timedelta(days=offset)
        payload = {
            **package()["payload"],
            "is_open": opened,
            "coverage_start": str(DAY - timedelta(days=1)),
            "coverage_end": str(DAY),
        }
        ids.append(calendar(conn, data_date=day, payload=payload))
    saved = bar(conn)
    store.register_completion(conn, **receipt(conn, saved))
    queries: list[str] = []

    def trace(*args: Any) -> None:  # noqa: ANN401
        queries.append(str(args[2]))

    event.listen(conn, "before_cursor_execute", trace)
    provider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**SCOPE, as_of=CUTOFF)
    assert len(queries) == 3
    assert b.calendar is not None
    assert not b.gaps
    assert b.calendar.days == ((DAY - timedelta(days=1), False), (DAY, True))
    assert b.calendar.version_id == str(ids[-1])
    assert b.calendar.dependency_ids == tuple(str(v) for v in ids)
    assert (b.calendar.first_seen_at, b.calendar.available_at) == (NOW, NOW)
    result = collect(conn, UUID(U), "SYN", [], as_of=CUTOFF, evidence_provider=provider)
    assert result.d == DAY
    assert all(q.lstrip().upper().startswith("SELECT") for q in queries)


@pytest.mark.parametrize("case", ["fork", "same_day", "coverage", "missing_day"])
def test_calendar_gaps_are_not_filled(conn: Connection, case: str) -> None:
    p = package(code=None)
    if case == "coverage":
        p["payload"]["coverage_end"] = str(DAY - timedelta(days=1))
    elif case == "missing_day":
        p["data_date"] = DAY - timedelta(days=1)
        p["payload"]["coverage_start"] = str(p["data_date"])
    root = store.register_version(conn, **p)
    if case == "fork":
        for revision in ("v2", "v3"):
            store.register_version(conn, **{**p, "source_version": revision, "supersedes_id": root})
    elif case == "same_day":
        store.register_version(conn, **{**p, "source_key": "other"})
    saved = bar(conn)
    store.register_completion(conn, **receipt(conn, saved))
    b = DatabaseHorizonEvidenceProvider(conn).read_basis(**SCOPE, as_of=CUTOFF)
    gap = "calendar_conflict" if case == "same_day" else "calendar_not_covered"
    assert f"{gap}:{DAY}" in b.gaps
    assert select_day(b, **SCOPE, as_of=CUTOFF).d is None
    if case in {"fork", "same_day"}:
        assert f"version_conflict_day:{DAY}" in b.gaps
        assert not b.bars
        assert not b.proofs
        assert not b.batches


@pytest.mark.parametrize("case", ["blocked", "conflict"])
def test_unusable_day_preserves_previous_completed_day(conn: Connection, case: str) -> None:
    previous = DAY - timedelta(days=1)
    p = package()
    p["payload"]["coverage_start"] = str(previous)
    calendar(conn, payload=p["payload"])
    calendar(conn, data_date=previous, payload=p["payload"])
    p = package("daily_bar", data_date=previous)
    p["payload"]["trade_date"] = str(previous)
    saved = store.register_version(conn, **p)
    c = receipt(conn, saved)
    c["proof"]["trade_date"] = str(previous)
    store.register_completion(conn, **c)
    today = bar(conn)
    store.register_completion(conn, **receipt(conn, today))
    if case == "blocked":
        store.register_completion(conn, **receipt(conn, today, is_final=False))
    else:
        for revision in ("v2", "v3"):
            bar(conn, source_version=revision, supersedes_id=today)
    b = DatabaseHorizonEvidenceProvider(conn).read_basis(**SCOPE, as_of=CUTOFF)
    assert select_day(b, **SCOPE, as_of=CUTOFF).d == previous
    assert [p.version.version_id for p in b.proofs] == [str(saved)]

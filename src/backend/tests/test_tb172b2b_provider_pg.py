"""T-A202 §4：真实适配器读取合成登记材料，仅隔离测试数据库。"""

# ruff: noqa: S101
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, event, insert

from app.db.tables.realtime import pipeline_runs
from app.features import horizon_evidence_store as store
from app.features.horizon_evidence_provider import DatabaseHorizonEvidenceProvider
from app.features.horizon_sources import DailyBarVersion, HorizonEvidenceProvider
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
LATER = NOW + timedelta(hours=1)
SCOPE = {"user_id": UUID(U), "licence_id": None, "code": "SYN"}


def bar(connection: Connection, **changes: Any) -> UUID:  # noqa: ANN401
    return store.register_version(connection, **package("daily_bar", source_key="none", **changes))


@pytest.mark.parametrize("case", ["chain", "late", "fork", "roots", "hidden", "other_key"])
def test_a192_a1b_provider_revision_isolation(conn: Connection, case: str) -> None:  # noqa: F811
    first = bar(conn)
    second = bar(
        conn,
        source_version="v2",
        supersedes_id=None if case == "roots" else first,
        available_at=LATER if case in {"late", "hidden"} else NOW,
    )
    expected = first if case in {"late", "hidden"} else second
    if case == "chain":
        expected = bar(conn, source_version="v3", supersedes_id=second)
    if case in {"fork", "other_key"}:
        bar(conn, source_version="v3", supersedes_id=first)
    if case == "other_key":
        # 不同源内逻辑键各自保留；同一天不能据此任意挑一根用于完成判定。
        extra = store.register_version(conn, **package("daily_bar", source_key="other"))
        expected = extra
    provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(conn)
    args = {**SCOPE, "kind": "daily_bar", "dates": [DAY], "as_of": NOW}
    got = provider.read_versions(**args)
    assert [v.version_id for v in got.versions] == (
        [] if case in {"fork", "roots"} else [str(expected)]
    )
    assert bool(got.gaps) is (case in {"fork", "roots", "other_key"})
    if case == "late":
        store.register_completion(conn, **completion(conn, first))
        assert provider.read_versions(**{**args, "as_of": LATER}).versions[0].version_id == str(
            second
        )
        assert provider.read_versions(**args) == got
        assert provider.read_basis(**SCOPE, as_of=NOW).proofs[0].version.version_id == str(first)
        assert not provider.read_basis(**SCOPE, as_of=LATER).proofs
    if case == "hidden":
        # 不可见后继不能遮住截止前已存在的版本。
        assert provider.read_basis(**SCOPE, as_of=NOW).bars[0].version_id == str(first)


@pytest.mark.parametrize(
    "case", ["user", "licence", "none", "synthetic", "public", "null", "future", "date"]
)
def test_a188_source_revision_and_licence_isolation(conn: Connection, case: str) -> None:  # noqa: F811
    licence = uuid4()
    args = {**SCOPE, "licence_id": licence}
    changes: dict[str, Any] = {"source": "mairui", "scope": "per_licence", "licence_id": licence}
    kind = "daily_bar"
    if case in {"user", "licence", "none"}:
        args["user_id" if case == "user" else "licence_id"] = (
            UUID(int=1724) if case == "user" else None if case == "none" else uuid4()
        )
    elif case == "synthetic":
        changes = {}
        args["licence_id"] = None
    elif case == "public":
        kind = "calendar"
        changes = {"source": "merged_calendar", "scope": "public"}
        args["licence_id"] = None
    elif case == "null":
        changes["available_at"] = None
    elif case == "future":
        changes.update(first_seen_at=LATER, available_at=LATER)
    saved = store.register_version(conn, **package(kind, **changes))
    provider = DatabaseHorizonEvidenceProvider(conn)
    result = provider.read_versions(
        **args, kind=kind, dates=[DAY - timedelta(days=1) if case == "date" else DAY], as_of=NOW
    )
    allowed = case in {"synthetic", "public"}
    assert [v.version_id for v in result.versions] == ([str(saved)] if allowed else [])
    assert bool(result.gaps) is not allowed
    basis = provider.read_basis(**args, as_of=NOW)
    if case in {"user", "licence", "none", "null", "future"}:
        assert not basis.bars


@pytest.mark.parametrize("state", [True, False, None, "late", "null", "conflict"])
def test_completion_visibility_and_batches(conn: Connection, state: object) -> None:  # noqa: F811
    licence, run = uuid4(), uuid4()
    identity = {**SCOPE, "licence_id": licence}
    saved = bar(conn, source="mairui", scope="per_licence", licence_id=licence)
    conn.execute(
        insert(pipeline_runs).values(id=run, kind="daily_batch", run_date=DAY, status="ok")
    )
    batch = {
        **BATCH,
        "run_id": str(run),
        "licence_id": str(licence),
        "status": "partial",
        "issues": ["OTHER"],
        "window_trading_days": None,
    }
    c = completion(conn, saved, pipeline_run_id=run, proof_kind="source_final_receipt")
    c["proof"]["batches"] = [batch]
    c.update(
        is_final=state if state in (True, False, None) else True,
        available_at=LATER if state == "late" else None if state == "null" else NOW,
    )
    if state == "null":
        c["is_final"] = None
    store.register_completion(conn, **c)
    if state == "conflict":
        store.register_completion(conn, **{**c, "is_final": False})
    provider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**identity, as_of=NOW)
    assert len(b.proofs) == (0 if state in {"late", "null", "conflict"} else 1)
    if b.proofs:
        p = b.proofs[0]
        assert p.is_final is state
        assert p.available_at == NOW
        assert p.source_final_receipt == "synthetic fixture"
        assert p.run_id == str(run)
        assert p.version.version_id == str(saved)
        r = b.batches[0]
        assert (r.run_id, r.owner_id, r.licence_id, r.members) == (
            str(run),
            None,
            licence,
            ((UUID(U), "SYN"),),
        )
        assert (r.status, r.issues, r.finished_at, r.available_at) == (
            "partial",
            ("OTHER",),
            NOW,
            NOW,
        )
        assert (r.kind, r.step, r.run_date, r.window_trading_days) == (
            "daily_batch",
            "daily_bars.fetch",
            DAY,
            None,
        )
    else:
        assert b.gaps
    if state == "late":
        assert provider.read_basis(**identity, as_of=LATER).proofs[0].available_at == LATER


def test_calendar_mapping_collect_and_read_only(conn: Connection) -> None:  # noqa: F811
    for offset, opened in ((-1, False), (0, True)):
        day = DAY + timedelta(days=offset)
        payload = {
            **package()["payload"],
            "is_open": opened,
            "coverage_start": str(DAY - timedelta(days=1)),
            "coverage_end": str(DAY),
        }
        store.register_version(conn, **package(code=None, data_date=day, payload=payload))
    saved = bar(
        conn,
        payload={
            **package("daily_bar")["payload"],
            "price_unit": "CNY",
            "is_suspended": False,
            "fetched_at": NOW.isoformat(),
        },
    )
    store.register_completion(conn, **completion(conn, saved))
    queries: list[str] = []

    def trace(*args: Any) -> None:  # noqa: ANN401
        queries.append(str(args[2]))

    event.listen(conn, "before_cursor_execute", trace)
    provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**SCOPE, as_of=NOW)
    assert len(queries) <= 3
    assert b.calendar is not None
    assert b.calendar.days == ((DAY - timedelta(days=1), False), (DAY, True))
    v = b.bars[0]
    assert isinstance(v, DailyBarVersion)
    assert (v.unit, v.fetched_at, v.is_suspended, v.adj_type) == ("CNY", NOW, False, "none")
    assert v.transform_version == "v1"
    assert v.dependency_ids == ()
    assert b.calendar.dependency_ids[-1] == b.calendar.version_id
    assert select_day(b, **SCOPE, as_of=NOW + timedelta(minutes=30)).d == DAY
    result = collect(
        conn, UUID(U), "SYN", [], as_of=NOW + timedelta(minutes=30), evidence_provider=provider
    )
    assert result.d == DAY
    assert all(q.lstrip().upper().startswith("SELECT") for q in queries)


def test_empty_dates_vendor_and_naive_cutoff(conn: Connection) -> None:  # noqa: F811
    provider = DatabaseHorizonEvidenceProvider(conn)
    for kind, dates in (("daily_bar", []), ("vendor_factor", [DAY])):
        result = provider.read_versions(**SCOPE, kind=kind, dates=dates, as_of=NOW)
        assert not result.versions
    with pytest.raises(ValueError, match="aware"):
        provider.read_basis(**SCOPE, as_of=NOW.replace(tzinfo=None))


@pytest.mark.parametrize("case", ["fork", "coverage", "missing_day"])
def test_calendar_gaps_are_not_filled(conn: Connection, case: str) -> None:  # noqa: F811
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
    saved = bar(conn)
    store.register_completion(conn, **completion(conn, saved))
    provider = DatabaseHorizonEvidenceProvider(conn)
    b = provider.read_basis(**SCOPE, as_of=LATER)
    assert b.gaps
    selected = select_day(b, **SCOPE, as_of=LATER)
    assert selected.d is None
    assert selected.gaps


def test_other_kinds_keep_dates_and_dependencies(conn: Connection) -> None:  # noqa: F811
    dependency = store.register_version(conn, **package())
    saved = store.register_version(conn, **package("ex_rights", dependency_ids=[dependency]))
    bundle = DatabaseHorizonEvidenceProvider(conn).read_versions(
        **SCOPE, kind="ex_rights", dates=[DAY, DAY - timedelta(days=1)], as_of=NOW
    )
    assert [v.version_id for v in bundle.versions] == [str(saved)]
    assert bundle.versions[0].dependency_ids == (str(dependency),)
    assert bundle.gaps == (f"version_missing:{DAY - timedelta(days=1)}",)

"""T-A202 §4 / T-A204 阻断3：只读隔离测试库中的合成登记版本。"""

# ruff: noqa: S101
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, event, insert, select

from app.db.tables.horizon import horizon_completion_evidence as completions
from app.db.tables.horizon import horizon_input_versions as versions
from app.db.tables.realtime import pipeline_runs
from app.features import horizon_evidence_store as store
from app.features.horizon_evidence_provider import DatabaseHorizonEvidenceProvider
from app.features.horizon_sources import (
    CalendarVersion,
    DailyBarVersion,
    HorizonEvidenceProvider,
)
from app.features.horizon_windows import select_day
from app.strategy.horizon import inputs
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


def test_b2b1_complete_registration_still_has_no_basis(conn: Connection) -> None:  # noqa: F811
    store.register_version(conn, **package("calendar"))
    p = package("daily_bar")
    p["payload"].update(is_suspended=False, fetched_at=NOW.isoformat())
    saved = store.register_version(conn, **p)
    run = uuid4()
    conn.execute(
        insert(pipeline_runs).values(
            id=run,
            kind="daily_batch",
            run_date=DAY,
            step="daily_bars.fetch",
            status="ok",
            started_at=NOW,
            finished_at=NOW,
        )
    )
    c = completion(conn, saved, pipeline_run_id=run)
    c["proof"]["batches"] = [{**BATCH, "run_id": str(run)}]
    proof_id = store.register_completion(conn, **c)
    row = conn.execute(select(completions).where(completions.c.id == proof_id)).mappings().one()
    assert (row["is_final"], row["available_at"]) == (True, NOW)
    batch = row["proof"]["batches"][0]
    assert (batch["status"], datetime.fromisoformat(batch["finished_at"])) == ("ok", NOW)
    assert datetime.fromisoformat(batch["available_at"]) == NOW
    provider = DatabaseHorizonEvidenceProvider(conn)
    for kind in ("calendar", "daily_bar"):
        assert provider.read_versions(**SCOPE, kind=kind, dates=[DAY], as_of=LATER).versions
    basis = provider.read_basis(**SCOPE, as_of=LATER)
    assert (basis.bars, basis.proofs, basis.batches) == ((), (), ())
    assert "basis_unavailable" in basis.gaps
    assert select_day(basis, **SCOPE, as_of=LATER).d is None
    collected = inputs.collect(conn, UUID(U), "SYN", [], as_of=LATER, evidence_provider=provider)
    assert collected.d is None


@pytest.mark.parametrize("case", ["chain", "late", "fork", "roots", "hidden", "other_key"])
def test_a192_a1b_provider_revision_isolation(conn: Connection, case: str) -> None:  # noqa: F811
    first = bar(conn)
    second = bar(
        conn,
        source_version="v2",
        supersedes_id=None if case == "roots" else first,
        available_at=LATER if case == "late" else None if case == "hidden" else NOW,
    )
    expected = first if case in {"late", "hidden"} else second
    if case == "chain":
        expected = bar(conn, source_version="v3", supersedes_id=second)
    if case in {"fork", "other_key"}:
        bar(conn, source_version="v3", supersedes_id=first)
    if case == "other_key":
        expected = store.register_version(conn, **package("daily_bar", source_key="other"))
    provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(conn)
    args = {**SCOPE, "kind": "daily_bar", "dates": [DAY], "as_of": NOW}
    got = provider.read_versions(**args)
    assert [v.version_id for v in got.versions] == (
        [] if case in {"fork", "roots"} else [str(expected)]
    )
    assert got.gaps == (
        (f"version_conflict:daily_bar:{DAY}:none",)
        + (() if case == "other_key" else (f"version_missing:{DAY}",))
        if case in {"fork", "roots", "other_key"}
        else ()
    )
    if case == "late":
        assert provider.read_versions(**{**args, "as_of": LATER}).versions[0].version_id == str(
            second
        )
        assert provider.read_versions(**args) == got


@pytest.mark.parametrize(
    "case",
    [
        "own",
        "user",
        "licence",
        "none",
        "synthetic",
        "public",
        "bound_public",
        "null",
        "future",
        "date",
        "code",
    ],
)
def test_a188_source_revision_and_licence_isolation(conn: Connection, case: str) -> None:  # noqa: F811
    licence = uuid4()
    args = {**SCOPE, "licence_id": licence}
    changes: dict[str, Any] = {"source": "mairui", "scope": "per_licence", "licence_id": licence}
    kind = "daily_bar"
    if case in {"user", "licence", "none", "code"}:
        key = "user_id" if case == "user" else "code" if case == "code" else "licence_id"
        args[key] = (
            "OTHER"
            if case == "code"
            else UUID(int=1724)
            if case == "user"
            else (None if case == "none" else uuid4())
        )
    elif case == "synthetic":
        changes = {}
        args["licence_id"] = None
    elif case in {"public", "bound_public"}:
        kind = "calendar"
        changes = {"source": "merged_calendar", "scope": "public", "code": None}
        if case == "public":
            args["licence_id"] = None
    elif case == "null":
        changes.update(first_seen_at=None, available_at=None)
    elif case == "future":
        changes.update(first_seen_at=LATER, available_at=LATER)
    saved = store.register_version(conn, **package(kind, **changes))
    result = DatabaseHorizonEvidenceProvider(conn).read_versions(
        **args, kind=kind, dates=[DAY - timedelta(days=1) if case == "date" else DAY], as_of=NOW
    )
    allowed = case in {"own", "synthetic", "public", "bound_public"}
    assert [v.version_id for v in result.versions] == ([str(saved)] if allowed else [])
    assert bool(result.gaps) is not allowed


@pytest.mark.parametrize("key", ["price_unit", "volume_unit", "amount_unit"])
@pytest.mark.parametrize("nullable", [False, True])
def test_a204_daily_bar_units_round_trip(conn: Connection, key: str, nullable: bool) -> None:  # noqa: F811
    p = package("daily_bar")
    units: dict[str, str | None] = {
        "price_unit": "CNY",
        "volume_unit": "share",
        "amount_unit": "CNY",
    }
    if nullable:
        units[key] = None
    p["payload"].update(**units, fetched_at=NOW.isoformat(), is_suspended=False)
    saved = store.register_version(conn, **p)
    provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(conn)
    bundle = provider.read_versions(**SCOPE, kind="daily_bar", dates=[DAY], as_of=NOW)
    assert bundle.gaps == ()
    v = bundle.versions[0]
    assert isinstance(v, DailyBarVersion)
    assert getattr(v, "unit" if key == "price_unit" else key) == units[key]
    assert (v.version_id, v.fetched_at, v.is_suspended, v.adj_type) == (
        str(saved),
        NOW,
        False,
        "none",
    )
    assert (v.transform_version, v.dependency_ids) == ("v1", ())


@pytest.mark.parametrize("kind", ["calendar", "ex_rights", "adjust_factor", "feature"])
def test_other_kinds_keep_dates_and_dependencies(conn: Connection, kind: str) -> None:  # noqa: F811
    dependency_kind = "calendar" if kind == "ex_rights" else "ex_rights"
    deps = [store.register_version(conn, **package(dependency_kind)), bar(conn)]
    p = package(kind, dependency_ids=deps)
    if kind == "feature":
        proof = store.register_completion(conn, **completion(conn, deps[1]))
        p["payload"].update(dependency_ids=[str(d) for d in deps], evidence_ids=[str(proof)])
    saved = store.register_version(conn, **p)
    bundle = DatabaseHorizonEvidenceProvider(conn).read_versions(
        **SCOPE, kind=kind, dates=[DAY, DAY - timedelta(days=1)], as_of=NOW
    )
    assert [v.version_id for v in bundle.versions] == [str(saved)]
    v = bundle.versions[0]
    row = conn.execute(select(versions).where(versions.c.id == saved)).mappings().one()
    assert (v.version_hash, v.source_version, v.source, v.persisted_receipt) == (
        row["version_hash"],
        "v1",
        p["source"],
        "synthetic",
    )
    assert (v.first_seen_at, v.available_at, v.dependency_ids) == (
        NOW,
        NOW,
        tuple(str(d) for d in deps),
    )
    if kind == "calendar":
        assert isinstance(v, CalendarVersion)
        assert v.days == ((DAY, True),)
    assert bundle.gaps == (f"version_missing:{DAY - timedelta(days=1)}",)


def test_empty_dates_vendor_naive_cutoff_and_read_only(conn: Connection) -> None:  # noqa: F811
    bar(conn)
    provider: HorizonEvidenceProvider = DatabaseHorizonEvidenceProvider(conn)
    queries: list[str] = []

    def capture(*args: Any) -> None:  # noqa: ANN401
        queries.append(args[2])

    event.listen(conn, "before_cursor_execute", capture)
    for kind, dates in (("daily_bar", []), ("vendor_factor", [DAY])):
        bundle = provider.read_versions(**SCOPE, kind=kind, dates=dates, as_of=NOW)
        assert not bundle.versions
        assert bundle.gaps == (
            () if not dates else ("vendor_factor_unavailable", f"version_missing:{DAY}")
        )
    assert not queries
    basis = provider.read_basis(**SCOPE, as_of=NOW)
    assert basis.bars
    assert not basis.proofs
    queries.clear()
    for method, kwargs in (
        (provider.read_basis, {}),
        (provider.read_versions, {"kind": "daily_bar", "dates": []}),
    ):
        with pytest.raises(ValueError, match="aware"):
            method(**SCOPE, **kwargs, as_of=NOW.replace(tzinfo=None))
    result = provider.read_versions(**SCOPE, kind="daily_bar", dates=[DAY], as_of=NOW)
    assert result.versions
    assert (
        provider.read_versions(
            **SCOPE,
            kind="daily_bar",
            dates=[DAY],
            as_of=NOW.astimezone(timezone(timedelta(hours=8))),
        )
        == result
    )
    assert len(queries) == 2
    assert all(q.lstrip().upper().startswith("SELECT") for q in queries)

"""登记幂等、修订链、来源隔离：仅独立临时数据库。"""

# ruff: noqa: S101
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, insert, select

from app.db.tables.horizon import horizon_input_versions as versions
from app.db.tables.realtime import pipeline_runs
from app.db.tables.users import users
from app.features import horizon_evidence_store as store
from tests.test_tb172b1a_horizon_versions_pg import world  # noqa: F401
from tests.test_tb172b2a_evidence_store_offline import BATCH, PAYLOADS, PROOF, U

NOW = datetime(2026, 11, 15, 9, tzinfo=UTC)


@pytest.fixture
def conn(world: SimpleNamespace) -> Iterator[Connection]:  # noqa: F811
    with world.engine.begin() as connection:
        for n in (1723, 1724):
            connection.execute(
                insert(users).values(
                    id=UUID(int=n),
                    username=f"synthetic_{n}",
                    password_hash="unusable",  # noqa: S106
                    role="user",
                    status="approved",
                )
            )
        yield connection


def package(kind: str = "calendar", **changes: object) -> dict[str, Any]:
    return {
        "user_id": UUID(U),
        "licence_id": None,
        "kind": kind,
        "source": "derived" if kind in {"feature", "adjust_factor"} else "fake",
        "scope": "public" if kind in {"feature", "adjust_factor"} else "synthetic",
        "code": "SYN",
        "data_date": date(2026, 11, 15),
        "source_key": "merged_calendar",
        "source_version": "v1",
        "payload": {**PAYLOADS[kind], "persisted_receipt": "synthetic"},
        "first_seen_at": NOW,
        "available_at": NOW,
        "computed_at": None,
        "dependency_ids": [],
        "transform_version": "v1",
    } | changes


def completion(conn: Connection, bar: UUID, **changes: object) -> dict[str, Any]:
    row = conn.execute(select(versions).where(versions.c.id == bar)).mappings().one()
    proof = {
        **PROOF,
        "version_hash": row["version_hash"],
        "source": row["source"],
        "licence_id": str(row["licence_id"]) if row["licence_id"] else None,
        "persisted_receipt": "synthetic",
        "source_final_receipt": "synthetic fixture",
    }
    return {
        "bar_version_id": bar,
        "pipeline_run_id": None,
        "is_final": True,
        "available_at": NOW,
        "proof_kind": "synthetic",
        "proof": proof,
    } | changes


def test_registration_idempotency(conn: Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    p = package()
    first = store.register_version(conn, **p)
    assert store.register_version(conn, **p) == first
    digest = conn.scalar(select(versions.c.version_hash).where(versions.c.id == first))
    assert digest == store.canon_sha256({**p, "supersedes_id": None})
    monkeypatch.setattr(store, "canon_sha256", lambda obj: digest)
    with pytest.raises(store.EvidenceConflict):
        store.register_version(conn, **(p | {"source_version": "changed"}))


@pytest.mark.parametrize("case", ["same", "licence", "key", "missing"])
def test_revision_chain(conn: Connection, case: str) -> None:
    p = package(source="merged_calendar", scope="per_licence", licence_id=uuid4())
    old = store.register_version(conn, **p)
    p |= {"source_version": "v2", "supersedes_id": old}
    if case == "licence":
        p["licence_id"] = uuid4()
    elif case == "key":
        p["source_key"] = "other"
    elif case == "missing":
        p["supersedes_id"] = uuid4()
    if case == "same":
        assert store.register_version(conn, **p) != old
    else:
        with pytest.raises(store.EvidenceRejected):
            store.register_version(conn, **p)


@pytest.mark.parametrize("case", ["user", "licence", "missing", "duplicate", "self"])
def test_source_isolation(conn: Connection, case: str, monkeypatch: pytest.MonkeyPatch) -> None:
    licence = uuid4()
    dep = store.register_version(
        conn, **package(source="merged_calendar", scope="per_licence", licence_id=licence)
    )
    p = package(
        "adjust_factor",
        computed_at=NOW,
        dependency_ids=[dep],
        scope="per_licence",
        licence_id=licence,
    )
    if case == "user":
        p["user_id"] = UUID(int=1724)
    elif case == "licence":
        p["licence_id"] = uuid4()
    elif case == "missing":
        p["dependency_ids"] = [uuid4()]
    elif case == "duplicate":
        p["dependency_ids"] = [dep, dep]
    else:
        monkeypatch.setattr(store, "uuid4", lambda: dep)
    with pytest.raises(store.EvidenceRejected):
        store.register_version(conn, **p)


@pytest.mark.parametrize("unknown", [False, True])
@pytest.mark.parametrize("hours", [-1, 1])
def test_derived_available_at(conn: Connection, unknown: bool, hours: int) -> None:
    dep = store.register_version(conn, **package(available_at=None if unknown else NOW))
    computed = NOW + timedelta(hours=hours)
    p = package("adjust_factor", computed_at=computed, dependency_ids=[dep], available_at=None)
    result = store.register_version(conn, **p)
    assert conn.scalar(select(versions.c.available_at).where(versions.c.id == result)) == (
        None if unknown else max(NOW, computed)
    )
    with pytest.raises(store.EvidenceRejected):
        store.register_version(conn, **(p | {"available_at": NOW + timedelta(hours=2)}))


@pytest.mark.parametrize("field", list(PROOF))
def test_completion_binding(conn: Connection, field: str) -> None:
    bar = store.register_version(conn, **package("daily_bar"))
    p = completion(conn, bar)
    p["proof"][field] = str(uuid4()) if field.endswith("id") else "b" * 64
    if field == "sha256":  # 材料摘要不等于版本摘要，允许独立取值。
        store.register_completion(conn, **p)
    else:
        with pytest.raises(store.EvidenceRejected):
            store.register_completion(conn, **p)


COMPLETION_CASES = "kind scope batches pipeline members date valid synthetic missing_run"


@pytest.mark.parametrize("case", COMPLETION_CASES.split())
def test_completion_gates_and_idempotency(conn: Connection, case: str) -> None:
    p = (
        package()
        if case == "kind"
        else package("daily_bar", source="mairui", scope="per_licence", licence_id=uuid4())
    )
    if case == "synthetic":
        p = package("daily_bar")
    bar = store.register_version(conn, **p)
    c = completion(conn, bar)
    if case not in {"kind", "synthetic"}:
        if case != "scope":
            c["proof_kind"] = "source_final_receipt"
        if case != "batches":
            run = uuid4()
            conn.execute(
                insert(pipeline_runs).values(
                    id=run, kind="daily_batch", run_date=p["data_date"], status="ok"
                )
            )
            c["pipeline_run_id"] = run
            c["proof"]["batches"] = [{**BATCH, "run_id": U if case == "pipeline" else str(run)}]
    if case == "missing_run":
        c["pipeline_run_id"] = None
    if case in {"members", "date"}:
        c["proof"]["batches"][0]["members" if case == "members" else "run_date"] = (
            [] if case == "members" else "2026-11-14"
        )
    if case in {"valid", "synthetic"}:
        first = store.register_completion(conn, **c)
        assert store.register_completion(conn, **c) == first
    else:
        with pytest.raises(store.EvidenceRejected):
            store.register_completion(conn, **c)

"""T-A202 权息读取：隔离 PG、登记合成材料，禁止外部采集。"""

# ruff: noqa: S101
from datetime import timedelta
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Connection, event

from app.features import horizon_evidence_store as store
from app.features.horizon_adjustments import read_adjustment_factors, to_prepare_factors
from app.features.horizon_evidence_store import register_version
from app.features.pipeline import prepare
from tests.test_tb172b2a_evidence_store_pg import (
    NOW,
    conn,  # noqa: F401
    package,
    world,  # noqa: F401
)

DAY = NOW.date()
OLD = DAY - timedelta(days=2)
MID = DAY - timedelta(days=1)
SHA = "a" * 64
ARGS = {"user_id": UUID(int=1723), "licence_id": None, "code": "SYN", "as_of": NOW}


def reference_bar(connection: Connection, **changes: Any) -> UUID:  # noqa: ANN401
    day = changes.pop("data_date", OLD - timedelta(days=1))
    p = package("daily_bar", data_date=day, **changes)
    p["payload"] = {
        **p["payload"],
        "close": "10",
        "price_unit": "CNY/share",
        "trade_date": str(day),
        **changes.get("payload", {}),
    }
    p["payload"]["hash"] = store.material_hash(p["payload"])
    return register_version(connection, **p)


def factor(connection: Connection, day: object = OLD, **changes: Any) -> UUID:  # noqa: ANN401
    if "dependency_ids" not in changes:
        changes["dependency_ids"] = [
            register_version(connection, **package("ex_rights")),
            reference_bar(connection),
        ]
    payload = {
        **package("adjust_factor")["payload"],
        "date": str(day),
        "value": "2",
        "coverage_start": str(OLD),
        "coverage_end": str(DAY),
        "trade_dates": [str(OLD), str(MID), str(DAY)],
        "algo_audit": {"synthetic": True, "verified": True},
        "integrity_audit": {"synthetic": True, "verified": True},
        **changes.pop("payload", {}),
    }
    return register_version(
        connection,
        **package(
            "adjust_factor",
            data_date=day,
            source_key="cumulative",
            computed_at=changes.pop("computed_at", NOW),
            payload=payload,
            **changes,
        ),
    )


@pytest.mark.parametrize(
    "case",
    [
        "valid",
        "late",
        "unknown",
        "bar_late",
        "bar_unknown",
        "bar_revision",
        "future_event",
        "dependency_revision",
        "transitive_future",
        "snapshot",
        "licence",
        "user",
        "empty",
    ],
)
def test_a192_pn03_unknown_visibility_and_single_snapshot(
    conn: Connection,  # noqa: F811
    case: str,
) -> None:
    event_day = DAY + timedelta(days=1) if case == "future_event" else OLD
    dep_args: dict[str, Any] = {}
    if case in {"late", "unknown"}:
        dep_args["available_at"] = None if case == "unknown" else NOW + timedelta(hours=1)
    if case == "transitive_future":
        dep_args["dependency_ids"] = [
            register_version(
                conn, **package("ex_rights", data_date=DAY + timedelta(days=1), source_key="future")
            )
        ]
    dep = register_version(
        conn,
        **package(
            "ex_rights",
            data_date=event_day,
            payload={**package("ex_rights")["payload"], "ex_date": str(event_day)},
            **dep_args,
        ),
    )
    if case == "dependency_revision":
        register_version(
            conn,
            **package(
                "ex_rights",
                data_date=OLD,
                source_version="v2",
                supersedes_id=dep,
            ),
        )
    # b2a 合法包将参考价的 code/trade_date/source/source_licence_id 绑定外层。
    bar = reference_bar(
        conn,
        available_at=None if case == "bar_unknown" else NOW + timedelta(hours=case == "bar_late"),
    )
    if case == "bar_revision":
        reference_bar(conn, source_version="v2", supersedes_id=bar)
    args = {**ARGS}
    if case == "licence":
        args["licence_id"] = uuid4()
    if case == "user":
        args["user_id"] = UUID(int=1724)
    changes: dict[str, Any] = {"dependency_ids": [dep, bar], "available_at": None}
    if case == "licence":
        changes.update(scope="per_licence", licence_id=uuid4())
    if case != "empty":
        saved = factor(
            conn, payload={"snapshot_sha256": "b" * 64 if case == "snapshot" else SHA}, **changes
        )
    queries: list[str] = []
    event.listen(conn, "before_cursor_execute", lambda *a: queries.append(a[2]))
    result = read_adjustment_factors(conn, **args, dates=[MID, DAY], snapshot_sha256=SHA)
    assert all(q.lstrip().upper().startswith("SELECT") for q in queries)
    assert "horizon_input_versions.user_id =" in queries[0]
    assert result.snapshot_sha256 == SHA
    assert bool(result.factors) is (case == "valid")
    if case == "valid":
        assert result.dependency_ids == (str(saved), str(dep), str(bar))
        assert not result.gaps
        assert result.coverage == (MID, DAY)
        assert to_prepare_factors(result)[0]["available_at"] == NOW.isoformat()
    else:
        assert f"adjust_factor_missing:{DAY}" in result.gaps
        assert to_prepare_factors(result) == []


@pytest.mark.parametrize(
    "case",
    [
        "sparse",
        "chain",
        "late_revision",
        "fork",
        "roots",
        "coverage",
        "trade_dates",
        "issues",
        "mixed",
        "anchor",
    ],
)
def test_a188_qfq_future_event_and_anchor(conn: Connection, case: str) -> None:  # noqa: F811
    root = factor(conn)
    expected = root
    if case in {"chain", "late_revision", "fork", "roots"}:
        expected = factor(
            conn,
            source_version="v2",
            supersedes_id=None if case == "roots" else root,
            computed_at=NOW + timedelta(hours=1) if case == "late_revision" else NOW,
            available_at=None,
            payload={"value": "3"},
        )
        if case == "chain":
            expected = factor(
                conn, source_version="v3", supersedes_id=expected, payload={"value": "4"}
            )
        if case == "fork":
            factor(conn, source_version="v3", supersedes_id=root)
    if case in {"coverage", "trade_dates", "issues", "mixed", "anchor"}:
        payload = {
            "coverage": {"coverage_end": str(MID)},
            "trade_dates": {"trade_dates": [str(OLD), str(MID)]},
            "issues": {"issues": ["unknown event visibility"]},
            "mixed": {"snapshot_sha256": "b" * 64},
            "anchor": {"value": "4"},
        }[case]
        factor(conn, DAY, payload=payload)
    result = read_adjustment_factors(conn, **ARGS, dates=[MID, DAY], snapshot_sha256=SHA)
    failed = case in {"fork", "roots", "coverage", "trade_dates", "issues"}
    if failed:
        assert f"adjust_factor_missing:{DAY}" in result.gaps
        assert to_prepare_factors(result) == []
    else:
        assert result.factors[0].version_id == str(root if case == "late_revision" else expected)
    instrument = {
        "adjust": "none",
        "currency": "CNY",
        "price_unit": "CNY/share",
        "amount_unit": "CNY",
        "volume_unit": "share",
        "bars": [
            {
                "trade_date": str(MID),
                "first_seen_at": NOW.isoformat(),
                "is_final": True,
                "open": "10",
                "high": "10",
                "low": "10",
                "close": "10",
                "amount": "100",
            }
        ],
    }
    prepared = prepare(
        instrument, [str(MID)], as_of=NOW, factors=to_prepare_factors(result), registry={}
    )
    assert prepared["series"]["f.close_qfq"] == [None if failed else 5 if case == "anchor" else 10]
    assert bool(prepared["gaps"]) is failed
    if case == "late_revision":
        later = read_adjustment_factors(
            conn,
            **{**ARGS, "as_of": NOW + timedelta(hours=1)},
            dates=[MID, DAY],
            snapshot_sha256=SHA,
        )
        assert later.factors[0].version_id == str(expected)
        assert (
            read_adjustment_factors(conn, **ARGS, dates=[MID, DAY], snapshot_sha256=SHA) == result
        )


@pytest.mark.parametrize(
    "key", [k for k in package("adjust_factor")["payload"] if k != "persisted_receipt"]
)
def test_invalid_selected_payload_cannot_hide_behind_old_observation(
    conn: Connection,  # noqa: F811
    key: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factor(conn)
    # 模拟历史材料字段未知；仍经登记写入，不修改追加表或 b2a 公开行为。
    with monkeypatch.context() as patch:
        patch.setattr(store, "validate_payload", lambda *a, **kw: None)
        factor(conn, DAY, payload={key: None})
    result = read_adjustment_factors(conn, **ARGS, dates=[MID, DAY], snapshot_sha256=SHA)
    assert any(g.startswith("adjust_factor_invalid:") for g in result.gaps)
    assert f"adjust_factor_missing:{DAY}" in result.gaps
    assert to_prepare_factors(result) == []


@pytest.mark.parametrize("slot", ["algo_audit", "integrity_audit"])
@pytest.mark.parametrize(
    "audit",
    [
        {"verified": True},
        {"verified": False},
        {"synthetic": True},
        {"verified": "true"},
        {"verified": 1},
    ],
)
@pytest.mark.parametrize("real_labels", [False, True])
def test_r252_audits_fail_closed(
    conn: Connection,  # noqa: F811
    slot: str,
    audit: dict[str, object],
    real_labels: bool,
) -> None:
    factor(conn)  # 最新材料被拒绝后，不得回退此旧观测填洞。
    licence = uuid4() if real_labels else None
    dep = register_version(
        conn,
        **package(
            "ex_rights", **({"source": "tdx_gbbq", "scope": "public"} if real_labels else {})
        ),
    )
    bar = reference_bar(
        conn,
        **(
            {"source": "mairui", "scope": "per_licence", "licence_id": licence}
            if real_labels
            else {}
        ),
    )
    saved = factor(
        conn,
        DAY,
        dependency_ids=[dep, bar],
        licence_id=licence,
        scope="per_licence" if real_labels else "public",
        payload={slot: audit},
    )
    result = read_adjustment_factors(
        conn, **{**ARGS, "licence_id": licence}, dates=[MID, DAY], snapshot_sha256=SHA
    )
    if audit.get("verified") is True:
        assert result.coverage == (MID, DAY)
        assert not result.gaps
    else:
        assert result.coverage == (MID,)
        assert f"adjust_factor_unverified:{saved}" in result.gaps
        assert f"adjust_factor_missing:{DAY}" in result.gaps
        assert to_prepare_factors(result) == []


@pytest.mark.parametrize("slot", ["algo_audit", "integrity_audit"])
@pytest.mark.parametrize("verified", [False, True])
def test_r252_nested_factor_audits(
    conn: Connection,  # noqa: F811
    slot: str,
    verified: bool,
) -> None:
    nested = factor(conn, code="NESTED", payload={slot: {"verified": verified}})
    deps = [register_version(conn, **package("ex_rights")), reference_bar(conn), nested]
    factor(conn, dependency_ids=deps)
    result = read_adjustment_factors(conn, **ARGS, dates=[DAY], snapshot_sha256=SHA)
    assert bool(result.factors) is verified
    if not verified:
        assert f"adjust_factor_unverified:{nested}" in result.gaps
        assert f"adjust_factor_missing:{DAY}" in result.gaps
        assert to_prepare_factors(result) == []


@pytest.mark.parametrize(
    "case", ["valid", "close_null", "unit_null", "unit_missing", "same_day", "after_day", "late"]
)
def test_r252_reference_price_fail_closed(
    conn: Connection,  # noqa: F811
    case: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factor(conn)
    payload = dict(package("daily_bar")["payload"], close="10", price_unit="CNY/share")
    bar_day = DAY if case == "after_day" else MID if case == "same_day" else OLD
    payload["trade_date"] = str(bar_day)
    if case == "close_null":
        payload["close"] = None
    if case == "unit_null":
        payload["price_unit"] = None
    if case == "unit_missing":
        del payload["price_unit"]
    if case != "unit_missing":
        payload["hash"] = store.material_hash(payload)
    with monkeypatch.context() as patch:
        if case == "unit_missing":  # 追加历史损坏材料；不改 b2a 或不可变记录。
            patch.setattr(store, "validate_payload", lambda *a, **kw: None)
        bar = register_version(
            conn,
            **package(
                "daily_bar",
                data_date=bar_day,
                payload=payload,
                available_at=NOW + timedelta(seconds=1) if case == "late" else NOW,
            ),
        )
    dep = register_version(
        conn,
        **package(
            "ex_rights",
            data_date=MID,
            payload={**package("ex_rights")["payload"], "ex_date": str(MID)},
        ),
    )
    original_row = store._row
    with monkeypatch.context() as patch:
        if case == "late":
            # 模拟父因子可见时间陈旧；读取仍必须验证真实参考价版本的 PIT。
            def stale_parent(*args: Any) -> dict[str, Any]:  # noqa: ANN401
                row = dict(original_row(*args))
                if args[-1] == bar:
                    row["available_at"] = NOW
                return row

            patch.setattr(store, "_row", stale_parent)
        saved = factor(conn, DAY, dependency_ids=[dep, bar])
    result = read_adjustment_factors(conn, **ARGS, dates=[MID, DAY], snapshot_sha256=SHA)
    if case == "valid":
        assert result.coverage == (MID, DAY)
        assert not result.gaps
    else:
        assert result.coverage == (MID,)
        assert f"adjust_factor_dependency_unavailable:{saved}" in result.gaps
        assert f"adjust_factor_missing:{DAY}" in result.gaps
        assert to_prepare_factors(result) == []

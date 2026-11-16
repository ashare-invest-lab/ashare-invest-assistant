"""T-B179：虚构材料固定向量；JSON 常量是精确 UTF-8 文本，无 BOM/尾换行。"""

# ruff: noqa: S101
import socket
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from app.features import horizon_evidence_store as store

ID = "abcdefab-cdef-4abc-8def-abcdefabcdef"
T = datetime.fromisoformat("2026-01-02T11:04:05+08:00")
CANON_JSON = (
    '{"id":"abcdefab-cdef-4abc-8def-abcdefabcdef","missing":null,'
    '"note":"中文","t":"2026-01-02T03:04:05.000000Z"}'
)
CANON_SHA = "54fd26faaf78fedda4ae870c58c2facdba6f03cd556c79fb954bd2f00461b125"
# 全部为合成字段；null 保留，十进制字符串不改写精度/尾零。
MATERIAL: dict[str, Any] = {
    "code": "SYN",
    "trade_date": "2026-01-02",
    "adj_type": "none",
    "open": "10.00",
    "high": "11.00",
    "low": "9.00",
    "close": "10.50",
    "volume": "100.00",
    "amount": "1050.00",
    "pre_close": None,
    "is_suspended": False,
    "source": "fake",
    "source_licence_id": ID.upper(),
    "raw_fields": {"说明": "中文", "价格": "10.50", "缺失": None},
    "raw_units": {"价格": "元/股", "未知": None},
    "price_unit": "CNY/share",
    "volume_unit": "share",
    "amount_unit": "CNY",
    "fetched_at": "2026-01-02T11:04:05+08:00",
    "persisted_receipt": "synthetic",
}
MATERIAL_JSON = (
    '{"adj_type":"none","amount":"1050.00","amount_unit":"CNY","close":"10.50","code":"SYN","high'
    '":"11.00","is_suspended":false,"low":"9.00","open":"10.00","pre_close":null,"price_unit":"CN'
    'Y/share","raw_fields":{"价格":"10.50","缺失":null,"说明":"中文"},"raw_units":{"价格":"元/股","未知":null},'
    '"source":"fake","source_licence_id":"abcdefab-cdef-4abc-8def-abcdefabcdef","trade_date":"202'
    '6-01-02","volume":"100.00","volume_unit":"share"}'
)
MATERIAL_SHA = "2c88300810edc94f706bcde6021898c3fcff1e144c20404399add7ec6d6ba5a8"
VERSION_JSON = (
    '{"available_at":"2026-01-02T03:04:05.000000Z","code":"SYN","computed_at":null,"data_date":"2'
    '026-01-02","dependency_ids":[],"first_seen_at":"2026-01-02T03:04:05.000000Z","kind":"daily_b'
    'ar","licence_id":"abcdefab-cdef-4abc-8def-abcdefabcdef","payload":{"adj_type":"none","amount'
    '":"1050.00","amount_unit":"CNY","close":"10.50","code":"SYN","fetched_at":"2026-01-02T03:04:'
    '05.000000Z","hash":"2c88300810edc94f706bcde6021898c3fcff1e144c20404399add7ec6d6ba5a8","high"'
    ':"11.00","is_suspended":false,"low":"9.00","open":"10.00","persisted_receipt":"synthetic","p'
    're_close":null,"price_unit":"CNY/share","raw_fields":{"价格":"10.50","缺失":null,"说明":"中文"},"raw'
    '_units":{"价格":"元/股","未知":null},"source":"fake","source_licence_id":"abcdefab-cdef-4abc-8def-'
    'abcdefabcdef","trade_date":"2026-01-02","volume":"100.00","volume_unit":"share"},"scope":"sy'
    'nthetic","source":"fake","source_key":"none","source_version":"synthetic-v1","supersedes_id"'
    ':null,"transform_version":"identity-v1","user_id":"abcdefab-cdef-4abc-8def-abcdefabcdef"}'
)
VERSION_SHA = "48398bd567357291fbebfa3cadf1a805ffaa277b89a2e456d98a26ada44c0941"


@pytest.fixture(autouse=True)
def deny_network(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        pytest.fail("T-B179 外呼必须为零")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)


def material() -> dict[str, Any]:
    return {**deepcopy(MATERIAL), "hash": store.material_hash(MATERIAL)}


def version() -> dict[str, Any]:
    payload = material()
    payload["source_licence_id"] = ID  # 与外层绑定；大写 UUID 的归一由材料向量覆盖。
    return {
        "user_id": UUID(ID),
        "licence_id": UUID(ID),
        "kind": "daily_bar",
        "source": "fake",
        "scope": "synthetic",
        "code": "SYN",
        "data_date": date(2026, 1, 2),
        "source_key": "none",
        "source_version": "synthetic-v1",
        "payload": payload,
        "first_seen_at": T,
        "available_at": T,
        "computed_at": None,
        "dependency_ids": [],
        "transform_version": "identity-v1",
        "supersedes_id": None,
    }


def validate(payload: dict[str, Any]) -> None:
    store.validate_payload(
        "daily_bar", payload, dependency_ids=[], transform_version="identity-v1", available_at=T
    )


def test_contract_vector_and_recursive_types() -> None:
    obj = {"id": UUID(ID.upper()), "t": T, "note": "中文", "missing": None}
    assert store._canon(obj) == CANON_JSON
    assert store.canon_sha256(obj) == CANON_SHA
    assert store._canon({"v": [Decimal("1.20"), date(2026, 1, 2), None]}) == (
        '{"v":["1.20","2026-01-02",null]}'
    )
    assert store.canon_sha256(obj) == store.canon_sha256(dict(reversed(list(obj.items()))))
    assert store.canon_sha256(obj) == store.canon_sha256(
        {**obj, "t": datetime.fromisoformat("2026-01-02T03:04:05+00:00")}
    )
    assert store.canon_sha256([1, 2]) != store.canon_sha256([2, 1])
    # raw_fields 内部结构未验证：同名原始字符串没有被声明为 UUID/时间。
    raw = {"raw_fields": {"id": "原始编号", "available_at": "未知", "t": T}}
    assert store._canon(raw) == (
        '{"raw_fields":{"available_at":"未知","id":"原始编号","t":"2026-01-02T03:04:05.000000Z"}}'
    )
    assert store.canon_sha256({"members": [[ID.upper(), "SYN"]], "dependency_ids": [ID]}) == (
        store.canon_sha256({"members": [[ID, "SYN"]], "dependency_ids": [UUID(ID)]})
    )


@pytest.mark.parametrize(
    "bad",
    [
        datetime(2026, 1, 2),
        object(),
        {1, 2},
        (1, 2),
        {1: "x"},
        float("nan"),
        float("inf"),
        Decimal("NaN"),
    ],
)
def test_reject_non_json_or_naive(bad: object) -> None:
    with pytest.raises((store.EvidenceRejected, ValueError)):
        store.canon_sha256({"nested": [bad]})


@pytest.mark.parametrize("bad", [{"members": [[ID, "SYN", "extra"]]}, {"user_id": object()}])
def test_declared_types_rejected(bad: object) -> None:
    with pytest.raises(store.EvidenceRejected):
        store.canon_sha256(bad)


def test_material_and_full_registration_vectors(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = material()
    validate(payload)
    covered = {k: payload[k] for k in store.MATERIAL_FIELDS}
    assert store._canon(covered) == MATERIAL_JSON
    assert payload["hash"] == MATERIAL_SHA
    assert store._canon(version()) == VERSION_JSON
    assert store.canon_sha256(version()) == VERSION_SHA
    # 走真实登记组包路径，替换的只有持久化边界；无需 DB/外呼。
    saved: list[dict[str, Any]] = []

    def capture(conn: object, table: object, values: dict[str, Any], keys: object) -> UUID:
        saved.append(values)
        return UUID(int=179)

    monkeypatch.setattr(store, "_save", capture)
    package = version()
    store.register_version(None, **package)
    assert saved[0]["version_hash"] == VERSION_SHA


@pytest.mark.parametrize("key", tuple(MATERIAL.keys() - {"fetched_at", "persisted_receipt"}))
def test_each_covered_field_and_missing(key: str) -> None:
    payload = material()
    value = payload[key]
    payload[key] = (
        str(UUID(int=179))
        if key == "source_licence_id"
        else {"changed": True}
        if isinstance(value, dict)
        else "changed"
    )
    assert store.material_hash(payload) != MATERIAL_SHA
    del payload[key]
    with pytest.raises(store.EvidenceRejected, match=key):
        store.material_hash(payload)
    with pytest.raises(store.EvidenceRejected, match=key):
        validate(payload)


@pytest.mark.parametrize(
    "key", ["fetched_at", "persisted_receipt", "hash", "version_hash", "proof_hash"]
)
def test_exclusions_and_no_self_reference(key: str) -> None:
    payload = material()
    payload[key] = "changed"
    assert store.material_hash(payload) == MATERIAL_SHA
    del payload[key]
    assert store.material_hash(payload) == MATERIAL_SHA


def test_nullable_timezone_and_outer_coverage() -> None:
    payload = material()
    for stamp in ("2026-01-02T03:04:05Z", None):
        other = {**payload, "fetched_at": stamp}
        validate(other)
        assert store.material_hash(other) == MATERIAL_SHA
    upper = {**payload, "source_licence_id": ID}
    assert store.material_hash(upper) == MATERIAL_SHA
    assert store.material_hash(dict(reversed(list(payload.items())))) == MATERIAL_SHA
    with pytest.raises(store.EvidenceRejected, match="fetched_at"):
        validate({**payload, "fetched_at": "2026-01-02T03:04:05"})
    with pytest.raises(store.EvidenceRejected, match="timezone_required"):
        store.canon_sha256({"available_at": "2026-01-02T03:04:05"})
    assert store.canon_sha256({"available_at": T, "licence_id": UUID(ID)}) == (
        store.canon_sha256({"available_at": "2026-01-02T03:04:05Z", "licence_id": ID.upper()})
    )
    package = version()
    changed = {**package, "payload": {**package["payload"], "hash": "0" * 64}}
    assert store.canon_sha256(package) != store.canon_sha256(changed)
    # version_hash 包含 payload.hash；proof_hash 经 proof.version_hash 引用它。
    proof = {"proof": {"version_hash": store.canon_sha256(package)}}
    assert store.canon_sha256(proof) != store.canon_sha256(
        {"proof": {"version_hash": store.canon_sha256(changed)}}
    )
    nullable = {
        **payload,
        **dict.fromkeys(
            [
                "open",
                "high",
                "low",
                "close",
                "pre_close",
                "volume",
                "amount",
                "is_suspended",
                "price_unit",
                "volume_unit",
                "amount_unit",
                "source",
                "source_licence_id",
                "fetched_at",
            ]
        ),
    }
    nullable["hash"] = store.material_hash(nullable)
    validate(nullable)


@pytest.mark.parametrize(
    "bad", [None, "", "material", "A" * 64, "g" * 64, "a" * 63, "a" * 65, "0" * 64]
)
def test_hash_format_and_mismatch(bad: object) -> None:
    with pytest.raises(store.EvidenceRejected, match="daily_bar:hash"):
        validate({**material(), "hash": bad})
    payload = material()
    payload["close"] = "10.51"
    with pytest.raises(store.EvidenceRejected, match="daily_bar:hash_mismatch"):
        validate(payload)

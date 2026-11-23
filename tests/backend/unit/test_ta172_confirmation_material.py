"""可信确认材料最小增量：synthetic / source=fake，绝非生产材料。

契约出处：docs/contracts/daily-bars-source.md，origin/main 当前 f4e3525 上该文件
blob 与 d02b0ac（docs(T-A180b): §10.12 治理员必改两处与建议 a–d）相同；
章节「### 10.12 可信确认材料、tb143 SQL 定位与演练链（T-A180）」第 1 条
「可信确认材料（T-A179 残项 R1）」。本条不在 PR base be/T-B163r3@444dae9 的 docs 中。

raw_bytes 是虚构 JSON/CSV；解析字段仅兼容当前 confirm，不模拟可信解析器。
隔离哈希清单按代码绑定接口族、请求范围及两侧 sha256，只交 bj_isolated_list。
现有夹具仅保留清单的代码键，丢弃哈希值；confirm 忽略 raw_bytes。
因此实绿只证明既有数值/隔离语义；三个 strict xfail 记录可信材料缺口，
不宣称原始字节或哈希已被实现消费。未来材料 API/夹具落地时须适配此边界。
"""

import json
import socket
from datetime import UTC, date, datetime
from hashlib import sha256
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import bj_offline_volume as gate
from app.marketdata import daily_bars as writer

DAY = date(2031, 1, 2)
CODES = tuple(f"9209{i:02d}.BJ" for i in range(20))
TRUST_CONTRACT_SOURCE = (
    "docs/contracts/daily-bars-source.md，origin/main 当前 f4e3525 上该文件 blob 与 "
    "d02b0ac（docs(T-A180b): §10.12 治理员必改两处与建议 a–d）相同；"
    "章节「### 10.12 可信确认材料、tb143 SQL 定位与演练链（T-A180）」"
    "第 1 条「可信确认材料（T-A179 残项 R1）」"
)
TRUST_PENDING = pytest.mark.xfail(
    strict=True,
    raises=pytest.fail.Exception,  # 只容许预期的“应拒绝却未抛错”，不掩盖构造错误。
)


@pytest.fixture(autouse=True)
def offline_state(monkeypatch, bj_isolated_list):
    def deny(*args, **kwargs):
        raise AssertionError("synthetic fixture must not connect")

    monkeypatch.setattr(socket.socket, "connect", deny)
    monkeypatch.setattr(socket, "create_connection", deny)
    bj_isolated_list([])
    with pytest.raises(gate.RowReject, match="requires_20"):
        gate.confirm_bj_offline_volume_units([])
    yield
    with pytest.raises(gate.RowReject, match="requires_20"):
        gate.confirm_bj_offline_volume_units([])


def synthetic_material(patches=()):
    pairs, manifest = [], {}
    for code in CODES:
        pair = {
            "mairui": {"code": code, "t": f"{DAY} 00:00:00", "v": "1",
                       "source": "fake", "sf": 0},
            "tdx_local": {"code": code, "trade_date": "20310102", "volume": "100",
                          "source": "tdx_local", "is_suspended": False},
        }
        if not pairs:
            for side, field, value in patches:
                pair[side][field] = value
        mr, tdx = pair["mairui"], pair["tdx_local"]
        # legacy source 标签只为兼容；原始材料始终 synthetic / source=fake。
        mr_raw = json.dumps(dict(mr, synthetic=True), sort_keys=True).encode("ascii")
        tdx_raw = (
            "synthetic,source,code,trade_date,volume,is_suspended\n"
            f"true,fake,{code},{tdx['trade_date']},{tdx['volume']},{tdx['is_suspended']}\n"
        ).encode("ascii")
        pair["mairui"]["raw_bytes"] = mr_raw
        pair["tdx_local"]["raw_bytes"] = tdx_raw
        manifest[code] = {
            "synthetic": True, "source": "fake", "code": code,
            "interface": "/hsstock/history", "request_range": (str(mr["t"])[:10], str(mr["t"])[:10]),
            "mairui_sha256": sha256(mr_raw).hexdigest(),
            "tdx_sha256": sha256(tdx_raw).hexdigest(),
            "tdx_path": f"synthetic-readonly/{code}.csv",
        }
        pairs.append(pair)
    return pairs, manifest


def install_valid_material(bj_isolated_list, pairs, manifest):
    # 每个数值反例都重新生成哈希；不能用旧哈希掩盖数值拒绝。
    assert set(manifest) == set(CODES)
    for pair in pairs:
        entry = manifest[pair["mairui"]["code"]]
        for side, key in (("mairui", "mairui_sha256"), ("tdx_local", "tdx_sha256")):
            assert sha256(pair[side]["raw_bytes"]).hexdigest() == entry[key]
    bj_isolated_list(manifest)  # 现有夹具只注入键；哈希验证仍待另单。


def upsert_one():
    conn = MagicMock()
    conn.execute.return_value = SimpleNamespace(all=lambda: [
        SimpleNamespace(code=CODES[0], trade_date=DAY, adj_type="none")
    ])
    bar = writer.DailyBar(CODES[0], DAY, "none", *([None] * 8))
    stats = writer.upsert_daily_bars(
        conn, writer.FetchResult([bar]), source="tdx_local", licence_id=None,
        fetched_at=datetime(2031, 1, 2, tzinfo=UTC),
    )
    if stats.blocked_bj_unconfirmed:
        conn.execute.assert_not_called()
    else:
        conn.execute.assert_called_once()
    return stats


@TRUST_PENDING(reason=(
    "T-B182：只给已解析对加自填 source 应拒绝；"
    "缺口：confirm 仍接受已解析字段；出处：" + TRUST_CONTRACT_SOURCE
))
def test_ta172_parsed_pairs_with_self_filled_source_are_rejected(bj_isolated_list):
    pairs, manifest = synthetic_material()
    install_valid_material(bj_isolated_list, pairs, manifest)
    for pair in pairs:
        for side in ("mairui", "tdx_local"):
            del pair[side]["raw_bytes"]
    # 伪填当前要求的 tdx_local 标签、代码在隔离清单，也不能当可信材料。
    with pytest.raises(gate.RowReject):
        gate.confirm_bj_offline_volume_units(pairs)


@TRUST_PENDING(reason=(
    "T-B183：sha256 不在清单中应拒绝；"
    "缺口：现有夹具丢弃哈希，confirm 未校验清单 sha256；出处：" + TRUST_CONTRACT_SOURCE
))
def test_ta172_sha256_absent_from_isolated_list_is_rejected(bj_isolated_list):
    pairs, manifest = synthetic_material()
    install_valid_material(bj_isolated_list, pairs, manifest)
    manifest[CODES[0]]["mairui_sha256"] = sha256(b"synthetic absent material").hexdigest()
    actual = sha256(pairs[0]["mairui"]["raw_bytes"]).hexdigest()
    assert actual != manifest[CODES[0]]["mairui_sha256"]
    bj_isolated_list(manifest)  # 代码仍在，只缺对应原始字节的哈希。
    with pytest.raises(gate.RowReject):
        gate.confirm_bj_offline_volume_units(pairs)


@TRUST_PENDING(reason=(
    "T-B184：字节被改动一位应拒绝；"
    "缺口：confirm 忽略 raw_bytes，未拒绝字节篡改；出处：" + TRUST_CONTRACT_SOURCE
))
def test_ta172_one_bit_flip_in_raw_bytes_is_rejected(bj_isolated_list):
    pairs, manifest = synthetic_material()
    install_valid_material(bj_isolated_list, pairs, manifest)
    original = pairs[0]["mairui"]["raw_bytes"]
    changed = bytearray(original)
    index = original.index(b'"v": "1"') + len(b'"v": "')
    changed[index] ^= 1  # ASCII 1 -> 0；已解析 v 和原清单不动。
    assert sum((a ^ b).bit_count() for a, b in zip(original, changed)) == 1
    pairs[0]["mairui"]["raw_bytes"] = bytes(changed)
    assert sha256(changed).hexdigest() != manifest[CODES[0]]["mairui_sha256"]
    with pytest.raises(gate.RowReject):
        gate.confirm_bj_offline_volume_units(pairs)


@pytest.mark.parametrize("tdx_date", ["20310102", "2031-01-02 00:00:00"])
def test_ta172_synthetic_material_legacy_confirmation_and_revoke(bj_isolated_list, tdx_date):
    pairs, manifest = synthetic_material((("tdx_local", "trade_date", tdx_date),))
    install_valid_material(bj_isolated_list, pairs, manifest)
    assert upsert_one().blocked_bj_unconfirmed == 1  # 清单本身不能放行。
    assert gate.confirm_bj_offline_volume_units(pairs) == frozenset(CODES)
    assert upsert_one().inserted == 1
    with pytest.raises(gate.RowReject, match="requires_20"):
        gate.confirm_bj_offline_volume_units([])
    assert upsert_one().blocked_bj_unconfirmed == 1


def test_ta172_synthetic_material_never_unlocks_production_without_list():
    pairs, _ = synthetic_material()
    assert gate.confirm_bj_offline_volume_units(pairs) == frozenset(CODES)
    assert upsert_one().blocked_bj_unconfirmed == 1


@pytest.mark.parametrize("patches,error", [
    ((("mairui", "v", "1.000000000000000000000000000001"),), "volume_mismatch"),
    ((("mairui", "sf", 1),), "requires_20"),
    ((("tdx_local", "is_suspended", True),), "requires_20"),
    ((("mairui", "v", "0"),), "requires_20"),
    ((("tdx_local", "volume", "0"),), "requires_20"),
    ((("mairui", "t", "2031-01-03"),), "date_mismatch"),
    ((("mairui", "t", "2031-01-03"), ("tdx_local", "trade_date", "20310103")), "requires_20"),
    ((("mairui", "t", "2031-01-02 00:00:01"),), "trade_date_invalid"),
], ids=["precision-tail", "mr-suspended", "tdx-suspended", "zero-lots", "zero-shares",
        "cross-day", "no-common-day", "non-midnight"])
def test_ta172_numeric_rejection_has_matching_synthetic_hashes_and_revokes(
    bj_isolated_list, patches, error,
):
    pairs, manifest = synthetic_material()
    install_valid_material(bj_isolated_list, pairs, manifest)
    assert gate.confirm_bj_offline_volume_units(pairs) == frozenset(CODES)
    assert upsert_one().inserted == 1
    invalid, valid_manifest = synthetic_material(patches)
    install_valid_material(bj_isolated_list, invalid, valid_manifest)
    with pytest.raises(gate.RowReject, match=error):
        gate.confirm_bj_offline_volume_units(invalid)
    assert upsert_one().blocked_bj_unconfirmed == 1

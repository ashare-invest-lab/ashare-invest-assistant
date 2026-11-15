# ruff: noqa: S101, ANN401, F811
"""T-T80 红灯：T-B141 证书验证消费者，以及 owned 快照纳入已绑定 active 证书的 mairui 行。

契约出处：
- docs/plan.md：PUT 或 POST /me/data-licence/test 后，api 向 ingest:requests
  投递 verify_licence（只带 licence_id）；ingest 用一次轻量接口验证，结果写回状态表。
- docs/api-contract.md：verify_licence 须走 mairui_get。
- reports/T-B140e-readpaths.md：4aae38a 上仅有入队、尚无消费者；build_owned_snapshot
  对 source=mairui 无条件记 owned_snapshot_licence_unbound 并整只省略。

未验证：轻量接口的具体路径（计划只举例交易日历或单只实时行情）；
成功路径以外的 SSE data_licence 通知是否纳入本单硬验收。
不调用真实麦蕊（env -u MAIRUI_LICENCE，沿用 tb128 的 no_egress）。
隔离 PG 仅 o61 临时库，用后由 temp_db 删除。
"""

from __future__ import annotations

import functools
import uuid
from pathlib import Path
from typing import Any

import pytest
import yaml
from sqlalchemy import insert, update
from sqlalchemy.engine import Engine

from app.config_files import IngestConfig
from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars
from app.ingest import verify_licence
from app.ingest.core import IngestCore
from app.ingest.egress import mairui_get
from app.licences.service import enqueue_verify, live_row
from selfchecks.test_tb128_daily_snapshot import (  # noqa: F401
    CODE_A,
    DAY_1010,
    U1,
    U2,
    _fetch_bars,
    _import_impl,
    _owned_row,
    _seed_core,
    no_egress,
    temp_db,
)


class _MemoryRedis:
    """入队和消费者共用的内存流，不连真实 Redis。"""

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []
        self.read = 0

    def xadd(self, name: str, fields: dict[str, str]) -> bytes:
        self.entries.append((name, dict(fields)))
        return b"1-1"

    def xgroup_create(self, name: str, group: str, id: str, mkstream: bool) -> None:
        pass

    def xreadgroup(
        self, group: str, consumer: str, streams: dict[str, str], count: int
    ) -> list[tuple[bytes, list[tuple[bytes, dict[bytes, bytes]]]]]:
        entries = self.entries[self.read:self.read + count]
        self.read += len(entries)
        return [
            (name.encode(), [(b"1-1", {k.encode(): v.encode() for k, v in fields.items()})])
            for name, fields in entries
        ]

    def xack(self, name: str, group: str, mid: bytes) -> None:
        pass


def _seed_licence(conn: Any, owner: uuid.UUID, *, status: str) -> uuid.UUID:
    ident = uuid.uuid4()
    conn.execute(
        insert(user_data_licences).values(
            id=ident,
            user_id=owner,
            status=status,
            tier="free",
            ciphertext=b"purely-synthetic-never-decrypted",
            seal_key_version=1,
            licence_hmac=uuid.uuid4().bytes + uuid.uuid4().bytes,
        )
    )
    return ident


def test_verify_licence_consumer_writes_active_after_queued_intent(
    temp_db: Engine, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # plan.md：ingest 消费 verify_licence 后把状态写回（成功应为 active，并记 last_verified_at）。
    # 轻量接口路径未验证，本例不固定 URL；不外呼。
    lid = None
    with temp_db.begin() as conn:
        _seed_core(conn)
        lid = _seed_licence(conn, U1, status="pending_verification")
    rds = _MemoryRedis()
    verification_id = uuid.uuid4()
    enqueue_verify(rds, licence_id=lid, verification_id=verification_id)
    assert rds.entries
    stream, fields = rds.entries[0]
    assert stream == "ingest:requests"
    assert fields["kind"] == "verify_licence"
    assert fields["licence_id"] == str(lid)
    assert fields["verification_id"] == str(verification_id)
    assert fields["priority"] == "P0"
    assert "licence" not in fields  # 明文不得经过 Redis（plan / enqueue_verify 注释）
    # 通过真实消费者和离线日历桩验证入队后状态写回 active。
    fake = "tb141-fake-licence-not-a-real-key"

    def transport(path: str, secret: str) -> tuple[int, object]:
        assert secret == fake
        return 200, [{"date": "2026-11-13", "is_open": 1}]

    monkeypatch.setattr(
        verify_licence, "mairui_get", functools.partial(mairui_get, transport=transport)
    )
    root = Path(__file__).resolve().parents[3]
    cfg = IngestConfig.model_validate(
        yaml.safe_load((root / "config/ingest.yaml").read_text(encoding="utf-8"))
    ).licences
    verify_licence.tick(
        temp_db,
        rds,
        secret_loader=lambda e, lid: fake,
        stop=tmp_path / "STOP",
        halt=tmp_path / "HALT",
        core=IngestCore(cfg, engine=temp_db),
    )
    with temp_db.connect() as conn:
        row = live_row(conn, U1)
        assert row is not None
        assert row.status == "active", (
            f"verify_licence 消费后状态应为 active，实际为 {row.status!r}"
        )
        assert row.last_verified_at is not None


def test_owned_snapshot_includes_mairui_bound_to_active_licence(temp_db: Engine) -> None:
    # T-B140e / T-B141：source=mairui 且 source_licence_id 等于本人当前 active 证书时，
    # 应纳入 owned 快照，而不是无条件 owned_snapshot_licence_unbound。
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        lid = _seed_licence(conn, U1, status="active")
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == CODE_A)
            .values(source="mairui", source_licence_id=lid)
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
    assert ident is not None
    assert f"owned_snapshot_licence_unbound:{CODE_A}" not in issues
    with temp_db.connect() as conn:
        items = _owned_row(conn, ident).items
    assert CODE_A in {i["security_code"] for i in items["instruments"]}


def test_owned_snapshot_omits_mairui_bound_to_foreign_or_empty_licence(temp_db: Engine) -> None:
    # 对照：未绑定或绑定他人证书的 mairui 行仍应省略（T-B140e 读路径）。
    snap = _import_impl()
    with temp_db.begin() as conn:
        _seed_core(conn)
        _fetch_bars(conn)
        _seed_licence(conn, U1, status="active")
        foreign = _seed_licence(conn, U2, status="active")
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == CODE_A, daily_bars.c.trade_date == DAY_1010)
            .values(source="mairui", source_licence_id=foreign)
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        assert f"owned_snapshot_licence_unbound:{CODE_A}" in issues
        items = _owned_row(conn, ident).items
        assert CODE_A not in {i["security_code"] for i in items["instruments"]}
        conn.execute(
            update(daily_bars)
            .where(daily_bars.c.code == CODE_A, daily_bars.c.trade_date == DAY_1010)
            .values(source="mairui", source_licence_id=None)
        )
        ident, issues = snap.build_owned_snapshot(conn, U1, DAY_1010)
        assert ident is not None
        assert f"owned_snapshot_licence_unbound:{CODE_A}" in issues
        items = _owned_row(conn, ident).items
        assert CODE_A not in {i["security_code"] for i in items["instruments"]}

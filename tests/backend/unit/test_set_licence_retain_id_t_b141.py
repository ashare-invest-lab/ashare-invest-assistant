"""T-B141：同证书 PUT 保留绑定；仅临时库、一次性公钥与虚构证书。"""

from __future__ import annotations

import base64
import datetime as dt
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from sqlalchemy import insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import Settings, load_yaml_dir
from app.db.tables.licences import data_licence_events, user_data_licences
from app.db.tables.market import daily_bars
from app.licences.service import set_licence
from app.marketdata.daily_snapshot import _mairui_unbound
from daily_bars_t70_support import ROOT, _open_temp_db

FAKE = "tb141-fake-licence-a-not-a-real-key"


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    # Settings 不接触宿主环境里的证书或主密钥。
    monkeypatch.setattr(Settings, "settings_customise_sources", classmethod(
        lambda cls, settings_cls, init_settings, **kwargs: (init_settings,)
    ))
    der = X25519PrivateKey.generate().public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo
    )
    settings = Settings(
        _env_file=None, app_env="test", service_name="api",
        business=load_yaml_dir(ROOT / "config"),
        data_licence_seal_public_keys=json.dumps({"1": base64.b64encode(der).decode()}),
        data_licence_seal_key_version=1,
    )
    gen = _open_temp_db()
    ctx = next(gen)
    ctx.settings = settings
    try:
        yield ctx
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def _put(conn: Any, ctx: SimpleNamespace, licence: str = FAKE, tier: str = "annual") -> Any:
    return set_licence(conn, ctx.settings, user_id=ctx.u1, licence=licence,
                       tier=tier, has_quant_pro=False, expires_on=None)


def _seed(conn: Any, ctx: SimpleNamespace, status: str) -> Any:
    row = _put(conn, ctx).row
    conn.execute(update(user_data_licences).where(user_data_licences.c.id == row.id).values(
        status=status, last_error_code="102", last_error_at=dt.datetime.now(dt.UTC)
    ))
    conn.execute(insert(daily_bars).values(
        code="600001.SH", trade_date=dt.date(2026, 11, 10), adj_type="none",
        open=10, high=12, low=9, close=11, pre_close=10, volume=1000,
        amount=11000, is_suspended=False, source="mairui", source_licence_id=row.id,
        fetched_at=dt.datetime(2026, 11, 14, 10, tzinfo=dt.UTC),
    ))
    return row


def test_same_licence_reput_keeps_id_and_goes_pending(world: SimpleNamespace) -> None:
    with world.engine.begin() as conn:
        old = _seed(conn, world, "active")
        ciphertext = conn.execute(select(user_data_licences.c.ciphertext).where(
            user_data_licences.c.id == old.id
        )).scalar_one()
        result = _put(conn, world, tier="free")
        assert result.row.id == old.id
        assert result.row.status == "pending_verification"
        assert result.verification_id is not None
        assert result.row.deleted_at is None
        assert result.row.last_error_code is None and result.row.last_error_at is None
        assert conn.execute(select(user_data_licences.c.ciphertext).where(
            user_data_licences.c.id == old.id
        )).scalar_one() != ciphertext
        assert result.row.tier == "free"
        conn.execute(update(user_data_licences).where(user_data_licences.c.id == old.id).values(
            status="active"
        ))
        bar = conn.execute(select(daily_bars)).one()
        assert bar.source_licence_id == old.id
        assert not _mairui_unbound(bar, old.id)
        events = conn.execute(select(data_licence_events).where(
            data_licence_events.c.licence_id == old.id
        )).all()
        assert [e.event for e in events] == ["set", "set"]
        assert events[-1].from_status == "active"
        assert events[-1].to_status == "pending_verification"


def test_same_licence_invalid_reput_keeps_id(world: SimpleNamespace) -> None:
    with world.engine.begin() as conn:
        old = _seed(conn, world, "invalid")
        result = _put(conn, world)
        assert result.row.id == old.id
        assert result.row.status == "pending_verification"
        assert result.verification_id is not None


@pytest.mark.parametrize("status", ["quota_exceeded", "ip_limited", "paused_by_admin"])
def test_same_licence_cooldown_still_keeps_state(world: SimpleNamespace, status: str) -> None:
    with world.engine.begin() as conn:
        old = _seed(conn, world, status)
        result = _put(conn, world)
        assert result.row.id == old.id and result.row.status == status
        assert result.verification_id is None
        assert result.row.last_error_code == "102"


def test_different_licence_creates_new_id_bars_unchanged(world: SimpleNamespace) -> None:
    with world.engine.begin() as conn:
        old = _seed(conn, world, "active")
        before = conn.execute(select(daily_bars)).one()
        result = _put(conn, world, "tb141-fake-licence-b-not-a-real-key")
        assert result.row.id != old.id
        previous = conn.execute(select(user_data_licences).where(
            user_data_licences.c.id == old.id
        )).one()
        assert previous.deleted_at is not None
        after = conn.execute(select(daily_bars)).one()
        assert after == before and after.source_licence_id == old.id

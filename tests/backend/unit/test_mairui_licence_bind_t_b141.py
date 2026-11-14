"""T-B141：按清单绑定、回滚历史 mairui 行（仅临时数据库与合成证书）。"""

from __future__ import annotations

import csv
import datetime as dt
import stat
import sys
import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import insert, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.cli.mairui_licence_bind import BindReport, bind, main, rollback
from app.db.tables.licences import user_data_licences
from app.db.tables.market import daily_bars
from daily_bars_t70_support import _open_temp_db


@pytest.fixture
def world() -> Iterator[SimpleNamespace]:
    gen = _open_temp_db()
    ctx = next(gen)
    try:
        ctx.lid, ctx.other = uuid.uuid4(), uuid.uuid4()
        with ctx.engine.begin() as conn:
            conn.execute(insert(user_data_licences).values(**_licence(ctx.lid, ctx.u1)))
            conn.execute(insert(daily_bars), [
                _bar(1), _bar(2), _bar(3),
                _bar(4, licence=ctx.other), _bar(5, source="fake"),
                _bar(6, source="tdx_local"),
            ])
        yield ctx
    finally:
        try:
            next(gen)
        except StopIteration:
            pass


def _licence(lid: uuid.UUID, uid: uuid.UUID) -> dict[str, Any]:
    return dict(id=lid, user_id=uid, provider="mairui", ciphertext=b"\x00",
                seal_key_version=1, licence_hmac=uuid.uuid4().bytes, tier="annual",
                has_quant_pro=False, status="active")


def _bar(n: int, *, source: str = "mairui",
         licence: uuid.UUID | None = None) -> dict[str, Any]:
    return dict(code="600001.SH", trade_date=dt.date(2026, 11, n), adj_type="none",
                open=10, high=12, low=9, close=11, pre_close=10, volume=1000,
                amount=11000, is_suspended=False, source=source, source_licence_id=licence,
                fetched_at=dt.datetime(2026, 11, 14, 10, tzinfo=dt.UTC))


def _snapshot(ctx: SimpleNamespace) -> list[dict[str, Any]]:
    with ctx.engine.connect() as conn:
        return [dict(r) for r in conn.execute(select(daily_bars).order_by(
            daily_bars.c.code, daily_bars.c.trade_date, daily_bars.c.adj_type
        )).mappings()]


def _bound(ctx: SimpleNamespace, path: Path) -> list[dict[str, Any]]:
    before = _snapshot(ctx)
    with ctx.engine.begin() as conn:
        assert bind(conn, path, apply=True) == BindReport(ctx.lid, 3, True)
    return before


def test_dry_run(world: SimpleNamespace, tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    before = _snapshot(world)
    with world.engine.begin() as conn:
        assert bind(conn, path, apply=False) == BindReport(world.lid, 3, False)
    assert _snapshot(world) == before
    assert not path.exists()


def test_apply_preserves_every_other_field(world: SimpleNamespace, tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    before = _bound(world, path)
    expected = [dict(row) for row in before]
    for row in expected[:3]:
        row["source_licence_id"] = world.lid
    assert _snapshot(world) == expected
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    with path.open(newline="", encoding="utf-8") as stream:
        assert stream.readline() == f"# licence_id={world.lid}\n"
        assert list(csv.reader(stream)) == [
            ["code", "trade_date", "adj_type"],
            *[[row["code"], row["trade_date"].isoformat(), row["adj_type"]]
              for row in before[:3]],
        ]


def test_rerun_and_existing_manifest(world: SimpleNamespace, tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    _bound(world, path)
    before = _snapshot(world)
    fresh = tmp_path / "fresh"
    with world.engine.begin() as conn:
        assert bind(conn, fresh, apply=True) == BindReport(world.lid, 0, True)
    assert _snapshot(world) == before
    assert not fresh.exists()
    with world.engine.begin() as conn:
        conn.execute(insert(daily_bars).values(**_bar(7)))
    before = _snapshot(world)
    contents = path.read_bytes()
    with pytest.raises(FileExistsError), world.engine.begin() as conn:
        bind(conn, path, apply=True)
    assert _snapshot(world) == before
    assert path.read_bytes() == contents


@pytest.mark.parametrize("active_count", [0, 2])
@pytest.mark.parametrize("apply", [False, True])
def test_refused(world: SimpleNamespace, tmp_path: Path, active_count: int, apply: bool) -> None:
    with world.engine.begin() as conn:
        if active_count == 0:
            conn.execute(update(user_data_licences).values(status="pending_verification"))
        else:
            conn.execute(insert(user_data_licences).values(**_licence(uuid.uuid4(), world.u2)))
    before = _snapshot(world)
    path = tmp_path / "manifest"
    with world.engine.begin() as conn:
        assert bind(conn, path, apply=apply) == BindReport(
            None, 0, False, f"active_licence_count:{active_count}"
        )
    assert _snapshot(world) == before
    assert not path.exists()


def test_rollback(world: SimpleNamespace, tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    before = _bound(world, path)
    bound = _snapshot(world)
    contents = path.read_bytes()
    with world.engine.begin() as conn:
        assert rollback(conn, path, apply=False) == BindReport(world.lid, 3, False)
    assert _snapshot(world) == bound
    with world.engine.begin() as conn:
        assert rollback(conn, path, apply=True) == BindReport(world.lid, 3, True)
    assert _snapshot(world) == before
    for apply in (False, True):
        with world.engine.begin() as conn:
            assert rollback(conn, path, apply=apply) == BindReport(world.lid, 0, apply)
    assert _snapshot(world) == before
    assert path.read_bytes() == contents


def test_rollback_only_manifest_licence(world: SimpleNamespace, tmp_path: Path) -> None:
    path = tmp_path / "manifest"
    before = _bound(world, path)
    with world.engine.begin() as conn:
        conn.execute(update(daily_bars).where(
            daily_bars.c.trade_date == before[0]["trade_date"]
        ).values(source_licence_id=world.other))
    with world.engine.begin() as conn:
        assert rollback(conn, path, apply=False).rows == 2
        assert rollback(conn, path, apply=True) == BindReport(world.lid, 2, True)
    before[0]["source_licence_id"] = world.other
    assert _snapshot(world) == before


def test_main(world: SimpleNamespace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
              capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setenv("DATABASE_URL", world.engine.url.render_as_string(hide_password=False))
    path = tmp_path / "manifest"
    before = _snapshot(world)
    assert main(["--manifest", str(path)]) == 0
    assert capsys.readouterr().out == f"licence_id={world.lid} rows=3\n"
    assert main(["--manifest", str(path), "--dry-run"]) == 0
    assert capsys.readouterr().out == f"licence_id={world.lid} rows=3\n"
    assert _snapshot(world) == before
    assert not path.exists()
    with world.engine.begin() as conn:
        conn.execute(update(user_data_licences).values(status="pending_verification"))
    assert main(["--manifest", str(path)]) == 3
    assert capsys.readouterr().out == "active_licence_count:0\n"
    assert _snapshot(world) == before
    assert not path.exists()

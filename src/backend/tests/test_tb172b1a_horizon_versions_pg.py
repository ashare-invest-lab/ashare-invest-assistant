"""T-A192：每例独立临时数据库，仅使用环境指定测试 PG 与虚构数据。"""

# ruff: noqa: S101
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from psycopg import sql
from sqlalchemy import Connection, create_engine, func, insert, inspect, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db.base import metadata
from app.db.tables.users import users

OWNER = UUID(int=1721)
NOW = datetime(2026, 11, 15, 9, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    preset = os.environ.get("AIA_TEST_DATABASE_URL")
    if not preset:
        pytest.skip("AIA_TEST_DATABASE_URL 未设置")
    url = make_url(preset)
    name = "tb172b1a_" + uuid4().hex
    with psycopg.connect(
        url.set(drivername="postgresql").render_as_string(hide_password=False), autocommit=True
    ) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
        engine = create_engine(url.set(drivername="postgresql+psycopg", database=name))
        config = Config()
        config.set_main_option(
            "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
        )
        monkeypatch.setenv("DATABASE_URL", engine.url.render_as_string(hide_password=False))
        try:
            command.upgrade(config, "head")
            yield SimpleNamespace(engine=engine, config=config)
        finally:
            engine.dispose()
            admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(name)))


def seed(conn: Connection) -> dict[str, Any]:
    conn.execute(
        insert(users).values(
            id=OWNER,
            username="synthetic_horizon",
            password_hash="unusable",  # noqa: S106 - synthetic fixture
            role="user",
            status="approved",
        )
    )
    return {
        "id": uuid4(),
        "user_id": OWNER,
        "kind": "calendar",
        "source": "synthetic",
        "scope": "public",
        "data_date": date(2026, 11, 15),
        "source_key": "merged_calendar",
        "source_version": "synthetic-v1",
        "version_hash": "a" * 64,
        "payload": {},
        "transform_version": "identity-v1",
    }


def test_a192_a1a_single_head_empty_upgrade_guarded_downgrade(world: SimpleNamespace) -> None:
    from app.db.tables.horizon import horizon_input_versions as table

    assert ScriptDirectory.from_config(world.config).get_revision("0037").down_revision == "0036"
    command.downgrade(world.config, "0037")
    command.upgrade(world.config, "0037")
    with world.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM public.alembic_version")) == "0037"
        assert conn.scalar(select(func.count()).select_from(table)) == 0
    command.downgrade(world.config, "0036")
    with world.engine.connect() as conn:
        assert not inspect(conn).has_table(table.name, schema="app")
        assert (
            conn.scalar(text("SELECT to_regprocedure('app.reject_horizon_input_update()')")) is None
        )
    command.upgrade(world.config, "0037")
    with world.engine.begin() as conn:
        row = seed(conn)
        conn.execute(insert(table).values(**row))
    with pytest.raises(DBAPIError, match=r"horizon_input_versions.*not empty"):
        command.downgrade(world.config, "0036")
    with world.engine.connect() as conn:
        assert inspect(conn).has_table(table.name, schema="app")
        assert conn.scalar(select(table.c.id)) == row["id"]
        assert conn.scalar(text("SELECT version_num FROM public.alembic_version")) == "0037"


def test_a192_a1a_append_only_no_history_backfill(world: SimpleNamespace) -> None:
    from app.db.tables.horizon import horizon_input_versions as table

    with world.engine.begin() as conn:
        assert conn.scalar(select(func.count()).select_from(table)) == 0
        row = seed(conn)
        conn.execute(insert(table).values(**row))
        original = conn.execute(select(table)).one()
        for values in ({"payload": {"changed": True}}, {"id": row["id"]}):
            with pytest.raises(DBAPIError, match="immutable"), conn.begin_nested():
                conn.execute(update(table).where(table.c.id == row["id"]).values(**values))
        for scope, licence_id in (("public", None), ("per_licence", uuid4())):
            candidate = {**row, "id": uuid4(), "scope": scope, "licence_id": licence_id}
            if licence_id is not None:
                conn.execute(insert(table).values(**candidate))
            with (
                pytest.raises(IntegrityError, match="uq_horizon_input_versions_version"),
                conn.begin_nested(),
            ):
                conn.execute(insert(table).values(**{**candidate, "id": uuid4()}))
        revised = {
            **row,
            "id": uuid4(),
            "version_hash": "b" * 64,
            "supersedes_id": row["id"],
            "payload": {"revision": 2},
        }
        conn.execute(insert(table).values(**revised))
        assert conn.execute(select(table).where(table.c.id == row["id"])).one() == original
        assert (
            conn.scalar(select(table.c.supersedes_id).where(table.c.id == revised["id"]))
            == row["id"]
        )
        conn.execute(table.delete().where(table.c.user_id == OWNER))
        assert conn.scalar(select(func.count()).select_from(table)) == 0


def test_checks_defaults_and_migration_matches_metadata(world: SimpleNamespace) -> None:
    from app.db.tables.horizon import horizon_input_versions as table

    with world.engine.begin() as conn:
        row = seed(conn)
        conn.execute(insert(table).values(**row))
        stored = conn.execute(select(table)).one()
        assert stored.dependency_ids == []
        assert stored.recorded_at is not None
        assert all(
            getattr(stored, key) is None
            for key in (
                "licence_id",
                "code",
                "first_seen_at",
                "available_at",
                "computed_at",
                "supersedes_id",
            )
        )
        invalid = [
            ("licence_scope", {"scope": "per_licence"}),
            ("licence_scope", {"licence_id": uuid4()}),
            ("code", {"kind": "daily_bar"}),
            ("version_hash_hex", {"version_hash": "A" * 64}),
            (
                "first_seen_order",
                {"first_seen_at": NOW, "available_at": NOW - timedelta(seconds=1)},
            ),
            ("first_seen_order", {"available_at": NOW}),
            (
                "computed_order",
                {
                    "first_seen_at": NOW,
                    "available_at": NOW,
                    "computed_at": NOW + timedelta(seconds=1),
                },
            ),
            ("kind", {"kind": "unknown", "code": "SYNTHETIC"}),
            ("scope", {"scope": "unknown"}),
        ]
        for constraint, changes in invalid:
            with (
                pytest.raises(IntegrityError, match="ck_horizon_input_versions_" + constraint),
                conn.begin_nested(),
            ):
                conn.execute(insert(table).values(**{**row, "id": uuid4(), **changes}))
        for kind in (
            "calendar",
            "daily_bar",
            "vendor_factor",
            "ex_rights",
            "adjust_factor",
            "feature",
        ):
            conn.execute(
                insert(table).values(
                    **{
                        **row,
                        "id": uuid4(),
                        "kind": kind,
                        "scope": "synthetic",
                        "code": "SYNTHETIC",
                        "first_seen_at": NOW,
                        "available_at": NOW,
                        "computed_at": NOW,
                    }
                )
            )
        context = MigrationContext.configure(
            conn,
            opts={
                "include_schemas": True,
                "include_name": lambda name, type_, parent_names: (
                    name == "app"
                    if type_ == "schema"
                    else name == table.name
                    if type_ == "table"
                    else True
                ),
                "include_object": lambda obj, name, type_, reflected, compare_to: (
                    name == table.name if type_ == "table" else True
                ),
                "compare_server_default": True,
            },
        )
        assert compare_metadata(context, metadata) == []
        inspector = inspect(conn)
        assert {c["name"] for c in inspector.get_check_constraints(table.name, schema="app")} == {
            c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"
        }

"""T-A192 §3.2/3.3：独立临时测试库，只使用合成版本与证明。"""

# ruff: noqa: S101
import os
from collections.abc import Iterator
from datetime import UTC, date, datetime
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

OWNER = UUID(int=1722)
NOW = datetime(2026, 11, 15, 9, tzinfo=UTC)


@pytest.fixture
def world(monkeypatch: pytest.MonkeyPatch) -> Iterator[SimpleNamespace]:
    preset = os.environ.get("AIA_TEST_DATABASE_URL")
    if not preset:
        pytest.skip("AIA_TEST_DATABASE_URL 未设置")
    url = make_url(preset)
    name = "tb172b1b_" + uuid4().hex
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


@pytest.fixture
def role_conn(world: SimpleNamespace) -> Iterator[Connection]:
    # CREATE ROLE / GRANT 均在事务内；回滚清理自建角色并恢复复用角色的原权限。
    with world.engine.connect() as conn:
        try:
            for role in ("aia_api", "aia_maint"):
                if not conn.scalar(
                    text("SELECT 1 FROM pg_roles WHERE rolname = :role"), {"role": role}
                ):
                    conn.execute(text(f"CREATE ROLE {role} NOLOGIN"))
                conn.execute(text(f"GRANT USAGE ON SCHEMA app TO {role}"))
                conn.execute(
                    text(f"GRANT SELECT, DELETE ON app.horizon_completion_evidence TO {role}")
                )
                conn.execute(
                    text(f"GRANT SELECT, DELETE ON app.horizon_input_versions TO {role}")
                )
            yield conn
        finally:
            conn.rollback()


def seed(conn: Connection, *, kind: str = "daily_bar", scope: str = "synthetic") -> dict[str, Any]:
    from app.db.tables.horizon import horizon_input_versions as versions

    conn.execute(
        insert(users).values(
            id=OWNER,
            username="synthetic_completion",
            password_hash="unusable",  # noqa: S106
            role="user",
            status="approved",
        )
    )
    version_id = uuid4()
    conn.execute(
        insert(versions).values(
            id=version_id,
            user_id=OWNER,
            kind=kind,
            source="fake",
            scope=scope,
            code="SYNTHETIC",
            data_date=date(2026, 11, 15),
            source_key="none",
            source_version="synthetic-v1",
            version_hash="a" * 64,
            payload={},
            transform_version="identity-v1",
        )
    )
    return {
        "id": uuid4(),
        "bar_version_id": version_id,
        "proof_kind": "synthetic",
        "proof_hash": "a" * 64,
        "proof": {"synthetic": True},
    }


def test_completion_single_head_empty_upgrade_guarded_downgrade(world: SimpleNamespace) -> None:
    from app.db.tables.horizon import horizon_completion_evidence as table

    assert ScriptDirectory.from_config(world.config).get_heads() == ["0039"]
    with world.engine.connect() as conn:
        assert conn.scalar(text("SELECT version_num FROM public.alembic_version")) == "0039"
        assert conn.scalar(select(func.count()).select_from(table)) == 0
    command.downgrade(world.config, "0037")
    with world.engine.connect() as conn:
        assert not inspect(conn).has_table(table.name, schema="app")
        assert inspect(conn).has_table("horizon_input_versions", schema="app")
        for function in (
            "validate_horizon_completion_version",
            "reject_horizon_completion_update",
            "reject_horizon_completion_delete",
        ):
            assert (
                conn.scalar(text("SELECT to_regprocedure(:f)"), {"f": f"app.{function}()"}) is None
            )
    command.upgrade(world.config, "head")
    with world.engine.begin() as conn:
        row = seed(conn)
        conn.execute(insert(table).values(**row))
    with pytest.raises(DBAPIError, match=r"horizon_completion_evidence.*not empty"):
        command.downgrade(world.config, "0037")
    with world.engine.connect() as conn:
        assert conn.scalar(select(table.c.id)) == row["id"]
        assert conn.scalar(text("SELECT version_num FROM public.alembic_version")) == "0039"


def test_completion_append_only_and_privacy_delete(role_conn: Connection) -> None:
    from app.cli.delete_user_data import STEPS, unknown_triggers
    from app.db.tables.horizon import horizon_completion_evidence as table
    from app.db.tables.horizon import horizon_input_versions as versions

    with role_conn.begin_nested():
        conn = role_conn
        row = seed(conn)
        conn.execute(insert(table).values(**row))
        original = conn.execute(select(table)).one()
        for changes in ({"proof": {"changed": True}}, {"id": row["id"]}):
            with pytest.raises(DBAPIError, match="immutable"), conn.begin_nested():
                conn.execute(update(table).where(table.c.id == row["id"]).values(**changes))
        with (
            pytest.raises(IntegrityError, match="uq_horizon_completion_evidence"),
            conn.begin_nested(),
        ):
            conn.execute(insert(table).values(**{**row, "id": uuid4()}))
        conn.execute(
            insert(table).values(
                **{
                    **row,
                    "id": uuid4(),
                    "proof_hash": "b" * 64,
                    "is_final": True,
                    "available_at": NOW,
                    "proof": {"synthetic": True, "final": True},
                }
            )
        )
        assert conn.execute(select(table).where(table.c.id == row["id"])).one() == original
        assert conn.scalar(select(func.count()).select_from(table)) == 2
        assert unknown_triggers(conn, [table.fullname]) == []
        step = next(s for s in STEPS if s.table == table.fullname)
        conn.execute(text("SET ROLE aia_maint"))
        assert conn.scalar(text("SELECT current_user")) == "aia_maint"
        conn.execute(text(f"DELETE FROM {step.table} WHERE {step.where}"), {"uid": OWNER})  # noqa: S608
        assert conn.scalar(select(func.count()).select_from(table)) == 0
        conn.execute(versions.delete().where(versions.c.user_id == OWNER))
        conn.execute(text("RESET ROLE"))


def test_delete_requires_aia_maint(role_conn: Connection) -> None:
    from app.db.tables.horizon import horizon_completion_evidence as table

    row = seed(role_conn)
    role_conn.execute(insert(table).values(**row))
    role_conn.execute(text("SET ROLE aia_api"))
    assert role_conn.scalar(text("SELECT current_user")) == "aia_api"
    with pytest.raises(DBAPIError, match="DELETE forbidden"), role_conn.begin_nested():
        role_conn.execute(table.delete().where(table.c.id == row["id"]))
    assert role_conn.scalar(select(table.c.id)) == row["id"]
    role_conn.execute(text("SET ROLE aia_maint"))
    assert role_conn.scalar(text("SELECT current_user")) == "aia_maint"
    role_conn.execute(table.delete().where(table.c.id == row["id"]))
    assert role_conn.scalar(select(func.count()).select_from(table)) == 0
    role_conn.execute(text("RESET ROLE"))


@pytest.mark.parametrize(
    ("changes", "kind", "scope", "error"),
    [
        ({"proof_hash": "A" * 64}, "daily_bar", "synthetic", "proof_hash_hex"),
        ({"is_final": True}, "daily_bar", "synthetic", "final_available"),
        ({"proof_kind": "unknown"}, "daily_bar", "synthetic", "proof_kind"),
        ({}, "calendar", "synthetic", "must reference daily_bar"),
        ({}, "daily_bar", "public", "requires synthetic version"),
        ({"pipeline_run_id": UUID(int=999)}, "daily_bar", "synthetic", "pipeline_run_id"),
        ({"bar_version_id": UUID(int=999)}, "daily_bar", "synthetic", "daily_bar"),
    ],
)
def test_completion_rejects_invalid_evidence(
    world: SimpleNamespace,
    changes: dict[str, Any],
    kind: str,
    scope: str,
    error: str,
) -> None:
    from app.db.tables.horizon import horizon_completion_evidence as table

    with world.engine.begin() as conn:
        row = seed(conn, kind=kind, scope=scope)
        with pytest.raises(DBAPIError, match=error), conn.begin_nested():
            conn.execute(insert(table).values(**{**row, **changes}))
        assert conn.scalar(select(func.count()).select_from(table)) == 0


def test_completion_defaults_and_migration_matches_metadata(world: SimpleNamespace) -> None:
    from app.db.tables.horizon import horizon_completion_evidence as table

    with world.engine.begin() as conn:
        row = seed(conn, scope="public")
        row["proof_kind"] = "source_final_receipt"
        conn.execute(insert(table).values(**row))
        stored = conn.execute(select(table)).one()
        assert stored.recorded_at is not None
        assert stored.pipeline_run_id is stored.is_final is stored.available_at is None
        conn.execute(
            insert(table).values(
                **{
                    **row,
                    "id": uuid4(),
                    "proof_hash": "b" * 64,
                    "is_final": False,
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
        assert {
            c["name"] for c in inspect(conn).get_check_constraints(table.name, schema="app")
        } == {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}

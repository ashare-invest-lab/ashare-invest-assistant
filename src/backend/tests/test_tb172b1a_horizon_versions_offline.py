"""T-A192 §3.1：纯合成结构验收，不连接数据库。"""

# ruff: noqa: S101
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ARRAY, CheckConstraint, Date, DateTime, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID


def test_migration_single_head_and_parent() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    script = ScriptDirectory.from_config(config)
    assert len(script.get_heads()) == 1
    assert script.get_revision("0037").down_revision == "0036"


def test_a192_a1a_schema_keys_nullability_indexes() -> None:
    from app.db.tables.horizon import horizon_input_versions as table

    nullable = {
        "licence_id",
        "code",
        "first_seen_at",
        "available_at",
        "computed_at",
        "supersedes_id",
    }
    types = {
        "id": UUID,
        "user_id": UUID,
        "licence_id": UUID,
        "kind": Text,
        "source": Text,
        "scope": Text,
        "code": Text,
        "data_date": Date,
        "source_key": Text,
        "source_version": Text,
        "version_hash": Text,
        "payload": JSONB,
        "first_seen_at": DateTime,
        "available_at": DateTime,
        "computed_at": DateTime,
        "dependency_ids": ARRAY,
        "transform_version": Text,
        "supersedes_id": UUID,
        "recorded_at": DateTime,
    }
    assert table.fullname == "app.horizon_input_versions"
    assert set(table.c.keys()) == set(types)
    assert [c.name for c in table.primary_key] == ["id"]
    for column in table.c:
        assert isinstance(column.type, types[column.name])
        assert column.nullable is (column.name in nullable)
        assert column.default is None
        if isinstance(column.type, DateTime):
            assert column.type.timezone
        if column.name not in {"dependency_ids", "recorded_at"}:
            assert column.server_default is None
    assert isinstance(table.c.dependency_ids.type.item_type, UUID)
    assert str(table.c.dependency_ids.server_default.arg) == "'{}'::uuid[]"
    assert str(table.c.recorded_at.server_default.arg) == "now()"
    assert {(fk.parent.name, fk.target_fullname, fk.ondelete) for fk in table.foreign_keys} == {
        ("user_id", "app.users.id", None),
        ("supersedes_id", "app.horizon_input_versions.id", None),
    }
    assert {
        c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    } == {
        "ck_horizon_input_versions_kind": (
            "kind IN ('calendar', 'daily_bar', 'vendor_factor', "
            "'ex_rights', 'adjust_factor', 'feature')"
        ),
        "ck_horizon_input_versions_scope": "scope IN ('per_licence', 'public', 'synthetic')",
        "ck_horizon_input_versions_licence_scope": (
            "(scope = 'per_licence') = (licence_id IS NOT NULL)"
        ),
        "ck_horizon_input_versions_code": "kind = 'calendar' OR code IS NOT NULL",
        "ck_horizon_input_versions_version_hash_hex": "version_hash ~ '^[0-9a-f]{64}$'",
        "ck_horizon_input_versions_first_seen_order": (
            "available_at IS NULL OR (first_seen_at IS NOT NULL AND available_at >= first_seen_at)"
        ),
        "ck_horizon_input_versions_computed_order": (
            "available_at IS NULL OR computed_at IS NULL OR available_at >= computed_at"
        ),
    }
    indexes = {index.name: index for index in table.indexes}
    expected = {
        "uq_horizon_input_versions_version": [
            "user_id",
            "licence_id",
            "kind",
            "source",
            "code",
            "data_date",
            "source_key",
            "version_hash",
        ],
        "ix_horizon_input_versions_read": [
            "user_id",
            "licence_id",
            "kind",
            "code",
            "data_date",
            "available_at",
        ],
        "ix_horizon_input_versions_supersedes_id": ["supersedes_id"],
    }
    assert {name: [c.name for c in index.columns] for name, index in indexes.items()} == expected
    for name, index in indexes.items():
        assert index.unique is name.startswith("uq_")
    assert indexes["uq_horizon_input_versions_version"].dialect_options["postgresql"][
        "nulls_not_distinct"
    ]

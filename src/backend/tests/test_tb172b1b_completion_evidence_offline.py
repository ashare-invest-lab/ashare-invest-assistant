"""T-A192 §3.2：完成证据结构与 purge 接线，无数据库连接。"""

# ruff: noqa: S101
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Boolean, CheckConstraint, DateTime, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID


def test_migration_single_head_and_parent() -> None:
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    script = ScriptDirectory.from_config(config)
    assert script.get_heads() == ["0040"]
    assert script.get_revision("0040").down_revision == "0039"
    assert script.get_revision("0039").down_revision == "0038"
    assert script.get_revision("0038").down_revision == "0037"


def test_completion_schema_keys_nullability_indexes() -> None:
    from app.db.tables.horizon import horizon_completion_evidence as table

    types = {
        "id": UUID,
        "bar_version_id": UUID,
        "pipeline_run_id": UUID,
        "is_final": Boolean,
        "available_at": DateTime,
        "proof_kind": Text,
        "proof_hash": Text,
        "proof": JSONB,
        "recorded_at": DateTime,
    }
    assert table.fullname == "app.horizon_completion_evidence"
    assert set(table.c.keys()) == set(types)
    assert [c.name for c in table.primary_key] == ["id"]
    for column in table.c:
        assert isinstance(column.type, types[column.name])
        assert column.nullable is (column.name in {"pipeline_run_id", "is_final", "available_at"})
        assert column.default is None
        if isinstance(column.type, DateTime):
            assert column.type.timezone
        if column.name != "recorded_at":
            assert column.server_default is None
    assert str(table.c.recorded_at.server_default.arg) == "now()"
    assert {(fk.parent.name, fk.target_fullname, fk.ondelete) for fk in table.foreign_keys} == {
        ("bar_version_id", "app.horizon_input_versions.id", None),
        ("pipeline_run_id", "app.pipeline_runs.id", None),
    }
    assert {
        c.name: str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)
    } == {
        "ck_horizon_completion_evidence_proof_hash_hex": "proof_hash ~ '^[0-9a-f]{64}$'",
        "ck_horizon_completion_evidence_final_available": (
            "is_final IS DISTINCT FROM true OR available_at IS NOT NULL"
        ),
        "ck_horizon_completion_evidence_proof_kind": (
            "proof_kind IN ('source_final_receipt', 'synthetic')"
        ),
    }
    assert {
        c.name: [col.name for col in c.columns]
        for c in table.constraints
        if isinstance(c, UniqueConstraint)
    } == {
        "uq_horizon_completion_evidence_bar_version_id_proof_hash": ["bar_version_id", "proof_hash"]
    }
    assert {i.name: [c.name for c in i.columns] for i in table.indexes} == {
        "ix_horizon_completion_evidence_read": ["bar_version_id", "available_at"],
        "ix_horizon_completion_evidence_pipeline_run_id": ["pipeline_run_id"],
    }
    assert all(not i.unique for i in table.indexes)


def test_purge_step_and_trigger_allowlist() -> None:
    from app.cli.delete_user_data import HANDLED_FK, STEPS, TRIGGER_ALLOWLIST

    steps = [s for s in STEPS if s.table == "app.horizon_completion_evidence"]
    assert len(steps) == 1
    assert steps[0].action == "delete"
    assert steps[0].where == (
        "bar_version_id IN (SELECT id FROM app.horizon_input_versions WHERE user_id = :uid)"
    )
    assert STEPS.index(steps[0]) < next(
        i for i, s in enumerate(STEPS) if s.table == "app.horizon_input_versions"
    )
    assert not any(c.startswith("app.horizon_completion_evidence.") for c in HANDLED_FK)
    assert {
        (
            "app.horizon_completion_evidence",
            "trg_horizon_completion_evidence_validate",
            "app.validate_horizon_completion_version",
        ),
        (
            "app.horizon_completion_evidence",
            "trg_horizon_completion_evidence_no_update",
            "app.reject_horizon_completion_update",
        ),
        (
            "app.horizon_completion_evidence",
            "trg_horizon_completion_evidence_no_delete",
            "app.reject_horizon_completion_delete",
        ),
    } <= TRIGGER_ALLOWLIST

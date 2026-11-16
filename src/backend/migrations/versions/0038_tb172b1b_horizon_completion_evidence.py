"""T-B172b1b：T-A192 §3.2/3.3 追加式完成证据，无历史回填。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "0038"
down_revision = "0037"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 当日 mairui 例行路径 pipeline_run_id 必填及 proof 正文校验由服务层 A1b 负责。
    op.create_table(
        "horizon_completion_evidence",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("bar_version_id", UUID(), nullable=False),
        sa.Column("pipeline_run_id", UUID(), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proof_kind", sa.Text(), nullable=False),
        sa.Column("proof_hash", sa.Text(), nullable=False),
        sa.Column("proof", JSONB(), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["bar_version_id"], ["app.horizon_input_versions.id"]),
        sa.ForeignKeyConstraint(["pipeline_run_id"], ["app.pipeline_runs.id"]),
        sa.UniqueConstraint("bar_version_id", "proof_hash"),
        sa.CheckConstraint("proof_hash ~ '^[0-9a-f]{64}$'", name="proof_hash_hex"),
        sa.CheckConstraint(
            "is_final IS DISTINCT FROM true OR available_at IS NOT NULL", name="final_available"
        ),
        sa.CheckConstraint(
            "proof_kind IN ('source_final_receipt', 'synthetic')", name="proof_kind"
        ),
        schema="app",
    )
    op.create_index(
        "ix_horizon_completion_evidence_read",
        "horizon_completion_evidence",
        ["bar_version_id", "available_at"],
        schema="app",
    )
    op.create_index(
        "ix_horizon_completion_evidence_pipeline_run_id",
        "horizon_completion_evidence",
        ["pipeline_run_id"],
        schema="app",
    )
    op.execute("""
        CREATE FUNCTION app.validate_horizon_completion_version() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE
            version_kind text;
            version_scope text;
        BEGIN
            SELECT kind, scope INTO version_kind, version_scope
            FROM app.horizon_input_versions WHERE id = NEW.bar_version_id;
            IF NOT FOUND OR version_kind IS DISTINCT FROM 'daily_bar' THEN
                RAISE EXCEPTION 'horizon_completion_evidence must reference daily_bar';
            END IF;
            IF NEW.proof_kind = 'synthetic' AND version_scope IS DISTINCT FROM 'synthetic' THEN
                RAISE EXCEPTION 'synthetic proof requires synthetic version';
            END IF;
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER trg_horizon_completion_evidence_validate
        BEFORE INSERT ON app.horizon_completion_evidence
        FOR EACH ROW EXECUTE FUNCTION app.validate_horizon_completion_version();

        CREATE FUNCTION app.reject_horizon_completion_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'horizon_completion_evidence is immutable: UPDATE forbidden';
        END;
        $$;
        CREATE TRIGGER trg_horizon_completion_evidence_no_update
        BEFORE UPDATE ON app.horizon_completion_evidence
        FOR EACH ROW EXECUTE FUNCTION app.reject_horizon_completion_update();
        CREATE FUNCTION app.reject_horizon_completion_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> 'aia_maint' THEN
                RAISE EXCEPTION 'horizon_completion_evidence is immutable: DELETE forbidden';
            END IF;
            RETURN OLD;
        END;
        $$;
        CREATE TRIGGER trg_horizon_completion_evidence_no_delete
        BEFORE DELETE ON app.horizon_completion_evidence
        FOR EACH ROW EXECUTE FUNCTION app.reject_horizon_completion_delete();
    """)


def downgrade() -> None:
    op.execute("LOCK TABLE app.horizon_completion_evidence IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM app.horizon_completion_evidence) THEN
                RAISE EXCEPTION 'horizon_completion_evidence not empty: refusing downgrade 0038';
            END IF;
        END $$;
    """)
    op.execute(
        "DROP TRIGGER trg_horizon_completion_evidence_validate ON app.horizon_completion_evidence"
    )
    op.execute(
        "DROP TRIGGER trg_horizon_completion_evidence_no_update ON app.horizon_completion_evidence"
    )
    op.execute(
        "DROP TRIGGER trg_horizon_completion_evidence_no_delete ON app.horizon_completion_evidence"
    )
    op.execute("DROP FUNCTION app.validate_horizon_completion_version()")
    op.execute("DROP FUNCTION app.reject_horizon_completion_update()")
    op.execute("DROP FUNCTION app.reject_horizon_completion_delete()")
    op.drop_table("horizon_completion_evidence", schema="app")

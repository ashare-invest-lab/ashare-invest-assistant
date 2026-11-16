"""T-B172b1a：Horizon 输入版本，普通表、只追加、无历史回填。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID

revision = "0037"
down_revision = "0036"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 派生 kind 清单与 source 枚举未验证，待契约出处后另补（编排者裁定 T-B172b1a 第 4 条）。
    # kind 白名单归服务层 b2a。
    op.create_table(
        "horizon_input_versions",
        sa.Column("id", UUID(), nullable=False),
        sa.Column("user_id", UUID(), nullable=False),
        sa.Column("licence_id", UUID(), nullable=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("scope", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=True),
        sa.Column("data_date", sa.Date(), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_version", sa.Text(), nullable=False),
        sa.Column("version_hash", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "dependency_ids", ARRAY(UUID()), nullable=False, server_default=sa.text("'{}'::uuid[]")
        ),
        sa.Column("transform_version", sa.Text(), nullable=False),
        sa.Column("supersedes_id", UUID(), nullable=True),
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["app.users.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["app.horizon_input_versions.id"]),
        sa.CheckConstraint("scope IN ('per_licence', 'public', 'synthetic')", name="scope"),
        sa.CheckConstraint(
            "(scope = 'per_licence') = (licence_id IS NOT NULL)", name="licence_scope"
        ),
        sa.CheckConstraint("kind = 'calendar' OR code IS NOT NULL", name="code"),
        sa.CheckConstraint("version_hash ~ '^[0-9a-f]{64}$'", name="version_hash_hex"),
        sa.CheckConstraint(
            "available_at IS NULL OR (first_seen_at IS NOT NULL AND available_at >= first_seen_at)",
            name="first_seen_order",
        ),
        sa.CheckConstraint(
            "available_at IS NULL OR computed_at IS NULL OR available_at >= computed_at",
            name="computed_order",
        ),
        # 派生 kind 清单出处：契约 §3.1 kind/source 出处表（48177db）。
        sa.CheckConstraint(
            "kind NOT IN ('adjust_factor', 'feature') OR computed_at IS NOT NULL",
            name="derived_computed_at",
        ),
        schema="app",
    )
    op.create_index(
        "uq_horizon_input_versions_version",
        "horizon_input_versions",
        [
            "user_id",
            "licence_id",
            "kind",
            "source",
            "code",
            "data_date",
            "source_key",
            "version_hash",
        ],
        unique=True,
        schema="app",
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_horizon_input_versions_read",
        "horizon_input_versions",
        ["user_id", "licence_id", "kind", "code", "data_date", "available_at"],
        schema="app",
    )
    op.create_index(
        "ix_horizon_input_versions_supersedes_id",
        "horizon_input_versions",
        ["supersedes_id"],
        schema="app",
    )
    op.execute("""
        CREATE FUNCTION app.reject_horizon_input_update() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'horizon_input_versions is immutable: UPDATE forbidden';
        END;
        $$;
        CREATE TRIGGER trg_horizon_input_versions_no_update
        BEFORE UPDATE ON app.horizon_input_versions
        FOR EACH ROW EXECUTE FUNCTION app.reject_horizon_input_update();
        CREATE FUNCTION app.reject_horizon_input_delete() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF current_user <> 'aia_maint' THEN
                RAISE EXCEPTION 'horizon_input_versions is immutable: DELETE forbidden';
            END IF;
            RETURN OLD;
        END;
        $$;
        CREATE TRIGGER trg_horizon_input_versions_no_delete
        BEFORE DELETE ON app.horizon_input_versions
        FOR EACH ROW EXECUTE FUNCTION app.reject_horizon_input_delete();
    """)


def downgrade() -> None:
    op.execute("LOCK TABLE app.horizon_input_versions IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM app.horizon_input_versions) THEN
                RAISE EXCEPTION 'horizon_input_versions not empty: refusing downgrade 0037';
            END IF;
        END $$;
    """)
    op.execute("DROP TRIGGER trg_horizon_input_versions_no_update ON app.horizon_input_versions")
    op.execute("DROP FUNCTION app.reject_horizon_input_update()")
    op.execute("DROP TRIGGER trg_horizon_input_versions_no_delete ON app.horizon_input_versions")
    op.execute("DROP FUNCTION app.reject_horizon_input_delete()")
    op.drop_table("horizon_input_versions", schema="app")

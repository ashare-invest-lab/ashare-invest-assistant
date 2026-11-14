"""T-B143：权息事件与离线分钟文件目录，均为普通表。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0036"
down_revision = "0035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 字段、主键和六位数值精度均来自契约 §3.3、§3.4（契约约定，未验证）。
    op.create_table(
        "ex_rights_events",
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("ex_date", sa.Date(), nullable=False),
        sa.Column("cash_per_share", sa.Numeric(20, 6), nullable=False),
        sa.Column("rights_price", sa.Numeric(20, 6), nullable=False),
        sa.Column("bonus_ratio", sa.Numeric(20, 6), nullable=False),
        sa.Column("rights_ratio", sa.Numeric(20, 6), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("snapshot_sha256", sa.Text(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("code", "ex_date", "snapshot_sha256"),
        sa.CheckConstraint("source IN ('tdx_gbbq')", name="source"),
        sa.CheckConstraint("snapshot_sha256 ~ '^[0-9a-f]{64}$'", name="snapshot_sha256_hex"),
        schema="market",
    )
    op.create_table(
        "minute_file_catalog",
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("rel_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("row_count", sa.BigInteger(), nullable=False),
        sa.Column("splice_segment", sa.Text(), nullable=False),
        sa.Column("generator", sa.Text(), nullable=False),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("source", "code", "kind", "rel_path"),
        sa.CheckConstraint("source IN ('hf_1min', 'tdx_local')", name="source"),
        sa.CheckConstraint("kind IN ('1m', '5m')", name="kind"),
        sa.CheckConstraint(
            "splice_segment IN ('hf_1m', 'vipdoc_1m', 'lc5')", name="splice_segment"
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="sha256_hex"),
        sa.CheckConstraint("row_count >= 0", name="row_count_nonnegative"),
        sa.CheckConstraint("date_from <= date_to", name="date_order"),
        sa.CheckConstraint(
            "rel_path NOT LIKE '/%' AND position(chr(92) in rel_path) = 0 "
            "AND rel_path !~ '(^|/)[.][.](/|$)' AND position(':' in rel_path) = 0",
            name="rel_path_safe",
        ),
        schema="market",
    )


def downgrade() -> None:
    conn = op.get_bind()
    events = conn.execute(sa.text("SELECT count(*) FROM market.ex_rights_events")).scalar_one()
    catalog = conn.execute(sa.text("SELECT count(*) FROM market.minute_file_catalog")).scalar_one()
    if events or catalog:
        raise RuntimeError("拒绝降级 0036：权息事件或分钟文件目录非空")
    op.drop_table("minute_file_catalog", schema="market")
    op.drop_table("ex_rights_events", schema="market")

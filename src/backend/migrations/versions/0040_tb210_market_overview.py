from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0040"
down_revision: str | Sequence[str] | None = "0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market"
TABLE = "quotes_snapshot"
NEW_COLUMNS = (
    "volume",
    "amount",
    "is_suspended",
    "limit_up",
    "limit_down",
    "batch_id",
)
COLUMN_TYPES = (
    ("volume", sa.Numeric()),
    ("amount", sa.Numeric(20, 4)),
    ("is_suspended", sa.Boolean()),
    ("limit_up", sa.Boolean()),
    ("limit_down", sa.Boolean()),
    ("batch_id", postgresql.UUID(as_uuid=True)),
)


def upgrade() -> None:
    for name, type_ in COLUMN_TYPES:
        op.add_column(TABLE, sa.Column(name, type_, nullable=True), schema=SCHEMA)


def downgrade() -> None:
    conn = op.get_bind()
    count = conn.execute(
        sa.text(
            "SELECT count(*) FROM market.quotes_snapshot WHERE "
            "volume IS NOT NULL OR amount IS NOT NULL OR is_suspended IS NOT NULL "
            "OR limit_up IS NOT NULL OR limit_down IS NOT NULL OR batch_id IS NOT NULL"
        )
    ).scalar_one()
    if int(count) > 0:
        raise RuntimeError(
            "refusing downgrade 0040: quotes_snapshot has market overview values; data loss avoided"
        )
    for column in reversed(NEW_COLUMNS):
        op.drop_column(TABLE, column, schema=SCHEMA)

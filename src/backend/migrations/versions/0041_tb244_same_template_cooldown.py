"""T-B244：为同模板同证券冷却新增专用原因码。"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0041"
down_revision: str | Sequence[str] | None = "0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "app"
SAME_TEMPLATE_COOLDOWN = "SAME_TEMPLATE_COOLDOWN"
REASON_CODES = (
    "DATA_STALE",
    "KEY_DATA_MISSING",
    "LOW_CONFIDENCE",
    "NON_TRADING_TIME",
    "SUSPENDED",
    "LIMIT_LOCKED",
    "ST_OR_DELISTING",
    "NEW_LISTING",
    "INSUFFICIENT_CASH",
    "T1_NOT_SELLABLE",
    "NO_POSITION",
    "POSITION_CAP_REACHED",
    "STRATEGY_BUDGET_EXHAUSTED",
    "SECTOR_EXPOSURE_EXCEEDED",
    "REGIME_MISMATCH",
    "SAME_DIRECTION_PLAN_EXISTS",
    "CONFLICTS_CONFIRMED_PLAN",
    "BLOCKLISTED",
    "COOLING_OFF",
    SAME_TEMPLATE_COOLDOWN,
    "LOSS_STREAK_PAUSE",
    "STRATEGY_CONFLICT",
    "USER_MUTED",
)
LEGACY_REASON_CODES = tuple(code for code in REASON_CODES if code != SAME_TEMPLATE_COOLDOWN)


def _in(column: str, values: Sequence[str]) -> str:
    return f"{column} IN (" + ", ".join(f"'{value}'" for value in values) + ")"


def _set_check(table: str, column: str, values: Sequence[str]) -> None:
    name = op.f(f"ck_{table}_{column}")
    op.drop_constraint(name, table, type_="check", schema=SCHEMA)
    op.create_check_constraint(name, table, _in(column, values), schema=SCHEMA)


def upgrade() -> None:
    _set_check("non_executable_reasons", "code", REASON_CODES)
    _set_check("strategy_instances", "pause_reason_code", REASON_CODES)


def downgrade() -> None:
    conn = op.get_bind()
    for statement in (
        "SELECT count(*) FROM app.non_executable_reasons WHERE code = :code",
        "SELECT count(*) FROM app.strategy_instances WHERE pause_reason_code = :code",
    ):
        count = conn.execute(
            sa.text(statement),
            {"code": SAME_TEMPLATE_COOLDOWN},
        ).scalar_one()
        if int(count) > 0:
            raise RuntimeError(
                f"refusing downgrade 0041: {SAME_TEMPLATE_COOLDOWN} rows exist"
            )
    _set_check("strategy_instances", "pause_reason_code", LEGACY_REASON_CODES)
    _set_check("non_executable_reasons", "code", LEGACY_REASON_CODES)

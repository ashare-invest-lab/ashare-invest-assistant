"""T-B196 I2 intraday ownership storage migration.

The migration implements ``docs/contracts/intraday-ownership.md`` §§1–5.
``T-B196-I2-ISOLATION`` is a source-level sentinel used by the offline
acceptance checks.  Existing rows retain NULL source, licence and fingerprint
values.  Only the generated row identity and ``revision=0`` are backfilled.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0039"
down_revision: str | Sequence[str] | None = "0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA = "market"
TABLES = ("quotes_snapshot", "realtime_quotes", "minute_bars", "minute5_bars")
HYPERTABLES = ("realtime_quotes", "minute_bars", "minute5_bars")
MINUTE_TABLES = ("minute_bars", "minute5_bars")

OFFLINE_SOURCE_SQL = "'tdx_local', 'pro_latest', 'pro_history', 'ssjy_more', 'ssjy_all', 'real_all'"


def _qualified(table: str) -> str:
    return f"{SCHEMA}.{table}"


def _assert_no_compressed_chunks() -> None:
    conn = op.get_bind()
    if not conn.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb')")
    ).scalar():
        return
    for table in HYPERTABLES:
        count = conn.execute(
            sa.text(
                "SELECT count(*) FROM timescaledb_information.chunks "
                "WHERE hypertable_schema = :schema AND hypertable_name = :table "
                "AND is_compressed IS TRUE"
            ),
            {"schema": SCHEMA, "table": table},
        ).scalar_one()
        if count:
            raise RuntimeError(
                f"refusing migration 0039: {table} has {count} compressed chunks; "
                "stop writes and decompress_chunk per the operations manual, then rerun; "
                "migration will not decompress or change compression/retention policies"
            )


def _add_i2_columns(table: str) -> None:
    if table == "quotes_snapshot":
        op.add_column(table, sa.Column("source", sa.Text(), nullable=True), schema=SCHEMA)
        op.add_column(
            table,
            sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema=SCHEMA,
        )
    elif table == "realtime_quotes":
        op.add_column(
            table,
            sa.Column("source_licence_id", postgresql.UUID(as_uuid=True), nullable=True),
            schema=SCHEMA,
        )
    op.add_column(
        table,
        sa.Column("row_id", postgresql.UUID(as_uuid=True), nullable=True),
        schema=SCHEMA,
    )
    op.add_column(table, sa.Column("revision", sa.BigInteger(), nullable=True), schema=SCHEMA)
    op.add_column(table, sa.Column("content_fingerprint", sa.Text(), nullable=True), schema=SCHEMA)
    if table in MINUTE_TABLES:
        op.add_column(table, sa.Column("is_final", sa.Boolean(), nullable=True), schema=SCHEMA)


def _backfill_identity(table: str) -> None:
    op.execute(
        sa.text(
            f"UPDATE {_qualified(table)} "  # noqa: S608 - table names are fixed migration constants
            "SET row_id = COALESCE(row_id, gen_random_uuid()), "
            "revision = COALESCE(revision, 0) "
            "WHERE row_id IS NULL OR revision IS NULL"
        )
    )
    op.alter_column(
        table,
        "row_id",
        existing_type=postgresql.UUID(as_uuid=True),
        nullable=False,
        server_default=sa.text("gen_random_uuid()"),
        schema=SCHEMA,
    )
    op.alter_column(
        table,
        "revision",
        existing_type=sa.BigInteger(),
        nullable=False,
        server_default=sa.text("0"),
        schema=SCHEMA,
    )


def _replace_primary_key(table: str, columns: tuple[str, ...]) -> None:
    op.drop_constraint(f"pk_{table}", table, type_="primary", schema=SCHEMA)
    op.create_primary_key(f"pk_{table}", table, list(columns), schema=SCHEMA)


def _create_ownership_checks(table: str) -> None:
    if table == "quotes_snapshot":
        op.create_check_constraint(
            "ck_quotes_snapshot_source",
            table,
            "source IN ('mairui')",
            schema=SCHEMA,
        )
    op.create_check_constraint(
        f"ck_{table}_source_licence_relation",
        table,
        "(source IS NULL AND source_licence_id IS NULL) OR "
        "(source = 'mairui' AND source_licence_id IS NOT NULL) OR "
        "(source IS NOT NULL AND source <> 'mairui' AND source_licence_id IS NULL)",
        schema=SCHEMA,
    )
    op.create_check_constraint(
        f"ck_{table}_revision_nonnegative",
        table,
        "revision >= 0",
        schema=SCHEMA,
    )


def _create_ownership_indexes(table: str) -> None:
    prefix = table
    licensed_where = "source_licence_id IS NOT NULL AND source IN ('mairui')"
    offline_where = "source_licence_id IS NULL AND source IN (" + OFFLINE_SOURCE_SQL + ")"
    legacy_where = "source IS NULL AND source_licence_id IS NULL"
    op.create_index(
        f"uq_{prefix}_ownership_licence_revision",
        table,
        ["code", "ts", "source", "source_licence_id", "revision"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(licensed_where),
    )
    op.create_index(
        f"uq_{prefix}_ownership_offline_revision",
        table,
        ["code", "ts", "source", "revision"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(offline_where),
    )
    op.create_index(
        f"uq_{prefix}_ownership_legacy",
        table,
        ["code", "ts"],
        unique=True,
        schema=SCHEMA,
        postgresql_where=sa.text(legacy_where),
    )
    for scope, predicate in (("licence", licensed_where), ("offline", offline_where)):
        op.create_index(
            f"uq_{prefix}_fingerprint_{scope}",
            table,
            ["code", "ts", "source", "source_licence_id", "content_fingerprint"],
            unique=True,
            schema=SCHEMA,
            postgresql_where=sa.text(predicate),
        )


def upgrade() -> None:
    _assert_no_compressed_chunks()
    for table in TABLES:
        _add_i2_columns(table)
    for table in TABLES:
        _backfill_identity(table)

    _replace_primary_key("quotes_snapshot", ("row_id",))
    for table in HYPERTABLES:
        _replace_primary_key(table, ("ts", "row_id"))

    for table in TABLES:
        _create_ownership_checks(table)
        _create_ownership_indexes(table)


def _drop_ownership_objects(table: str) -> None:
    for suffix in (
        "ownership_licence_revision",
        "ownership_offline_revision",
        "ownership_legacy",
        "fingerprint_licence",
        "fingerprint_offline",
    ):
        op.drop_index(f"uq_{table}_{suffix}", table_name=table, schema=SCHEMA)
    op.drop_constraint(f"ck_{table}_revision_nonnegative", table, schema=SCHEMA)
    op.drop_constraint(f"ck_{table}_source_licence_relation", table, schema=SCHEMA)
    if table == "quotes_snapshot":
        op.drop_constraint("ck_quotes_snapshot_source", table, schema=SCHEMA)


def downgrade() -> None:
    _assert_no_compressed_chunks()
    conn = op.get_bind()
    for table in ("quotes_snapshot", "realtime_quotes", "minute_bars", "minute5_bars"):
        conditions = ["source_licence_id IS NOT NULL"]
        if table == "quotes_snapshot":
            conditions.append("source = 'mairui'")
        if table in MINUTE_TABLES:
            conditions.append("is_final IS NOT NULL")
        where = " OR ".join(conditions)
        if (
            int(
                conn.execute(
                    sa.text(
                        f"SELECT count(*) FROM {_qualified(table)} WHERE ({where}) OR revision > 0"  # noqa: S608 - fixed migration constants
                    )
                ).scalar_one()
            )
            > 0
        ):
            raise RuntimeError(
                f"refusing downgrade 0039: {table} has new ownership rows; data loss avoided"
            )

    for table in TABLES:
        _drop_ownership_objects(table)

    _replace_primary_key("quotes_snapshot", ("code", "ts"))
    for table in HYPERTABLES:
        _replace_primary_key(table, ("code", "ts"))

    for table in TABLES:
        if table in MINUTE_TABLES:
            op.drop_column(table, "is_final", schema=SCHEMA)
        op.drop_column(table, "content_fingerprint", schema=SCHEMA)
        op.drop_column(table, "revision", schema=SCHEMA)
        op.drop_column(table, "row_id", schema=SCHEMA)
        if table in ("quotes_snapshot", "realtime_quotes"):
            op.drop_column(table, "source_licence_id", schema=SCHEMA)
        if table == "quotes_snapshot":
            op.drop_column(table, "source", schema=SCHEMA)

"""T-A192 §3.1：Horizon 追加式输入版本。"""

from sqlalchemy import CheckConstraint, Index, Table, UniqueConstraint, text

from app.db.base import (
    APP,
    boolean,
    created_at,
    day,
    jsonb,
    metadata,
    one_of,
    ts,
    txt,
    user_fk,
    uuid_array,
    uuid_col,
)

# 派生 kind 清单与 source 枚举未验证，待契约出处后另补（编排者裁定 T-B172b1a 第 4 条）。
horizon_input_versions = Table(
    "horizon_input_versions",
    metadata,
    uuid_col("id", nullable=False, primary_key=True),
    user_fk(),
    uuid_col("licence_id"),
    txt("kind", nullable=False),
    txt("source", nullable=False),
    txt("scope", nullable=False),
    txt("code"),
    day("data_date", nullable=False),
    txt("source_key", nullable=False),
    txt("source_version", nullable=False),
    txt("version_hash", nullable=False),
    jsonb("payload", nullable=False),
    ts("first_seen_at"),
    ts("available_at"),
    ts("computed_at"),
    uuid_array("dependency_ids", nullable=False, server_default=text("'{}'::uuid[]")),
    txt("transform_version", nullable=False),
    uuid_col("supersedes_id", fk="app.horizon_input_versions.id"),
    created_at("recorded_at"),
    one_of(
        "kind", ["calendar", "daily_bar", "vendor_factor", "ex_rights", "adjust_factor", "feature"]
    ),
    one_of("scope", ["per_licence", "public", "synthetic"]),
    CheckConstraint("(scope = 'per_licence') = (licence_id IS NOT NULL)", name="licence_scope"),
    CheckConstraint("kind = 'calendar' OR code IS NOT NULL", name="code"),
    CheckConstraint("version_hash ~ '^[0-9a-f]{64}$'", name="version_hash_hex"),
    CheckConstraint(
        "available_at IS NULL OR (first_seen_at IS NOT NULL AND available_at >= first_seen_at)",
        name="first_seen_order",
    ),
    CheckConstraint(
        "available_at IS NULL OR computed_at IS NULL OR available_at >= computed_at",
        name="computed_order",
    ),
    schema=APP,
)
Index(
    "uq_horizon_input_versions_version",
    *(
        horizon_input_versions.c[name]
        for name in (
            "user_id",
            "licence_id",
            "kind",
            "source",
            "code",
            "data_date",
            "source_key",
            "version_hash",
        )
    ),
    unique=True,
    postgresql_nulls_not_distinct=True,
)
Index(
    "ix_horizon_input_versions_read",
    *(
        horizon_input_versions.c[name]
        for name in ("user_id", "licence_id", "kind", "code", "data_date", "available_at")
    ),
)
Index("ix_horizon_input_versions_supersedes_id", horizon_input_versions.c.supersedes_id)

# T-A192 §3.2：可见性未知保持 NULL，登记时间不代替证据可见时间。
horizon_completion_evidence = Table(
    "horizon_completion_evidence",
    metadata,
    uuid_col("id", nullable=False, primary_key=True),
    uuid_col("bar_version_id", nullable=False, fk="app.horizon_input_versions.id"),
    uuid_col("pipeline_run_id", fk="app.pipeline_runs.id"),
    boolean("is_final"),
    ts("available_at"),
    txt("proof_kind", nullable=False),
    txt("proof_hash", nullable=False),
    jsonb("proof", nullable=False),
    created_at("recorded_at"),
    UniqueConstraint("bar_version_id", "proof_hash"),
    CheckConstraint("proof_hash ~ '^[0-9a-f]{64}$'", name="proof_hash_hex"),
    CheckConstraint(
        "is_final IS DISTINCT FROM true OR available_at IS NOT NULL", name="final_available"
    ),
    one_of("proof_kind", ["source_final_receipt", "synthetic"]),
    schema=APP,
)
Index(
    "ix_horizon_completion_evidence_read",
    horizon_completion_evidence.c.bar_version_id,
    horizon_completion_evidence.c.available_at,
)
Index(
    "ix_horizon_completion_evidence_pipeline_run_id", horizon_completion_evidence.c.pipeline_run_id
)

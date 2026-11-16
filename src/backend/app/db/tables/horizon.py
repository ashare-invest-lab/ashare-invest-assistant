"""T-A192 §3.1：Horizon 追加式输入版本。"""

from sqlalchemy import CheckConstraint, Index, Table, text

from app.db.base import (
    APP,
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
# kind 白名单归服务层 b2a。
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
    # 派生 kind 清单出处：契约 §3.1 kind/source 出处表（48177db）。
    CheckConstraint(
        "kind NOT IN ('adjust_factor', 'feature') OR computed_at IS NOT NULL",
        name="derived_computed_at",
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

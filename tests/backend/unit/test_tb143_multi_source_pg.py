"""T-B143 可选 PG 验收；沿用共享 pg_conn，无 PG 环境自动跳过。"""

from __future__ import annotations

import csv
import io
import uuid
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[3] / "src/backend"


@pytest.fixture
def offline_schema(pg_conn):
    """在测试事务中用真实迁移建两个新表，避免触碰已有业务表。"""
    schema = "tb143_" + uuid.uuid4().hex
    pg_conn.execute(f'CREATE SCHEMA "{schema}"')
    config = Config()
    config.set_main_option("script_location", str(BACKEND / "migrations"))
    migration = ScriptDirectory.from_config(config).get_revision("0036").module
    output = io.StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        migration.upgrade()
    pg_conn.execute(output.getvalue().replace("market.", f'"{schema}".'))
    # 只构造本次加载涉及的日线列；不依赖其他迁移或业务数据。
    pg_conn.execute(f'''
        CREATE TABLE "{schema}".daily_bars (
          code text, trade_date date, adj_type text, open numeric, high numeric,
          low numeric, close numeric, volume numeric, amount numeric, source text,
          pre_close numeric, is_suspended boolean, source_licence_id uuid, fetched_at timestamptz,
          PRIMARY KEY (code, trade_date, adj_type)
        );
        INSERT INTO "{schema}".daily_bars (code, trade_date, adj_type, close, volume, amount, source)
          VALUES ('600999.SH', '2025-01-02', 'none', 12.00, 700, 8400, 'mairui');
    ''')
    return schema


def _load(
    conn,
    schema,
    catalog_sha="a",
    duplicate_sha=None,
    *,
    meta=False,
    before="2025-01-01",
    extra_catalog=None,
    extra_day=None,
):
    """执行拆分 SQL；以 STDIN 代替服务端文件，事务边界由测试 fixture 回滚。"""
    csv_rows = {
        "day_stage": [
            [
                "code",
                "trade_date",
                "adj_type",
                "open",
                "high",
                "low",
                "close",
                "volume",
                "amount",
            ],
            ["600999.SH", "2024-01-02", "none", 12.34, 12.34, 12.34, 12.34, 700, 8638],
        ],
        "gbbq_stage": [
            [
                "code",
                "ex_date",
                "cash_per_share",
                "rights_price",
                "bonus_ratio",
                "rights_ratio",
                "source",
                "snapshot_sha256",
            ],
            ["600999.SH", "2025-01-02", 0.2, 8, 0.1, 0.1, "tdx_gbbq", "b" * 64],
        ],
        "catalog_stage": [
            [
                "source",
                "code",
                "kind",
                "date_from",
                "date_to",
                "rel_path",
                "sha256",
                "row_count",
                "splice_segment",
                "generator",
            ],
            [
                "hf_1min",
                "600999.SH",
                "1m",
                "2025-01-02",
                "2026-08-07",
                "hf/x.parquet",
                catalog_sha * 64,
                240,
                "hf_1m",
                "c" * 40,
            ],
        ],
    }
    if duplicate_sha:
        csv_rows["catalog_stage"].append(csv_rows["catalog_stage"][-1][:])
        csv_rows["catalog_stage"][-1][6] = duplicate_sha * 64
    if extra_catalog:
        csv_rows["catalog_stage"].extend(extra_catalog)
    if extra_day:
        csv_rows["day_stage"].extend(extra_day)
    filename = "tb143_load_meta.sql" if meta else "tb143_load_day.sql"
    source = (BACKEND / "probes" / filename).read_text(encoding="utf-8")
    source = source.replace(":'before'", f"'{before}'")
    source = source.replace("market.", f'"{schema}".')
    pending = []
    for line in source.splitlines():
        if line.startswith("\\") or line in (
            "BEGIN;",
            "COMMIT;",
            "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;",
        ):
            continue
        if line.startswith("COPY "):
            if pending:
                conn.execute("\n".join(pending))
            pending.clear()
            table = line.split()[1]
            data = io.StringIO()
            csv.writer(data).writerows(csv_rows[table])
            with conn.cursor().copy(
                f"COPY {table} FROM STDIN WITH (FORMAT csv, HEADER true)"
            ) as copy:
                copy.write(data.getvalue())
        else:
            pending.append(line)
    conn.execute("\n".join(pending))


@pytest.mark.parametrize("preload", [False, True])
def test_msi_existing_mairui_never_overwritten(pg_conn, offline_schema, preload):
    if preload:
        pg_conn.execute(f'''
            INSERT INTO "{offline_schema}".daily_bars
              (code, trade_date, adj_type, close, volume, amount, source, fetched_at)
              VALUES ('600999.SH', '2024-01-02', 'none', 12.34, 700, 8638, 'tdx_local', now()),
                     ('600999.SH', '2026-01-02', 'none', 12.34, 700, 8638, 'tdx_local', now());
            INSERT INTO "{offline_schema}".ex_rights_events
              VALUES ('600999.SH', '2025-01-02', 0.2, 8, 0.1, 0.1, 'tdx_gbbq',
                      repeat('b', 64), now());
            INSERT INTO "{offline_schema}".minute_file_catalog
              VALUES ('hf_1min', '600999.SH', '1m', '2025-01-02', '2026-08-06',
                      'hf/x.parquet', repeat('a', 64), 240, 'hf_1m', repeat('c', 40), now());
        ''')
    _load(pg_conn, offline_schema)
    assert pg_conn.execute(
        f"SELECT close, source FROM \"{offline_schema}\".daily_bars WHERE trade_date='2025-01-02'"
    ).fetchone() == (12, "mairui")
    rows = pg_conn.execute("SELECT candidates, inserted, skipped FROM load_counts").fetchall()
    assert rows == [
        (1, 0 if preload else 1, 1 if preload else 0),
    ]
    assert (
        pg_conn.execute("SELECT * FROM mairui_before").fetchone()
        == pg_conn.execute("SELECT * FROM mairui_after").fetchone()
    )
    assert pg_conn.execute(f'''
        SELECT bool_and(pre_close IS NULL AND is_suspended IS NULL AND source_licence_id IS NULL
                        AND fetched_at IS NOT NULL)
        FROM "{offline_schema}".daily_bars WHERE source = 'tdx_local'
    ''').fetchone() == (True,)


@pytest.mark.parametrize("existing", [False, True])
def test_msi_catalog_sha_mismatch_refused(pg_conn, offline_schema, existing):
    import psycopg

    if existing:
        pg_conn.execute(f'''
            INSERT INTO "{offline_schema}".minute_file_catalog
              VALUES ('hf_1min', '600999.SH', '1m', '2025-01-02', '2026-08-06',
                      'hf/x.parquet', repeat('a', 64), 240, 'hf_1m', repeat('c', 40), now())
        ''')
    with pytest.raises(psycopg.errors.RaiseException, match="SHA256"):
        with pg_conn.transaction():
            _load(
                pg_conn,
                offline_schema,
                catalog_sha="d",
                duplicate_sha=None if existing else "e",
                meta=True,
            )
    assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".daily_bars').fetchone() == (1,)
    assert pg_conn.execute(
        f'SELECT count(*) FROM "{offline_schema}".ex_rights_events'
    ).fetchone() == (0,)
    assert pg_conn.execute(
        f'SELECT sha256 FROM "{offline_schema}".minute_file_catalog'
    ).fetchall() == ([("a" * 64,)] if existing else [])


@pytest.mark.parametrize("conflict", [False, True])
def test_msi_catalog_one_source_per_stock_day(pg_conn, offline_schema, conflict):
    import psycopg

    lc = [
        "tdx_local",
        "600999.SH",
        "1m",
        "2026-08-07",
        "2026-08-10",
        "tdx-min/a.lc1",
        "b" * 64,
        240,
        "vipdoc_1m",
        "c" * 40,
    ]
    if conflict:
        other = lc[:]
        other[5] = "tdx-min/b.lc1"
        with pytest.raises(psycopg.errors.RaiseException, match="有效区间重叠"):
            with pg_conn.transaction():
                _load(pg_conn, offline_schema, meta=True, extra_catalog=[lc, other])
    else:
        _load(pg_conn, offline_schema, meta=True, extra_catalog=[lc])
        assert pg_conn.execute(
            f'SELECT count(*) FROM "{offline_schema}".minute_file_catalog'
        ).fetchone() == (2,)


@pytest.mark.parametrize(
    "before,extra_day,reason",
    [
        ("2024-01-02", None, "日期必须"),
        ("2026-01-01", None, "已有麦蕊行"),
        (
            "2025-01-01",
            [["600999.SH", "2023-01-02", "none", 12.34, 12.34, 12.34, 12.34, 700, 8638]],
            "只能加载一年",
        ),
    ],
)
def test_day_load_refuses_invalid_batch(pg_conn, offline_schema, before, extra_day, reason):
    import psycopg

    with pytest.raises(psycopg.errors.RaiseException, match=reason):
        with pg_conn.transaction():
            _load(pg_conn, offline_schema, before=before, extra_day=extra_day)
    assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".daily_bars').fetchone() == (1,)


@pytest.mark.parametrize("rel", ["/absolute", "x/../y", r"x\y", "F:drive"])
def test_catalog_path_constraints(pg_conn, offline_schema, rel):
    import psycopg

    with pytest.raises(psycopg.errors.CheckViolation):
        with pg_conn.transaction():
            pg_conn.execute(
                f'''
                INSERT INTO "{offline_schema}".minute_file_catalog
                  VALUES ('hf_1min', '600999.SH', '1m', '2025-01-02', '2026-08-06',
                          %s, repeat('a', 64), 240, 'hf_1m', repeat('c', 40), now())
            ''',
                (rel,),
            )


def test_load_mairui_count_change_rolls_back(pg_conn, offline_schema):
    """合成触发器意外新增麦蕊行时，行数断言必须拒绝并回滚本次加载。"""
    import psycopg

    pg_conn.execute(f'''
        CREATE FUNCTION "{offline_schema}".unexpected_mairui() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
          INSERT INTO "{offline_schema}".daily_bars
            (code, trade_date, adj_type, close, volume, amount, source)
            VALUES ('600998.SH', NEW.trade_date, 'none', 1, 1, 1, 'mairui');
          RETURN NEW;
        END $$;
        CREATE TRIGGER unexpected_mairui AFTER INSERT ON "{offline_schema}".daily_bars
          FOR EACH ROW WHEN (NEW.source = 'tdx_local')
          EXECUTE FUNCTION "{offline_schema}".unexpected_mairui();
    ''')
    with pytest.raises(psycopg.errors.RaiseException, match="麦蕊行数前后必须"):
        with pg_conn.transaction():
            _load(pg_conn, offline_schema)
    assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".daily_bars').fetchone() == (1,)
    for table in ("ex_rights_events", "minute_file_catalog"):
        assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".{table}').fetchone() == (
            0,
        )

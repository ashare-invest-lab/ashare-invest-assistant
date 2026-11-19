"""T-B143 可选 PG 验收；沿用共享 pg_conn，无 PG 环境自动跳过。"""

from __future__ import annotations

import csv
import datetime as dt
import io
import re
import uuid
from decimal import Decimal
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
    return _create_offline_schema(pg_conn)


def _create_offline_schema(pg_conn):
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


@pytest.fixture
def python_day_batch(pg_url, monkeypatch):
    """独立 schema；入口持有真实事务，另一个自动提交连接负责夹具和快照。"""
    import psycopg

    from app.marketdata import daily_bars as writer
    from app.cli import tb143_day_load

    calls = []
    inside_public_writer = False
    public_writer = writer.upsert_daily_bars

    def observed(conn, *args, **kwargs):
        nonlocal inside_public_writer
        call = {"conn": conn, "result": args[0] if args else kwargs.get("result"), "kwargs": kwargs}
        calls.append(call)
        inside_public_writer = True
        try:
            call["stats"] = public_writer(conn, *args, **kwargs)
        finally:
            inside_public_writer = False
        return call["stats"]

    monkeypatch.setattr(writer, "upsert_daily_bars", observed)
    monkeypatch.setattr(tb143_day_load, "upsert_daily_bars", observed)
    dsn = tb143_day_load.to_psycopg_dsn(pg_url)
    with psycopg.connect(dsn, autocommit=True) as setup_conn:
        with setup_conn.transaction():
            schema = _create_offline_schema(setup_conn)

        class IsolatedCursorMixin:
            def execute(self, statement, *args, **kwargs):
                # 原入口不经过 SQLAlchemy Connection；在真正发送给 PG 的游标层
                # 替代 before_cursor_execute 守卫，并把固定 market schema 路由到夹具。
                assert isinstance(statement, str), "不可绕过测试的 SQL schema 隔离与 DML 守卫"
                statement = re.sub(r'(?<![\w"])"?market"?\.', f'"{schema}".', statement)
                if re.search(
                    r'\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE(?:\s+TABLE)?|MERGE\s+INTO|COPY)'
                    r'\s+(?:ONLY\s+)?(?:[\w\"]+\.)?"?daily_bars\b', statement, re.I
                ):
                    assert inside_public_writer, "目标日线 DML 必须实际由 upsert_daily_bars 执行"
                return super().execute(statement, *args, **kwargs)

        class IsolatedCursor(IsolatedCursorMixin, psycopg.Cursor):
            pass

        class IsolatedServerCursor(IsolatedCursorMixin, psycopg.ServerCursor):
            pass

        try:
            with psycopg.connect(dsn, cursor_factory=IsolatedCursor) as conn:
                conn.server_cursor_factory = IsolatedServerCursor
                assert conn.info.transaction_status == psycopg.pq.TransactionStatus.IDLE
                yield setup_conn, schema, conn, calls
        finally:
            setup_conn.execute(f'DROP SCHEMA "{schema}" CASCADE')


def _load_day_batch(conn, tmp_path, *, before="2025-01-01", extra_day=None):
    """只生成年度 CSV；整批校验、事务、公共 writer 和计数守卫均走真实入口。"""
    from app.cli.tb143_day_load import load_day

    rows = [["600999.SH", "2024-01-02", "none", 12.34, 12.34, 12.34, 12.34, 700, 8638]]
    rows.extend(extra_day or [])
    csv_path = tmp_path / "day_2024.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows([
            ["code", "trade_date", "adj_type", "open", "high", "low", "close", "volume", "amount"],
            *rows,
        ])
    assert conn.info.transaction_status == 0, "load_day 必须在无活动事务的连接上进入"
    try:
        return load_day(conn, csv_path, dt.date.fromisoformat(before))
    finally:
        assert conn.info.transaction_status == 0, "load_day 必须完成提交或失败回滚"


def _daily_rows(conn, schema, *, mairui_only=False):
    where = " WHERE source = 'mairui'" if mairui_only else ""
    return conn.execute(
        f'SELECT * FROM "{schema}".daily_bars{where} ORDER BY code, trade_date, adj_type'
    ).fetchall()


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
def test_msi_existing_mairui_never_overwritten(python_day_batch, tmp_path, preload):
    pg_conn, offline_schema, conn, calls = python_day_batch
    # Populate every protected field, so the full-row snapshot is not all NULLs.
    pg_conn.execute(f'''
        UPDATE "{offline_schema}".daily_bars
        SET open=11, high=13, low=10, pre_close=11.5, is_suspended=false,
            source_licence_id='00000000-0000-0000-0000-000000000197',
            fetched_at='2031-01-02 13:00:00+00'
        WHERE source='mairui'
    ''')
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
    mairui_before = _daily_rows(pg_conn, offline_schema, mairui_only=True)
    _load_day_batch(conn, tmp_path)
    assert pg_conn.execute(
        f"SELECT close, source FROM \"{offline_schema}\".daily_bars WHERE trade_date='2025-01-02'"
    ).fetchone() == (12, "mairui")
    assert calls, "整批写入必须实际经过 upsert_daily_bars"
    assert all(call["conn"].conn is conn for call in calls), "公共 writer 适配器必须使用同一事务连接"
    assert all(call["kwargs"]["source"] == "tdx_local" for call in calls)
    rows = [(sum(len(call["result"].bars) for call in calls),
             sum(call["stats"].inserted for call in calls),
             sum(call["stats"].unchanged + call["stats"].conflicts for call in calls))]
    assert rows == [
        (1, 0 if preload else 1, 1 if preload else 0),
    ]
    assert (
        mairui_before == _daily_rows(pg_conn, offline_schema, mairui_only=True)
    )
    assert pg_conn.execute(f'''
        SELECT open, high, low, close, volume, amount, source
        FROM "{offline_schema}".daily_bars WHERE trade_date='2024-01-02'
    ''').fetchone() == ((None, None, None) if preload else (Decimal("12.34"),) * 3) + (
        Decimal("12.34"), 700, 8638, "tdx_local")
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
        ("2024-01-02", None, "日线日期必须全部小于 before，拒绝加载"),
        ("2026-01-01", None, "before 之前已有麦蕊行，拒绝加载"),
        (
            "2025-01-01",
            [["600999.SH", "2023-01-02", "none", 12.34, 12.34, 12.34, 12.34, 700, 8638]],
            "每次只能加载一年的日线 CSV",
        ),
    ],
)
def test_day_load_refuses_invalid_batch(python_day_batch, tmp_path, before, extra_day, reason):
    import psycopg

    pg_conn, offline_schema, conn, calls = python_day_batch
    original = _daily_rows(pg_conn, offline_schema)
    error = ValueError if "已有麦蕊行" in reason else psycopg.errors.RaiseException
    with pytest.raises(error, match=reason):
        _load_day_batch(conn, tmp_path, before=before, extra_day=extra_day)
    assert not calls, "整批日期边界/已有麦蕊区间/跨年校验必须先于公共 writer"
    assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".daily_bars').fetchone() == (1,)
    assert _daily_rows(pg_conn, offline_schema) == original


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


def test_load_mairui_count_change_rolls_back(python_day_batch, tmp_path):
    """合成触发器意外新增麦蕊行时，行数断言必须拒绝并回滚本次加载。"""
    pg_conn, offline_schema, conn, calls = python_day_batch

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
    original = _daily_rows(pg_conn, offline_schema)
    with pytest.raises(ValueError, match="麦蕊行数变化，回滚本年加载"):
        _load_day_batch(conn, tmp_path)
    assert calls and all(call["conn"].conn is conn for call in calls)
    assert sum(call["stats"].inserted for call in calls) == 1, "必须真实触发公共 writer INSERT"
    assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".daily_bars').fetchone() == (1,)
    assert _daily_rows(pg_conn, offline_schema) == original
    for table in ("ex_rights_events", "minute_file_catalog"):
        assert pg_conn.execute(f'SELECT count(*) FROM "{offline_schema}".{table}').fetchone() == (
            0,
        )

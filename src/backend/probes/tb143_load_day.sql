-- 每次仅加载一年的 CSV，每次调用独立提交；本脚本不调用元数据加载脚本。
-- psql -v csv=/服务端可读/day_2022.csv -v before=2023-01-01 -f tb143_load_day.sql
\set ON_ERROR_STOP on
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
CREATE TEMP TABLE load_params (before_date date NOT NULL) ON COMMIT DROP;
INSERT INTO load_params VALUES (:'before'::date);
CREATE TEMP TABLE day_stage (
  code text, trade_date date, adj_type text CHECK (adj_type = 'none'),
  open numeric, high numeric, low numeric, close numeric, volume numeric, amount numeric
) ON COMMIT DROP;
COPY day_stage FROM :'csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM day_stage WHERE trade_date IS NULL
      OR trade_date >= (SELECT before_date FROM load_params)
  ) THEN
    RAISE EXCEPTION '日线日期必须全部小于 before，拒绝加载';
  END IF;
  IF (SELECT count(DISTINCT extract(year FROM trade_date)) FROM day_stage) > 1 THEN
    RAISE EXCEPTION '每次只能加载一年的日线 CSV';
  END IF;
END $$;
CREATE TEMP VIEW mairui_count AS
  SELECT count(*) AS n FROM market.daily_bars
  WHERE source = 'mairui' AND trade_date < (SELECT before_date FROM load_params);
CREATE TEMP TABLE mairui_before ON COMMIT DROP AS SELECT * FROM mairui_count;
CREATE TEMP TABLE load_counts (candidates bigint, inserted bigint, skipped bigint) ON COMMIT DROP;
DO $$
DECLARE
  n bigint;
  total bigint;
BEGIN
  IF (SELECT n FROM mairui_before) <> 0 THEN
    RAISE EXCEPTION 'before 之前已有麦蕊行，拒绝加载';
  END IF;
  SELECT count(*) INTO total FROM day_stage;
  INSERT INTO market.daily_bars (
    code, trade_date, adj_type, open, high, low, close, volume, amount,
    source, pre_close, is_suspended, source_licence_id, fetched_at
  )
  SELECT code, trade_date, adj_type, open, high, low, close, volume, amount,
    'tdx_local', NULL, NULL, NULL, now()
  FROM day_stage
  ON CONFLICT (code, trade_date, adj_type) DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  INSERT INTO load_counts VALUES (total, n, total - n);
END $$;
CREATE TEMP TABLE mairui_after ON COMMIT DROP AS SELECT * FROM mairui_count;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM mairui_before b CROSS JOIN mairui_after a
    WHERE b.n <> 0 OR a.n <> 0 OR b.n IS DISTINCT FROM a.n
  ) THEN
    RAISE EXCEPTION '麦蕊行数前后必须为 0 且不变，回滚本年加载';
  END IF;
END $$;
SELECT 'before' AS stage, * FROM mairui_before
UNION ALL SELECT 'after', * FROM mairui_after;
SELECT candidates, inserted, skipped FROM load_counts;
COMMIT;

-- T-B143：离线 CSV 只追加加载；调用方先审核 summary.json，拒绝包不得加载。
-- 用法：psql -v csvdir=/服务端可读的导出目录 -f tb143_load.sql
-- 三个 CSV 都为 UTF-8、带表头；COPY 在服务端读文件，需相应文件读取权限。
-- --before 只是导出时避让回填窗口的可选过滤；这里不设契约截止日。
\set ON_ERROR_STOP on
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
-- 阻止并发目录登记绕过同键 SHA 检查；不阻止读取。
LOCK TABLE market.minute_file_catalog IN SHARE ROW EXCLUSIVE MODE;
-- 麦蕊回填并行时保持前后校验处于同一快照，避免把其他事务的新行当成污染。
-- 日线只追加且 ON CONFLICT DO NOTHING，不阻塞整张日线表。
CREATE TEMP TABLE day_stage (
  code text, trade_date date, adj_type text CHECK (adj_type = 'none'),
  open numeric, high numeric, low numeric, close numeric, volume numeric, amount numeric
) ON COMMIT DROP;
CREATE TEMP TABLE gbbq_stage (
  code text, ex_date date, cash_per_share numeric, rights_price numeric,
  bonus_ratio numeric, rights_ratio numeric, source text, snapshot_sha256 text
) ON COMMIT DROP;
CREATE TEMP TABLE catalog_stage (
  source text, code text, kind text, date_from date, date_to date, rel_path text,
  sha256 text, row_count bigint, splice_segment text, generator text
) ON COMMIT DROP;
\set day_csv :csvdir '/daily_bars.csv'
\set gbbq_csv :csvdir '/ex_rights_events.csv'
\set catalog_csv :csvdir '/minute_file_catalog.csv'
COPY day_stage FROM :'day_csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
COPY gbbq_stage FROM :'gbbq_csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
COPY catalog_stage FROM :'catalog_csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');

CREATE TEMP VIEW mairui_signature AS
  SELECT count(*) AS n,
    md5(coalesce(string_agg(
      jsonb_build_array(code, trade_date, close, volume, amount)::text,
      ',' ORDER BY code, trade_date, adj_type), '')) AS digest
  FROM market.daily_bars WHERE source = 'mairui';
CREATE TEMP TABLE mairui_before ON COMMIT DROP AS SELECT * FROM mairui_signature;
CREATE TEMP TABLE load_counts (
  target text, year integer, inserted bigint, skipped bigint
) ON COMMIT DROP;
DO $$
DECLARE
  yr integer;
  n bigint;
  total bigint;
BEGIN
  IF EXISTS (
    SELECT 1 FROM catalog_stage a JOIN catalog_stage b
      USING (source, code, kind, rel_path) WHERE a.sha256 IS DISTINCT FROM b.sha256
  ) OR EXISTS (
    SELECT 1 FROM catalog_stage s JOIN market.minute_file_catalog m
      USING (source, code, kind, rel_path) WHERE s.sha256 IS DISTINCT FROM m.sha256
  ) THEN
    RAISE EXCEPTION '目录同键 SHA256 不同，拒绝登记';
  END IF;
  -- 每年执行一条 INSERT，所有年份仍处于同一个事务。
  FOR yr IN SELECT DISTINCT extract(year FROM trade_date)::integer FROM day_stage ORDER BY 1
  LOOP
    SELECT count(*) INTO total FROM day_stage
      WHERE trade_date >= make_date(yr, 1, 1) AND trade_date < make_date(yr + 1, 1, 1);
    INSERT INTO market.daily_bars (
      code, trade_date, adj_type, open, high, low, close, volume, amount,
      source, pre_close, is_suspended, source_licence_id, fetched_at
    )
    SELECT code, trade_date, adj_type, open, high, low, close, volume, amount,
      'tdx_local', NULL, NULL, NULL, now()
    FROM day_stage
    WHERE trade_date >= make_date(yr, 1, 1) AND trade_date < make_date(yr + 1, 1, 1)
    ON CONFLICT (code, trade_date, adj_type) DO NOTHING;
    GET DIAGNOSTICS n = ROW_COUNT;
    INSERT INTO load_counts VALUES ('daily_bars', yr, n, total - n);
  END LOOP;
  INSERT INTO market.ex_rights_events (
    code, ex_date, cash_per_share, rights_price, bonus_ratio, rights_ratio, source, snapshot_sha256
  ) SELECT code, ex_date, cash_per_share, rights_price, bonus_ratio, rights_ratio, source, snapshot_sha256
    FROM gbbq_stage
    ON CONFLICT (code, ex_date, snapshot_sha256) DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  INSERT INTO load_counts VALUES ('ex_rights_events', NULL, n, (SELECT count(*) FROM gbbq_stage) - n);
  INSERT INTO market.minute_file_catalog (
    source, code, kind, date_from, date_to, rel_path, sha256, row_count, splice_segment, generator
  ) SELECT source, code, kind, date_from, date_to, rel_path, sha256, row_count, splice_segment, generator
    FROM catalog_stage
    ON CONFLICT (source, code, kind, rel_path) DO NOTHING;
  GET DIAGNOSTICS n = ROW_COUNT;
  INSERT INTO load_counts VALUES ('minute_file_catalog', NULL, n, (SELECT count(*) FROM catalog_stage) - n);
END $$;
CREATE TEMP TABLE mairui_after ON COMMIT DROP AS SELECT * FROM mairui_signature;
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM mairui_before b CROSS JOIN mairui_after a
    WHERE b.n IS DISTINCT FROM a.n OR b.digest IS DISTINCT FROM a.digest
  ) THEN
    RAISE EXCEPTION '麦蕊行前后摘要改变，整次导入回滚';
  END IF;
END $$;
SELECT 'before' AS stage, * FROM mairui_before
UNION ALL SELECT 'after', * FROM mairui_after;
SELECT * FROM load_counts ORDER BY target, year;
COMMIT;

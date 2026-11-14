-- gbbq + 目录单独加载；与日线脚本互不调用。
-- psql -v csvdir=/服务端可读的导出目录 -f tb143_load_meta.sql
\set ON_ERROR_STOP on
BEGIN;
-- 串行化目录登记，防止并发检查均通过后写入重叠条目。
LOCK TABLE market.minute_file_catalog IN SHARE ROW EXCLUSIVE MODE;
CREATE TEMP TABLE gbbq_stage (
  code text, ex_date date, cash_per_share numeric, rights_price numeric,
  bonus_ratio numeric, rights_ratio numeric, source text, snapshot_sha256 text
) ON COMMIT DROP;
CREATE TEMP TABLE catalog_stage (
  source text, code text, kind text, date_from date, date_to date, rel_path text,
  sha256 text, row_count bigint, splice_segment text, generator text
) ON COMMIT DROP;
\set gbbq_csv :csvdir '/ex_rights_events.csv'
\set catalog_csv :csvdir '/minute_file_catalog.csv'
COPY gbbq_stage FROM :'gbbq_csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
COPY catalog_stage FROM :'catalog_csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8');
-- 定稿 8b32fcf §3.3：DS splice HF_END=08-06、SINGLE_DAY=08-07、MAIN_START=08-10。
-- vipdoc_1m 合并 SINGLE_DAY 与 MAIN_START 起的主段，lc5 不限日期。
CREATE TEMP VIEW catalog_effective AS
  SELECT source, code, kind, rel_path, first_day, last_day FROM (
    SELECT source, code, kind, rel_path,
      CASE WHEN splice_segment = 'vipdoc_1m'
        THEN greatest(date_from, DATE '2026-08-07') ELSE date_from END AS first_day,
      CASE WHEN splice_segment = 'hf_1m'
        THEN least(date_to, DATE '2026-08-06') ELSE date_to END AS last_day
    FROM (
      SELECT source, code, kind, rel_path, date_from, date_to, splice_segment FROM catalog_stage
      UNION
      SELECT source, code, kind, rel_path, date_from, date_to, splice_segment
        FROM market.minute_file_catalog
    ) entries
  ) ranges WHERE first_day <= last_day;
CREATE TEMP TABLE load_counts (target text, candidates bigint, inserted bigint, skipped bigint)
  ON COMMIT DROP;
DO $$
DECLARE
  v_inserted bigint;
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
  IF EXISTS (
    SELECT 1 FROM catalog_effective a JOIN catalog_effective b USING (code, kind)
    WHERE (a.source, a.rel_path) <> (b.source, b.rel_path)
      AND greatest(a.first_day, b.first_day) <= least(a.last_day, b.last_day)
  ) THEN
    RAISE EXCEPTION '目录有效区间重叠，拒绝登记';
  END IF;
  INSERT INTO market.ex_rights_events (
    code, ex_date, cash_per_share, rights_price, bonus_ratio, rights_ratio, source, snapshot_sha256
  ) SELECT s.code, s.ex_date, s.cash_per_share, s.rights_price, s.bonus_ratio, s.rights_ratio,
      s.source, s.snapshot_sha256
    FROM gbbq_stage AS s
    ON CONFLICT (code, ex_date, snapshot_sha256) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  INSERT INTO load_counts
    SELECT 'ex_rights_events', count(*), v_inserted, count(*) - v_inserted FROM gbbq_stage AS s;
  INSERT INTO market.minute_file_catalog (
    source, code, kind, date_from, date_to, rel_path, sha256, row_count, splice_segment, generator
  ) SELECT s.source, s.code, s.kind, s.date_from, s.date_to, s.rel_path, s.sha256, s.row_count,
      s.splice_segment, s.generator
    FROM catalog_stage AS s
    ON CONFLICT (source, code, kind, rel_path) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  INSERT INTO load_counts
    SELECT 'minute_file_catalog', count(*), v_inserted, count(*) - v_inserted FROM catalog_stage AS s;
END $$;
SELECT * FROM load_counts ORDER BY target;
COMMIT;

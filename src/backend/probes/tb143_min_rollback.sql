-- T-B143 分钟线格式验证：1 只股票 .lc1/.lc5 在事务里写入 minute_bars/minute5_bars 后整体 ROLLBACK。
-- 用法：psql -v lc1=<CSV> -v lc5=<CSV> -f 本文件。只验证列类型/约束/主键与写入速率，不留任何行。
\set ON_ERROR_STOP on
\pset footer off
\timing on
BEGIN;
CREATE TEMP TABLE m1 (code text, ts timestamptz, open numeric, high numeric, low numeric,
  close numeric, volume numeric, amount numeric) ON COMMIT DROP;
CREATE TEMP TABLE m5 (LIKE m1) ON COMMIT DROP;
COPY m1 FROM :'lc1' WITH (FORMAT csv, HEADER true);
COPY m5 FROM :'lc5' WITH (FORMAT csv, HEADER true);
WITH ins AS (INSERT INTO market.minute_bars (code, ts, open, high, low, close, volume, amount, source)
  SELECT code, ts, open, high, low, close, volume, amount, 'tdx_local' FROM m1
  ON CONFLICT DO NOTHING RETURNING 1) SELECT count(*) AS lc1_inserted, (SELECT count(*) FROM m1) AS lc1_rows FROM ins;
WITH ins AS (INSERT INTO market.minute5_bars (code, ts, open, high, low, close, volume, amount, source)
  SELECT code, ts, open, high, low, close, volume, amount, 'tdx_local' FROM m5
  ON CONFLICT DO NOTHING RETURNING 1) SELECT count(*) AS lc5_inserted, (SELECT count(*) FROM m5) AS lc5_rows FROM ins;
SELECT code, min(ts) AT TIME ZONE 'Asia/Shanghai' AS first_bj, max(ts) AT TIME ZONE 'Asia/Shanghai' AS last_bj,
       count(*) FILTER (WHERE (ts AT TIME ZONE 'Asia/Shanghai')::time = '09:31') AS bars_0931,
       count(DISTINCT (ts AT TIME ZONE 'Asia/Shanghai')::date) AS days
FROM market.minute_bars WHERE source = 'tdx_local' GROUP BY code;
-- 与已入库麦蕊日线同日对算：1 分钟量之和 vs 日量、末根收盘 vs 日收盘
WITH d AS (SELECT (ts AT TIME ZONE 'Asia/Shanghai')::date AS day, sum(volume) AS v,
                  (array_agg(close ORDER BY ts DESC))[1] AS c
           FROM market.minute_bars WHERE source = 'tdx_local' GROUP BY 1)
SELECT count(*) AS days_vs_mairui, count(*) FILTER (WHERE d.c = b.close) AS close_eq,
       count(*) FILTER (WHERE d.v = b.volume) AS vol_eq,
       round(max(abs(d.v - b.volume) / nullif(b.volume, 0)), 6) AS max_vol_rel_diff
FROM d JOIN market.daily_bars b ON b.code = :'code' AND b.trade_date = d.day AND b.source = 'mairui' AND b.adj_type = 'none';
SELECT pg_size_pretty(sum(pg_total_relation_size(format('%I.%I', chunk_schema, chunk_name)::regclass))) AS minute_chunks_size_in_tx
FROM timescaledb_information.chunks WHERE hypertable_name = 'minute_bars';
ROLLBACK;
SELECT (SELECT count(*) FROM market.minute_bars) AS minute_rows_after, (SELECT count(*) FROM market.minute5_bars) AS minute5_rows_after;

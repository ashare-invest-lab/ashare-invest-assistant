-- T-B143 小样本：通达信日线（tdx_local）与麦蕊同日 none 行逐字段对算，并只追加截止日 D 及以前的行。
-- 用法（在 postgres 容器内，服务端 COPY 读容器内文件，需 pg_read_server_files）：psql -v csv=<容器内CSV> -v until=2023-11-10 -v exclude=<逗号分隔整文件拒绝代码> -f 本文件
-- 口径：daily-bars-tdx.md §2（source=tdx_local、adj none、DO NOTHING）、§3.4（D=麦蕊回填起点前一开市日，
--       重叠期只核对不写入）、§5（OHLC 到分相等、量相等、额容差 max(1, |麦蕊|*2.4e-7)）。
-- 绝不 UPDATE/DELETE；麦蕊行前后 count + md5 校验。
\set ON_ERROR_STOP on
\pset footer off
CREATE TEMP TABLE tdx_s (code text, trade_date date, open numeric, high numeric, low numeric,
  close numeric, volume numeric, amount numeric);
COPY tdx_s FROM :'csv' WITH (FORMAT csv, HEADER true);
SELECT now() AS t0 \gset
CREATE TEMP TABLE s_codes AS SELECT DISTINCT code FROM tdx_s;
CREATE TEMP VIEW mairui_sig AS
  SELECT count(*) AS n, md5(coalesce(string_agg(concat_ws('|', code, trade_date, adj_type, open, high, low,
         close, volume, amount, pre_close, is_suspended, source, source_licence_id, fetched_at), ','
         ORDER BY code, trade_date, adj_type), '')) AS h
  FROM market.daily_bars WHERE source = 'mairui' AND code IN (SELECT code FROM s_codes);
\echo == before
SELECT n AS mairui_rows_sample, h AS mairui_md5_sample FROM mairui_sig;
SELECT count(*) AS mairui_rows_total FROM market.daily_bars WHERE source = 'mairui';
SELECT count(*) AS tdx_local_rows_total FROM market.daily_bars WHERE source = 'tdx_local';

CREATE TEMP TABLE j AS
  SELECT t.code, t.trade_date, t.open, t.high, t.low, t.close, t.volume, t.amount,
         m.open AS m_open, m.high AS m_high, m.low AS m_low, m.close AS m_close,
         m.volume AS m_volume, m.amount AS m_amount
  FROM tdx_s t JOIN market.daily_bars m USING (code, trade_date)
  WHERE m.adj_type = 'none' AND m.source = 'mairui';
CREATE TEMP TABLE diffs AS
  SELECT code, trade_date, f.field, f.tv, f.mv, abs(f.tv - f.mv) AS d,
         CASE WHEN f.field = 'amount' THEN abs(f.tv - f.mv) <= greatest(1, abs(f.mv) * 2.4e-7)
              ELSE f.tv = f.mv END AS ok
  FROM j, LATERAL (VALUES ('open', open, m_open), ('high', high, m_high), ('low', low, m_low),
       ('close', close, m_close), ('volume', volume, m_volume), ('amount', amount, m_amount)) AS f(field, tv, mv);
\echo == overlap per field
SELECT field, count(*) AS n, count(*) FILTER (WHERE ok) AS ok,
       round(100.0 * count(*) FILTER (WHERE ok) / nullif(count(*), 0), 3) AS ok_pct,
       max(d) AS max_abs_diff,
       round(max(CASE WHEN mv <> 0 THEN d / abs(mv) END), 8) AS max_rel_diff
FROM diffs GROUP BY field ORDER BY field;
\echo == overlap per code (mismatch keys)
SELECT code, count(DISTINCT trade_date) AS keys,
       count(DISTINCT trade_date) FILTER (WHERE NOT ok) AS mismatch_keys,
       string_agg(DISTINCT field, ',') FILTER (WHERE NOT ok) AS fields
FROM diffs GROUP BY code ORDER BY code;
\echo == mismatch samples (top 5 per field by abs diff)
SELECT field, code, trade_date, tv AS tdx, mv AS mairui, d AS abs_diff FROM (
  SELECT *, row_number() OVER (PARTITION BY field ORDER BY d DESC, code, trade_date) AS rn
  FROM diffs WHERE NOT ok) x WHERE rn <= 5 ORDER BY field, rn;
\echo == one-side-only within overlap window (codes having mairui rows)
WITH w AS (SELECT min(trade_date) AS lo FROM market.daily_bars WHERE source = 'mairui'),
     hi AS (SELECT max(trade_date) AS hi FROM tdx_s)
SELECT s.code,
  (SELECT count(*) FROM tdx_s t, w, hi WHERE t.code = s.code AND t.trade_date BETWEEN w.lo AND hi.hi) AS tdx_days,
  (SELECT count(*) FROM market.daily_bars m, w, hi WHERE m.code = s.code AND m.source = 'mairui'
     AND m.adj_type = 'none' AND m.trade_date BETWEEN w.lo AND hi.hi) AS mairui_days,
  (SELECT count(*) FROM j WHERE j.code = s.code) AS both_days
FROM s_codes s ORDER BY s.code;

\echo == append tdx_local rows with trade_date <= until (ON CONFLICT DO NOTHING)
BEGIN;
CREATE TEMP TABLE cand AS
  SELECT * FROM tdx_s WHERE trade_date <= :'until'::date
    AND code <> ALL (string_to_array(:'exclude', ','));
SELECT count(*) AS candidates, count(DISTINCT code) AS codes, min(trade_date), max(trade_date) FROM cand;
WITH ins AS (
  INSERT INTO market.daily_bars (code, trade_date, adj_type, open, high, low, close, volume, amount, source)
  SELECT code, trade_date, 'none', open, high, low, close, volume, amount, 'tdx_local' FROM cand
  ON CONFLICT DO NOTHING RETURNING 1)
SELECT count(*) AS inserted, (SELECT count(*) FROM cand) - count(*) AS skipped_on_conflict FROM ins;
COMMIT;

\echo == after
SELECT n AS mairui_rows_sample, h AS mairui_md5_sample FROM mairui_sig;
SELECT count(*) AS mairui_rows_sample_pre_t0, md5(coalesce(string_agg(concat_ws('|', code, trade_date, adj_type,
       open, high, low, close, volume, amount, pre_close, is_suspended, source, source_licence_id, fetched_at), ','
       ORDER BY code, trade_date, adj_type), '')) AS mairui_md5_sample_pre_t0
  FROM market.daily_bars WHERE source = 'mairui' AND code IN (SELECT code FROM s_codes) AND fetched_at < :'t0';
SELECT count(*) AS mairui_rows_total FROM market.daily_bars WHERE source = 'mairui';
SELECT code, count(*) AS tdx_local_rows, min(trade_date), max(trade_date)
FROM market.daily_bars WHERE source = 'tdx_local' GROUP BY code ORDER BY code;

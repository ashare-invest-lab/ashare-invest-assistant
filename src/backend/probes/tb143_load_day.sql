-- 每次仅加载一年的 CSV，每次调用独立提交；本脚本不调用元数据加载脚本。
-- psql -v csv=/服务端可读/day_2022.csv -v before=2023-01-01 -f tb143_load_day.sql
-- 默认跳过未确认 BJ，计入 skipped，沪深照常提交；不接受 confirmed 布尔参数。
-- 需放行时，在本 psql 会话先按下列结构创建并填充 TEMP tb143_bj_volume_pairs。
-- mairui_* 为离线原始 code/t/v；其余列为本地 code/trade_date/volume/source。
-- 排除停牌及零量后，共同单日至少 20 个不同合法 .BJ 码；同码同日、source=tdx_local，
-- 全部对照通过才允许写 BJ（不限样本码）。每次重新校验；新会话须重新提供对照。
\set ON_ERROR_STOP on
BEGIN;
SET TRANSACTION ISOLATION LEVEL REPEATABLE READ;
CREATE TEMP TABLE IF NOT EXISTS pg_temp.tb143_bj_volume_pairs (
  mairui_code text, mairui_t date, mairui_v numeric,
  code text, trade_date date, volume numeric, source text
) ON COMMIT PRESERVE ROWS;
ALTER TABLE pg_temp.tb143_bj_volume_pairs
  ADD COLUMN IF NOT EXISTS mairui_sf text,
  ADD COLUMN IF NOT EXISTS is_suspended text;
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
CREATE TEMP TABLE load_counts (
  candidates bigint, inserted bigint, skipped bigint, blocked_bj bigint
) ON COMMIT DROP;
DO $$
DECLARE
  v_inserted bigint;
  v_total bigint;
  v_blocked_bj bigint;
  v_bj_confirmed boolean;
BEGIN
  IF (SELECT b.n FROM mairui_before AS b) <> 0 THEN
    RAISE EXCEPTION 'before 之前已有麦蕊行，拒绝加载';
  END IF;
  SELECT count(*) INTO v_total FROM day_stage AS s;
  -- 不保存可复用的确认位；对照不足或任意一项不符（含 NULL）均关闭门闩。
  WITH pairs AS (
    SELECT p.*, (p.mairui_v = 0 OR p.volume = 0
      OR coalesce(lower(p.mairui_sf::text) IN ('1', 'true'), false)
      OR coalesce(lower(p.is_suspended::text) IN ('1', 'true'), false)) AS excluded
    FROM pg_temp.tb143_bj_volume_pairs AS p
  )
  SELECT EXISTS (SELECT 1 FROM pairs WHERE NOT excluded AND mairui_v > 0 AND volume > 0
    GROUP BY trade_date HAVING count(DISTINCT code) >= 20)
    AND coalesce(bool_and(coalesce(
    p.code ~ '^(43[0-9]|83[0-9]|87[0-9]|920)[0-9]{3}[.]BJ$'
    AND p.mairui_code = p.code AND p.mairui_t = p.trade_date
    AND isfinite(p.mairui_t) AND isfinite(p.trade_date)
    AND p.source = 'tdx_local'
    AND p.mairui_v::text NOT IN ('NaN', 'Infinity', '-Infinity')
    AND p.volume::text NOT IN ('NaN', 'Infinity', '-Infinity')
    AND p.mairui_v >= 0 AND p.volume >= 0
    AND (p.excluded OR (p.volume = trunc(p.volume) AND p.mairui_v * 100 = p.volume)),
    false)), false)
  INTO v_bj_confirmed FROM pairs AS p;
  SELECT count(*) INTO v_blocked_bj FROM day_stage AS s
  WHERE NOT v_bj_confirmed AND (
    s.code ~ '[.]BJ$' OR s.code ~ '^(43[0-9]|83[0-9]|87[0-9]|920)[0-9]{3}'
  );
  INSERT INTO market.daily_bars (
    code, trade_date, adj_type, open, high, low, close, volume, amount,
    source, pre_close, is_suspended, source_licence_id, fetched_at
  )
  SELECT s.code, s.trade_date, s.adj_type, s.open, s.high, s.low, s.close, s.volume, s.amount,
    'tdx_local', NULL, NULL, NULL, now()
  FROM day_stage AS s
  WHERE v_bj_confirmed OR NOT coalesce((
    s.code ~ '[.]BJ$'
    OR s.code ~ '^(43[0-9]|83[0-9]|87[0-9]|920)[0-9]{3}'
  ), false)
  ON CONFLICT (code, trade_date, adj_type) DO NOTHING;
  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  INSERT INTO load_counts VALUES (v_total, v_inserted, v_total - v_inserted, v_blocked_bj);
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
SELECT 'blocked_bj_unconfirmed' AS reason, blocked_bj FROM load_counts;
COMMIT;

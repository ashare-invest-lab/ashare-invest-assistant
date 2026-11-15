-- 仅校验临时 staging；目标表必须由 app.marketdata.daily_bars 公共 writer 写入。
-- psql 不持有 Python 进程许可；不读取或恢复任何 BJ 确认产物。
-- 调用方必须开启事务，并在公共 writer 完成后提交。
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
-- staging 不代表完成；skipped / blocked 由 Python 公共 writer 返回。

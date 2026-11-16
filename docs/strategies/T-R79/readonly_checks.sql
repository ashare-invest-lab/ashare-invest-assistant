-- 草稿，未执行；仅供运维在本地栈只读执行，执行需另行授权
-- T-R79c：独立 SELECT/WITH 草稿；本单没有连接数据库或执行本文件。
-- 参数须由运维绑定，不拼接：:code、:date_from、:date_to、:as_of、:source、
-- :observation_snapshot_id、:result_snapshot_id、:suggestion_id。
-- 日期窗口含两端；:as_of 是带时区时间，绑定所审计修订冻结的实际运行/补算时点。
-- 快照/建议标识只可绑定另行授权范围内的本地对象；不输出账户、持仓或快照全文。
-- 缺行、空集、NULL、类型转换失败均不能判作通过；先确认目标对象/日历覆盖。
-- JSON 路径来自 service.py:98-116,246-254,346-358 及 models.py:14-38，
-- 均在 src/backend/app/tracking/ 下；JSON 键不是新增表列。
-- SQL 只检查当前库存及已有快照，不能证明历史首次可见、修订历史或真实可成交。

-- Q01 / U04：列出窗口权息事件版本及事件日原始行情/停牌标志，供逐项对账。
-- 表列：src/backend/migrations/versions/0036_tb143_ex_rights_minute_catalog.py:16-35；
-- src/backend/app/db/tables/market.py:390-405（全部事件列）。
-- 行情表列：src/backend/migrations/versions/0001_baseline.py:502-515；
-- src/backend/migrations/versions/0032_tb127_daily_bars_source_columns.py:32-34；
-- src/backend/app/db/tables/market.py:362-385（code/trade_date/adj_type/OHLC/source/is_suspended/fetched_at）。
-- 判读：应与获准使用的逐事件清单、因子快照一致；空集须区分无事件与漏采。
-- 同日多个 snapshot_sha256 需核修订来源，不自动选最新版；registered_at 不等于 available_at。
-- NULL 停牌标志/缺行情只代表未知；不能推断停牌、可成交，不能据此重建因子。
-- registered_at晚于:as_of的事件仅供发现迟到登记，不得倒填为截止前已知事件。
SELECT e.ex_date, e.cash_per_share, e.rights_price, e.bonus_ratio, e.rights_ratio,
       e.source AS event_source, e.snapshot_sha256, e.registered_at,
       b.open, b.high, b.low, b.close, b.is_suspended,
       b.source AS bar_source, b.fetched_at
FROM market.ex_rights_events AS e
LEFT JOIN market.daily_bars AS b
  ON b.code = e.code AND b.trade_date = e.ex_date AND b.adj_type = 'none'
 AND b.fetched_at <= CAST(:as_of AS timestamptz)
WHERE e.code = :code
  AND e.ex_date BETWEEN CAST(:date_from AS date) AND CAST(:date_to AS date)
ORDER BY e.ex_date, e.registered_at, e.snapshot_sha256;

-- Q02 / U04：核对指定观测快照内因子/事实数量、时点及缺失可成交字段。
-- 表列：src/backend/migrations/versions/0001_baseline.py:316-325；
-- src/backend/app/db/tables/reviews.py:23-31,55（id/created_at/purpose/items/hash）。
-- JSON 结构/可见性：src/backend/app/tracking/service.py:98-116,246-254；
-- src/backend/app/features/pipeline.py:151-164；事实键：tracking/engine.py:198-234。
-- 判读：快照应恰好一行且 payload_present=true；因子数须满足两端锚定需要，
-- missing_factor_fields / nonpositive_factors 应为0；future_* 可为正，但必须被引擎过滤。
-- missing_fact_fields盘点三类事实；按原动作所需键复核，不能因未用键缺失新增阻断规则。
-- facts 数须与需要事实的日期清单对账；本查询不查 holdings，不证明 forced_hold 接线。
-- 快照建立时刻须另行与截止对账；本条只检查因子/事实自己的可见时点。
-- 空值/非法数字日期须人工排查；本查询不重算 qfq，也不验证复杂权息因子经济含义。
WITH obs AS (
    SELECT items -> 'instruments' -> CAST(:code AS text) AS payload
    FROM app.data_snapshots
    WHERE id = CAST(:observation_snapshot_id AS uuid)
      AND purpose = 'report'
      AND items ->> 'schema_version' = 'p2n03-market-observations-v1'
), factors AS (
    SELECT f.value AS item
    FROM obs CROSS JOIN LATERAL jsonb_array_elements(obs.payload -> 'factors') AS f(value)
), facts AS (
    SELECT f.key AS fact_date, f.value AS item
    FROM obs CROSS JOIN LATERAL jsonb_each(obs.payload -> 'facts') AS f(key, value)
)
SELECT (SELECT count(*) FROM obs) AS snapshot_rows,
       (SELECT payload IS NOT NULL FROM obs) AS payload_present,
       (SELECT count(*) FROM factors) AS factor_count,
       (SELECT count(*) FROM factors WHERE item ->> 'date' IS NULL
          OR item ->> 'available_at' IS NULL OR item ->> 'value' IS NULL) AS missing_factor_fields,
       (SELECT count(*) FROM factors WHERE CAST(item ->> 'value' AS numeric) <= 0
          OR item ->> 'value' IN ('NaN', 'Infinity', '-Infinity')) AS nonpositive_factors,
       (SELECT count(*) FROM factors
        WHERE CAST(item ->> 'available_at' AS timestamptz) > CAST(:as_of AS timestamptz)
           OR CAST(item ->> 'date' AS date) > CAST(:date_to AS date)) AS future_factors,
       (SELECT count(*) FROM facts) AS fact_dates,
       (SELECT count(*) FROM facts WHERE item ->> 'available_at' IS NULL
          OR (jsonb_typeof(item -> 'values' -> 'is_suspended') IS DISTINCT FROM 'boolean')
          OR (jsonb_typeof(item -> 'values' -> 'limit_locked_up') IS DISTINCT FROM 'boolean')
          OR (jsonb_typeof(item -> 'values' -> 'limit_locked_down') IS DISTINCT FROM 'boolean')) AS missing_fact_fields,
       (SELECT count(*) FROM facts
        WHERE CAST(item ->> 'available_at' AS timestamptz) > CAST(:as_of AS timestamptz)
           OR CAST(fact_date AS date) > CAST(:date_to AS date)) AS future_facts;

-- Q03 / U05：检查当前 none 日线窗口来源组合及 fetched_at 范围。
-- 表列：src/backend/migrations/versions/0001_baseline.py:502-515；
-- src/backend/migrations/versions/0032_tb127_daily_bars_source_columns.py:32-34；
-- src/backend/migrations/versions/0033_tb133_daily_bars_tdx_local.py:32-38（来源枚举扩展）；
-- src/backend/app/db/tables/market.py:362-385。
-- 判读：应有且仅有一个非空来源分组、天数与Q04已核日历相符；多源或NULL提示不能作单源快照。
-- fetched_at 不同本身不违规；当前主键不保留每次修订，单一来源也不证明 data_version/hash 重放。
SELECT source, count(*) AS bar_count, min(trade_date) AS first_day,
       max(trade_date) AS last_day, min(fetched_at) AS earliest_fetch,
       max(fetched_at) AS latest_fetch
FROM market.daily_bars
WHERE code = :code AND adj_type = 'none'
  AND trade_date BETWEEN CAST(:date_from AS date) AND CAST(:date_to AS date)
  AND fetched_at <= CAST(:as_of AS timestamptz)
GROUP BY source
ORDER BY source;

-- Q04 / U06：按库存日历核对指定来源整窗OHLC；是覆盖诊断，D03已裁定端点与完整性分开。
-- 日历表列：src/backend/migrations/versions/0001_baseline.py:650-654；
-- src/backend/app/db/tables/market.py:354-359。
-- 行情表列同Q03，OHLC：0001_baseline.py:506-509；market.py:368-371。
-- 判读：calendar_days应等于自然日跨度+1，open_days>0且missing_or_invalid_bars=0。
-- calendar_days不足/窗口反向/零开市日均不能通过；日历覆盖完整也不证明其来源或版本正确。
-- 开市日缺行、非正、非有限或OHLC关系错误计异常；fetched_at不能证明首次可见/定稿。
WITH days AS (
    SELECT date, is_open FROM market.trading_calendar
    WHERE date BETWEEN CAST(:date_from AS date) AND CAST(:date_to AS date)
), covered AS (
    SELECT d.date,
           b.code IS NOT NULL
           AND b.open > 0 AND b.high > 0 AND b.low > 0 AND b.close > 0
           AND b.open::text NOT IN ('NaN', 'Infinity', '-Infinity')
           AND b.high::text NOT IN ('NaN', 'Infinity', '-Infinity')
           AND b.low::text NOT IN ('NaN', 'Infinity', '-Infinity')
           AND b.close::text NOT IN ('NaN', 'Infinity', '-Infinity')
           AND b.low <= b.open AND b.open <= b.high
           AND b.low <= b.close AND b.close <= b.high AS valid_bar
    FROM days AS d
    LEFT JOIN market.daily_bars AS b
      ON b.trade_date = d.date AND b.code = :code AND b.adj_type = 'none'
     AND b.source = :source AND b.fetched_at <= CAST(:as_of AS timestamptz)
    WHERE d.is_open
)
SELECT (SELECT count(*) FROM days) AS calendar_days,
       CAST(:date_to AS date) - CAST(:date_from AS date) + 1 AS expected_calendar_days,
       count(*) AS open_days,
       count(*) FILTER (WHERE valid_bar IS DISTINCT FROM true) AS missing_or_invalid_bars,
       array_agg(date ORDER BY date) FILTER (WHERE valid_bar IS DISTINCT FROM true) AS anomaly_dates
FROM covered;

-- Q05 / U05/U10：核对指定结果快照的版本/摘要/原输入结构是否存在。
-- 表列：src/backend/migrations/versions/0001_baseline.py:316-325；
-- src/backend/app/db/tables/reviews.py:23-31,55；JSON：tracking/service.py:346-358。
-- 判读：应恰一行，schema_matches=true且算法/as_of/观测引用/摘要均有值。
-- 当前raw_benchmark通常无source/data_version；缺这些仍是未验证，不能以外层hash代替来源版本。
-- hash_shape_ok只检查形状；摘要真值须按service.py:34-39的Python canonical算法另行核对。
-- 即使结构齐备，也未验证日历版本、定稿、混源拒绝或同版重算。
SELECT items ->> 'schema_version' = 'p2n03-tracking-v1' AS schema_matches,
       items ->> 'algorithm_version' AS algorithm_version,
       items ->> 'as_of' AS as_of,
       items ->> 'observation_snapshot_id' IS NOT NULL AS has_observation_ref,
       items ->> 'observation_hash' IS NOT NULL AS has_observation_hash,
       hash ~ '^[0-9a-f]{64}$' AS hash_shape_ok,
       items -> 'raw_benchmark' ? 'source' AS has_benchmark_source,
       items -> 'raw_benchmark' ? 'data_version' AS has_benchmark_version,
       items ? 'calendar_version' AS has_calendar_version
FROM app.data_snapshots
WHERE id = CAST(:result_snapshot_id AS uuid) AND purpose = 'review';

-- Q06 / U10：每次绑定一版冻结结果快照，核对该次实际as_of及行情输入门禁。
-- 只读草稿，未执行；表列：0001_baseline.py:1914-1936,316-325；
-- 均在src/backend/migrations/versions/下；模型：src/backend/app/db/tables/
-- realtime.py:229-251、reviews.py:23-31,55；JSON键同Q05及tracking/service.py:55-95。
-- :result_snapshot_id逐次绑定首次评估/补算修订/旧版，不以当前时间替代快照as_of。
-- :suggestion_id限定建议；窗口按results中的horizon_days与持久化due_date匹配。
-- 判读：每个快照/窗口应恰一行，result_count>0且input_bar_count>0；
-- missing_*须false/0，unverified_*、future_*、after_due_bars均须为0，
-- 且as_of_timezone_verified=true，才满足本条行情门禁。
-- available_at、first_seen_at、as_of均须显式时区，按timestamptz瞬时比较，等号有效；
-- trade_date<=due_date(D_h)，as_of晚于到期日是合法补算，不据此拒绝。
-- 当前raw_stock/raw_benchmark通常没有available_at：报告未验证，不用first_seen_at代证。
-- 非法日期/时间导致转换失败即不能通过，不隐式补时区；只查字段不能证明时点来源真实。
-- 此处仅审计冻结包内股票/主基准日线；缺端点、final及来源版本另按R03/R09/R12核对，
-- 因子/事实见Q02；辅槽/分钟及未来扩展字段不假定已有schema，不据此宣称全输入通过。
-- current_container_status/computed_at仅作当前状态参照，不代表本版结果或历史冻结时点。
-- 混合终态容器须逐结果核对原冻结包，不能借另一unavailable的新as_of解冻终态。
-- 单次SELECT不证明五日逐日作业、旧版重放或冻结历史；须另行跨日审计，日历未知不推进5日。
-- 股票complete缺基准仍冻结、新增对照仅研究包；第5日作业具体钟点「未验证」。
WITH snapshot AS (
    SELECT id, items
    FROM app.data_snapshots
    WHERE id = CAST(:result_snapshot_id AS uuid) AND purpose = 'review'
      AND items ->> 'schema_version' = 'p2n03-tracking-v1'
), windows AS (
    SELECT s.id, s.items, t.horizon_days, t.due_date, t.status, t.computed_at,
           (SELECT count(*) FROM jsonb_array_elements(s.items -> 'results') AS r(value)
            WHERE CAST(r.value ->> 'horizon_days' AS integer) = t.horizon_days) AS result_count
    FROM snapshot AS s
    JOIN app.suggestion_tracking AS t
      ON t.suggestion_id = CAST(:suggestion_id AS uuid)
    WHERE EXISTS (
        SELECT 1 FROM jsonb_array_elements(s.items -> 'results') AS r(value)
        WHERE CAST(r.value ->> 'horizon_days' AS integer) = t.horizon_days
    )
), input_rows AS (
    SELECT s.id, b.value AS item
    FROM snapshot AS s
    CROSS JOIN LATERAL (
        SELECT value FROM jsonb_array_elements(s.items -> 'raw_stock' -> 'bars')
        UNION ALL
        SELECT value FROM jsonb_array_elements(s.items -> 'raw_benchmark' -> 'bars')
    ) AS b
), checked AS (
    SELECT w.*, i.item,
           w.items ->> 'as_of' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' AS as_of_has_zone,
           i.item ->> 'available_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' AS available_has_zone,
           i.item ->> 'first_seen_at' ~ '(Z|[+-][0-9]{2}:[0-9]{2})$' AS first_seen_has_zone
    FROM windows AS w LEFT JOIN input_rows AS i ON i.id = w.id
)
SELECT id AS result_snapshot_id, horizon_days, due_date,
       status AS current_container_status, computed_at, items ->> 'as_of' AS as_of,
       (items ->> 'as_of' IS NULL) AS missing_as_of,
       bool_and(as_of_has_zone IS TRUE) AS as_of_timezone_verified,
       due_date IS NULL AS missing_due_date, result_count,
       count(item) AS input_bar_count,
       count(*) FILTER (WHERE item ->> 'trade_date' IS NULL) AS missing_trade_dates,
       count(*) FILTER (WHERE available_has_zone IS DISTINCT FROM true) AS unverified_available_at,
       count(*) FILTER (WHERE first_seen_has_zone IS DISTINCT FROM true) AS unverified_first_seen_at,
       count(*) FILTER (WHERE CASE WHEN as_of_has_zone AND available_has_zone THEN
           CAST(item ->> 'available_at' AS timestamptz) > CAST(items ->> 'as_of' AS timestamptz)
           ELSE false END) AS future_available_at,
       count(*) FILTER (WHERE CASE WHEN as_of_has_zone AND first_seen_has_zone THEN
           CAST(item ->> 'first_seen_at' AS timestamptz) > CAST(items ->> 'as_of' AS timestamptz)
           ELSE false END) AS future_first_seen_at,
       count(*) FILTER (WHERE CAST(item ->> 'trade_date' AS date) > due_date) AS after_due_bars
FROM checked
GROUP BY id, horizon_days, due_date, status, computed_at, items, result_count
ORDER BY horizon_days;

-- Q07 / U12/U11：指定结果快照按策略版本/周期/基准分组重数，输出匿名计数、hold可用数。
-- 表列：src/backend/migrations/versions/0001_baseline.py:316-325；
-- src/backend/app/db/tables/reviews.py:23-31,55。
-- JSON字段：src/backend/app/tracking/models.py:14-32；service.py:330-358；api.py:72-120。
-- 判读：同一快照每组通常observations=1；主槽非空数不等于方向n，辅槽不应被冒充已接入。
-- 这里的单快照计数不替代API跨建议去重，不输出策略标识；不默认存在辅槽/metadata键。
-- hold_complete_with_excess只是样本可用性起点，不能校准1/2/5；仍须预先冻结真实样本，
-- 按策略版本/周期/市场状态分层，时间外留出并处理重叠窗口依赖，报告误判率/置信区间/敏感性。
WITH result_rows AS (
    SELECT r.value AS item
    FROM app.data_snapshots AS s
    CROSS JOIN LATERAL jsonb_array_elements(s.items -> 'results') AS r(value)
    WHERE s.id = CAST(:result_snapshot_id AS uuid) AND s.purpose = 'review'
      AND s.items ->> 'schema_version' = 'p2n03-tracking-v1'
)
SELECT item ->> 'horizon_days' AS horizon_days,
       item ->> 'benchmark_code' AS benchmark_code,
       count(*) AS observations,
       count(*) FILTER (WHERE item ->> 'state' = 'complete') AS complete_n,
       count(*) FILTER (WHERE item ->> 'state' = 'complete'
                         AND item ->> 'return_pct' IS NOT NULL) AS return_n,
       count(*) FILTER (WHERE item ->> 'state' = 'complete'
                         AND item ->> 'excess_pct' IS NOT NULL) AS excess_n,
       count(*) FILTER (WHERE item ->> 'state' = 'complete'
                         AND item ->> 'direction_correct' IS NOT NULL) AS direction_n,
       count(*) FILTER (WHERE item ->> 'action' = 'hold' AND item ->> 'state' = 'complete'
                         AND item ->> 'excess_pct' IS NOT NULL) AS hold_complete_with_excess
FROM result_rows
GROUP BY item ->> 'strategy_version_id', item ->> 'horizon_days', item ->> 'benchmark_code'
ORDER BY horizon_days, benchmark_code;

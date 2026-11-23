# origin/main 实时行情可用性缺口审查

基线为 `origin/main`（仅依据仓库内契约、实现和测试静态核对）。这里的“现状”描述主线已有行为，不把契约草案、合成夹具或 `xfail` 预期当作已验收能力。

| 缺口 | 契约条款或文件:行号出处 | 现状 | 建议归属角色 | 预计规模（S/M/L） |
|---|---|---|---|---|
| `/quotes` 没有实时优先读链 | `docs/contracts/T-A232-quote-semantics.md` §1.1、RT-03 验收；`src/backend/app/marketdata/quotes_read.py:86-131`；`tests/backend/unit/test_tt114_realtime_read_chain.py:583-595` | 读取器只查 `market.daily_bars`，不会读取 `quotes_snapshot`。测试用 `require_intraday_or_xfail` 表达目标行为，不能证明已接通。 | 后端读链 | M |
| `/quotes` 未统一捕获查询时点，且日线回落把 `fetched_at` 当 `data_as_of` | `docs/contracts/T-A232-quote-semantics.md` §1.1、§2.3；`src/backend/app/marketdata/quotes_read.py:37-64,86-129` | 读取器内部取当前时钟，日线项的 `data_as_of` 写入 `row.fetched_at`，不是可信行情时点 `t`。盘中、15:00、17:10、未来 `fetched_at` 的 PIT 验收未闭合。 | 后端读链 | M |
| 盘中采集字段和单位证据未闭合 | `docs/contracts/T-A209-market-wiring.md` §0.1、U8；`src/backend/app/marketdata/realtime_collect.py:56-67,154-170`；`tests/backend/unit/test_tb213_realtime_collect.py:280-300` | 字段映射注释明确标为未验证，采集器把 `is_suspended`、`limit_up`、`limit_down` 固定为 `None`。现有测试只验证合成字段保留，不能证明供应商字段、量额单位或停牌状态。 | 后端采集＋数据核验 | L |
| 没有生产 1 分钟实时 K 线采集和规范化链 | `docs/contracts/T-A209-market-wiring.md` §0.1 的“1分钟不复权”及 §0.3 入口验收；`src/backend/app/marketdata/realtime_collect.py:399-470`；`tests/backend/unit/test_tb213_realtime_collect.py:96-113` | 现有任务只规范化并写 `quotes_snapshot` 快照，未看到分钟请求、`minute_bars` 写入、迟到修订或完成判据。采集测试只覆盖快照任务。 | 后端采集 | L |
| 采集范围与市场概览范围不匹配 | `docs/contracts/T-A209-market-wiring.md` §0.3、§3.1；`src/backend/app/marketdata/realtime_collect.py:294-322`；`src/backend/app/aggregates/market_overview.py:418-437` | 采集器按每个用户的持仓和自选代码取数。市场概览按全体 SH/SZ/BJ 股票与指数代码选批，因而无法形成契约要求的同批全市场宽度和成交额。 | 后端采集＋聚合 | L |
| 快照批次缺少可审计的完成记录 | `docs/contracts/T-A209-market-wiring.md` §0.2、§0.3；`docs/contracts/T-A219-market-overview.md` §2、§3.1A；`src/backend/app/marketdata/realtime_collect.py:232-291,467-470` | 写入只产生 `quotes_snapshot` 行和 `batch_id`，没有来源完成事实、资格证据或批次完整性记录。概览虽按 `batch_id` 选批，却无法判定批次是否完成。 | 后端采集＋数据平台 | L |
| 市场概览无法满足指数、宽度和成交额的完整实时口径 | `docs/contracts/T-A219-market-overview.md` §2、§4、§5、§6；`src/backend/app/aggregates/market_overview.py:147-163,339-357,477-529` | 指数卡片只由证券主数据生成，实时字段依赖快照。缺少停牌、涨跌停或量额字段时主动产生 gap，且 BJ 默认剔除。由于上游快照范围和字段尚未闭合，不能每天给出完整概览。 | 后端聚合＋数据核验 | L |
| SSE 没有实时 `quote` 发布源 | `docs/contracts/T-A232-quote-semantics.md` §1.1、§2.5；`src/backend/app/api/v1/notifications.py:178-245`；`src/backend/app/notify/transport.py:35-83`；`tests/backend/unit/test_tt114_realtime_read_chain.py:653-724` | SSE 只从通知 Redis 缓冲重放通知事件和心跳。仓库未找到 `publish_quote` 或等价的实时行情事件生产者。测试构造合成 `quote` 事件并直接塞入 Redis，不能证明生产发布链。 | 后端事件与 SSE | M |
| SSE 工程参数未由配置统一驱动 | `docs/contracts/T-A230-realtime-params.md:30-37,43-47`；`src/backend/app/api/v1/notifications.py:205,223-239`；`src/backend/app/notify/transport.py:17-26,53-76` | 心跳 15 秒、重连 3000 毫秒、重放窗 600 秒写死在代码中，`config/realtime.yaml` 的对应键未被通知运行时读取。调整配置不能保证前后端同步。 | 后端平台＋前端 | S |
| `/terminal`、`/today` 尚未形成实时读链的逐入口 PIT 验收 | `docs/contracts/T-A232-quote-semantics.md` RT-03 验收；`src/backend/app/aggregates/service.py:88-103,119-130`；`tests/backend/unit/test_tt114_realtime_read_chain.py:305-320` | 终端复用 `read_quotes`，因此继承日线回落现状。测试对 `rc1` 盘中快照使用 `xfail` 兼容未合入实现，不能作为主线已完成证据。 | 后端聚合与风险读链 | M |
| 采集健康状态不能代表行情新鲜度和批次可用 | `docs/contracts/T-A209-market-wiring.md` §0.3；`src/backend/app/workers/ingest.py:95-125,157-217`；`docs/contracts/T-A230-realtime-params.md:35-38` | ingest 心跳持续写 Redis，实时任务失败只记录 warning 并保留心跳。状态没有把快照/分钟完成记录、队列错误和实际 freshness 绑定起来，可能出现“心跳正常但行情不可用”。 | 运维＋后端采集 | M |

## 结论

要达到“每天可用”，优先闭合实时快照读链、1 分钟 K 线、全市场批次完成记录和 SSE `quote` 发布。当前主线的合成测试覆盖了门闩和预期接口形状，但未覆盖这些生产闭环。

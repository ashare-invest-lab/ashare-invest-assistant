# T-A219：市场概览聚合后端契约

状态：实现契约草案。本文把现有 API 形状、主线表列和 T-R107（本地提交 `06b32d21`，PR #326）的保守结论接到 `app.aggregates.service.market`。未验证的供应商字段、覆盖率门槛和 F25/G-02 参数不生效。本文不授权真实麦蕊调用。

## 1. 范围、现状和响应形状

`GET /market/overview` 只读缓存，响应复用 §3 已有枚举、§4 已有错误码和 §5.1 的 `DataStatusBlock`。目标结构如下。

```text
MarketOverview {
  basis: MarketBasis | null
  trade_date: date
  session: market_session
  indices: MarketIndexQuote[]
  breadth: Breadth | null
  regime: market_regime | null
  regime_position_range: RegimePositionRange | null
  turnover_total: string(decimal) | null
  data_status: fresh | stale | partial | unavailable
  data_as_of: datetime | null
  gaps: Gap[]
}
MarketIndexQuote {
  security_code: string
  name: string
  price: string(decimal) | null
  change_pct: string(decimal) | null
  amount: string(decimal) | null
  t: datetime | null
}
Breadth {
  up: int | null
  down: int | null
  flat: int | null
  up_ratio: string(decimal) | null
  down_ratio: string(decimal) | null
  flat_ratio: string(decimal) | null
  limit_up: int | null
  limit_down: int | null
}
RegimePositionRange { min_pct: string(decimal), max_pct: string(decimal) }
```

`up_ratio`、`down_ratio`、`flat_ratio` 是 0 到 1 的比例，使用 Decimal 计算并序列化为字符串，例如 `"0.2500"`。它们不是百分数字符串。宽度分母为同一观察批次中合格、非停牌、成交量大于零且有完整比较字段的股票数。分母为零时宽度字段和比例均为 `null`。

主线现状是 `service.py:market(clock)` 固定返回空指数、空宽度、空 regime、空成交额和 `unavailable/no_source`。下文是目标契约，不把该函数现状写成已实现。

## 2. 字段来源和缺列

以下只引用当前代码中已经存在的表和列。表中未存在的列明确标为「须迁移，未验证」，后端不得用相邻字段猜值。

| 响应字段 | 盘中来源（`mode=intraday`） | 收盘来源（`mode=close`） | 计算与缺口 |
|---|---|---|---|
| `trade_date` | `market.trading_calendar.date/is_open`，由 `aggregates.calendar.market_clock` 决定 | 同左 | 不按自然日或工作日猜测。日历不覆盖使用既有 `503 CALENDAR_NOT_COVERED`。 |
| `session` | `trading_calendar.is_open` 加 `config/market_rules.yaml` 的时段解析 | 同左 | 时段缺规则使用既有 `503 MAINTENANCE`，不降级成普通交易时段。 |
| 指数代码、名称 | `market.securities.code/name`，且 `type='index'` | 同左 | 清单来自后端配置，配置只确定展示卡，不证明有行情。 |
| 指数 `price` | `market.quotes_snapshot.price` | `market.daily_bars.close`，`adj_type='none'` | 盘中行必须有 `source='mairui'` 且绑定本人证书。当前 `quotes_snapshot` 没有 `source`、`source_licence_id` 列，均为须迁移，未验证。 |
| 指数 `change_pct` | `market.quotes_snapshot.pct_change` | 由 `daily_bars.close` 和 `daily_bars.pre_close` 以 Decimal 计算，或使用来源已给的同日涨跌幅 | 不用浮点容差。日线 `pre_close` 已有列，但旧行可能为空。 |
| 指数 `amount` | `market.quotes_snapshot.payload` 中的来源成交额字段 | `market.daily_bars.amount` | `quotes_snapshot` 没有独立 `volume/amount` 列，payload 字段映射和单位均为须迁移，未验证。未知时为 null。 |
| 指数 `t` | `market.quotes_snapshot.ts` | 交易日 15:00（北京时间）的收盘行情时点 | `fetched_at` 只用于 PIT 可见性，不替代行情时点。 |
| 宽度上涨/下跌 | `quotes_snapshot.pct_change` 或 payload 中经证据核实的前收比较字段 | `daily_bars.close/pre_close` | 盘中只用同一批次、同一知识时点的行。缺少可比较字段的行进 `missing`，不记平盘。 |
| 宽度平盘 | 同上 | `daily_bars.close = pre_close` | 仅 Decimal 精确相等。缺失不是平盘。 |
| 宽度比例 | 上述计数和同一批次分母 | 同左 | 只在分母大于零且批次资格证据可解释时计算。 |
| `limit_up/limit_down` | 来源明确给出的封板字段；当前表中不存在，须迁移，未验证 | 来源字段，或 `app.market_rule_versions.effective_from/rules` 与当日股票状态逐行匹配后按交易所规则计算 | 不得按 ±10% 猜。规则版本、最小价位单位、无涨跌幅日任一缺失时为 null 并给 `no_source`。 |
| `turnover_total` | 同一合格成交批次的来源成交额字段之和 | 同一交易日合格 `daily_bars.amount` 之和 | 单位元，Decimal 字符串。不能把样本和写成全市场合计。 |
| `basis.snapshot_id` | `app.data_snapshots.id` | 同左 | 只引用已存在的主键。快照 purpose、批次、证书、来源时点没有独立市场列，必须由后端迁移或在 `items` 中形成可审计约定，未验证。 |
| `basis.observed_date/mode/scope` | 现有表无对应列，须迁移，未验证 | 同左 | `mode` 只能是既有字面量 `intraday` 或 `close`。 |
| `basis.eligible/observed/trading/suspended/missing` | 由资格池和同批行计算 | 同左 | 这些是证据计数，不是覆盖率阈值。没有资格池证据时全部为 null。 |
| `basis.source` | 现有 `quotes_snapshot` 无来源列，须迁移，未验证 | `daily_bars.source` 可读，但只有 `mairui` 可进入生产市场概览 | 不扩展 `data_provider` 枚举，不写证书值。 |
| `regime` | 不由盘中临时推导 | 候选存储为 `market.feature_bars_daily.values` 中的 `f.market_regime` 或 `f.market_regime_idx`，其 `computed_at` 受 PIT 过滤，且 `app.feature_catalog.status='verified_live'` | T-R107 未批准 F25/G-02 参数，当前 `enabled=false`，故固定 null+gap。 |
| `regime_position_range` | 不单独计算 | 候选配置为 `config/risk_controls.yaml` 的 RC3 `regime_ranges` | 只有 regime 已启用且同一版本给出区间时返回。RC3 默认值不是 regime 证据。 |
| `data_as_of` | 参与响应的行情 `ts` 中最早非空值 | 收盘行情时点为 T 日 15:00，北京时间 | 不取请求时刻、生成时刻或 `fetched_at` 代替。全空为 null。 |
| 盘中批次键与知识截止 | `market.quotes_snapshot.batch_id`（`uuid`，可空，由迁移 0040/#371 新增，**在途 PR，未验证**） | — | 同一 `batch_id` 下全部行的 `max(fetched_at)` 为知识截止；按 §4 选批。 |

`quotes_snapshot` 当前主键是 `(code, ts)`，无法隔离不同证书的同一时点。迁移前不得把无归属旧行冒领为本人 `source='mairui'` 行，也不得把 `realtime_quotes` 代替本任务要求的 `quotes_snapshot`。

## 3. 资格池和 basis

### 3.1 资格池

资格池的候选范围是观察日已上市、沪深 A 股、非 BJ、非 ETF/指数的 `market.securities` 成员。历史上市状态应按 `market.security_listing_status_history(code, listing_status, valid_from, valid_until)` 做 PIT 读取，不能用今天的名单回看历史。

保守默认如下。

- 沪、深股票进入候选池，停牌与零量成员仍在资格池中。
- 北交所股票默认拦截，不进入沪深合计、宽度分母、涨跌停计数或成交额。只有独立来源、规则版本和同日对账门闩全部具备时，另行启用 BJ 口径。当前 `MarketBasis.scope` 仍为既有的「沪深股票口径」。
- `type='etf'`、`type='index'`、基金、债券和其他非股票证券不计入宽度和成交额资格池。指数只出现在 `indices` 卡片。
- `listing_status='listed'` 才进入。`delisting_period`、`delisted`、`missing_from_list` 和无法在观察日确定上市状态的行排除，并给资格缺口。
- `is_suspended`、成交量和比较字段不改变资格池成员资格。现有 `daily_bars.is_suspended` 可作为收盘证据，盘中停牌字段在 `quotes_snapshot` 中没有独立列，须迁移，未验证；真实零量保留，字段缺失不补零。
- ST/*ST 仍进入资格池，宽度按下表计算。ST 的涨跌停比例必须按当日规则版本，不能固定套用历史 5%。

资格池证据或所需批次事实缺失时，五项计数均为 `null`；行级状态未知不推断停牌。覆盖率阈值没有现有出处，`market.overview.coverage_threshold` 保持 `enabled=false`，不得用任意百分比放行，也不得把固定分母写成覆盖率证据。

### 3.1A basis 与宽度冻结映射

| 字段 | 冻结映射 |
|---|---|
| `eligible` | 资格池 P 的成员数。无资格池证据时 `eligible`、`observed`、`suspended`、`trading`、`missing` 五项均为 `null`。 |
| `observed` | P 中在所选批次有行的成员数，含停牌、零量和缺比较字段行。盘中 `batch_id` 为 `NULL` 的旧行不计入。 |
| `suspended` | `observed` 中 `is_suspended=true` 的成员数，状态未知不计入。 |
| `trading` | `observed` 中非停牌且 `volume>0` 的成员数。零量非停牌行计入 `observed`，不计入 `trading`。 |
| `missing` | `eligible - observed`。 |
| 宽度 `N` 与涨跌 | `trading` 中有完整 `pct_change` 或 `close/pre_close` 的成员才计入 N，按上涨、下跌、平盘分别计数；缺比较字段不计 N、不记平盘，并记 `{key:"market.breadth", reason:"no_source"}`。 |
| `turnover_total` | `trading` 成员 `amount` 之和。任一 `amount=null` 时为 `null`，并记 `market.turnover_total/no_source`。 |
| 恒等式 | `missing=eligible-observed`，`N<=trading<=observed-suspended`。 |

盘中 `batch_id` 为 `NULL` 的行不得参与宽度、成交额和 basis 计数，指数卡片可显示但不给 `fresh`，并记 `market.basis/no_source`。收盘计数只使用 §4 选定的单一 T* 日线。

### 3.2 BJ 门闩

BJ 默认关闭。启用前必须有至少 20 个不同合法 BJ 代码在同一交易日由两来源同码同日对照，来源行均非停牌、非零量，排除后仍足数。对照结果、来源时点和规则版本须可追溯。缺任何一项时保持默认拦截；该门闩是待合入契约要求，不是当前主线已验收事实。

BJ 门闩的收口依据是 PR #182 的 `docs/T-A172` 分支 `docs/contracts/daily-bars-source.md` §10。该契约尚待合入，本文件不把门闩要求或建议用例写成已实现、已验收。

## 4. 盘中/收盘选择和 PIT

后端在请求开始捕获带时区的 `query_as_of`，所有查询同时满足：

1. 行情时点 `ts <= query_as_of`。日线收盘的逻辑行情时点是 T 日 15:00 北京时间。
2. 行的 `fetched_at <= query_as_of`。无时区的时间拒绝参与。
3. 盘中交易日按 `market_clock` 确定的 T，收盘按本节选定的 T*，不跨日拼接，不用当前时钟替换历史事实。
4. 证书归属匹配当前用户。不可用证书不借用其他用户或无归属缓存。

盘中批次键为 `market.quotes_snapshot.batch_id`。只在 `source='mairui'` 且 `source_licence_id` 等于本人当前证书的行中，按每一交易日选择知识截止不晚于 `query_as_of` 的最近批次。知识截止是该 `batch_id` 下全部行的 `max(fetched_at)`，知识截止最大者优先，平手取 `max(ts)`。批次内任一行 `ts` 或 `fetched_at > query_as_of` 时整批不可见，不得部分纳入。`batch_id=NULL` 的行不参与盘中聚合。

收盘口径只取单一交易日 `T*`。`T*` 是所有可见合格行中满足 17:10 完成门槛且 `fetched_at <= query_as_of` 的最大 `trade_date`，只使用 T* 的 `daily_bars` 行，禁止按代码各取最近日或混合 T-1 与 T-2。`basis.observed_date` 写实际选定批次或 T* 的日期，不写 `clock.trade_date`。

时段规则如下。

| 条件 | 允许的行情 | 禁止事项 |
|---|---|---|
| 交易日 09:30 前 | 最近一个已完成收盘批，若存在则标 stale | 不取当日盘中，不把预开盘或集合竞价当收盘 |
| 09:30–15:00 | 当日按上述规则选定的 `quotes_snapshot` 盘中批次；无批次可回退上一完整收盘批并标 stale | 不把盘中行标为 close，不使用未来 `fetched_at` |
| 15:00–17:10 | 仍按盘中批次；无批次回退上一完整收盘批 | 不因当前时间已过 15:00 放行当日旧盘中行作为正式收盘 |
| 17:10 后 | 仅使用 T* 日 `daily_bars` 中 `adj_type='none'`、`source='mairui'`、`source_licence_id` 匹配且 `fetched_at` 不早于 T* 日 17:10 的收盘行 | 不使用早于 17:10 的日线冒充最终日线，不混用 `tdx_local` |
| 午休或非交易日 | 保留已可见的最近批次并如实标 stale 或 partial | 不刷新时间伪装 fresh，不拼接不同交易日成员 |

17:10 是既有 `FINAL_AFTER` 门槛，15:00 只是市场时点。盘中行即使在 15:00 后抓到，也仍是盘中行。日线行的 `fetched_at` 早于 T* 日 17:10 时不能作为概览收盘输入。

## 5. 宽度、涨跌停和成交额

### 5.1 宽度

按 §3.1A 的冻结映射，对同一 T、同一来源批次、同一知识截止的有效集合 E：

`up`、`down`、`flat` 分别按完整 `pct_change` 或 `close/pre_close` 的 Decimal 比较计数，`N = up + down + flat`。

`up_ratio = up/N`、`down_ratio = down/N`、`flat_ratio = flat/N`，用 Decimal 保留至少 4 位有效小数后序列化。N=0、成员跨批次、前收或收盘缺失时，比例为 null。缺比较字段的 trading 成员不记平盘，并给 `{key:"market.breadth", reason:"no_source"}`。宽度字段不得由持仓、自选、策略实例或指数成分替代。

### 5.2 涨跌停

优先使用同一来源批次明确提供的封板字段。若来源没有字段，只能使用与 T 日匹配的 `app.market_rule_versions(effective_from, rules, source_note)`，按证券板块、ST 状态、上市阶段和无涨跌幅例外逐行取得比例与最小价位单位，再以 Decimal 计算并按规则价位取整。

规则来源、最小价位单位、前收或无涨跌幅日任一缺失时，`limit_up=null`、`limit_down=null`，并给 `gap{key:"market.breadth.limit_counts", reason:"no_source"}`。禁止统一 ±10%、禁止用展示值四舍五入、禁止用上一交易日规则跨日套用。停牌、零量和无涨跌幅日不计数。北交所不因存在 30% 规则而自动打开 BJ 门闩。

涨跌停统计的内部门控名为 `market.overview.limit_counts.enabled`。只有来源字段或交易所规则出处、规则版本和逐行映射都可追溯时才可为 true；其余情况固定 false、字段为 null、gap 为 `no_source`。该门控不作为新的响应字段或枚举。

### 5.3 成交额

`turnover_total` 只累加同一观察批次中 trading 成员的 `amount`，单位元，Decimal 字符串。任一 trading 成员 `amount=null` 时返回 `null` 并记 `market.turnover_total/no_source`，不把已观测样本外推为全市场合计。盘中 `batch_id=NULL` 的行不参与聚合，真实合计为 `"0"` 时保留字符串零。

## 6. data_status、data_as_of 和 gaps

只使用 §3 已有 `fresh/stale/partial/unavailable`。`GET /market/overview` 适用 §1.1 的 T-A219 例外，只读缓存，不入队、不返回 `pending`。状态判定如下。

- `fresh`：本次返回的所需组件均来自同一可见盘中批次或同一 T* 收盘日；盘中时点未超过现有 `config/realtime.yaml` 的过期规则（`stale_threshold_s=null` 时沿用 2 倍快照间隔）；收盘时已满足 17:10 完成门槛。
- `stale`：有可见的旧完整批次，但不满足 fresh 时效，或开盘前、午休、非交易日展示上一完整收盘批。旧批次的原始 `data_as_of` 保留。
- `partial`：至少一个指数或宽度/成交额组件有可见值，另一个组件因缺字段、缺资格或未批准参数为 null。已知覆盖不足不得把部分样本标成 fresh。
- `unavailable`：没有任何合格行情输入，或本人证书不存在/不可用且没有可使用的本人缓存。无合格批次时行情、宽度、成交额和 basis 为 null，保留公开指数代码和名称时不改变该状态。

`data_as_of` 是实际参与响应的行情时点的最早值，全部为空为 null。gap 的 `reason` 只用现有枚举：来源未接或字段未验证用 `no_source`，已知未到发布点用 `not_yet_published`，上游事实故障用 `upstream_error`，证书不可用用 `data_licence_unavailable`，确认停牌用 `suspended`。不得新增 `coverage_unknown`、`regime_disabled` 等枚举。

推荐 gap key：

- `market.indices.<code>`
- `market.breadth`
- `market.breadth.limit_counts`
- `market.turnover_total`
- `market.regime`
- `market.basis`

## 7. regime 规则

T-R107 明确 F25/G-02 的窗口、阈值、防抖天数、最少有效值和参考区间均未获批准。后端必须把 regime 计算门控设为 `enabled=false`，不读取仓内候选值作为正式结论。

因此：

- `regime=null`，`regime_position_range=null`；
- 增加 `market.regime` gap，`reason="no_source"`，message 写明“F25/G-02 参数未批准，未生成市场环境结论”；
- 不沿用前一日 regime，不返回 `range` 作为默认，不用 F50 或 RC3 区间补出结论；
- 仅当后续有版本化、PIT 可见且批准的 feature 产物，才读取 `feature_bars_daily.values`，并按 §3 的 `feature_catalog.status='verified_live'` 过滤。

## 8. 错误和空态

| 场景 | HTTP 与响应 |
|---|---|
| 未登录 | 既有 `401 AUTH_REQUIRED`。不解析业务参数。 |
| 账号非 approved | 既有 `403 ACCOUNT_NOT_APPROVED`。 |
| 日历未覆盖请求时点 | 既有 `503 CALENDAR_NOT_COVERED`，不按工作日猜测。 |
| 市场时段规则缺失 | 既有 `503 MAINTENANCE`。 |
| 无本人证书 | `200`，`indices` 可保留配置代码/名称，行情字段、breadth、turnover、regime 和 range 为 null，`data_status=unavailable`，gap 为 `data_licence_unavailable` 和未验证来源的 `no_source`。 |
| 本人证书可用但无合格批次 | `200`，只读缓存，不入队、不返回 `pending`；行情与宽度字段为 null，`data_status=unavailable`，`gaps` 含 `{key:"market", reason:"no_source"}`。 |
| 交易日开盘前 | `200`，不取当日盘中或收盘。若有上一完整收盘批，返回 stale，否则 unavailable。 |
| 非交易日 | `200`，沿 `market_clock` 的最近交易日读取可见完整收盘批并标 stale；没有批次则 unavailable。 |
| 交易日全部缺失 | 按 §1.1 的 T-A219 例外处理；`200`，所有数值字段为 null，`indices` 仍可保留主数据卡片，`data_status=unavailable`，给 `market/no_source` gap。 |
| 部分指数、宽度或成交额缺失 | `200`，保留可解释值，`data_status=partial`，对应字段 null 和 gap。 |
| 非法方法或不存在路径 | 沿既有 `405`/`404 NOT_FOUND`，不新增错误码。 |

## 9. 虚构测试夹具

以下均为隔离测试库和 fake transport 的虚构数据，不需真调麦蕊，不含证书值。每个夹具必须显式给 `query_as_of`、行情 `ts`、`fetched_at`、来源和证书归属占位 UUID。

| 夹具 | 虚构数据与断言 |
|---|---|
| 完整盘中 | `600000.SH`“示例银行”、`000001.SZ`“演示电子”、`688001.SH`“虚构芯片”三只；quotes_snapshot 同一批次、`source='mairui'`、证书 A、成交量均为正，涨跌为 2/1/0。断言三比例 Decimal 字符串、同批 basis 和 turnover。 |
| 盘中缺量额 | 两只股票有 price/pct_change，payload 缺 volume/amount；断言价格可读、宽度和成交额为 null 或 partial+gap，不把缺量当零。 |
| 15:00 边界 | query 在 14:59:59、15:00:01、17:09:59、17:10:01；同日盘中行和 fetched_at=17:11 的日线行分别可见。断言 15:00 前后均不把盘中行标 close，17:10 前不读日线，17:10 后才读合格 daily_bars。 |
| 日线收盘 | `daily_bars` 给 `600000.SH`、`000001.SZ` 的 `adj_type='none'`、`source='mairui'`、`source_licence_id=A`、`is_suspended=false`、完整 close/pre_close/volume/amount，fetched_at 为 17:15。断言 close 模式和金额单位元。 |
| 停牌、零量、退市、ST | 四只虚构证券分别为停牌、volume=0、listing_status=delisted、risk_flag=st。断言前三类排除；ST 进入基础宽度但其涨跌停必须有当日规则，否则 limit 字段 null+gap。 |
| ETF、指数、BJ | `510001.SH` type=etf、`000300.SH` type=index、`830001.BJ` type=stock。断言 ETF/指数不进入宽度；BJ 默认不进入 scope，指数只作为卡片。 |
| 涨跌停缺证 | 有 close/pre_close，但 market_rule_versions 缺 T 日规则或来源缺最小价位单位。断言 limit_up/limit_down 为 null，gap reason=no_source，禁止 ±10% 推算。 |
| regime 门控 | feature_bars_daily.values 含 `f.market_regime='uptrend'`，feature_catalog.status 分别为 declared 与 verified_live。两组均因 F25/G-02 未批准而返回 null+no_source，不返回 range。 |
| 无证书与全空 | 当前用户无证书，或证书 A 下全部行 fetched_at 晚于 query_as_of。断言 HTTP 200、公开卡片可留、所有行情值 null、unavailable、data_licence_unavailable/no_source。 |
| 非交易日与开盘前 | trading_calendar 给休市日及前一开市日，前一日有完整收盘。断言 session、trade_date、stale 和不读当日盘中。 |
| BJ 门闩 | 生成 830001.BJ–830020.BJ 的 20 个虚构合法代码，同一日两来源同码；再加入一停牌行和一零量行。断言排除后不足 20 仍关闭 BJ，足数且证据可追溯时才允许单独门闩。 |
| PIT 交叉证书 | 证书 A、B 在同一 `code,ts` 各有一行，另有未来 fetched_at 行。断言只读 A、排除未来行，旧无归属 quotes_snapshot 行不被冒领。 |

## 10. 后端须改、前端须改和未决项

### 后端须改

1. `app.aggregates.service.market` 接入连接、当前用户、本人证书和 `query_as_of`，不再固定返回空对象；读取时按 §4 PIT。
2. 为 `quotes_snapshot` 增加并迁移 `source='mairui'`、`source_licence_id`、可审计的 volume/amount/停牌字段或等价 payload 版本约定，并处理旧主键的证书隔离。迁移前旧行只能排除。
3. 实现同批次资格池、宽度 Decimal 计算、成交额合计、basis 计数和 gap 投影。资格覆盖率阈值保持 `enabled=false`。
4. 只从来源字段或 `market_rule_versions` 的 PIT 规则计算涨跌停，规则不全时返回 null+gap。
5. 实现 15:00、17:10、`fetched_at` 和行情时点门槛，收盘读取只能走 `daily_bars` 的合格行，并复用唯一写入口已定的来源字段语义。
6. 接入已批准的 regime 产物前保持 F25/G-02 disabled。当前主线没有可宣称完成的 regime 聚合。

### 前端须改

1. `src/frontend/src/api/types.ts` 的 `MarketOverview`、`MarketIndexQuote` 和 breadth 类型加入 `basis`、三个 ratio 字段及字段级 null。
2. `MarketPage`、`BreadthPanel`、`RegimePanel` 处理 denominator=0、部分缺失、stale、来源 gap 和 null+gap，不把 null 当 0，也不把比例再次按百分数解释。
3. 指数卡显示 `t` 与盘中/收盘来源说明；无证书、开盘前、非交易日和全空响应沿用 §3/§4 既有文案，不新增枚举或错误码。
4. fixture 使用本节虚构代码和数值，关闭 MSW 后按真实 API 结构断言。

新增字段只解释已有需求：`up_ratio/down_ratio/flat_ratio` 是宽度比例，`basis` 已在 v0.2.11 存在。没有新增公共枚举、错误码或请求参数。

## 11. 当前主线与验收边界

当前主线仅能验收 `market()` 的空态保护，不能验收本契约的聚合结果。T-A209 的 U1（全市场/指数字段和单位）、U4（涨跌停来源与覆盖）、U8（盘中字段、单位、累计量额和 ETF 覆盖）仍未验证。PR #326 只提供口径卡和交易规则出处，不提供真实供应商覆盖、批次完成或 15:05 终值证据。后续实现必须先用虚构夹具完成离线测试，真实调用须按团队红线审批（编排者审后代批或用户本人批准）。

## 12. 对在途实现与测试的影响

- #371（be/T-B210）须改：收盘回退按单一 T* 选行，`observed_date` 取实际日期，basis 计数按 §3.1A，`batch_id=NULL` 的行不参与聚合；B1 已与 #371 现行只读实现一致。
- #366（tst/T-T113）须改：空态 gap 断言与 B1 一致（已符合）；非交易日 `trade_date` 断言按 `market_clock` 的最近开市日；新增批次不可部分纳入、`NULL batch_id` 不参与、跨日不混合、basis 恒等式四个夹具，由测试方补（T-T115b）。
- 对齐清单（非阻断，R371 非阻断 5）：证书不可用时逐项 `market.indices.<code>` 与 `market.basis` 的 `no_source` gap 按 §1.1 为「推荐」，#371 后续补齐，不作为合入门槛。

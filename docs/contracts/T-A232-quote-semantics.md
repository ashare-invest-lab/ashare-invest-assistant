# T-A232 行情口径契约

## 1. 范围与 #387 的关系

本文件裁定 `/quotes`、聚合行情与 SSE `quote` 的五项语义，配套主契约为 `docs/api-contract.md` §1、§5.1、§7.3、§8。它只补充语义，不改既有端点行内字段清单。

PR #387 的 `/quotes` 行尾时段表为准，引用要点如下。`[09:30,11:30)`、`[13:00,15:00)` 是盘中，午休参照当日 11:30，收盘后（含 15:00 整点）参照当日 15:00，盘前与闭市日参照上一开市日 15:00 收盘。该表由 `marketdata.quotes_read._reference_time`（#390）实现，本分支不复制或改写其端点行。

RT-04：见 PR #405 docs/contracts/T-A233-*（合入后生效）。

### 1.1 RT-03 时点、过期阈值与降级覆盖

本节为 RT-03 目标契约，四个入口的实现验收仍未完成。

- `marketdata.quotes_read._reference_time` 统一计算北京时间交易时段和查询时点。15:00 只确定市场收盘时点，`marketdata.quotes_read._daily_closes` 仍须等到 17:10 终值门槛并满足 `fetched_at <= query_as_of` 才能作为正式收盘输入。盘中行不会因当前时钟已过 15:00 而升级为收盘行。
- `stale_threshold_s` 的唯一配置来源是 `config/realtime.yaml`，沿用 §7.9 的 `plan 0A.7` 初值 30 秒【未验证】。它只决定行情按 `t` 的 freshness，不得缩短 SSE 断线后的降级轮询间隔。§7.3、§8 的轮询下限保持每次至少 15 秒并带 `If-None-Match`，与 T-A232 同一版本口径覆盖 `/terminal`、`/today` 的聚合读链。
- 四个读发布入口共同捕获 `query_as_of`，并按 `t`、`fetched_at` 的可见性做 PIT 过滤。`GET /quotes` 调 `_reference_time`/`_daily_closes`，`GET /terminal` 和 `GET /market/overview` 复用同一时段与 17:10 收口，`GET /stream` 的 `quote` 帧复用项级 `t` 和 `data_as_of`。午休、闭市、15:00、17:10、未来 `fetched_at` 均不得前视。

RT-03 验收（按入口）：

- `GET /quotes`：覆盖 15:00 前后、17:10 前后、午休、闭市和未来 `fetched_at`，断言盘中回退、stale 判定、`t`/`data_as_of` 及无新增错误码。
- `GET /terminal`：断言行级行情沿用同一 `query_as_of`，SSE 断线后按至少 15 秒并带 `If-None-Match` 轮询，不能把旧盘中行当收盘。
- `GET /market/overview`：断言 17:10 前不读正式日线收口，17:10 后只读单一可见交易日批次，跨日不拼接。
- `GET /stream`：断言 `quote` 帧按项级 `t` 判 stale，帧级 `data_as_of` 取最早可信 `t`，断线降级不改变帧字段或错误码。

## 2. 五项裁定

### 2.1 市场收盘与日线终值

- 北京时间 15:00 是市场收盘时点，用于 `GET /quotes` 日线回落资格、项级行情时点 `t` 与 freshness 收盘后参考时刻。实现出处为 `src/backend/app/marketdata/quotes_read.py:_daily_closes`，契约出处为 plan 0A.3、§7.9；`_fresh_close_day` 还要求开市日 15:00 前不视为当日 fresh 收盘日。
- 北京时间 17:10 是日线终值和正式收盘批完成门槛，用于 `/market/overview` 收盘模式及 owned 日线 `is_final`，不能以 15:00 替代。出处为 `daily_snapshot.py:FINAL_AFTER`、`aggregates/market_overview.py:FINAL_AFTER`、`docs/contracts/T-A219-market-overview.md` §4 与 `T-A209-market-wiring.md`；公开说明见 [麦蕊沪深历史分时交易](https://www.mairuiapi.com/hsdata)（「日线及以上级别每日15:30开始更新，预计17:10完成」）与 [麦蕊指数历史分时交易](https://www.mairuiapi.com/hszsdata)（「日线以上数据每日下午15:30开始更新，预计17:10完成更新」）；T-A219 见 PR #359@4d0ad2d0（尚未合入 main）。
- 厂商仅称预计 17:10 完成，实际每日完成时刻未实测，门槛仍按本仓契约执行。

### 2.2 `change_pct` 与价格小数位

- 类型仍为 `string(decimal)`。`change_pct` 服务端最多四位小数并四舍五入，按 `aggregates/market_overview.py:RATIO_QUANTUM = Decimal("0.0001")`；不得输出除法展开的超长有理数。少于四位可保留原样，例如实时透传 `"1.386"`。出处为 §1、#371 `aggregates/market_overview.py`，日线分支现状 `quotes_read` 须跟改。
- ETF `price` 最多三位小数，沿 v0.2.8 与 `/quotes` 既有说明及 ETF `format(..., ".3f")`；股票不强制补齐两位尾零，沿现有 `format(..., "f")`。前端展示位数自定，字段类型不变。

### 2.3 `data_as_of` 是行情时点

- 遵循 A-12（§1.1、§5.1 `DataStatusBlock`），`data_as_of` 取实际参与内容的数据时点中最早的非空值，不能用生成、评估、当前、发布或心跳时刻替代。Evidence 示例已区分 `data_as_of=2026-11-02T15:00:00+08:00` 与 `fetched_at=2026-11-02T16:40:00+08:00`。
- 项级 `t` 是行情时点，实时取行情 ts，日线回落取交易日 15:00+08:00。有可信 `t` 时，项级 `data_as_of` 必须等于该条 `t`。仅有采集时点时才可用对应 `fetched_at`。出处为 §5.1、§8、#385 `realtime_publish.build_quote_data`（`min(items[].t)`）、#390 实时分支 `data_as_of = stamp` 与 #371 `_row_time`。
- 日线回落现状把 `row.fetched_at` 写入项级 `data_as_of`，与本裁定不符，后端须改为与 `t` 相同。不得前视，`fetched_at` 不在 `/quotes` 项级输出。

### 2.4 `volume` 与 `amount`

`volume` 单位为股，`amount` 单位为元，类型均为 `string(decimal)`，与 §5.1 `Bar` 一致。上游若返回手，由 ingest 换算为股；接口不改成手，前端按手展示时自行除以 100（1 手 = 100 股/份）。不强制固定小数位或尾零。出处为 §5.1 `Bar`；上游量额单位仍【待 T003 核实】。

### 2.5 SSE `quote` 帧与发布返回值

- `quote` 帧允许日线回落项，条件是 `t` 为可信行情时点（交易日 15:00+08:00）；允许 stale 项同帧。出处为 A-12「至少一条有可信行情时点的变化项」与 #385 `build_quote_data`（只要求非空 `t`，不过滤来源和 `data_status`）。不改 §8 既有形状 `{items: [{security_code, name, price, change_pct, amount, t}], data_as_of}`。
- 客户端按 `t`、#387 时段表和 `stale_threshold_s` 自行判断过期，不把旧 `t` 当新行情。帧级 `data_as_of` 仍取 `items[].t` 最早值，旧 stale 项会按既有规则拉低该值。
- `notify.transport.publish` 去重未出帧返回空串。`marketdata.realtime_publish.publish_quote` 必须仅在实际写入新 quote 事件时返回 `True`。数据为空、发布失败或 transport 返回空标识均返回 `False`。出处为 Lua `SET NX` 去重逻辑、`publish_quote` 现状与 A-12「无 quote 变化不发布」；#385 须跟改。

## 3. 须跟改

- 后端：修正日线 `change_pct` 四舍五入、项级 `data_as_of=t`，并使 `publish_quote` 传播空标识和发布失败；保持 15:00 与 17:10 两道门槛。
- 前端：按 SSE 项级 `t` 判断 stale；展示位数由前端自定，不改变字段类型或 §8 帧结构。

## 4. 未验证清单

- 厂商所称 17:10 为预计完成时刻，本仓未实测实际每日完成时刻。
- 上游量额单位待 T003 核实，本文件不据此关闭 §5.1 `Bar` 的待办。

# T-R103 复盘与建议跟踪指标口径卡

```yaml
document: review_tracking_metrics
task: T-R103
lifecycle: draft
scope: 候选信号的模拟跟踪、实际成交复盘及实盘与样本外回测对比
G7: ☐
```

## 1. 边界与共同规则

本卡只描述候选信号的记录与复盘口径，不构成荐股、买卖指令或收益承诺。模拟跟踪、实际成交和样本外回测必须分开保存，不能用模拟结果代替用户实际收益，也不能用实际成交结果回填历史候选信号。

一条候选信号观测的去重键为 `suggestion_id`、`strategy_version_id`、`horizon_days`。`horizon_days` 只取 1、5、20 个交易日，统计窗口以交易所交易日历计数。复盘接口对照 #349@2fd6730c 草案（未合入），以合入版本为准。该草案 §7.8.4 明确四项 `Stat`（`holding_return`、`benchmark_return`、`excess_return`、`max_drawdown`）只按本人实际可见成交、版本快照和计算时点计算，当前不能以模拟跟踪补值。`entry_price`、`exit_price`、`benchmark_code`、`price_basis` 等只属于计算输入或证据，不替代接口字段。字段存在不等于数据链路已验收。

计算时固定 `generated_at`、`data_as_of`、`available_at`、交易日历版本、行情版本、复权因子版本、基准代码和成本表。只使用在本次计算时点已经可见且业务日期不晚于到期日的数据。迟到、修订或后来复牌的数据不能改写已经冻结的历史观测。缺字段输出 `null` 并记录 `gaps`，不以零、邻日价格或当前时钟补值。

盘后候选信号的模拟入场价取信号发出后下一交易日的第一可成交价，通常为下一交易日开盘价。盘中候选信号取生成时刻之后的下一根可见分钟线开盘价。若该价因停牌、涨停封板或缺乏可成交证据而不可得，观测记为 `untradable` 或 `unavailable`，不伪造成交。该规则只适用于独立的 `simulated_tracking`，不能写入 §7.8 四项 `Stat`。具体可成交性仍需 A 股数据复测。[上交所交易规则（2026年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；[深交所交易规则（2026年修订）](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)。

## 2. 指标口径

### 2.1 `simulated_tracking` 候选命中与目标、止损结果

**定义。** 这是 `simulated_tracking` 内部的方向命中率，分母只包含 `state=complete`、`excess_pct` 非空且动作属于 `buy`、`add`、`sell`、`reduce`、`hold` 的模拟观测。`wait` 只展示，不进入命中率。不可成交、停牌、涨跌停锁定、`pending`、`unavailable`、`excluded` 和 `forced_hold` 单独计数，不进入分母。该统计不写入 §7.8 四项 `Stat`。

**公式。**

```text
simulated_hit_rate = 命中观测数 / 有效观测数
buy/add       命中 ⇔ excess_pct > 0
sell/reduce   命中 ⇔ excess_pct < 0
hold          命中 ⇔ |excess_pct| ≤ θ_h
θ_1=1.0%，θ_5=2.0%，θ_20=5.0%
```

`direction_correct` 直接保存上述模拟布尔值。阈值是产品初值，属于未验证（待回测），不能据此宣称策略有效。命中率与盈亏大小分开报告，胜率高不代表收益为正。命中率和平均胜负幅度作为两个互补维度的公开讨论见 [CFA Digest 关于 hit ratio 与 win/loss magnitude](https://rpc.cfainstitute.org/research/cfa-digest/2018/07/dig-v48-n7-8)。

若候选信号在卡片中预先登记了止损和止盈，另记首次可证明触发的 `target_hit`、`stop_hit` 或 `neither` 结果。需要 `stops.stop_loss`、`stops.take_profit`、逐时点可见的高低价、成交状态和 `invalidation_triggered_at`。同一根 K 线同时触及目标和止损且无法证明先后时，按止损优先的最坏规则，或标记顺序未知并剔除该细分统计。不能用收盘价越过阈值倒推盘中触发。目标、止损优先级和 A 股有效性未验证（待回测）。

**窗口与时点。** 每条候选信号在 T+1、T+5、T+20 收盘后各计算一次。命中率聚合只使用已经结束的窗口，窗口端点以该次作业的 `as_of` 截断。

**最少样本量。** 单个命中率在 `n<5` 时只返回空值和样本数，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。上述 `n` 只包括有效、已结束且有 `direction_correct` 的观测。

**边界。** 目标或止损命中后，退出价取实际可成交价，不取阈值价。涨停买不进、跌停卖不出和停牌不补成交。无法卖出的仓位保留为未平仓或不可用观测，不能用事后复牌价补成交。上述规则的工程细节未验证（待回测）。

### 2.2 实际成交复盘的持有期收益

**定义。** §7.8 的 `holding_return.value` 只表示实际成交复盘结果，不能使用候选信号的模拟入场或模拟退出。只有本人未作废成交已在版本快照中可见，且费用、现金流和同一复权口径的入场与退出端点均可追溯时才计算，单位为百分数。#349@2fd6730c 草案（未合入）仍以合入版本为准。价格比值收益与绩效评价中的区间收益定义一致，风险指标和收益口径的公开方法见 [CFA Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation)。

**公式。**

```text
holding_return.value = 100 × (exit_price / entry_price − 1)
```

实际成交的端点和费用必须来自版本快照中的成交证据。现有成交接口可核对 `trade_date`、`trade_time`、`qty`、`price`、`fee_total`、`side`、`security_code`、`created_at`、`voided` 和 `id`，但接口没有直接的 `available_at`、逐日价格路径或复权因子版本。缺少任一必需来源时，`holding_return.value=null`，顶层 `gaps` 记录 `outcome_metrics.holding_return` 与适用的 `no_source` 或 `user_input_missing`，不得用模拟值、邻日价格或零费用补齐。显式佣金可按适用日期的公开规则建模，[证监会关于调整证券交易佣金收取标准的通知](https://www.csrc.gov.cn/csrc/c100024/c1492350/1492350/files/928bdd362fa24b79bdadb0072d67acee.pdf)规定 A 股佣金上限 3‰ 且单笔不足 5 元按 5 元收取。历史税费必须按成交日期规则取值，[国家税务总局等关于减半征收证券交易印花税的公告汇编](https://www.chinatax.gov.cn/chinatax/c102414/c5216997/5216997/files/%E5%BB%B6%E7%BB%AD%E4%BC%98%E5%8C%96%E5%AE%8C%E5%96%84%E7%9A%84%E7%A8%8E%E8%B4%B9%E4%BC%98%E6%83%A0%E6%94%BF%E7%AD%96%E6%B1%87%E7%BC%96%EF%BC%882023%E5%B9%B4%E7%89%88%EF%BC%89-20231124113552902.pdf)给出 2023-08-28 起的历史税率变化。费用和滑点压力档位尚无 A 股普适验证，标记未验证（待回测）。

**输入字段。** 实际成交只能使用以下来源表中在计算时点可见的字段。实际成交必须满足 §7.8 草案要求的 `available_at <= calculation_as_of`，并在版本快照中冻结。逐日 `close`、基准端点、复权因子版本、现金流、分红和可成交队列证据仍无项目来源，保持 `enabled=false`、`value=null`，并记录对应 gap。

**B3 逐字段来源登记。**

| 接口或内部结构 | 数据库列 | 单位和时区 | `available_at` 计算 | 证据端点 | 验证状态 |
|---|---|---|---|---|---|
| `GET /trades.trade_time` | `traded_at` | `HH:MM[:SS]`，接口按 Asia/Shanghai 展示 | 手工成交取 `created_at`；导入成交取 `max(created_at, import_batches.committed_at)`，并要求不晚于 `calculation_as_of` | `src/backend/app/api/v1/trades.py:61-80`；`src/backend/app/domain/trades.py:90-108`；`src/backend/app/feedback/plan_source.py:143-168` | 字段映射已核对；完整可见性覆盖未验收 |
| `GET /trades.qty` | `quantity` | 十进制股数，无时区 | 同上，按创建/导入提交时间冻结 | `src/backend/app/api/v1/trades.py:61-72`；`src/backend/app/db/tables/accounts.py:130-148` | 字段映射已核对；PIT 覆盖未验收 |
| `GET /trades.price` | `price` | 十进制元/股，无时区 | 同上，按创建/导入提交时间冻结 | `src/backend/app/api/v1/trades.py:69-72`；`src/backend/app/db/tables/accounts.py:138-145` | 字段映射已核对；费用和价格链未验收 |
| `GET /trades.fee_total` | `commission`、`stamp_tax`、`transfer_fee`、`other_fee` | 十进制元，无时区；各列非空值求和 | 同上；费用缺失保持 `null`，不得按零补齐 | `src/backend/app/domain/trades.py:23-24,83-87,113-115` | 派生规则已核对；逐笔费用可见性未验收 |
| 成交事实 | `commission` | 十进制元，无时区 | 随成交行的 `known` 时点冻结 | `src/backend/app/db/tables/accounts.py:142-145`；`src/backend/app/domain/trades.py:83-87` | 数据库列已核对；可见性未验收 |
| 成交事实 | `stamp_tax` | 十进制元，无时区 | 随成交行的 `known` 时点冻结 | `src/backend/app/db/tables/accounts.py:142-145`；`src/backend/app/domain/trades.py:83-87` | 数据库列已核对；可见性未验收 |
| 成交事实 | `transfer_fee` | 十进制元，无时区 | 随成交行的 `known` 时点冻结 | `src/backend/app/db/tables/accounts.py:142-145`；`src/backend/app/domain/trades.py:83-87` | 数据库列已核对；可见性未验收 |
| 成交事实 | `other_fee` | 十进制元，无时区 | 随成交行的 `known` 时点冻结 | `src/backend/app/db/tables/accounts.py:142-145`；`src/backend/app/domain/trades.py:83-87` | 数据库列已核对；可见性未验收 |
| 成交事实 | `traded_at` | 带时区时间戳；展示时转 Asia/Shanghai | 交易执行时间不替代知识时点；`available_at` 仍取 `known` | `src/backend/app/db/tables/accounts.py:147-148`；`src/backend/app/domain/trades.py:93-108` | 执行时间映射已核对；PIT 规则未验收 |
| 成交事实 | `voided_at` | 带时区时间戳 | 作废时间在 `calculation_as_of` 前才标记作废，并把它并入冻结知识时点 | `src/backend/app/db/tables/accounts.py:160-164`；`src/backend/app/feedback/plan_source.py:163-168` | 作废边界已核对；完整历史覆盖未验收 |
| 成交事实 | `created_at` | 带时区时间戳 | 手工成交直接使用；导入成交与 `import_batches.committed_at` 取最大值 | `src/backend/app/db/tables/accounts.py:164`；`src/backend/app/feedback/plan_source.py:143-156` | 构造链已核对；端到端 PIT 未验收 |
| `feedback.Fill.available_at` | 无直接列，属于反馈投影 | 带时区时间戳 | `Fill` 显式携带 `available_at`；成交投影按创建时间，导入投影按创建/提交时间构造，缺提交证明则记 gap | `src/backend/app/feedback/core.py:136-149`；`src/backend/app/feedback/plan_source.py:143-178` | 内部字段和构造链已登记；完整来源覆盖未验收 |
| `CandidateSignal.stops` | 无直接成交列 | `stop_loss`/`take_profit` 为十进制元/股，`time_stop_days` 为天，无时区 | 以候选信号快照及其逐项 Evidence 的 `data_as_of` 作为来源时点；缺证据则 `null` 加 gap | `docs/api-contract.md:1063-1073`；`src/backend/app/signals/models.py:61-64,108-118` | 候选信号来源存在；与成交复盘的可见性链未验收 |
| `CandidateSignal.evidence[]` | 无直接成交列 | `value` 按 `unit`，`data_as_of`/`fetched_at` 为带时区时间戳 | 每项 Evidence 使用自身 `data_as_of`，端点缺失或晚于计算时点则不能使用 | `docs/api-contract.md:627-638,1063-1073`；`src/backend/app/signals/models.py:31-39` | 逐项证据结构已核对；实际端点覆盖未验收 |
| `tracking.Result` | 无成交列；模拟投影 | `return_pct` 等为百分数，时间字段为带时区时间戳；**不含 `stops`** | Result 没有独立 `available_at`，只能按其 evidence/状态作模拟研究可见性判断 | `src/backend/app/tracking/models.py:14-39`；`src/backend/app/tracking/service.py:173-197` | 模拟来源边界已核对；不得用于实际成交 Stat |
| 逐日收盘、基准端点、复权因子、现金流 | 无来源列 | 价格为元/股，时点应为 Asia/Shanghai；当前无可验证链 | 无来源，`available_at=null` | 本卡 §5.1 来源登记 | `enabled=false`、`value=null`，对应 gap |

**窗口与时点。** T+1、T+5、T+20 交易日收盘后计算。盘后生成的 T+1 入场不能使用生成日收盘价替代下一交易日可成交价。任何输入必须满足 `available_at ≤ calculation_as_of`，不能因当前已经收盘而放行旧盘中数据。

**实际成交边界。** §7.8 四项 `Stat` 只纳入版本快照中已存在、未作废且在计算时点可见的本人实际成交。成交缺少可见性、费用、现金流或退出证据时，相关 `Stat.value=null`，顶层 `gaps` 记录缺口，不以模拟入场、模拟退出或当前时钟补值。

**最少样本量。** 单个持有期收益需要一个完整的入场和退出端点。聚合收益在 `n<5` 时不返回均值，`5≤n<30` 标记样本少，`n≥30` 才可作为正常绩效摘要。

### 2.3 `simulated_tracking` 候选信号模拟跟踪

模拟跟踪单独保存并使用顶层标签 `simulated_tracking`。它记录候选信号发出后的假设入场、假设退出、状态和可成交证据，只用于研究跟踪，不进入实际成交复盘，也不填充 §7.8 的四项 `Stat`。现有 tracking 模型可核对 `entry_at`、`entry_price`、`exit_at`、`exit_price`、`benchmark_code`、`return_pct`、`benchmark_return_pct`、`excess_pct`、`max_drawdown_pct`、`price_basis`、`cost_applied`、`state`、`evidence` 和 `gaps`。这些字段属于模拟跟踪边界，不能映射成复盘指标名。

模拟入场仍按信号之后的下一可成交时点计算，模拟退出按已登记窗口和可见价格计算。缺少价格、交易日历、复权因子或可成交证据时，模拟记录保留 `null` 并记录 `no_source` 或 `not_yet_published` 缺口。模拟结果不得写入实际成交复盘的 `outcome_metrics`，即使候选信号后来产生实际成交，也必须由实际成交快照独立计算。

`tracking.Result` 是不含 `stops` 的模拟投影，只有 `entry_*`、`exit_*`、收益、状态、证据和缺口等字段。候选信号接口本身有 `stops.stop_loss`、`stops.take_profit`、`time_stop_days` 及逐项 `Evidence`，来源见上表。逐时点高低价、成交量、队列证据仍无项目来源，依赖这些输入的模拟目标、止损和可成交判断保持 `enabled=false`，输出 `null` 并记录顶层缺口，不由邻近价格或收盘方向推断。

### 2.4 相对基准超额

**基准口径（已裁定，见编排者裁定 R332-benchmark，与 #349@2fd6730c 草案一致）。** 三处口径的角色如下，基准有效性仍未验证。

1. 本卡原有通用默认是 `000300.SH`（沪深300）。中证指数资料说明其覆盖 300 只规模大、流动性好的 A 股。[CSI 300 factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300factsheeten.pdf)；[CSI 300 编制方法](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300_Index_Methodology_en.pdf)。
2. `config/strategies/sw_ma_trend_pullback.yaml` 的 `validation_summary.benchmark` 是所属申万一级行业指数，对照是中证全指 `000985.SH`。中证全指的覆盖说明见[官方 factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000985factsheet.pdf)和[编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175438-000985_Index_Methodology_cn.pdf)。
3. `src/backend/app/tracking/models.py` 的 `Result.benchmark_code` 默认写死为 `000300.SH`。

裁定结论：第 1 项 `000300.SH` 是产品计算基准的唯一默认，用于 `simulated_tracking`，标「未验证」；§7.8 复盘四项口径在合入前一律 `value=null` 并记 `no_source`，有默认也不出值。第 2 项属于研究员外部验证信息，不作产品跟踪或复盘基准，不覆盖第 1 项；行业基准须有 PIT 行业归属和指数端点，现无来源，日后启用须先改契约。第 3 项与契约 `TrackingResult.benchmark_code` 非空一致，可保留，但须随证据留存，缺端点时收益和超额为 `null` 并记缺口，不得以 `000985.SH` 或行业指数替代，§7.8 不读取该模拟结果。原「策略配置优先」建议不采纳。行业历史成分、指数价格、端点可见性和复权版本任一缺失时，`benchmark_return.value` 与 `excess_return.value` 均为 `null`，顶层 `gaps` 记录相应缺口，不能用另一处基准替代。

**公式。**

```text
benchmark_return.value = 100 × (benchmark_exit_price / benchmark_entry_price − 1)
excess_return.value = holding_return.value − benchmark_return.value
```

个股和基准必须使用相同的入场时点、到期日、复权或总收益定义和可见性截止点。基准只有一个端点、停牌或来源状态不合格时不补邻日价格。相对基准的收益分解属于公开投资绩效评价常用做法，但本项目基准覆盖、历史版本和 A 股有效性未验证（待回测）。

**最少样本量。** 只有 `holding_return.value` 和 `benchmark_return.value` 同时非空的观测进入超额统计。`n<5` 返回空值，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。

### 2.5 实际成交复盘的期间最大回撤

**定义。** 单条观测的路径从 `entry_price` 开始，随后按持有期内已经可见的交易日收盘价排列，最后一点为 `exit_price`。T+1 只有入场和退出两点。只用证券自身价格，不按动作取反。

**公式。**

```text
peak_t = max(P_0, ..., P_t)
drawdown_t = 100 × (P_t / peak_t − 1)
max_drawdown.value = min_t(drawdown_t)
```

结果应小于或等于 0。聚合净值回撤以同一窗口的逐日净值曲线计算，不能把各条观测的回撤简单平均。最大回撤是公开绩效评价中的风险字段，方法资料见 [CFA Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation) 和 [Pardo《The Evaluation and Optimization of Trading Strategies》](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。

**输入、窗口与边界。** 输入为 `entry_price`、逐交易日 `close`、`exit_price`、复权因子版本、`data_as_of` 和 `gaps`。停牌日没有有效收盘价就跳过该日，不以前值填充。入场或退出端点缺失时回撤为 `null`。除权除息必须使用同一 `price_basis` 和同一可见因子版本，不能将原始价格与复权价格拼接。退市后没有可证明的清算价格时，状态为未平仓或不可用，不读未来复牌或退市后价格。除权、停牌、退市和未平仓分支的 A 股历史覆盖未验证（待回测）。

**最少样本量。** 单条完整路径可以计算单条回撤，但聚合回撤至少需要 5 条完整路径才展示数值，30 条以上才解除样本少标记。缺少入场或退出端点的路径不计入 `n`。

### 2.6 建议偏离

**定义与来源登记。** 该项只作实际成交与候选信号记录的并列研究，不能把无来源的建议字段当成可计算输入。现有成交接口 `GET /trades` 可核对以下字段。

| 用途 | 现有字段 | 来源状态 | 输出约束 |
|---|---|---|---|
| 成交日期、方向、标的 | `trade_date`、`side`、`security_code` | 有来源 | 只读成交记录 |
| 成交时间 | `trade_time`（可空） | 有来源但可空 | 为空时相关时间偏离 `null` |
| 成交数量、价格、费用 | `qty`、`price`、`fee_total`（可空） | 有来源 | 费用为空不能按零处理 |
| 记录可见性 | `created_at`、`voided`、`id` | 有来源 | 版本快照筛选未作废记录 |
| 建议价格与建议时点 | `suggested_price`、`suggested_at` | 无来源 | `enabled=false`，输出 `null`，顶层 `gaps` 记 `outcome_metrics.suggestion_deviation`/`no_source` |
| 建议仓位、订单量、账户权益 | `suggested_position_weight`、`order_qty`、`portfolio_equity_at_fill` | 无来源 | `enabled=false`，输出 `null`，不得臆造 |
| 撤改单、队列和成交状态 | 对应字段 | 无来源 | `enabled=false`，输出 `null`，不得推断无成交 |

因此，价格偏离、时间偏离、仓位偏离和完成度当前均为 `enabled=false`。只有将建议记录和上述实际成交字段一并冻结，并补齐来源后，才可按数量加权计算。当前不使用 `filled_price`、`filled_at`、`filled_qty`、`order_qty` 或 `portfolio_equity_at_fill` 作为接口字段名，因为现有成交接口没有这些字段。无来源不能写成零，缺口统一保留为 `null` 加顶层 `gaps`。实际成交、到达价和执行价之间的实现偏差是公开交易成本分析的常用分解，见 [CFA Research Foundation《Transaction Cost Measurement and Management》](https://www.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2015/rf-v2015-n4-1-pdf.pdf)。

**最少样本量。** 单笔实际成交即可记录偏离，不能据此判断策略执行质量。聚合偏离在 `n<5` 时不返回均值，`5≤n<30` 标记样本少，`n≥30` 才可作为正常执行摘要。无成交订单另计，不进入成交偏离的 `n`。

### 2.7 盈亏比与研究候选指标

**模拟跟踪盈亏比。** `simulated_tracking.profit_loss_ratio` 只使用模拟 `tracking.Result.return_pct`。`src/backend/app/tracking/service.py:173-197` 的 `profit_loss` 只筛选 `state=complete`、`action ∈ {buy, add, hold}`、非空且非零的 `return_pct`，`src/backend/app/tracking/api.py:97-122` 以 `profit_loss_ratio` 对外返回。公式为：

```text
simulated_tracking.profit_loss_ratio = 平均正 return_pct / |平均负 return_pct|
```

无亏损样本时为 `null` 并记 `no_losing_samples`。有亏损但没有盈利且样本达到计算门槛时为 0。`sell`、`reduce`、`wait` 不进入该模拟统计，仍可进入方向命中率。该字段只属于模拟研究，不能写入 §7.8 的 `holding_return`、`benchmark_return`、`excess_return`、`max_drawdown` 四项 `Stat`，也不使用实际 `holding_return` 作为来源。

**实际成交 `payoff_ratio` 研究候选。** 若保留实际成交盈亏比，单列输出字段 `execution_research.payoff_ratio`，只使用 `trades`/`feedback` 已冻结的成交段、逐笔费用和 `available_at <= calculation_as_of` 的可见时点。当前没有完整闭合的成交段和费用来源，因此默认 `enabled=false`，输出 `value=null` 并记录 `execution_research.payoff_ratio`/`no_source`。该候选与 `simulated_tracking.profit_loss_ratio` 相互独立，均不写入 §7.8 四项 `Stat`。

**最少样本量。** `simulated_tracking.profit_loss_ratio` 的有效 `n` 为正、负 `return_pct` 样本数之和。`n<5` 时返回空值，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。零收益既不进入盈利分子，也不进入亏损分母。实际成交候选沿用同一展示门槛，但缺来源时保持 `null`。

**`profit_factor` 研究候选指标，未入契约。** §7.8 没有该字段，因此本卡不把它放入 `outcome_metrics`，也不把它作为通过、观察或淘汰依据。默认 `enabled=false`。

```text
profit_factor = Σ盈利金额 / |Σ亏损金额|
```

若未来修订契约，至少需要可追溯的盈利金额、亏损金额、逐笔费用、持仓数量或名义金额、冻结快照和来源时点。当前这些输入没有完整来源，结果必须为 `null`，顶层 `gaps` 记录 `outcome_metrics.profit_factor`/`no_source`。不登记 PF 通过线或淘汰线。盈亏比、该研究候选指标、命中率和收益幅度的关系可参阅 [CFA Digest 关于 hit ratio 与 win/loss magnitude](https://rpc.cfainstitute.org/research/cfa-digest/2018/07/dig-v48-n7-8) 和 [Pardo《The Evaluation and Optimization of Trading Strategies》](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。

### 2.8 样本数门槛

**指标展示。** 每个指标分别计算有效 `n`，不可成交和缺值不进入该指标的 `n`。`n<5` 时 `value=null`，`5≤n<30` 时保留数值并置 `small_sample=true`，`n≥30` 才可作为正常展示。没有任何有效样本时 `n=0` 是真实计数，不等于数据缺失。

**入门闸刀候选线。** 总交易数至少 30 笔，每个样本外折至少 10 笔，至少 5 个按时间不重叠的样本外折。低于任一项不能标记为“回测过”。这些是 T-A213 的候选工程线，公开研究只说明样本长度和重复试验会影响显著性，不能证明 30、10、5 对 A 股有效。[Bailey 与 López de Prado《The Deflated Sharpe Ratio》](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)；[Bailey 等《The Probability of Backtest Overfitting》](https://www.carmamaths.org/resources/jon/backtest2.pdf)；[Pardo《The Evaluation and Optimization of Trading Strategies》](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。状态为未验证（待回测）。

**统计窗口。** 逐信号窗口为 T+1、T+5、T+20。聚合报告必须同时写 `window_start`、`window_end`、`as_of`、策略版本、动作、基准、成本表和有效 `n`。不能以最近一次完成结果覆盖窗口内旧观测，也不能只保留通过样本。

## 3. 实盘与样本外回测偏差及降级

### 3.1 对齐条件

实盘组和样本外回测组必须使用同一候选信号版本、同一动作、同一周期、同一标的范围、同一基准、同一交易日历、同一成本表和同一可成交规则。实盘只使用真实成交和实际费用，未成交订单不能按理想价计入。回测组使用锁定后的样本外结果，不能在比较期间调参或扩大标的范围。

### 3.2 偏差公式与候选降级线

以相同窗口的 OOS 指标为基准，按日或按已配对的候选信号形成收益差序列。对配对日收益做保持时间相关性的区块 bootstrap，使用单侧 95% 置信区间。定义：

```text
Δ_P = (P_live − P_OOS) / max(|P_OOS|, ε)
Δ_SR = Sharpe_live − Sharpe_OOS
Δ_MDD = (MDD_live − MDD_OOS) / max(|MDD_OOS|, ε)
```

以下是接 T-A213 的候选降级规则，全部标记未验证（待回测）：置信区间排除 0 且 `Δ_P ≤ −30%`，或 `Δ_SR ≤ −0.50`，或 `Δ_MDD ≥ 50%`，则策略版本状态降级为“观察中”。`P` 必须预先指定为净收益或净超额，不能比较一组毛收益和一组扣费收益。实盘和 OOS 各自少于 30 个有效配对样本时，不自动改变状态，只显示样本不足和缺口。固定 30%、0.50、50% 不是公开文献给出的 A 股监管线，公开来源只支持按样本长度、选择偏差和风险指标进行比较。[Bailey 与 López de Prado《The Deflated Sharpe Ratio》](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)；[Bailey 等《The Probability of Backtest Overfitting》](https://www.carmamaths.org/resources/jon/backtest2.pdf)。

**最少样本量。** 实盘和 OOS 两侧各自至少 30 个有效、已结束且可配对的观测才允许触发自动状态判定。低于 30 只报告偏差和缺口，不改变生命周期状态。该 30 的比较门槛未验证（待回测）。

### 3.3 状态边界

“观察中”只表示实盘相对 OOS 的偏差达到预先登记的候选线，或处于 T-A213 明确的降级区间。它不表示已经证伪，也不产生新的候选信号。触发后冻结比较所用的版本、窗口、样本和证据，等待研究员复核和重新回测。没有足够样本、基准端点缺失、可成交性未知或未来可见性不完整时，保持“数据不足/未验证”，不能强行降级或宣称通过。

## 4. 共同边界处理

| 情形 | 处理 | 统计影响 |
|---|---|---|
| 分红、送转、除权除息 | 个股和基准使用同一 `price_basis`、同一复权因子版本和 `as_of`。因子时点或事件链不可证时不拼接原始价与复权价 | 相关收益、超额和回撤为 `null` 或单列缺口，不能用当前复权值回填历史 |
| 停牌 | 不把停牌日当作零收益或可成交日，不以前值制造退出 | 入场或退出受阻记 `untradable`/`unavailable`，不进入正常命中率分母 |
| 涨停买入 | 买单无可成交证据时不入场 | 不计入有效命中率，单列不可成交数和比例 |
| 跌停卖出 | 卖单无可成交证据时不补成交 | 保留未平仓或不可用状态，不能用之后复牌价补成交 |
| 退市 | 只使用退市前已可见且可成交的最后证据 | 无清算成交时不伪造退出价，记未平仓或不可用 |
| 未平仓 | 截止时点没有真实退出或可证明模拟退出 | 不进入已完成命中率和盈亏比，另报未平仓数及账面标记 |
| 分笔或部分成交 | 价格、时间按成交数量加权，记录完成度和未成交数量 | 部分成交按实际数量计，未成交部分计机会成本，不按全量成交 |
| 同一根 K 线触及目标与止损 | 无法证明先后时按止损优先或标记顺序未知 | 不得用收盘方向替代盘中顺序，相关样本单列 |

上述边界要求依据交易所公开规则建立，具体数据源覆盖、历史复权链、退市清算和队列成交仍未验证（待回测）。

## 5. 公开出处与访问核验

以下链接均为公开出处。它们用于支持交易约束、指数定义、绩效指标方法或选择偏差方法，不把公开论文当作 A 股有效性证明。基准与回撤直接相关的链接在写入前用 `curl -I -L` 核验，记录日期为 2026-11-21。

| 出处 | 用途 | 状态 |
|---|---|---|
| 上交所 2026 交易规则 | T+1、停牌、涨跌幅、成交边界 | 规则公开，历史适用性待回测 |
| 深交所 2026 交易规则 | T+1、停牌、涨跌幅、成交边界 | 规则公开，历史适用性待回测 |
| 中证沪深300 factsheet | 默认基准代表性、代码 000300 | 公开，覆盖与复权链待回测 |
| 中证沪深300编制方法 | 指数样本和发布口径 | 公开，接入待回测 |
| 中证全指 factsheet | 广义稳健性基准、代码 000985 | 公开，覆盖与复权链待回测 |
| 中证全指编制方案 | 全市场范围与样本说明 | 公开，接入待回测 |
| 证监会佣金通知 | 佣金上限与最低收费 | 规则公开，券商实际费率待核 |
| 国家税务总局税费汇编 | 印花税历史时点 | 规则公开，历史适用性待回测 |
| CFA Research Foundation 交易成本资料 | 到达价、执行价、实现偏差 | 方法公开，A 股字段接入未验证 |
| CFA Digest hit ratio 资料 | 命中率和平均胜负幅度的关系 | 方法公开，阈值未验证 |
| CFA Portfolio Performance Evaluation | 最大回撤等绩效风险指标 | 方法公开，A 股阈值未验证 |
| Bailey DSR | 样本长度、选择偏差、风险调整绩效 | 方法公开，固定门槛未验证 |
| Bailey PBO/CSCV | 样本外与过拟合概率方法 | 方法公开，固定门槛未验证 |
| Pardo 交易策略评价 | 滚动样本外、成本和回撤评价 | 方法公开，固定门槛未验证 |

### 5.1 基准、复权与区间来源登记

| 来源或能力 | 支持内容 | URL | curl 状态 | enabled | 说明 |
|---|---|---|---:|---:|---|
| 沪深300 factsheet | 基准指数为 000300，300 只规模大且流动性高的 A 股，目标为反映中国 A 股整体表现 | [CSI 300 factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300factsheeten.pdf) | 200 | true | 内部代码 `000300.SH` 的后缀映射仍需数据层验收 |
| 沪深300编制方法 | 价格指数、总收益指数和净总收益指数的计算，以及现金分红导致的参考开盘价调整 | [CSI 300 methodology](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300_Index_Methodology_en.pdf) | 200 | true | 公开方法区分价格、总收益和净总收益，不能证明本项目已接入因子链 |
| 绩效评价方法 | 同一评价区间比较、超额收益和最大回撤作为绩效风险指标 | [CFA Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation) | 200 | true | 支持方法口径，不证明 A 股数据覆盖 |
| 基准历史价格数据源 | `benchmark_return` 的入场和退出端点 | — | 未找到 | false | #356 没有接入基准价格来源，标记未验证 |
| 个股与基准复权因子版本链 | `holding_return`、`benchmark_return`、`max_drawdown` 的同口径复权 | — | 未找到 | false | #356 没有价格路径或因子版本输入，标记未验证 |
| 交易日历端点服务 | 区间端点、T+1/T+5/T+20 与 `not_yet_published` 判定 | — | 未找到 | false | #356 仅按工作日近似，标记未验证 |

### 5.2 阈值状态汇总

本表明确列出 7 项数值或工程规则，均标记为未验证（待回测）。其余数据覆盖、复权链、退市清算和队列成交缺口在相应指标和边界表中单独标记，不能视为通过。

| 阈值或规则 | 当前状态 |
|---|---|
| T+1/T+5/T+20 | 产品窗口规则有公开交易日约束，具体策略表现未验证（待回测） |
| hold 阈值 1%/2%/5% | 初值，未验证（待回测） |
| `n<5`、`n<30` 展示门槛 | 与现有统计字段对齐，A 股统计有效性未验证（待回测） |
| 总样本 30、每折 10、至少 5 折 | 候选闸刀线，未验证（待回测） |
| `profit_factor` | §7.8 无此字段，研究候选且 `enabled=false`；金额、费用和冻结来源未接入 |
| 实盘相对 OOS −30%、Sharpe −0.50、MDD +50% | 候选降级线，未验证（待回测） |
| 目标/止损同柱按最坏顺序 | 工程保守规则，未验证（待回测） |

本卡不声明任何策略已通过 G6、已进入 `published` 或已完成实盘验证。所有无 A 股实证的数值保留“未验证”或“待回测”状态。

## 6. §7.8 字段对齐与实现边界

### 6.1 #349@2fd6730c 草案字段（未合入）

| 字段 | 草案类型、单位与空值语义（以合入版本为准） |
|---|---|
| `data_status` | `fresh`、`stale`、`pending`、`partial`、`unavailable`；无单位；不得把未知当作 `fresh` |
| `data_as_of` | `string(datetime)` 或 `null`；实际使用来源的知识时点，无来源为 `null` |
| `gaps` | `Gap[]`；`{key:string, reason:gap_reason, message:string}`；无单位；reason 为 `no_source`、`not_yet_published`、`upstream_error`、`quota_deferred`、`user_input_missing`、`data_licence_unavailable`、`not_applicable` 或 `suspended`，未知 reason 原样保留 |
| `ReviewSummary.id`、`ReviewVersion.id` | `string(uuid)`，必填 |
| `plan_id` | `string(uuid)` 或 `null`；无单位 |
| `security_code` | `string` 或 `null`；证券代码 |
| `name` | `string` 或 `null`；代码为空时必须为 `null`，代码存在但主数据缺失可回退为代码 |
| `period_start`、`period_end` | `string(date)`，必填；闭区间，结束日不早于开始日 |
| `current_version_no`、`version_no` | `int`；草案规定前者至少 1，后者从 1 连续递增；无单位 |
| `current_version` | `ReviewVersion` 或 `null`；新建记录必有，旧数据缺版本时为 `null` |
| `plan_version_ids`、`trade_ids` | `string(uuid)[]`，必填；空集为 `[]` |
| `snapshot_id` | `string(uuid)` 或 `null`；历史缺快照保留 `null` |
| `lessons` | `string` 或 `null`；无单位 |
| `tags` | `string[]`；无标签为 `[]` |
| `attribution` | `{judgement: ReviewJudgement[], execution: TextWithEvidence[], market: TextWithEvidence[]}`；三类均可为空数组 |
| `outcome_metrics` | 四项 `Stat`：`holding_return`、`benchmark_return`、`excess_return`、`max_drawdown`；百分数单位，未知 `value=null` |
| `Stat.value` | `string(decimal)` 或 `null`；百分数，未知不得写 `"0"` |
| `Stat.n` | `int` 且 ≥0；真实有效样本数，无单位 |
| `Stat.window` | `string`，`YYYY-MM-DD/YYYY-MM-DD`；复盘窗口 |
| `Stat.small_sample` | `boolean`；`n<30` 为 `true`，`n≥30` 为 `false` |
| `timeline` | `ReviewTimelineItem[]`，按 `at` 升序；无事件为 `[]` |
| `ReviewTimelineItem` | `{kind: "review_version"|"plan_version"|"trade", at:string(datetime), resource_id:string(uuid)|null, version_no:int|null, evidence_ids:string[]}`；kind 为闭集枚举，数组无证据时为空 |
| `ReviewJudgement` | `{condition_text:string, fulfilled:boolean|null, note:string|null}`；`fulfilled=null` 表示未知 |
| `evidence` | `Evidence[]`；无证据为 `[]`，ID 只在本详情内解析 |

指标缺口只通过版本顶层 `DataStatusBlock.gaps` 对外表达。`Stat` 不新增 `gaps`、`source` 或 `label` 字段，除非先修订 §7.8。草案明确四项 `Stat` 只按实际可见成交和快照时点计算，模拟跟踪不进入这些字段。

### 6.2 `not_yet_published` 与模拟跟踪

`not_yet_published` 只表示结果期尚未结束或尚未到达草案规定的可发布时点，不表示收益为零，也不表示策略失败。此时四项指标的 `value` 均为 `null`，顶层 `data_status` 为 `pending`，顶层缺口使用该 reason；周期结束后仍缺来源则改用 `no_source` 或其他适用 reason。

模拟跟踪与实际成交复盘必须有独立的来源标签和存储边界。模拟结果只能标为“模拟跟踪”，实际成交结果只能标为“实盘成交复盘”；任何模拟结果进入复盘投影时均清空指标值并记录 `no_source`。对外叙述统一使用“候选信号”，不承诺收益，不把模拟跟踪写成实盘绩效。

### 6.3 实现参照

本卡对照 `eccb3d25` 的实现行号。该提交不是本卡的验收证明，缺失来源仍保持未验证。#349@2fd6730c 草案（未合入）仅作只读对照，以合入版本为准。

| 实现位置 | 结论 |
|---|---|
| `src/backend/app/reviews/metrics.py:18-24` | `Stat` 的百分数字符串、`n<5` 空值、`n<30` 小样本与草案结构相符 |
| `src/backend/app/reviews/metrics.py:14,51-60` | reason 只保留三项且会丢弃未知值，与 §7.8 完整枚举和原样保留要求不一致 |
| `src/backend/app/reviews/metrics.py:81-97` | `not_yet_published` 用工作日近似，未接交易日历，待后端改 |
| `src/backend/app/reviews/metrics.py:117-127` | 模拟来源被清空并改为 `no_source`，需保留用户可见的“模拟跟踪”标签边界 |
| `src/backend/app/reviews/service.py:171-197,210-240` | 仅从真实 execution 成交计算 holding，benchmark 与 drawdown 暂无来源，均为 `no_source` |
| `src/backend/app/reviews/service.py:185-191` | 以 `traded_at` 作为可见时点，未满足 `available_at` 约束，待后端改 |
| `src/backend/app/reviews/service.py:393-402,405-428` | 顶层状态、时间点与版本字段基本对齐，但状态读取再次按当前时钟判断，需冻结计算时点 |
| `src/backend/app/reviews/service.py:432-448` | 时间线三种闭集 kind、升序和证据 ID 与草案结构相符 |
| `src/backend/app/reviews/service.py:457-488` | summary/detail 字段齐全；旧数据无当前版本时 summary 仍可能输出 `current_version_no=null`，与草案 `≥1` 有差异 |

## 7. 收口状态

本卡仍为 `draft`，G7 保持 `☐`。#349@2fd6730c 草案（未合入）仅作为只读字段对照，以合入版本为准。基准历史价格、复权因子链、交易日历和最大回撤价格路径未接入前，相关指标保持 `value=null`、缺口和“未验证”，不得据此宣称策略有效或产生收益承诺。

# T-R116 复盘页指标口径与出处

- `lifecycle: draft`
- `G7: ☐`
- 口径范围：只统计用户本人持仓、自选和已出候选信号的自然积累，不跑全市场。
- 角色：策略研究员。本文只定义模拟跟踪指标，不荐股、不构成交易指令、不承诺收益。本页不是 #349 §7.8.4 的 `ReviewOutcomeMetrics`；定稿前该四项仍为 `value=null, n=0`，并保留 `outcome_metrics.<名>/no_source`，前端不得用 `TrackingResult` 填充。
- 基准分支：`origin/main`。路径与行号是主线核对结果。表中“主线”描述现有实现，“需后端补”描述当前不存在的字段或计算链。
- 时间规则：所有 `created_at`、`entry_at`、`exit_at`、`fetched_at` 和证据时间均按带时区的北京时间比较。输入只可使用指标时点已经可见的快照。收盘价须满足交易日 15:00 已闭市，不能用生成后才出现的字段回填触发时点。

## 共同分母与价格口径

有效样本只包含 `state=complete` 且所需值非空的观测。`pending` 是尚未到期，`unavailable` 是到期但缺计算数据，`untradable` 是停牌或涨跌停等不可成交，`excluded` 是 `wait`、`forced_hold` 或其他规则排除。以上四类不进入有效样本 `n`，但必须分别计数并展示原因。无结果显示 `unavailable` 数据状态和 gap，不能把缺数当失败。

买入或加仓的模拟入场取可见的下一可成交价格。T+1 只约束卖出或退出的可执行性，`sellable_at` 仅是可卖边界，不得用于信号触发、观察起点或命中判定。RC1 触发按不复权价格和各自可见时点判定，盘中用新鲜最新价，收盘后用当日 low/high 补判，事件时点分别为价格时间戳或当日 15:00（北京时间），依据 `origin/main` `docs/api-contract.md:1299-1303`。主线已有 `due_date`、`entry_at`、`exit_at` 的交易日历与可见性保护，但没有独立 `sellable_at`，需后端补齐。

现行收益口径是主线毛收益。`return_pct`、`benchmark_return_pct` 和 `excess_pct` 使用同一 as-of 的 qfq 序列，原始成交可成交性使用不复权价格。`候选口径（需后端补费用字段）` 才可使用佣金、印花税、过户费和其他费用计算净收益及净超额收益，当前不进入现行指标公式。A 股适用费率和指标效果仍未验证；现有上交所费率页仅作参考。

## 指标表

| 指标 | 计算公式（现行口径、时点与可卖约束） | 所需字段与现有来源（路径:行号） | 小样本处理 | 公开出处 URL 或同类产品做法 | 结论 |
|---|---|---|---|---|---|
| 候选信号命中率 | `wins / n`。`wins` 是 `state=complete` 且 `direction_correct=true` 的条数，`n` 是 `direction_correct` 非空条数。主线按毛 `excess_pct` 判定，买入/加仓要求 `excess_pct > 0`，卖出/减仓要求 `< 0`，持有沿用周期阈值，`wait` 不判定。T+1 只约束实际卖出或退出执行，触发、观察和命中时点沿各自可见 as-of。 | `Result` 字段见 `src/backend/app/tracking/models.py:14-39`；毛收益计算和超额收益见 `src/backend/app/tracking/engine.py:261-290`；方向判定见 `src/backend/app/tracking/engine.py:76-83,334-351`；聚合见 `src/backend/app/tracking/api.py:95-125`。净费用字段、`sellable_at`、逐项费率和费用金额需后端补。 | `n<5` 的 value 为 `null`，`n<30` 标 `small_sample=true`。 | 同类产品公开定义胜率为盈利交易数除总交易数：[QuantConnect PortfolioStatistics](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/backtest-statistics)。 | 仓内定义（主线毛收益方向统计已实现） |
| 候选信号盈亏比 | 只取有效 `buy/add/hold` 的毛 `return_pct`，零收益不计。`平均盈利 / |平均亏损|`，无亏损为 `null + no_losing_samples`，有亏损无盈利为 0。主线聚合不扣费用。`候选口径（需后端补费用字段）` 可另行评估净费用版本，不能替代现行公式。 | 主线 `profit_loss` 取毛 `return_pct`，见 `src/backend/app/tracking/service.py:173-197`；聚合入口见 `src/backend/app/tracking/api.py:95-125`；契约毛收益定义见 `docs/api-contract.md:1346-1353`。费用金额与费率需后端补。 | 沿 `Stat` 规则 `n<5` 为 `null`，`n<30` 为 `small_sample`，缺亏损 gap 不变。 | QuantConnect 将 profit-loss ratio 定义为平均盈利与平均亏损的比值，并展示交易费：[Backtest Statistics](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/backtest-statistics)。 | 仓内定义（现行公式为毛收益；候选口径（需后端补费用字段）未验证） |
| 候选信号后 N 日表现 | N 取 `1、5、20` 个交易日。现行结果 `return_pct` 和 `excess_pct` 的毛收益及毛超额收益。`entry_at` 为信号时点后首个可成交价；若 `exit_at` 代表卖出执行，则不得早于 `sellable_at`。观察端点按 N 个开市日取当时可见收盘，不以 `sellable_at` 作触发或观察起点。停牌或涨停锁买、跌停锁卖无法成交时置 `untradable`，数据缺失置 `unavailable`。 | 主线接口保留 `t1/t5/t20`，见 `src/backend/app/tracking/models.py:60-67`；结果字段与 qfq、状态见 `src/backend/app/tracking/models.py:14-39`；N 值契约见 `docs/api-contract.md:1336-1344`；费用和独立 `sellable_at` 需后端补。 | 各 N 独立计数，`n<5` 不显示数值，`n<30` 显示 `small_sample`。 | N 值为仓内契约定义。T+1 结算的公开同类说明见 [Investor.gov T+1](https://www.investor.gov/introduction-investing/investing-basics/glossary/settling-securities-transactions-t1)，不据此证明 A 股全部细则。 | 仓内定义（N 为仓内定义，费用与 T+1 执行边界待补） |
| 止损触发统计 | 对有明确 `stop_loss` 的买入/持有计划，按 RC1 的不复权可成交价和首个可见时点判定 `price <= stop_loss`，记录 `triggered / eligible`。盘中使用新鲜最新价，收盘后以当日 low 补判，事件时点不受 T+1 影响。触发后的实际退出若存在仍须满足 `sellable_at`，涨停锁卖、停牌或无可成交价不得记为成交退出。 | 规则见 `origin/main` `docs/api-contract.md:1299-1303`；候选 `stops` 见 `src/backend/app/db/tables/signals.py:76-105`；计划条件见 `src/backend/app/db/tables/research.py:228-245`；结果字段见 `src/backend/app/tracking/models.py:32-39`。触发事件、命中价、可成交状态和事件快照需后端补。 | `eligible<5` 不显示比率。停牌、涨跌停和缺价另列计数，不并入分母。 | 未找到可直接证明本项目规则的公开出处，外部同类产品通常记录 stop/take-profit 事件。 | 未验证，不建议默认启用 |
| 止盈触发统计 | 对有明确 `take_profit` 的买入/持有计划，按 RC1 的不复权可成交价和首个可见时点判定 `price >= take_profit`，记录 `triggered / eligible`。盘中使用新鲜最新价，收盘后以当日 high 补判，事件时点不受 T+1 影响。触发后的实际退出若存在仍须满足 `sellable_at`，涨停锁卖、停牌或缺价不得记为成交退出。 | 规则见 `origin/main` `docs/api-contract.md:1299-1303`；`stops` 和计划字段见 `src/backend/app/db/tables/signals.py:76-105`、`src/backend/app/db/tables/research.py:228-245`。触发事件、命中价、可成交状态和事件快照需后端补。 | `eligible<5` 显示 `null` 和原因，停牌、涨跌停、缺价单列。 | 未验证，未找到可直接证明本项目规则的公开 URL。 | 未验证，不建议默认启用 |
| 违反自身计划次数 | 现行只按 RC6 两项投影。计划版本有效期是半开区间 `[生效时刻, 被替代/关闭时刻)`，与 `executed_at` 比较；同方向计划内累计未冲正/未撤销成交数量 **>** 计划数量才触发 `qty_over_plan`，等于不触发，每个版本和检查只记一次；没有同方向计划时才判 `opposite_side`。仅有日期的成交按当日 15:00 比较，边界不明则 `unknown + gap`。价格范围、失效条件后成交等扩展项不属于当前 RC6 判定，不在本页另立定义。 | 契约原判定见 `origin/main` `docs/api-contract.md:1362-1363`；主线支持项和半开区间选择见 `src/backend/app/feedback/plans.py:22,87-123,152-164`；累计与两项 flag 见 `src/backend/app/feedback/plans.py:195-244`；数据库投影见 `src/backend/app/feedback/plan_source.py:58-123,124-182`。计划违反事件持久化、完整 qty/price 可执行投影及扩展项需后端补。 | `eligible_trades<5` 不显示比率，次数可显示但注明样本不足。RC6 缺字段进入 `unavailable`，不算遵守或违反。 | 未验证，未找到同类产品对“自身计划违反”的统一公开定义。 | 仓内定义（RC6 两项投影已有，事件链和扩展项待后端补） |
| 分策略汇总 | 按不可变 `strategy_version_id` 分组，分别计算命中率、盈亏比、N 日表现、止损/止盈触发和计划违反。观测唯一键为 `(suggestion_id, strategy_version_id, horizon_days)`，同一建议多个实例只保留一条，不跨策略合并。收益沿现行毛收益口径。 | 版本聚合表见 `src/backend/app/db/tables/strategy.py:266-297`；建议绑定与去重见 `src/backend/app/tracking/service.py:136-166`；事件明细需后端补。 | 每个策略版本独立执行 `n<5`、`n<30` 规则，不用总记录数替代有效 n。 | 同类产品提供按策略/回测结果的胜率和盈亏比汇总：[QuantConnect Backtest Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)。 | 仓内定义（策略聚合已有部分字段） |
| 分周期汇总 | 按策略声明周期分组，做 T `intraday_t→1`、短线 `short→5`、波段 `swing→20`、中长线 `long→20` 个交易日。多周期版本没有唯一声明时跳过并记 gap，不能取数组首项。每组沿用毛收益、qfq、可见时点和状态分母规则，T+1 只约束实际退出执行。 | 周期映射和未知跳过见 `docs/api-contract.md:1358`；结果仅有 `horizon_days`，见 `src/backend/app/tracking/models.py:14-19`；策略声明周期绑定与分组字段需后端补。 | 每个周期独立标记 `small_sample`，不跨周期合并凑 n。 | 周期值为仓内契约定义，未找到能证明本项目映射的外部 URL。 | 仓内定义（多周期完整投影未实现） |
| 样本量与窗口展示 | 最近 120 个交易日窗口按 `as_of` 截断，`n<5` 所有比率和均值为 `null`，`5≤n<30` 展示数值并标 `small_sample`，`n≥30` 才允许作为常规描述。窗口外样本不进入分母，状态计数仍可单列。120 日数值未验证，不把占位窗口写成契约承诺。 | 主线只在 `src/backend/app/strategy/promotions.py:220`、`src/backend/app/strategy/reviews.py:178` 生成 `120 trading days` 的空值占位；`stat` 的 `n>=5` 与 `small_sample` 见 `src/backend/app/tracking/service.py:507-515`。T-R112 `#383@3fd9c9fc` 未合入且标为数值未验证，窗口过滤字段需后端补。 | 以上规则是展示门槛，不为显示而虚增 n，不把 `pending/unavailable/untradable/excluded` 计入有效 n。 | `n>=30` 仅为统计经验法则，A 股有效性未验证，不把它写成收益保证。 | 未验证 |
| 状态与可见时点审计 | 对每条观测保存建议生成、入场、退出、数据快照 `as_of`、首次可见时间、交易日历和证据哈希。任何在触发或观察时点不可见的数据都不得进入公式。停牌、涨停锁买、跌停锁卖进入 `untradable`，`wait/forced_hold` 进入 `excluded`，日历缺失或复权桥缺失进入 `unavailable`。 | 交易日历和 `fetched_at` 截断见 `src/backend/app/tracking/service.py:62-108,121-133`；结果证据与 gap 见 `src/backend/app/tracking/models.py:34-39`；状态计数见 `src/backend/app/tracking/api.py:115-125`。费用、`sellable_at` 和事件快照需后端补。 | 无法证明可见时点即不计有效样本，保留 gap 和状态计数。 | 主线契约 `docs/api-contract.md:1336-1344` 已明确 `pending/unavailable/untradable/excluded` 处理，外部 URL 未验证。 | 仓内定义（主线已有大部分状态保护，可见性审计链待补） |

## 主线现状与待实现边界

- 主线已实现建议级 1、5、20 交易日结果结构、交易日历、北京时间收盘可见性、qfq 结果字段、原始价格证据、停牌/涨跌停/`wait`/`forced_hold` 状态和策略级匿名聚合。
- 主线尚未证明费用已经进入 `return_pct`，当前 `cost_applied` 默认可为 `false`，也没有佣金、印花税、过户费逐笔费率快照。主线也没有独立 `sellable_at`、止损止盈命中事件或计划违反事件的持久化链；RC6 两项投影本身已在主线，但完整历史覆盖仍可能给出 gap。
- §7.11.3 与本页中的 T+1、费用和窗口要求是文档口径。契约标记为 `status: draft` 的内容不能写成已验收。T-R112 `#383@3fd9c9fc` 与 T-R115 `#403@7e6e3a99` 均为未合入分支，T-R115 只作为验证计划引用，不把计划当实现证据。
- 展示文案统一使用“候选信号”和“模拟，不代表实际收益”。不输出荐股结论，不跑全市场规则有效性检验。

## 需后端补字段清单与计数

需后端补 7 项，按评审合并同类项排列。

- P1：`sellable_at` 与 T+1 入场/退出约束；净收益费用拆分与费率快照（先由架构师裁定契约）；可见时点审计链。
- P2：策略版本分组与周期映射；止损与止盈触发事件；计划违反事件与计划版本 qty/price 可执行投影；A 股适用费率与指标效果。

指标行 10：有据 0、仓内定义 8、未验证 2。该计数逐行统计结论，不能用“需后端补”7 项分类替代；已有字段和接口不列入补字段清单。

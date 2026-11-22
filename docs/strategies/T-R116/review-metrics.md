# T-R116 复盘页指标口径与出处

- `lifecycle: draft`
- `G7: ☐`
- 口径范围：只统计用户本人持仓、自选和已出候选信号的自然积累，不跑全市场。
- 角色：策略研究员。本文只定义复盘与跟踪指标，不荐股、不构成交易指令、不承诺收益。
- 基准分支：`origin/main`。路径与行号是主线核对结果。表中“主线”描述现有实现，“待后端补”描述当前不存在的字段或计算链。
- 时间规则：所有 `created_at`、`entry_at`、`exit_at`、`fetched_at` 和证据时间均按带时区的北京时间比较。输入只可使用该指标时点已经可见的快照。收盘价须满足交易日 15:00 已闭市，不能用生成后才出现的字段回填触发时点。

## 共同分母与价格口径

有效样本只包含 `state=complete` 且所需值非空的观测。`pending` 是尚未到期，`unavailable` 是到期但缺计算数据，`untradable` 是停牌或涨跌停等不可成交，`excluded` 是 `wait`、`forced_hold` 或其他规则排除。后三类不进入有效样本 `n`，但必须分别计数并展示原因。无结果显示 `unavailable` 数据状态和 gap，不能把缺数当失败。

买入或加仓的模拟入场取可见的下一可成交价格。A 股买入后最早可卖日为下一个交易日，T+1 约束必须使卖出或止盈止损观察不早于该日。现有主线在 `due_date`、`entry_at` 和 `exit_at` 上已有交易日历与可见性保护，但没有独立的 `sellable_at` 字段，需后端补齐并覆盖盘前创建的 T+1 边界。

收益使用同一 as-of 的前复权（qfq）序列，原始成交可成交性使用不复权价格。净收益应为
`(卖出金额 - 买入金额 - 佣金 - 印花税 - 过户费 - 其他可确认费用) / 买入金额 × 100`。
佣金费率由券商和账户约定，当前未验证。上交所公开费率页列出经手费、过户费和卖方印花税，可作费率来源参考，实际适用范围须由后端按市场规则确认：[SSE Trading Fees and Levies](https://english.sse.com.cn/access/stockconnect/settlement/)。

## 指标表

| 指标 | 计算公式（含 T+1 可卖约束、费用、复权口径、入场价与时点定义） | 所需字段与现有来源（路径:行号） | 小样本处理 | 公开出处 URL 或同类产品做法 | 结论 |
|---|---|---|---|---|---|
| 候选信号命中率 | `wins / n`。`wins` 是 `state=complete` 且 `direction_correct=true` 的条数，`n` 是 `direction_correct` 非空条数。买入/加仓要求净超额收益 > 0，卖出/减仓要求净超额收益 < 0，持有沿用周期阈值，`wait` 不判定。入场从候选信号 `created_at` 后的下一可成交时点开始，买入卖出遵守 T+1。收益使用同一 as-of qfq 开盘/收盘价并扣佣金、印花税、过户费和已确认其他费用。 | 主线已有 `Result.direction_correct`、`state`、`entry_at`、`exit_at`、`excess_pct`、`price_basis`、`cost_applied`，`src/backend/app/tracking/models.py:14-39`；判定在 `src/backend/app/tracking/engine.py:76-83,334-351`。净收益字段、`sellable_at`、逐项费率、费用金额需后端补。 | `n<5` 的 value 为 `null`，`n<30` 标 `small_sample=true`。 | 同类产品公开定义胜率为盈利交易数除总交易数：[QuantConnect PortfolioStatistics](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/backtest-statistics)。 | 仓内定义（主线方向统计已实现，T+1 净费用口径待补） |
| 候选信号盈亏比 | 只取有效 `buy/add/hold` 的净收益，零收益不计。`平均盈利 / |平均亏损|`，无亏损为 `null + no_losing_samples`，有亏损无盈利为 0。入场为候选信号生成后首个可成交价，买入后的卖出不得早于 T+1。每笔收益用同一 as-of qfq 端点并扣佣金、卖方印花税、过户费和其他可确认费用。 | 主线 `profit_loss` 只用毛 `return_pct` 且 `cost_applied=false`，`src/backend/app/tracking/service.py:174-197`；策略聚合入口 `src/backend/app/tracking/api.py:95-125`；费用金额与费率需后端补。 | 沿 `Stat` 规则 `n<5` 为 `null`，`n<30` 为 `small_sample`，缺亏损 gap 不变。 | QuantConnect 将 profit-loss ratio 定义为平均盈利与平均亏损的比值，并展示交易费：[Backtest Statistics](https://www.quantconnect.com/docs/v2/cloud-platform/api-reference/backtest-management/read-backtest/backtest-statistics)。 | 仓内定义（主线毛收益已有，净费用未验证） |
| 候选信号后 N 日表现 | N 取 `1、5、20` 个交易日。净收益为上述净收益公式，另报净超额收益 `net_return - benchmark_net_return`。`entry_at` 为候选信号时点后首个可成交价，买入的 `exit_at` 至少为首个 T+1 可卖日，之后按 N 个开市日取可见收盘。停牌或涨停锁买、跌停锁卖无法成交时不造价，置 `untradable`；数据缺失置 `unavailable`。 | 主线接口保留 `t1/t5/t20`，`src/backend/app/tracking/models.py:60-67`；结果字段与 qfq/状态见 `src/backend/app/tracking/models.py:14-39`；N 值契约 `docs/api-contract.md:1336-1344`。净费用和独立 `sellable_at` 需后端补。 | 各 N 独立计数，`n<5` 不显示数值，`n<30` 显示 `small_sample`。 | N 值为仓内契约定义。T+1 结算的公开同类说明见 [Investor.gov T+1](https://www.investor.gov/introduction-investing/investing-basics/glossary/settling-securities-transactions-t1)，不据此证明 A 股全部细则。 | 仓内定义（N 为仓内定义，净成本与 T+1 边界待验证） |
| 止损触发统计 | 对有明确 `stop_loss` 的买入/持有计划，按不复权、可成交价的首个北京时间可见时点判定 `price <= stop_loss`，并记录触发率 `triggered / eligible`。触发后的实际退出仍须满足 T+1，涨停锁卖、停牌或无可成交价不得记作已触发成交。止损价格和成交回报按各自时点留证，收益端再用同一 as-of qfq 并扣全费用。 | 止损定义在 `docs/api-contract.md:640,737`，候选 `stops` 在 `src/backend/app/db/tables/signals.py:76-105`，计划条件在 `src/backend/app/db/tables/research.py:228-245`。`invalidation_triggered_at` 仅是结果字段，`src/backend/app/tracking/models.py:32-39`，缺 stop 类型、命中价、可成交状态和事件快照，需后端补。 | `eligible<5` 不显示比率。停牌、涨跌停和缺价另列计数，不并入分母。 | 未找到可直接证明本项目规则的公开出处，外部同类产品通常记录 stop/take-profit 事件。 | 未验证，不建议默认启用 |
| 止盈触发统计 | 对有明确 `take_profit` 的买入/持有计划，按不复权、可成交价的首个北京时间可见时点判定 `price >= take_profit`，按 `triggered / eligible` 统计。买入后最早可卖日遵守 T+1，涨停锁卖、停牌或缺价不记为成交触发。收益仍按同一 as-of qfq 端点并扣全费用。 | `stops` 和计划字段来源同上，`src/backend/app/db/tables/signals.py:76-105`、`src/backend/app/db/tables/research.py:228-245`；触发事件、命中价格、可成交状态、费用字段需后端补。 | `eligible<5` 显示 `null` 和原因，停牌、涨跌停、缺价单列。 | 未验证，未找到可直接证明本项目规则的公开 URL。 | 未验证，不建议默认启用 |
| 违反自身计划次数 | 先冻结计划版本、动作、数量/金额、价格范围、止损止盈和条件可见时点。确定性判定为已确认成交在计划有效期内，且方向不符，或数量/价格超出冻结范围，或成交发生在已满足失效条件之后。部分成交按成交事实逐笔计数，同一更正链只保留未作废成交。`violations / eligible_trades`，不以没有成交推断遵守。计划触发或卖出仍须服从 T+1，成交金额保留佣金、印花税、过户费字段；计划一致性比较使用不复权成交价，关联表现才使用同一 as-of qfq。 | 成交事实含 `side、quantity、price、commission、stamp_tax、transfer_fee、traded_at、plan_version_id、voided_at`，`src/backend/app/db/tables/accounts.py:130-179`；计划版本与条件 `src/backend/app/db/tables/research.py:203-245`。计划版本缺可执行 qty/price 的完整持久化投影，违反事件和条件命中快照需后端补。 | `eligible_trades<5` 不显示比率，次数可显示但注明样本不足。不可判定因缺计划字段时进入 `unavailable`，不算遵守或违反。 | 未验证，未找到同类产品对“自身计划违反”的统一公开定义。 | 仓内定义（字段链未实现完整） |
| 分策略汇总 | 按不可变 `strategy_version_id` 分组，分别计算命中率、盈亏比、N 日表现、止损/止盈触发和计划违反。观测唯一键为 `(suggestion_id, strategy_version_id, horizon_days)`，同一建议多个实例只保留一条，不跨策略合并。范围仍限本人持仓、自选和已出候选信号。 | 版本聚合表有 `strategy_version_id、horizon、scope、n、wins、win_rate、avg_return_pct、avg_excess_pct、profit_loss_ratio`，`src/backend/app/db/tables/strategy.py:266-297`；建议绑定与去重 `src/backend/app/tracking/service.py:136-166`；事件明细需后端补。 | 每个策略版本独立执行 `n<5`、`n<30` 规则，不用总记录数替代有效 n。 | 同类产品提供按策略/回测结果的胜率和盈亏比汇总：[QuantConnect Backtest Results](https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/results)。 | 仓内定义（策略聚合已有部分字段） |
| 分周期汇总 | 按策略声明周期分组，做T `intraday_t→1`、短线 `short→5`、波段 `swing→20`、中长线 `long→20` 个交易日。多周期版本没有唯一声明时跳过并记 gap，不能取数组首项。每组沿用净收益、T+1、qfq、费用和状态分母规则。 | 周期映射和未知跳过见 `docs/api-contract.md:1358`；结果仅有 `horizon_days`，`src/backend/app/tracking/models.py:14-19`；策略声明周期绑定与分组字段需后端补。 | 每个周期独立标记 `small_sample`，不跨周期合并凑 n。 | 周期值为仓内契约定义，未找到能证明本项目映射的外部 URL。 | 仓内定义（多周期完整投影未实现） |
| 样本量与窗口展示 | 在最近 120 个交易日窗口内按 `as_of` 截断，`n<5` 所有比率和均值为 `null`，`5≤n<30` 展示数值并标 `small_sample`，`n≥30` 才允许作为常规描述。窗口外样本不进入分母，状态计数仍可单列。 | 阈值 `n>=5`、`n>=30` 和 120 交易日来自 `origin/docs/T-R112:docs/strategies/T-R112/params.md:78-81`；主线 `stat` 的 `n>=5` 与 `small_sample` 在 `src/backend/app/tracking/service.py:507-515`；窗口过滤字段需后端补。 | 以上规则是固定展示门槛，不为显示而虚增 n，不把 `pending/unavailable/untradable/excluded` 计入有效 n。 | `n>=30` 仅为统计经验法则，T-R112 已标注 A 股有效性未验证；不把它写成收益保证。 | 仓内定义（阈值与窗口登记于契约，A 股效果未验证） |
| 状态与可见时点审计 | 对每条观测保存建议生成、入场、退出、数据快照 `as_of`、首次可见时间、交易日历和证据哈希。任何在触发时点不可见的数据都不得进入公式。停牌、涨停锁买、跌停锁卖均进入 `untradable`，`wait/forced_hold` 进入 `excluded`，日历缺失或复权桥缺失进入 `unavailable`。 | 交易日历和 `fetched_at` 截断在 `src/backend/app/tracking/service.py:62-108,121-133`；结果证据与 gap 在 `src/backend/app/tracking/models.py:34-39`；状态计数在 `src/backend/app/tracking/api.py:115-125`。费用、sellable_at 和事件快照需后端补。 | 无法证明可见时点即不计有效样本，保留 gap 和状态计数。 | 主线契约 `docs/api-contract.md:1336-1344` 已明确 `pending/unavailable/untradable/excluded` 处理，外部 URL 未验证。 | 仓内定义（主线已有大部分状态保护，费用和 T+1 字段待补） |

## 主线现状与待实现边界

- 主线已实现建议级 1、5、20 交易日结果结构、交易日历、北京时间收盘可见性、qfq 结果字段、原始价格证据、停牌/涨跌停/`wait`/`forced_hold` 状态和策略级匿名聚合。
- 主线尚未证明净费用已经进入 `return_pct`，当前 `cost_applied` 默认可为 `false`，也没有佣金、印花税、过户费逐笔费率快照。主线也没有独立 `sellable_at`、止损止盈命中事件、完整计划可执行数量/价格投影或违反事件。
- §7.11.3 与本页中的 T+1、费用和窗口要求是文档口径。契约标记为 `status: draft` 的内容不能写成已验收。T-R115 只作为验证计划引用，不把计划当成实现证据。
- 展示文案统一使用“候选信号”和“模拟，不代表实际收益”。不输出荐股结论，不跑全市场规则有效性检验。

## 需后端补字段清单与计数

需后端补字段或事件共 11 项。

- 仓内定义 6 项：`sellable_at`；净收益费用拆分与费率快照；策略版本分组；周期映射；T+1 入场/退出约束；可见时点审计链。
- 未验证 5 项：止损触发事件；止盈触发事件；计划违反事件；计划版本完整 qty/price 可执行投影；A 股费用适用费率与复盘指标效果。

指标行 10：有据 0、仓内定义 8、未验证 2。以上是逐行指标结论计数；“需后端补”11 项的仓内定义 6 项／未验证 5 项分类仅针对补字段或事件清单，不是指标结论计数。已有字段和接口不列入补字段清单。

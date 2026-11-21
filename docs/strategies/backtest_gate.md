# 策略回测入门闸刀方案（T-A213，待用户拍板）

> **定位**：策略入门闸刀，独立于主线策略生命周期。本文是一份方案稿，不代表回测器、门禁接线、阈值配置或任何卡片已经实现。启用前须由用户本人拍板；启用后仍须完整执行 G1–G7。
>
> **现有依据**：`docs/strategies/card_promotion_gates.md` §3（G1–G7）、`docs/plan.md` §2.5.0B、§2.5.13、§2.5.14、§2.8–§2.8.2、§2.12.3–§2.12.4、§2.13、§9 C(6)–C(8)、`docs/plan-phase2-next.md` §1（共用依赖与 G7 约束）、`docs/strategies/validation.md` §1、§2.5、§5–§7、`docs/strategies/_template.md` §7.2、§11、§18、`config/market_rules.yaml` 的 `segments`、`fees`、`impact_cost`、`unfillable`、`t_plus` 字段、`docs/contracts/trading-calendar-exrights.md` §3–§6、`docs/reviews/T-A109-g7-delegation.md` §2。

## 1. 闸刀的边界与目标

本闸刀只回答一个问题：卡片原值在受限标的范围、按时点和真实交易约束运行后，是否形成一份可供 G6 和 G7 审阅的历史样本外证据包。结果只进入管理员可见的内部评估路径，沿用 `docs/plan.md` §2.12.4 的结果隔离约束，不进入普通用户的建议、通知或模型输入。

主线的 G1–G7 判定、`draft → simulating → published → observing → retired` 生命周期、卡片字段和交易规则保持现有定义。`docs/plan.md` §2.5.0B 明确 G6 默认只统计触发率、覆盖率和重合度，收益类内部评估属于获批后的附加报告。本文提出的回测结果只能作为该附加报告的输入，不能替换 fixtures、G1–G5 或 G7。

## 2. 运行范围与冻结材料

### 2.1 标的范围

每张卡建立一次 `universe_manifest`，只收以下集合的并集：

1. 用户当前持仓；
2. 用户自选；
3. 已经生成过的建议所涉及标的；
4. 用于比较的基准指数。

基准指数只用于同窗口比较，不作为股票交易标的。回测不扫描全市场，不用事后扩大的成分集合补足样本。卡片写明的 `universe.pool`、`screen` 和 `applicability.market_regime` 继续生效。现有卡片示例中，H-01 的 `universe.pool: 持仓`、W-01 的 `universe.pool: 持仓 ∪ 自选`，分别见 `docs/strategies/cards/hold_risk_monitor.md` 与 `docs/strategies/cards/sw_ma_trend_pullback.md` 的 `strategy-card` 块。

每个 `as_of` 都保存当日清单、来源、去重结果和缺失原因。清单无法追溯时写 `gap`，不以前值、全市场名单或基准指数成分补齐。全市场历史统计仍按 G6 的既有口径执行，不能被本闸刀的受限范围冒充。

### 2.2 卡片原值和版本

- 读取卡片当前 `key`、`version_no`、`params_schema.default`、规则表达式、`costs`、`horizons`、`data_needs`、`universe` 和 `validation_summary` 原值。
- 回测运行前冻结 `strategy_version_id`、参数哈希、规则版本、特征规格版本、日历版本、行情快照版本和代码版本。
- 禁止在样本外结果上改参数、改规则、改标的集合或改成本口径。任何修改都生成新版本，并重新建立一次样本外锁定记录。
- 卡片中的 `estimate`、`hypothesis`、`verified_doc`、`verified_live` 标记原样保留。未知值写 `null + gap`，不以默认震荡、零收益或历史最后值填充。

上述版本不可变要求来自 `docs/plan.md` §2.5.13 的 `strategy_versions` 生命周期和 `docs/strategies/card_promotion_gates.md` §4 S-02；时点数据缺口处理来自 `docs/contracts/trading-calendar-exrights.md` §4、§6。

### 2.3 样本外区间只锁定一次

1. 首次运行前写入 `oos_lock`，包括起止交易日、时区、卡片版本、标的清单哈希、基准、成本模型、市场规则版本、复权口径和运行者。
2. 样本外起止日由策略研究员先拟定，架构师复核后交用户拍板。第一次正式运行后，起止日只读，不能为追求更好结果而移动。
3. 样本外区间被查看或用于选择后，任何规则或参数改动都视为污染。必须升 `version_no` 并建立新的 `oos_lock`，旧报告保留为历史证据。
4. 区间缺交易日历覆盖、权息可见时点或关键字段时，报告 `calendar_not_covered`、`adjust_factor_missing` 或对应 `gap`，停止受影响样本的结论。

交易日和时区遵循 `docs/contracts/trading-calendar-exrights.md` §3 的 `Asia/Shanghai`、`is_open` 和 `calendar_not_covered` 语义。权息只取 `e ≤ t` 且 `available_at ≤ as_of` 的事件，qfq 序列按 §4.2 的 `qfq@as_of` 每个 T 独立重算；展示锚不得进入信号、指标或回测。

## 3. 具体运行方法

### 3.1 分段滚动（walk-forward）

采用 `docs/plan.md` §2.12.4 的时间序列 K 折默认值 `K=5`。每一折按时间先后滚动：只用折前已结束的数据形成研究输入，在下一段样本外区间评估，折间留出等于该卡持有期的 `embargo`。每折独立输出交易明细、收益、超额、不可成交计数、缺口和数据版本。

内部稳健度沿用 `docs/plan.md` §2.12.4 的定义：

```text
robustness = 0.6 × 各折结果的中位数 + 0.4 × 最差一折结果
```

`K=5`、`embargo=持有期`、`0.6/0.4` 和候选参数组合上限 50 均已有仓库出处。本文不把这些数值改成新的硬门槛。折数不足、某折无法按时点重放或最差折缺结果时，输出“样本外不完整”，不报告为通过。

### 3.2 成交、成本和交易约束

回测和后续模拟跟踪共用 `app/market_rules` 的规则版本，历史日期按 `config/market_rules.yaml` `segments.effective_from` 选择当时有效段。成本明细至少包括：

- `fees.commission_min_yuan` 的单笔最低佣金、用户实际佣金费率（没有费率则保留缺口）；
- `fees.stamp_duty_sell_pct` 的卖出印花税和 `fees.transfer_fee_pct` 的双向过户费；
- 卡片 `slippage_bp` 或 `fees.slippage_default_pct` 的基础滑点；
- `impact_cost.adv_basis: amount`、`adv_window_days: 20` 和五档 `tiers` 的冲击成本。

成交价取不利侧。对买入，若同一时点有可成交价区间，取该区间最高价；对卖出取最低价，再叠加适用的基础滑点和冲击成本。无法确定区间边界时，样本标 `price_gap`，不使用中间价猜测。

以下可成交性规则逐笔执行：一字涨停不能买，一字跌停不能卖，停牌不能成交，字段依据 `config/market_rules.yaml` `unfillable` 和 `docs/strategies/_template.md` §7.3、§17。股票 T+1 依据 `segments.t_plus`，当日买入的仓位当日不可卖。涨跌停幅度、无涨跌幅日、整手和零股规则按同一日期的 `segments.price_limit_pct`、`no_limit`、`lot` 字段。不可成交样本单独计数，不进入方向正确率或收益分母。

### 3.3 无前视的成交时点

- 日线信号在 T 日收盘且数据到齐后求值，最早 T+1 09:30 执行，模拟入场价为 T+1 开盘价。
- 盘中信号只使用已收完的 1 分钟 bar，入场价为下一根 1 分钟 bar 的开盘价。
- 每个特征必须满足 `available_at ≤ as_of`。财报以 `plrq`，公告和盘后数据按次一交易日 09:30 起可见。
- 指标价格使用 qfq@as_of，收益使用 `docs/strategies/validation.md` §1.3 所述的后复权或总收益口径；1 分钟数据为不复权，跨除权日窗口截断。
- 任何 T+h 窗口在窗口结束前都不读取 T+h 之后的数据。缺日历、缺可见时刻、缺复权因子、伪停牌行或数据陈旧时保留缺口。

以上规则对应 `docs/strategies/_template.md` §7.2、§7.3、§11、`docs/plan.md` §2.8.1、`docs/contracts/trading-calendar-exrights.md` §3–§6。这里的“次日开盘成交”与卡片 `validation` 机器块的 `horizon_days` 口径一致。

### 3.4 上涨、下跌、震荡分段报告

报告固定分为 `uptrend`、`range`、`downtrend` 三段。分段值优先使用卡片已经声明并通过 G2 检查的 `f.market_regime_idx` 或等价 `applicability.market_regime` 来源，不另造阈值。卡片没有可用分段字段时，记录 `market_regime_unknown`，单独列出该部分样本，不并入三段平均值。

每一折、每个持有期、每个动作和每个行情段都单列结果。至少报告区间收益、基准收益、超额收益、最大回撤、最大上涨、方向正确率、不可成交数、有效样本数和缺口数；指标统一附 `value`、`n`、`window`、`small_sample`，遵循 `docs/plan.md` §2.12.3。基准默认沪深300，卡片另有基准时按卡片声明并在清单中冻结，依据 `docs/plan.md` §2.8 与 `docs/strategies/validation.md` §3.2、§7.1。

## 4. 结果如何接入 G1–G7

### 4.1 G1–G5 保持原门槛

G1 仍检查规则完整性、退出和止损、反证以及证据；G2 仍要求 `feature_catalog` 白名单和至少 `verified_doc`；G3 仍检查 DSL 安全和无未来函数；G4 仍检查参数 schema；G5 仍检查 `gate_tradability`、涨跌停、T+1 和交易单位。依据为 `docs/strategies/card_promotion_gates.md` §3.1–§3.5 和 `docs/plan.md` §2.5.0B。

回测闸刀不能把 G2 的 `gap` 变成可用，也不能把 `verified_doc` 写成 `verified_live`。`docs/plan.md` §2.5.13 的现行生命周期要求继续适用。

### 4.2 回测结果作为 G6 的附加输入

G6 现行必查内容继续执行：至少 6 个虚构 fixtures 全过，最近 120 个交易日触发率和覆盖率体检，命中集合重复度检查以及配额检查，具体见 `docs/strategies/card_promotion_gates.md` §3.6。回测附加输入建议固定为：

```text
oos_lock
universe_manifest
fold_reports
regime_reports
trade_log（含成交价、成本、不可成交原因）
pit_checklist
data_versions
gap_summary
```

附加报告只供管理员在 G7 审核页查看。`validation_summary.oos_result` 没有已完成结果时继续写“未验证”；`validation` 机器块只放 G6 需要的结构，不能把摘要键塞进其中，依据 `docs/strategies/_template.md` §11 和 `docs/plan.md` §2.5.14 H②。

G6 的“通过、警告、失败”仍由现有引擎契约产生。本文不把任何新增收益阈值写成已生效硬门槛。用户若选择收益硬门槛，须先把阈值写入版本化配置、补测试并重新走 G6/G7。

### 4.3 G7 和责任链

1. **策略研究员**：确定标的范围、行情分段、指标定义、区间和阈值草案，冻结 `oos_lock`，核对卡片原文与结果。
2. **后端**：实现唯一回测器、按时点数据读取、交易规则调用、成本明细、报告存储和 G6 输入适配，禁止旁路数据口径。
3. **测试**：用纯虚构夹具核验前视、滚动切分、成本最坏侧、涨跌停、停牌、T+1、复权和报告完整性。
4. **架构师**：评审方案、口径、阈值出处、G6 接线和生命周期影响。
5. **用户本人**：按 `docs/reviews/T-A109-g7-delegation.md` §2 负责 G7 的最终批准。策略研究员核对和架构师复核完成后，只有存在覆盖该卡的用户本人授权，才可由编排者通过管理员可信交互会话代批并留审计。缺证据项为 0、G1–G6 无 `fail`、所有 `warn` 已确认，仍是代批前提。

### 4.4 三个卡片状态的映射

| 对外标签 | 现有生命周期 | 进入条件和含义 |
|---|---|---|
| 假设 | `draft` | 只有卡片机制与参数假设，尚未完成 G1–G7；不运行，不生成候选。 |
| 回测过 | `simulating` | G1–G7 完成后进入；已有一次冻结的样本外报告，产生候选并做模拟跟踪，不生成计划草案。 |
| 实盘验证 | `published` | 沿用 `docs/plan.md` §2.5.13：模拟样本 `n ≥ 20` 或模拟满 20 个交易日、必需字段全部 `verified_live`、管理员批准。实际成交若存在，单独保存并与模拟结果并列。 |

`observing` 只由 `published` 的健康度机制自动进入，`retired` 只由管理员确认。标签“实盘验证”表示已进入发布后的持续验证阶段，不把模拟收益写成用户实际收益。

## 5. 回测与实盘（或模拟）的自动对比

### 5.1 对比对象和度量

比较必须使用相同的卡片版本、动作、持有期、行情段、基准和成本口径，且只计已经关闭的窗口。回测基线为冻结样本外各折的 `robustness`，实时侧优先使用同卡片版本的模拟跟踪；有真实成交时另做执行侧序列，不与模拟样本混合。

每个对比单元保存：

- `delta_excess = 实时侧平均超额 − 回测基线平均超额`；
- `delta_direction = 实时侧方向正确率 − 回测基线方向正确率`；
- `robustness_ratio = 实时侧滚动稳健度 ÷ 回测基线稳健度`，仅在基线稳健度大于 0 时计算；
- `execution_gap`，买入为实际成交价减模拟不利买价，卖出为模拟不利卖价减实际成交价；
- 各指标的 `n`、窗口、行情段、缺口和不可成交数。

分母为 0 或负数时不强行计算比例，只报告绝对差并标 `ratio_undefined`。缺少 `n`、窗口未关闭、标的清单不一致或规则版本不一致时，不触发自动降级。

### 5.2 偏差触发和降级

本方案采用仓库已有的健康度触发条件作为默认可执行路径：

1. 当同口径实时侧样本 `n ≥ 20`，且发布基线的稳健度下降到基线的 70% 以下时，沿现有健康度机制触发 `published → observing`，并写入“偏差显著”审计事件。`70%` 和 `n ≥ 20` 的出处是 `docs/plan.md` §2.8.2、§2.5.7、§2.5.13；若用户选择“仅供 G7 参考”，则只记录候选事件，不改变生命周期。
2. 当全站 `weight < 0.8` 连续 5 个交易日时，沿同一节的健康度机制从 `published` 转为 `observing`。`0.8`、连续 5 个交易日和 `observing` 的自动跃迁均沿现有配置，不另建状态机。
3. 仅有一侧样本、样本少于 20、基线稳健度小于等于 0、或实时侧仍有未关闭窗口时，只记录偏差和缺口，不自动改变生命周期。
4. “偏差显著”候选事件触发复核通知，不等同于自动退役。`retired` 仍只能由管理员确认；恢复到 `published` 仍须满足 `weight ≥ 0.9` 连续 10 个交易日及内部复验恢复，依据 `docs/plan.md` §2.8.2。

如用户选择绝对超额差、方向正确率差或执行价差作为新的降级门槛，必须先给出公开出处或用户本人确认。没有出处的数值标为“未验证”，默认不生效。

## 6. 防过拟合三道防线

### 防线一：参数冻结

读取卡片 `params_schema.default` 后即冻结，样本外期间禁止调参。任何参数改动都升 `version_no`、生成新 `param_hash`、建立新 `oos_lock`。计划 §2.12.4 的候选参数组合上限为 50，本闸刀首版只运行卡片原值，组合数为 1。

### 防线二：样本外一次性

样本外起止日、标的集合、基准和成本模型在第一次运行前写入不可变清单，只开一次。研究员看过样本外结果后不能回到原区间重跑并选择更好结果；需要修改时只能出新版本和新锁定区间，旧结果保留并标注“已被查看”。

### 防线三：滚动折与多重检验记录

按 `K=5` 和 `embargo=持有期` 做 walk-forward，每折与每个行情段都出结果，稳健度使用 `0.6/0.4` 公式。所有尝试、失败尝试、指标、窗口和参数组合都写入试验日志；需要显著性检验时沿 `docs/strategies/validation.md` §5.2 的 Holm 或 Benjamini–Hochberg 规则，并把校正前后结果一起保存。`q=0.10` 在该节属于建议值，未获用户拍板前不作为新硬门槛。

## 7. 数值阈值与出处登记

备料文件为 `/workspace/team/reports/T-A213-thresholds.md`。本节逐条核对其 16 项阈值。论文链接和交易所规则链接均在备料的链接核验记录中列为 HTTP 200，本节只把可核对的原文方法或规则写为出处，不把论文中的方法证据升级成 A 股有效性。

仓库现行数值先按主线口径登记，不因备料改变：

| 仓库现行数值 | 用途 | 出处与状态 |
|---|---|---|
| `K=5`、`embargo=持有期`、稳健度 `0.6/0.4` | 滚动样本外与折间合成 | `docs/plan.md` §2.12.4、`validation.md` §2.5；方案值，尚未运行 |
| 参数组合不超过 `50` | 防数据挖掘 | `docs/plan.md` §2.12.4；首版原值为 1 组 |
| `n<5`、`5≤n<30`、`n≥30` | 统计展示 | `validation.md` §1.5；展示阈值，不是 G6 淘汰线 |
| `n≥20`、稳健度低于基线 `70%`、`weight<0.8` 连续 5 日 | 健康度和偏差候选 | `docs/plan.md` §2.5.7、§2.8.2、§2.5.13；现行健康度值，是否用于本闸刀仍待用户确认 |
| `weight≥0.9` 连续 10 日、`weight<0.6` 持续 20 日、稳健度低于基线 `50%` 持续 20 日 | 恢复或复审提示 | `docs/plan.md` §2.8.2；现行提示值，尚未接入本闸刀 |
| 佣金最低 5 元、印花税按历史段、过户费 `0.001%`、冲击成本 0/5/15/30/60 bp、ADV 20 日 | 成本模型 | `config/market_rules.yaml` `fees`、`impact_cost`；冲击档位标为初值、待校准 |
| 主板 10%、创业板/科创板 20%、北交所 30%，主板 ST 在 2026-07-06 前为 5% | 涨跌停规则 | `config/market_rules.yaml` `segments.price_limit_pct`；按生效日选择，回看范围受 `modeled_from` 约束 |

| 备料阈值 | 备料出处逐条核对 | 与仓库现行口径的处理 |
|---|---|---|
| 总交易数 `≥30`，每个 OOS 折 `≥10` | David H. Bailey、Marcos López de Prado，《The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality》，讨论样本长度 `T` 和回测长度对显著性的影响，未给出 `30` 或 `10` 固定线。 | `30/10` 保持未验证、默认不生效。`validation.md` §1.5 的 `n<5`、`5≤n<30`、`n≥30` 是展示分层，不是 G6 淘汰线。 |
| OOS 净收益、超额收益、风险调整绩效均为正 | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》第 11 章说明滚动样本外检验，第 12 章讨论绩效评价，未给出 A 股正值硬线。 | 保持未验证、默认不生效。`card_promotion_gates.md` §3.6 的 G6-03 现行只统计触发率和覆盖率，不计算收益、胜率、夏普。 |
| IS/OOS 衰减 `D≤50%` 通过、`≤70%` 观察、`>70%` 淘汰 | David H. Bailey、Jonathan Borwein、Marcos López de Prado、Qiji Jim Zhu，《The Probability of Backtest Overfitting》，提出用 OOS 相对 IS 表现研究过拟合，未给出 `50%` 或 `70%` 固定线。 | 保持未验证、默认不生效。仓库已有的健康度 `70%` 仅按 §2.8.2 和 §5.2 作为现行健康度候选。 |
| MDD `≤20%` 通过、`≤30%` 观察、`>30%` 淘汰 | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》第 12 章列出最大回撤作为风险评价字段，未给出 `20%` 或 `30%` 固定线。 | 保持未验证、默认不生效。仓库 G6 没有 MDD 硬线。 |
| 胜率 `≥45%` | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》第 12 章讨论 profit and loss consistency，未给出 `45%` 固定线。 | 保持未验证、默认不生效。`validation.md` §4.3 的胜率及期望值只属于研究侧建议初值。 |
| PF `≥1.20` 通过、`1.00≤PF<1.20` 观察 | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》第 12 章列出 reward to risk ratio 和 performance profile，未给出 `1.20` 固定线。 | 保持未验证、默认不生效。仓库只要求报告盈亏比，未把 PF 接入 G6。 |
| 全部费用、滑点、冲击成本乘 `2` 后净年化收益仍 `>0` | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》强调评估应纳入交易成本和真实交易假设，未给出“翻倍”固定线。 | 成本翻倍和净年化正值保持未验证、默认不生效。 |
| 实盘相对 OOS `Δ≤−30%`、Sharpe 低 `0.50` 或 MDD 高 `50%` 触发观察 | Bailey、López de Prado，《The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality》提供选择偏差修正方法，未给出这些实盘偏差线。 | 保持未验证、默认不生效。仓库只保留 §5.2 的稳健度 `70%`、`n≥20` 和健康度条件。 |
| `OOS_OPEN_COUNT=1`，打开后冻结参数、数据截止日、范围、成本 | Bailey、Borwein、López de Prado、Zhu，《The Probability of Backtest Overfitting》说明重复使用 holdout 会增加过拟合风险。 | 该方法出处可核对，且与本稿 §2.3 和 `validation.md` §5.3 一致。它仍是方案约束，A 股有效性未验证，默认不作为新增 G6 硬线。 |
| 至少 `5` 个 OOS 折，每折 `≥10` 笔，按 OOS 天数加权 | Robert Pardo，《The Evaluation and Optimization of Trading Strategies, 2nd Edition》第 11 章定义滚动优化窗口和随后 OOS 窗口，未给出 `5` 折或每折 `10` 笔固定线。 | `K=5` 和 `embargo=持有期` 是仓库 `plan.md` §2.12.4、`validation.md` §2.5 的现行方法。每折 `≥10`、天数加权保持未验证、默认不生效。 |
| DSR `Pr(SR_true>SR*)≥0.95` | David H. Bailey、Marcos López de Prado，《The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality》用 `N`、`T`、偏度、峰度和试验 Sharpe 分布修正选择偏差，示例使用 95% 置信水平。 | 方法和 `0.95` 示例出处可核对，但 A 股有效性未验证、默认不生效。`validation.md` §5.2 只允许 DSR 作可选参考，不能替换 G6。 |
| PBO `≤0.50` 基础线、`≤0.25` 强证据、`≥0.75` 淘汰 | Bailey、Borwein、López de Prado、Zhu，《The Probability of Backtest Overfitting》提出 CSCV 估计 PBO，未给出这三条统一监管线。 | 三个数值保持未验证、默认不生效。 |
| White RC 与 Hansen SPA 的 bootstrap `p<0.05` | Halbert White，《A Reality Check for Data Snooping》提出 bootstrap Reality Check。Peter R. Hansen，《A Test for Superior Predictive Ability》提出 studentized SPA。两文说明检验方法，未证明本项目 `0.05` 是 A 股门槛。 | 方法出处可核对，`p<0.05` 及“任一失败即不能回测过”保持未验证、默认不生效。 |
| 横截面因子 `t>3` | Campbell R. Harvey、Yan Liu、Heqing Zhu，《… and the Cross-Section of Expected Returns》提出新因子需超过 `t-ratio=3` 的多重检验门槛。 | 数值出处可核对，但 A 股有效性未验证、默认不生效。只在适用的横截面因子报告中记录，不能把普通 Sharpe 当作 HLZ `t`。 |
| T+1、涨跌停、停牌、风险警示和板块规则按交易所元数据 | 《上海证券交易所交易规则（2026年修订）》第 3.1.5、3.3.8、3.3.17、4.4.9、4.4.10、6.7 条涉及回转交易、申报单位、涨跌幅、风险警示交易限制和科创板申报。 《深圳证券交易所交易规则（2026年修订）》第 3.1.5、3.3.8、3.3.9、3.3.19 条涉及回转交易、申报单位、单笔数量和涨跌幅。 | 规则出处可核对，按 `config/market_rules.yaml` 和 G5 现行行为执行。仓库 `modeled_from=2023-04-10`，北交所 V1 不扫描，且 ETF `data_source=null` 时保守按 T+1。备料的“规则已公开”不等于 A 股成交影响已验证。 |
| 佣金上限 `3‰`、最低 `5` 元，过户费 `0.01‰` 双边，卖方印花税按日期，2023-08-28 起减半 | 中国证监会《关于调整证券交易佣金收取标准的通知》（证监发〔2002〕21 号）第一条规定佣金不高于成交金额 `3‰` 且不足 `5` 元按 `5` 元收取，第六条涉及费率按券商及客户约定。中国证券登记结算有限责任公司《上海市场证券登记结算业务收费及代收税费一览表》列示 A 股过户费 `0.01‰` 双边。财政部、税务总局《关于减半征收证券交易印花税的公告》（财政部 税务总局公告 2023 年第 39 号）规定 2023-08-28 起减半。 | 公开规则出处可核对。仓库现行 `commission_rate_default_pct=null`，按用户实际费率，不能把 `3‰` 写成默认费率。`commission_min_yuan=5`、`transfer_fee_pct=0.001%`、分段印花税按配置执行。压力测试加倍仍未验证、默认不生效。 |

公开出处链接均来自备料文件，2026-11-21 核验返回 HTTP 200：

- [Deflated Sharpe Ratio](https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf)、[Probability of Backtest Overfitting](https://www.carmamaths.org/resources/jon/backtest2.pdf)、[Pardo 交易策略评价](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。
- [White Reality Check](https://users.ssc.wisc.edu/~behansen/718/White2000.pdf)、[Hansen SPA](https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html)、[Harvey–Liu–Zhu](https://people.duke.edu/~charvey/Research/Published_Papers/P118_and_the_cross.PDF)。
- [上海证券交易所交易规则（2026年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)、[深圳证券交易所交易规则（2026年修订）](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)。
- [证监发〔2002〕21 号佣金通知](https://www.csrc.gov.cn/csrc/c100024/c1492350/1492350/files/928bdd362fa24b79bdadb0072d67acee.pdf)、[上海市场收费表公开转载](https://jrj.wuhan.gov.cn/ynzx_57/xwzx/202204/t20220429_1964160.shtml)、[2023 年证券交易印花税减半公告](https://www.chinatax.gov.cn/chinatax/c102414/c5216997/5216997/files/%E5%BB%B6%E7%BB%AD%E4%BC%98%E5%8C%96%E5%AE%8C%E5%96%84%E7%9A%84%E7%A8%8E%E8%B4%B9%E4%BC%98%E6%83%A0%E6%94%BF%E7%AD%96%E6%B1%87%E7%BC%96%EF%BC%882023%E5%B9%B4%E7%89%88%EF%BC%89-20231124113552902.pdf)。

### 7.1 与现有门禁和配置的冲突登记

- 备料把正收益、MDD、胜率、PF、费用翻倍、DSR、PBO、RC/SPA 和 HLZ 数值写成 G6 淘汰或降级条件。`card_promotion_gates.md` §3.6 的 G6-01 至 G6-06 仍是现行门禁，G6-03 明确不计算收益、胜率和夏普，所以上述新增硬线全部保持未验证、默认不生效。
- 备料的“每折至少 10 笔”没有 `validation.md` §2.5 的仓库出处。仓库保留 `K=5`、`embargo=持有期` 和 `0.6/0.4` 方法，`n` 仍按 `validation.md` §1.5 的展示分层，不能把 `n≥30` 改成 G6 淘汰线。
- 备料的成本压力测试写成全部成本乘 2。仓库 `config/market_rules.yaml` 按历史 `segments` 选择规则，佣金默认费率为空，冲击成本按成交额口径、近 20 个有效交易日和 0/5/15/30/60 bp 分档，均按现行配置执行。
- 备料包含北交所 30% 作为范围。仓库 `card_promotion_gates.md` §3.5 的 G5-05 规定首版不含北交所，涉及北交所的卡标为暂不可执行。

本文新增的绝对收益差、方向正确率差、执行价差、样本外起止日、每折交易数和上述论文工程线没有独立的 A 股公开验证，均默认不作为自动门槛。任何后续新增数值都必须登记完整出处、认识论类型、与 G1–G7 的关系和生效版本。

## 8. 需用户拍板的选项

1. 是否启用本闸刀，并把回测附加报告接入 G6。选项为关闭、仅供 G7 参考、作为 G6 硬门槛；硬门槛会延后 `simulating`。
2. 样本外起止区间和第一次运行日期。区间一经打开只读，是否允许以后升版本重开新区间。
3. `universe_manifest` 是否严格采用“持仓＋自选＋已出建议＋基准指数”，以及建议标的清单的保留期限。
4. 偏差触发是否沿用现有“稳健度低于 70%”和“`weight<0.8` 连续 5 日”，还是另设绝对差门槛。新数值无出处时默认不生效。
5. “实盘验证”标签是否接受模拟跟踪加 `verified_live` 字段作为 `published` 条件，真实成交只作并列证据；若要求真实成交，需另定数据来源和授权边界。
6. 是否采用 `docs/strategies/validation.md` §5.2 的多重检验校正，以及是否接受其中 `q=0.10` 建议值。

## 9. 交付前验收清单

- 文档审查确认 G1–G7、生命周期和 G7 授权原文未被放宽。
- 纯虚构夹具覆盖日线 T+1、盘中下一根 1 分钟 bar、复权、涨跌停、停牌、T+1、最坏成交价和缺日历。
- 每折、每行情段、每动作都有可追溯交易明细和 `n`，缺口不被转成零。
- 回测器只调用统一特征和 `app/market_rules`，没有全市场旁路、第二套成本或未来数据入口。
- G6 附加报告与 `validation` 机器块分离，管理员权限、审计和 G7 审核页留证均通过后，才可由用户本人决定启用。

截至本文撰写时，以上实现、测试、G6 接线、G7 审核和用户 Windows 实例均未因本任务而完成；本稿只提交方案供拍板。

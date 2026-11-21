# T-R103 复盘与建议跟踪指标口径卡

```yaml
document: review_tracking_metrics
task: T-R103
lifecycle: draft
scope: 候选信号的模拟跟踪、实际成交复盘及实盘与样本外回测对比
```

## 1. 边界与共同规则

本卡只描述候选信号的记录与复盘口径，不构成荐股、买卖指令或收益承诺。模拟跟踪、实际成交和样本外回测必须分开保存，不能用模拟结果代替用户实际收益，也不能用实际成交结果回填历史候选信号。

一条观测的去重键为 `suggestion_id`、`strategy_version_id`、`horizon_days`。`horizon_days` 只取 1、5、20 个交易日，统计窗口以交易所交易日历计数。字段沿用现有结果模型，包括 `action`、`state`、`entry_at`、`entry_price`、`exit_at`、`exit_price`、`return_pct`、`benchmark_code`、`benchmark_return_pct`、`excess_pct`、`max_drawdown_pct`、`direction_correct`、`invalidation_triggered_at`、`cost_applied`、`gaps`、`n` 和 `small_sample`。字段存在不等于数据链路已验收。

计算时固定 `generated_at`、`data_as_of`、`available_at`、交易日历版本、行情版本、复权因子版本、基准代码和成本表。只使用在本次计算时点已经可见且业务日期不晚于到期日的数据。迟到、修订或后来复牌的数据不能改写已经冻结的历史观测。缺字段输出 `null` 并记录 `gaps`，不以零、邻日价格或当前时钟补值。

盘后候选信号的模拟入场价取信号发出后下一交易日的第一可成交价，通常为下一交易日开盘价。盘中候选信号取生成时刻之后的下一根可见分钟线开盘价。若该价因停牌、涨停封板或缺乏可成交证据而不可得，观测记为 `untradable` 或 `unavailable`，不伪造成交。该时点规则与公开交易规则中停牌、涨跌幅和交收约束相容，具体可成交性仍需 A 股数据复测。[上交所交易规则（2026年修订）](https://www.sse.com.cn/lawandrules/sselawsrules2025/stocks/exchange/c/c_20260424_10816482.shtml)；[深交所交易规则（2026年修订）](https://docs.static.szse.cn/www/lawrules/rule/trade/current/W020260424690713155663.pdf)。

## 2. 指标口径

### 2.1 命中率与目标、止损结果

**定义。** 默认命中率是方向命中率。分母只包含 `state=complete`、结果值非空且动作属于 `buy`、`add`、`sell`、`reduce`、`hold` 的观测。`wait` 只展示，不进入命中率。不可成交、停牌、涨跌停锁定、`pending`、`unavailable`、`excluded` 和 `forced_hold` 单独计数，不进入分母。

**公式。**

```text
hit_rate = 命中观测数 / 有效观测数
buy/add       命中 ⇔ excess_pct > 0
sell/reduce   命中 ⇔ excess_pct < 0
hold          命中 ⇔ |excess_pct| ≤ θ_h
θ_1=1.0%，θ_5=2.0%，θ_20=5.0%
```

`direction_correct` 直接保存上述布尔值。阈值是产品初值，属于未验证（待回测），不能据此宣称策略有效。命中率与盈亏大小分开报告，胜率高不代表收益为正。命中率和平均胜负幅度作为两个互补维度的公开讨论见 [CFA Digest 关于 hit ratio 与 win/loss magnitude](https://rpc.cfainstitute.org/research/cfa-digest/2018/07/dig-v48-n7-8)。

若候选信号在卡片中预先登记了止损和止盈，另记首次可证明触发的 `target_hit`、`stop_hit` 或 `neither` 结果。需要 `stops.stop_loss`、`stops.take_profit`、逐时点可见的高低价、成交状态和 `invalidation_triggered_at`。同一根 K 线同时触及目标和止损且无法证明先后时，按止损优先的最坏规则，或标记顺序未知并剔除该细分统计。不能用收盘价越过阈值倒推盘中触发。目标、止损优先级和 A 股有效性未验证（待回测）。

**窗口与时点。** 每条候选信号在 T+1、T+5、T+20 收盘后各计算一次。命中率聚合只使用已经结束的窗口，窗口端点以该次作业的 `as_of` 截断。

**最少样本量。** 单个命中率在 `n<5` 时只返回空值和样本数，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。上述 `n` 只包括有效、已结束且有 `direction_correct` 的观测。

**边界。** 目标或止损命中后，退出价取实际可成交价，不取阈值价。涨停买不进、跌停卖不出和停牌不补成交。无法卖出的仓位保留为未平仓或不可用观测，不能用事后复牌价补成交。上述规则的工程细节未验证（待回测）。

### 2.2 持有期收益

**定义。** 持有期收益按实际模拟入场与到期退出的同一复权口径计算。现有字段 `return_pct` 以百分比保存。价格比值收益与绩效评价中的区间收益定义一致，风险指标和收益口径的公开方法见 [CFA Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation)。

**公式。**

```text
return_pct = 100 × (exit_price / entry_price − 1)
```

`entry_price` 是候选信号发出后下一可成交价，`exit_price` 是 T+h 到期时可成交的退出价或预先登记的退出规则首次成交价。`entry_at`、`exit_at`、`horizon_days`、`price_basis`、`cost_applied` 和成交状态必须同时保存。若展示扣费结果，费用、滑点、冲击成本逐笔记录，不能把未知费用当成零。显式佣金可按适用日期的公开规则建模，[证监会关于调整证券交易佣金收取标准的通知](https://www.csrc.gov.cn/csrc/c100024/c1492350/1492350/files/928bdd362fa24b79bdadb0072d67acee.pdf)规定 A 股佣金上限 3‰ 且单笔不足 5 元按 5 元收取。历史税费必须按成交日期规则取值，[国家税务总局等关于减半征收证券交易印花税的公告汇编](https://www.chinatax.gov.cn/chinatax/c102414/c5216997/5216997/files/%E5%BB%B6%E7%BB%AD%E4%BC%98%E5%8C%96%E5%AE%8C%E5%96%84%E7%9A%84%E7%A8%8E%E8%B4%B9%E4%BC%98%E6%83%A0%E6%94%BF%E7%AD%96%E6%B1%87%E7%BC%96%EF%BC%882023%E5%B9%B4%E7%89%88%EF%BC%89-20231124113552902.pdf)给出 2023-08-28 起的历史税率变化。费用和滑点压力档位尚无 A 股普适验证，标记未验证（待回测）。

**输入字段。** `generated_at`、`data_as_of`、`entry_at`、`entry_price`、`exit_at`、`exit_price`、`action`、`horizon_days`、`price_basis`、`cost_applied`、`is_suspended`、涨跌停状态、成交量或可成交证据、交易日历、复权因子版本及 `gaps`。

**窗口与时点。** T+1、T+5、T+20 交易日收盘后计算。盘后生成的 T+1 入场不能使用生成日收盘价替代下一交易日可成交价。任何输入必须满足 `available_at ≤ calculation_as_of`，不能因当前已经收盘而放行旧盘中数据。

**最坏成交规则。** 涨停买不进时不生成模拟入场，记 `untradable`。跌停卖不出、停牌或可卖量未知时不补成交，保留未平仓状态并单列不可成交比例。若研究包需要风险下界，使用窗口内已证明可成交的最差价格，另标 `worst_case_lower_bound`，不能把下界混入正常命中率。该下界规则未验证（待回测）。

**最少样本量。** 单个持有期收益需要一个完整的入场和退出端点。聚合收益在 `n<5` 时不返回均值，`5≤n<30` 标记样本少，`n≥30` 才可作为正常绩效摘要。

### 2.3 相对基准超额

**基准。** 默认 `benchmark_code=000300.SH`，即沪深300。中证指数公开资料称其由 300 只规模大、流动性好的 A 股组成，目标是反映中国 A 股市场整体表现，适合作为大盘候选信号的共同对照。[CSI 300 factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300factsheeten.pdf)；[CSI 300 编制方法](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/en/000300_Index_Methodology_en.pdf)。对小盘或全市场范围另做稳健性对照时使用 `000985.SH` 中证全指，其官方资料说明其覆盖沪深北市场并反映上市公司整体表现。[中证全指 factsheet](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000985factsheet.pdf)；[中证全指编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175438-000985_Index_Methodology_cn.pdf)。

行业基准只有在历史成分、指数价格和可见时点均齐备时才启用。缺少任一端点或版本证据时，保留个股收益，`benchmark_return_pct` 和 `excess_pct` 为 `null` 并记录缺口。行业超额不能用大盘超额替代，标记未验证。

**公式。**

```text
benchmark_return_pct = 100 × (benchmark_exit_price / benchmark_entry_price − 1)
excess_pct = return_pct − benchmark_return_pct
```

个股和基准必须使用相同的入场时点、到期日、复权或总收益定义和可见性截止点。基准只有一个端点、停牌或定稿状态不合格时不补邻日价格。相对基准的收益分解属于公开投资绩效评价常用做法，但本项目基准覆盖、历史版本和 A 股有效性未验证（待回测）。

**最少样本量。** 只有 `return_pct` 和 `benchmark_return_pct` 同时非空的观测进入超额统计。`n<5` 返回空值，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。

### 2.4 期间最大回撤

**定义。** 单条观测的路径从 `entry_price` 开始，随后按持有期内已经可见的交易日收盘价排列，最后一点为 `exit_price`。T+1 只有入场和退出两点。只用证券自身价格，不按动作取反。

**公式。**

```text
peak_t = max(P_0, ..., P_t)
drawdown_t = 100 × (P_t / peak_t − 1)
max_drawdown_pct = min_t(drawdown_t)
```

结果应小于或等于 0。聚合净值回撤以同一窗口的逐日净值曲线计算，不能把各条观测的回撤简单平均。最大回撤是公开绩效评价中的风险字段，方法资料见 [CFA Portfolio Performance Evaluation](https://www.cfainstitute.org/insights/professional-learning/refresher-readings/2026/portfolio-performance-evaluation) 和 [Pardo《The Evaluation and Optimization of Trading Strategies》](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。

**输入、窗口与边界。** 输入为 `entry_price`、逐交易日 `close`、`exit_price`、复权因子版本、`data_as_of` 和 `gaps`。停牌日没有有效收盘价就跳过该日，不以前值填充。入场或退出端点缺失时回撤为 `null`。除权除息必须使用同一 `price_basis` 和同一可见因子版本，不能将原始价格与复权价格拼接。退市后没有可证明的清算价格时，状态为未平仓或不可用，不读未来复牌或退市后价格。除权、停牌、退市和未平仓分支的 A 股历史覆盖未验证（待回测）。

**最少样本量。** 单条完整路径可以计算单条回撤，但聚合回撤至少需要 5 条完整路径才展示数值，30 条以上才解除样本少标记。缺少入场或退出端点的路径不计入 `n`。

### 2.5 建议偏离

**定义。** 将用户实际成交与候选信号或已确认计划的冻结价格、时间和仓位在三个维度并列比较。候选信号或计划字段至少包括 `suggested_price` 或价格区间、`suggested_at`、`suggested_position_weight`、`action`、有效期和计划版本。实际字段来自成交回报的 `filled_price`、`filled_at`、`filled_qty`、`order_qty`、`portfolio_equity_at_fill`、撤改单和成交状态。

**公式。** 对买入，价格偏离为 `(actual_vwap − suggested_price) / suggested_price`。对卖出，将符号反向为 `(suggested_price − actual_vwap) / suggested_price`，正值表示执行更差。时间偏离为实际首笔成交时刻减建议生效时刻，按交易分钟计。仓位偏离同时报告百分点和相对比例。

```text
price_deviation_pct = side × 100 × (actual_vwap / suggested_price − 1)
time_deviation_minutes = trading_minutes(filled_at_first − suggested_at)
actual_weight = actual_filled_notional / portfolio_equity_at_fill
weight_deviation_pp = 100 × (actual_weight − suggested_weight)
weight_deviation_ratio = (actual_weight − suggested_weight) / suggested_weight
```

当 `suggested_weight=0` 或建议价格为空时，相对比例或价格偏离记 `null`，保留百分点、绝对金额或缺口原因，不能除以零或把缺字段当成零。

分笔成交用数量加权平均价和数量加权成交时间。部分成交同时报告完成度 `filled_qty / order_qty`。无成交不能把偏离当成零，应标记 `no_fill` 并另报机会成本。实际成交、到达价和执行价之间的实现偏差是公开交易成本分析的常用分解，见 [CFA Research Foundation《Transaction Cost Measurement and Management》](https://www.cfainstitute.org/sites/default/files/-/media/documents/book/rf-publication/2015/rf-v2015-n4-1-pdf.pdf)。本卡的 A 股阈值、队列成交和仓位偏离容忍度未验证，标记未验证（待回测）。

**最少样本量。** 单笔实际成交即可记录偏离，不能据此判断策略执行质量。聚合偏离在 `n<5` 时不返回均值，`5≤n<30` 标记样本少，`n≥30` 才可作为正常执行摘要。无成交订单另计，不进入成交偏离的 `n`。

### 2.6 盈亏比与盈亏因子

**盈亏比。** 对有效完成观测中 `action ∈ {buy, add, hold}` 的非零收益计算，盈利样本为 `return_pct > 0`，亏损样本为 `< 0`。

```text
payoff_ratio = 平均盈利 / |平均亏损|
```

这与现有 `profit_loss` 统计的平均盈利除以平均亏损绝对值一致。无亏损样本时为 `null` 并记 `no_losing_samples`。有亏损但没有盈利且样本达到计算门槛时为 0。`sell`、`reduce`、`wait` 不进入这个盈亏比，仍可进入方向命中率。

**最少样本量。** 盈亏比的有效 `n` 为盈利数与亏损数之和。`n<5` 时返回空值，`5≤n<30` 标记样本少，`n≥30` 才进入正常汇总。零收益既不进入盈利分子，也不进入亏损分母。

**盈亏因子。** 为接入 T-A213，另报 `profit_factor`。

```text
profit_factor = Σ盈利金额 / |Σ亏损金额|
```

两者不混称。T-A213 候选线为 `PF ≥ 1.20` 通过，`1.00 ≤ PF < 1.20` 降级为“观察中”，`PF < 1.00` 淘汰。该数值线未被公开文献证明为 A 股普适阈值，属于未验证（待回测）。盈亏比、盈亏因子、命中率和收益幅度的关系可参阅 [CFA Digest 关于 hit ratio 与 win/loss magnitude](https://rpc.cfainstitute.org/research/cfa-digest/2018/07/dig-v48-n7-8) 和 [Pardo《The Evaluation and Optimization of Trading Strategies》](https://www.wiley.com/en-ca/the-evaluation-and-optimization-of-trading-strategies-2nd-edition-p-9780470128015)。

### 2.7 样本数门槛

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

以下链接均为公开出处。它们用于支持交易约束、指数定义、绩效指标方法或选择偏差方法，不把公开论文当作 A 股有效性证明。本文写入前用 `curl -I -L` 核验，记录日期为 2026-11-21，状态均为 HTTP 200。

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

### 5.1 阈值状态汇总

本表明确列出 7 项数值或工程规则，均标记为未验证（待回测）。其余数据覆盖、复权链、退市清算和队列成交缺口在相应指标和边界表中单独标记，不能视为通过。

| 阈值或规则 | 当前状态 |
|---|---|
| T+1/T+5/T+20 | 产品窗口规则有公开交易日约束，具体策略表现未验证（待回测） |
| hold 阈值 1%/2%/5% | 初值，未验证（待回测） |
| `n<5`、`n<30` 展示门槛 | 与现有统计字段对齐，A 股统计有效性未验证（待回测） |
| 总样本 30、每折 10、至少 5 折 | 候选闸刀线，未验证（待回测） |
| PF 1.20 通过、1.00–1.20 观察、低于 1 淘汰 | 候选闸刀线，未验证（待回测） |
| 实盘相对 OOS −30%、Sharpe −0.50、MDD +50% | 候选降级线，未验证（待回测） |
| 目标/止损同柱按最坏顺序 | 工程保守规则，未验证（待回测） |

本卡不声明任何策略已通过 G6、已进入 `published` 或已完成实盘验证。所有无 A 股实证的数值保留“未验证”或“待回测”状态。

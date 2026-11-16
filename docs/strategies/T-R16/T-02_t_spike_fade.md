# T-02 分时急拉回落减仓T `t_spike_fade` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/T-02.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `t_spike_fade`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：已有底仓的股票在盘中短时急拉、相对 VWAP 偏离过大且动能衰竭时，先卖出部分旧股、回落后买回，可以在持股数量不变的情况下降低成本。
- falsified_by：1) 盘后统计中，触发后到 14:50 回落到回补带的比例不高于随机时点基线；2) 扣费后单腿结果中位数 ≤ 0；3) 急拉后继续单边上涨（被迫高位回补）的比例 > 30%（hypothesis）。
- 维度：technical 为 core；sector_market 为 veto（G-02 判 uptrend 且当日涨幅大时不做 sell_first，见 C1）；news 由 N-01 系统挂载；原稿把 `f.main_net_20d` 列为资金辅助：未验证，已删除。

## 4 标的范围
只针对持有合规可卖底仓的证券（主板、创业板、科创板；北交所不含）；ST、停牌、退市整理由 G-01 处理。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | 元 / ratio / ratio | none（当日） | 本 bar 结束后 | 已注册；1 分钟历史覆盖未核实（DAT-1） |
| f.close_qfq / f.high_qfq / f.low_qfq | 日 | 元 | qfq@as_of | T−1 盘后 | 已注册 |
| f.limit_up_price / f.limit_down_price | 日 | 元 | none | T 日盘前 | market_rules 计算 |
预热：当日已完成 ≥ 30 根 1 分钟 bar（hypothesis），10:00 前不触发；不足时 `insufficient_data`，不产生候选。数据缺失：vwap 类特征缺失或过期 → `DATA_STALE`，不做T。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry（sell_first） | `f.vwap_dev >= p.spike_k * f.intraday_sigma and f.vwap_dev >= p.spike_min` | 急拉偏离：同时满足 σ 倍数与绝对下限 |
| E2 | entry | `f.vwap_dev < ref(f.vwap_dev, 1)` | 动能衰竭；`ref` 的 bar 粒度待定（RUL-4） |
| E0 | filter（拟议） | `ctx.sellable_qty > 0` | 入场条件中的 ctx 字段（ENG-2） |
| C1 | counter | `f.close_qfq >= f.limit_up_price * (1 - p.near_limit)` | 接近涨停时容易被封板，回补失败风险高；此处 `f.close_qfq` 指盘中最新价（口径见 RUL-5） |
| I1 | invalidation | `f.vwap_dev >= p.invalid_dev` | 偏离继续扩大，判定为趋势日，当日不再做T |
| X1 | exit（回补） | `f.vwap_dev <= p.revert_band * f.intraday_sigma` | 回到 VWAP 附近买回 |
| X2 | exit（止损） | `f.vwap_dev >= (p.spike_k + p.stop_add) * f.intraday_sigma` | 偏离扩大止损，按规则买回 |
| X-T | exit（时间） | `ctx.now_hhmm >= p.time_stop_hhmm` | 日终了结；ctx.now_hhmm 已在 plan 列出 |
- 原稿 `pair_window_bars`、`max_concurrent_t` 属于执行与配对层（ENG-1），已从规则中移出。

## 8–10 执行与仓位
T 腿数量 ≤ `p.t_ratio` × `ctx.sellable_qty`，按整手规则取整；同一证券每天最多 `p.max_t_per_day` 次；一笔 T 结束后持仓数量回到原值，不新增净敞口。日终未回补的腿按 X-T 了结（规则设计；执行配对见 ENG-1）。

## 11 验证（本轮不写 golden）
方法 `fixture`、`trigger_stats` + 盘后重放：触发后回补率、单腿扣费后结果、日终未回补率，均以 `Stat` 输出并标“模拟”；时间切分样本外，`min_n=30`。

## 14 不可执行原因
`NO_POSITION`、`T1_NOT_SELLABLE`、`LIMIT_LOCKED`（buy 或 sell 方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range；uptrend 中只在 C1 未触发时使用。节奏：盘后重放统计。

## 17 A 股约束
本卡保持 `lifecycle: draft`，G7：☐，当前仍不可导入；下列约束只说明候选信号的可执行边界，不构成荐股或收益承诺。

| 项目 | 本卡约束与出处 |
|---|---|
| 涨跌停（按板块） | 普通主板 10%；创业板、科创板（含 ST/*ST）20%；北交所（含 ST/*ST）30%。来源：config/market_rules.yaml:8、config/market_rules.yaml:10、config/market_rules.yaml:11、config/market_rules.yaml:12。 |
| 主板 ST 历史分段 | 沪深主板 ST/*ST 在已建模的 2023-04-10 至 2026-07-05 为 5%，2026-07-06 起为 10%，不得把历史 5% 用于全部板块或当前交易日。回看按成交日有效段；2023-04-10 之前标“交易规则未建模”。来源：config/market_rules.yaml:4、config/market_rules.yaml:6、config/market_rules.yaml:9、config/market_rules.yaml:66、config/market_rules.yaml:69、config/market_rules.yaml:126、config/market_rules.yaml:129。 |
| 无涨跌幅及不可成交 | 沪深注册制新股前 5 个交易日、北交所新股首日、退市整理期首日按无涨跌幅限制处理，不套普通比例；一字涨停不能买，一字跌停不能卖，执行层记 `LIMIT_LOCKED` 并写明方向，不假定候选信号必然成交。来源：config/market_rules.yaml:13、config/market_rules.yaml:14、config/market_rules.yaml:15、config/market_rules.yaml:16、config/market_rules.yaml:58、config/market_rules.yaml:59；docs/strategies/_template.md:268。 |
| T+1 | 当日买入股份当日不可卖；设计层退出候选信号遇可卖量不足时记 `T1_NOT_SELLABLE`，不能靠回补新股恢复当日可卖量；当前仅盘后统计，不生成运行中的候选信号。来源：config/market_rules.yaml:36；docs/plan.md:1614；docs/strategies/_template.md:230。 |
| ST / 退市整理 | G-01 阻断买入；已有持仓仍须评估退出候选信号并服从 T+1、停牌及跌停约束，不能把排除 ST 当作省略历史比例的理由。来源：docs/strategies/_template.md:236；docs/plan.md:1624；config/market_rules.yaml:36、config/market_rules.yaml:59、config/market_rules.yaml:60。 |
| 停牌 | 记 `SUSPENDED`，候选信号冻结、不假定成交；停牌日不计入成本估算的有效成交额窗口，复牌后重新检查可交易性。来源：config/market_rules.yaml:60、config/market_rules.yaml:49；docs/strategies/_template.md:235、docs/strategies/_template.md:266。 |
| 北交所 30% | 比例用于说明市场约束，本卡仍排除北交所，保持 `boards.bse=false`，不因补充规则扩大扫描范围。来源：config/market_rules.yaml:12；docs/plan.md:4085。 |
| 交易单位 | 沪深主板、创业板买入为 100 股整数倍；科创板单笔买卖至少 200 股，超过部分按 1 股递增的仓库口径仅部分核实，本次仍标“未验证”；零股余额一次性卖出。来源：config/market_rules.yaml:18、config/market_rules.yaml:19、config/market_rules.yaml:20、config/market_rules.yaml:23；docs/plan.md:1619。 |

做T只用 T−1 日及以前形成的合规可卖底仓（`ctx.sellable_qty > 0`），不为做T当日开新仓；无底仓记 `NO_POSITION`，可卖不足记 `T1_NOT_SELLABLE`。本卡 `sell_first` 先卖旧股、后买回；回补股当日不能再卖。两腿配对语义（ENG-1）未实现，**两腿未配对时不可执行**，保持 `post_close_stats`，不产生运行中的候选信号、草案或通知；回补遇停牌或封板不能假定日终已恢复原持仓（来源：docs/strategies/_template.md:231；docs/strategies/T-R16/engine_gaps.md:11、docs/strategies/T-R16/engine_gaps.md:14；config/market_rules.yaml:58、config/market_rules.yaml:59、config/market_rules.yaml:60）。

## 18 成本与滑点（estimate）
以下为候选信号研究的费用估算口径；有仓库出处不等于已用实际成交验证，费率、滑点及冲击成本校准均保留“未验证”。

| 成本项 | 计算口径与出处 |
|---|---|
| 佣金 | 买卖双边各按 `max(单笔成交额 × 用户实际费率, 5 元)` 计算，单笔最低 5 元；实际费率未设置时不得填零，记“未验证”。来源：config/market_rules.yaml:45、config/market_rules.yaml:46；docs/plan.md:1621。 |
| 印花税 | 只计卖出，按实际成交日取有效段：2023-04-10 至 2023-08-27 为 0.1%，2023-08-28 起为 0.05%；更早日期不外推。来源：config/market_rules.yaml:4、config/market_rules.yaml:126、config/market_rules.yaml:163、config/market_rules.yaml:66、config/market_rules.yaml:103、config/market_rules.yaml:43。 |
| 过户费 | 买卖双边各计成交额的 0.001%。来源：config/market_rules.yaml:44、config/market_rules.yaml:104、config/market_rules.yaml:164；docs/plan.md:1621。 |
| 基础滑点 | 单边默认 10 bp（0.1%），为估算初值、未验证；不视为真实成交偏差。来源：config/market_rules.yaml:47；docs/plan.md:1621。 |
| 冲击成本 | 参与率 r = 拟成交额 ÷ 近 20 个有效交易日日成交额均值（停牌日不计），拟成交额 = 计划数量 × 参考价；各单边按 r≤0.1%、0.1%<r≤0.5%、0.5%<r≤1%、1%<r≤2%、r>2% 依次计 0/5/15/30/60 bp；最高档标“容量受限”（来源：docs/strategies/_template.md:262）。均为估算初值、未验证、待校准。来源：config/market_rules.yaml:48、config/market_rules.yaml:49、config/market_rules.yaml:50、config/market_rules.yaml:52、config/market_rules.yaml:53、config/market_rules.yaml:54、config/market_rules.yaml:55、config/market_rules.yaml:56；docs/plan.md:1622。 |

每边价格成本率 = 基础滑点 bp + 冲击成本 bp；先除以 10000 并乘该边成交额换算为金额，再将两边金额与两笔佣金、两边过户费、卖出印花税相加得到往返成本，避免金额和 bp 混加或重复扣费（来源：docs/strategies/_template.md:264）。停牌或涨跌停不可成交时不计算冲击成本、不登记成交；均额为零或有效 K 少于 5 根时不做除法，按最高档并标“冲击成本无法可靠估算”（来源：docs/strategies/_template.md:266、docs/strategies/_template.md:267、docs/strategies/_template.md:268）。计划估算只用当时可得的成交额与参考价，不用未来成交补齐；金额或费率缺失时不能形成完整扣费结论（时点约束来源：docs/plan.md:1625）。

本卡 `p.slippage_bp` 默认 10 bp；§22 的可调范围和步长未验证。做T按单腿拟成交额分别计算两腿成本，最低佣金逐笔应用，不得把两腿净额抵消后只算一笔佣金；两腿未完成配对时，不形成完整往返扣费结论（来源：docs/strategies/_template.md:269；config/market_rules.yaml:46；docs/strategies/T-R16/engine_gaps.md:11）。

## 20 冲突
与 T-01（VWAP 回归，含 buy_first）、T-04 方向可能相同：同一证券同日只记一次T（配对规则，ENG-1）；与 H-01 的 exit 冲突时以 H-01 为准，展示上并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| spike_k | float | 2.0 | 1.5 | 3.0 | 0.5 |
| spike_min | float | 0.025 | 0.015 | 0.05 | 0.005 |
| revert_band | float | 0.5 | 0.2 | 1.0 | 0.1 |
| stop_add | float | 1.0 | 0.5 | 2.0 | 0.5 |
| invalid_dev | float | 0.05 | 0.03 | 0.08 | 0.01 |
| near_limit | float | 0.02 | 0.01 | 0.05 | 0.01 |
| t_ratio | float | 0.3 | 0.1 | 0.5 | 0.05 |
| max_t_per_day | int | 1 | 1 | 2 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |
| time_stop_hhmm | 待定（RUL-2） | 14:50 | — | — | — |

## 23 当前不可导入原因与引擎需补能力
- ENG-1 两腿配对（未配对时不可执行）
- ENG-2 入场条件中引用 ctx 字段
- ENG-4 盘中实时求值（C(5) 条件满足前只做盘后统计）
- RUL-2 时刻类参数类型
- RUL-4 盘中 `ref`、`for N bars` 的粒度（bar 还是 day）
- DAT-1 1 分钟覆盖与 vwap 单位
- RUL-5 盘中最新价与 qfq 序列的口径

## 复核记录（相对 DeepSeek 原稿）
1. 原稿把 vwap 类特征标为 qfq，实际是 none（ratio），已改正
2. 原稿把 `f.limit_locked_up == 0` 作为入场条件，已改为执行层原因
3. 原稿重复写 N-01、G-01 门禁，已删除
4. 原稿只有百分比止损（0.015），与偏离单位不一致，已改为 σ 倍数止损
5. 原稿时间 `145500` 写成整数，类型待定
6. 资金辅助维度已删除

## T-R91b 补充复核
本次仅补齐 §17、§18 的候选信号约束与费用出处；`lifecycle: draft`，G7：☐。§22 既有策略阈值、参数范围和步长仍为未验证假设；除上文明确引用的市场规则及费用默认值外，没有补充实测依据，不将其表述为验证结论。不可导入原因和引擎缺口保持原状。

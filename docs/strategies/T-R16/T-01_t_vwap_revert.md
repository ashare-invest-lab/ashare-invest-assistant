# T-01 均价偏离回归做T `t_vwap_revert` — 知识卡 v1（T-R16 首批）

> **当前状态：不可导入**（83a66cd 裁定：本批不补卡/golden，实现 MVP 后再议；文中做T配对、null 与组合约束、新特征等“待定”项一律暂停）。下文“可进入模板”仅表示未来潜力。

> **标签：仅知识卡**（不可进入可运行模板）。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/T-01.md`，未核实草稿），本文是研究员复核后的版本，改动见末节。所有阈值均为 hypothesis，不含收益或回测数字。来源：通用规则组合，无外部来源。
> 不能进模板的原因：① 盘中快照延迟只有小样本实测，不满足 C(5) 的开放条件；② 1 分钟历史覆盖**未核实**，`f.vwap_intraday`、`f.vwap_dev`、`f.intraday_sigma` 的单位与口径【待 T003】；③ 引擎已有 `t_leg`（plan 2.5.11A），但同一笔 T 的卖腿与买腿如何配对、回补怎么写成规则，plan 没有给示例（待架构师）。目前只能按 `scan.mode: post_close_stats` 做盘后统计，不产生候选、草案或通知。

## 1 身份
key `t_vwap_revert`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设与维度
- why_it_works（hypothesis）：持有底仓的股票在日内相对当日 VWAP 出现显著偏离（以当日已实现波动归一化）后，有向 VWAP 回归的倾向；顺着偏离的反方向做一次T，可以在不改变持仓数量的前提下降低持仓成本。
- falsified_by：① 盘后统计中，触发后到 14:50 前回到 VWAP 回补带的比例，不高于同股同日随机时点的基线；② 扣除往返成本后，单腿结果的中位数 ≤ 0；③ 14:50 时仍未回补的比例 > 30%（hypothesis）。
- 维度：technical 为 core；sector_market 为 veto（G-02 判定 `downtrend` 时不做 `buy_first`）；news 为 veto（N-01 由系统挂载，本卡不重复写）。capital、fundamental、sentiment 不参与（原稿把 `f.main_net_20d` 和 vwap 偏离归入资金、情绪维度，已删除）。

## 4 标的范围
**只针对已有合规可卖底仓的证券**：`ctx.sellable_qty > 0`，且可卖部分只来自 T−1 日及以前买入的持仓。A 股当日新买入的股份当日不能卖出：严禁“当日新仓卖出”，也不允许为了做T当日先开新仓。ST、停牌、退市整理由 G-01 处理；北交所不在范围内。

## 5 数据（PIT）
| 键 | 频率 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | none（当日不复权） | 本 bar 结束后 | 单位与口径【待 T003】，1 分钟历史覆盖未核实 |
| f.close_qfq（前收） | 日线 | qfq@as_of | T−1 收盘后 | 已实测 |
| f.limit_up_price / f.limit_down_price | 日 | none | T 日开盘前 | 由 market_rules 计算 |
| f.market_regime | 日 | — | T−1 盘后 | G-02 |
预热：σ 至少需要当日已完成的 30 根 1 分钟 bar（hypothesis），30 根之前（约 10:00 前）不触发。

## 7 规则（只在盘后重放时求值；DSL 写法待 `t_leg` 机制确定后才能定稿）
- E-S（sell_first 上偏）：`f.vwap_dev >= p.k * f.intraday_sigma and ctx.now_hhmm < p.last_entry_hhmm`，前提是 `ctx.sellable_qty > 0`（ctx 字段只能用在 hold/exit 角色，入场条件怎么表达**待定**）。
- E-B（buy_first 下偏）：`f.vwap_dev <= -p.k * f.intraday_sigma`，同时要求有足够的可卖底仓，用于当日卖出等量旧股完成回补；新买入的股份当日不可卖。
- X-R（回补）：`between(f.vwap_dev, -p.revert_band * f.intraday_sigma, p.revert_band * f.intraday_sigma)`。
- X-T（时间止损，止损类）：`ctx.now_hhmm >= p.time_stop_hhmm`，此时仍未回补就按规则了结当日的 T 腿。
- X-S（偏离扩大止损）：偏离达到 `p.stop_mult × k × σ`（abs 不在白名单内，上下两侧分开写）。
- C1（反证，趋势日）：日内涨跌幅超过 `p.trend_abs_pct`，用 `ctx.last_price` 相对前收计算；**不得使用当日收盘价**，原稿 `pct_change(f.close_qfq,1)` 在盘中会用到未来数据，已删除。
- I1（失效）：`f.market_regime == 'downtrend'`，不做 `buy_first`。
冲突处理：H-01 给出 weakening 或 exit 时，压制 `buy_first`，两张卡的结论并列展示。

## 8–10 入场 / 退出 / 仓位
同一证券每天最多做 `p.max_t_per_day` 次；T 腿数量 ≤ `p.t_ratio` × 可卖底仓，按 market_rules 的整手规则取整（科创板 ≥ 200 股、按 1 股递增；其余板块 100 股整数倍）。一笔 T 结束后持仓数量回到原值，不新增净敞口。

## 11 验证
方法：`fixture`、`trigger_stats`，加盘后重放统计（回补率、单腿扣费后结果、14:50 未回补率，均以 `Stat` 输出并标“模拟”）。按时间切分做样本外检验，`min_n=30`。

## 14 不可执行原因
`NO_POSITION`（无底仓）、`T1_NOT_SELLABLE`（可卖不足）、`LIMIT_LOCKED`（买卖两个方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range、uptrend；趋势日不做。节奏：盘后重放统计；开放盘中运行需满足 C(5) 条件并经用户确认。

## 17 A 股约束
本卡保持 `lifecycle: draft`，G7：☐，当前仍不可导入；下列约束只说明候选信号的可执行边界，不构成荐股或收益承诺。

| 项目 | 本卡约束与出处 |
|---|---|
| 涨跌停（按板块） | 普通主板 10%；创业板、科创板（含 ST/*ST）20%；北交所（含 ST/*ST）30%。来源：config/market_rules.yaml:8、config/market_rules.yaml:10、config/market_rules.yaml:11、config/market_rules.yaml:12。 |
| 主板 ST 历史分段 | 在已建模的 2023-04-10 至 2026-07-05，沪深主板 ST/*ST 涨跌幅限制为 5%，2026-07-06 起为 10%。按交易日和板块取值，早于建模起点的日期标“交易规则未建模”。见 config/market_rules.yaml 的 `modeled_from`、`segments[].price_limit_pct.main_board_st` 及[沪深交易所发布通知与修订说明 O1–O6](../market_rules_check.md)。 |
| 无涨跌幅及不可成交 | 沪深注册制新股前 5 个交易日、北交所新股首日、退市整理期首日按无涨跌幅限制处理，不套普通比例；一字涨停不能买，一字跌停不能卖，执行层记 `LIMIT_LOCKED` 并写明方向，不假定候选信号必然成交。来源：config/market_rules.yaml:13、config/market_rules.yaml:14、config/market_rules.yaml:15、config/market_rules.yaml:16、config/market_rules.yaml:58、config/market_rules.yaml:59；docs/strategies/_template.md:268。 |
| T+1 | 当日买入股份当日不可卖；当日退出候选信号仍记录，但执行层记 `T1_NOT_SELLABLE`，顺延至满足可卖及可成交条件的交易日。来源：config/market_rules.yaml:36；docs/plan.md:1614；docs/strategies/_template.md:230。 |
| ST / 退市整理 | G-01 阻断买入；已有持仓仍须评估退出候选信号并服从 T+1、停牌及跌停约束，不能把排除 ST 当作省略历史比例的理由。来源：docs/strategies/_template.md:236；docs/plan.md:1624；config/market_rules.yaml:36、config/market_rules.yaml:59、config/market_rules.yaml:60。 |
| 停牌 | 记 `SUSPENDED`，候选信号冻结、不假定成交；停牌日不计入成本估算的有效成交额窗口，复牌后重新检查可交易性。来源：config/market_rules.yaml:60、config/market_rules.yaml:49；docs/strategies/_template.md:235、docs/strategies/_template.md:266。 |
| 北交所 30% | 比例用于说明市场约束，本卡仍排除北交所，保持 `boards.bse=false`，不因补充规则扩大扫描范围。来源：config/market_rules.yaml:12；docs/plan.md:4085。 |
| 交易单位 | 沪深主板、创业板买入为 100 股整数倍；科创板单笔买卖至少 200 股，超过部分按 1 股递增的仓库口径仅部分核实，本次仍标“未验证”；零股余额一次性卖出。来源：config/market_rules.yaml:18、config/market_rules.yaml:19、config/market_rules.yaml:20、config/market_rules.yaml:23；docs/plan.md:1619。 |

做T只用昨日及以前形成的合规可卖底仓：`sell_first` 卖旧股；`buy_first` 也必须有足量旧股用于卖腿，当日新买股份不能充当可卖量。无底仓或可卖不足时不可执行；两腿配对仍未实现，保持盘后统计模式，不产生运行中的候选信号、草案或通知（来源：docs/strategies/_template.md:231；本卡 §4、§7 的既有边界）。

## 18 成本与滑点（estimate）
以下为候选信号研究的费用估算口径；有仓库出处不等于已用实际成交验证，费率、滑点及冲击成本校准均保留“未验证”。

| 成本项 | 计算口径与出处 |
|---|---|
| 佣金 | 沪深普通 A 股按买、卖每笔分别估算。实际费率、最低额及所含规费以券商协议为准，均未验证。5 元为仓库建模默认及历史制度背景。含规费佣金中已计的经手费、证管费不再叠加；缺实际收费口径时保留费用缺口。见 config/market_rules.yaml 的 `fees` 与[费用审计 §5 F24–F25](../T-R74/param_audit.md)。 |
| 印花税 | 仅卖出方按成交金额计税。本卡建模期内，2023-04-10 至 2023-08-27 为 0.1%，2023-08-28 起为 0.05%。依据[《印花税法》第三、五条及税目税率表](https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html)和[财政部、税务总局 2023 年第 39 号公告](https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm)。 |
| 过户费 | 中国结算自 2022-04-29 起按成交金额的 0.001% 向买卖双方分别收取，覆盖本卡从 2023-04-10 开始的建模期。此前沪深计费基数和费率按历史有效段另查。[中国结算降费通知](https://www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml)；[历史对照 F06–F10](../T-R74/param_audit.md)。 |
| 基础滑点 | 单边默认 10 bp（0.1%），为估算初值、未验证；不视为真实成交偏差。来源：config/market_rules.yaml:47；docs/plan.md:1621。 |
| 冲击成本 | 参与率 r = 拟成交额 ÷ 近 20 个有效交易日日成交额均值（停牌日不计），拟成交额 = 计划数量 × 参考价；各单边按 r≤0.1%、0.1%<r≤0.5%、0.5%<r≤1%、1%<r≤2%、r>2% 依次计 0/5/15/30/60 bp；最高档标“容量受限”。均为估算初值、未验证、待校准。来源：config/market_rules.yaml:48、config/market_rules.yaml:49、config/market_rules.yaml:50、config/market_rules.yaml:52、config/market_rules.yaml:53、config/market_rules.yaml:54、config/market_rules.yaml:55、config/market_rules.yaml:56；docs/plan.md:1622。 |

往返成本 = 两边基础滑点与冲击成本 + 两笔佣金 + 两边过户费 + 卖出印花税；价格成本与费用只计一次（来源：docs/strategies/_template.md:264）。停牌或涨跌停不可成交时不计算冲击成本、不登记成交；均额为零或有效 K 少于 5 根时不做除法，按最高档并标“冲击成本无法可靠估算”（来源：docs/strategies/_template.md:266、docs/strategies/_template.md:267、docs/strategies/_template.md:268）。计划估算只用当时可得的成交额与参考价，不用未来成交补齐；金额或费率缺失时不能形成完整扣费结论（时点约束来源：docs/plan.md:1625）。

做T按单腿拟成交额分别计算两腿成本，最低佣金逐笔应用（来源：docs/strategies/_template.md:269；config/market_rules.yaml:46）。保留既有研究条件：`k × σ` 对应价差须 ≥ `p.min_edge_cost_mult × 往返成本`；其中倍数默认 2.0 的成本门槛思路可追溯到 docs/strategies/_template.md:272，但等号边界、参数范围与本卡做T适用性均未验证，不据此判定晋级。

## 20 冲突
与 W-01、H-01 并列展示，不合并；G-01、N-01 由系统挂载。

## 22 参数（hypothesis）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| k | float | 2.0 | 1.0 | 4.0 | 0.5 |
| revert_band | float | 0.5 | 0.2 | 1.0 | 0.1 |
| stop_mult | float | 1.5 | 1.0 | 3.0 | 0.5 |
| trend_abs_pct | float | 0.05 | 0.02 | 0.08 | 0.01 |
| t_ratio | float | 0.3 | 0.1 | 0.5 | 0.1 |
| max_t_per_day | int | 1 | 1 | 2 | 1 |
| min_edge_cost_mult | float | 2.0 | 1.0 | 5.0 | 0.5 |
| time_stop_hhmm / last_entry_hhmm | — | 14:50 / 14:30 | — | — | — |
时刻类参数的类型不在 plan 2.5.14 D 节的 int/float/bool/enum 中，**待定**（建议用 enum）。

## 复核记录（相对 DeepSeek 原稿）
1. 原稿 key 与 name 互换，category 不在枚举内：已改正。
2. 原稿使用 `abs()`，不在 DSL 白名单内：已改为 between 或上下两侧分开写。
3. 原稿用 `pct_change(f.close_qfq,1)` 判趋势日，盘中会用到当日收盘价（未来数据）：已改为基于 `ctx.last_price`。
4. 原稿在入场条件里用 ctx 字段，当前 DSL 不允许：标为待定。
5. 原稿把 counter 角色写成“回补”：已改为 exit 类的回补规则，counter 只放反证。
6. 原稿冲击成本档位是自编的：已改为 plan 2.13 的分档。
7. 原稿把跌停写成 vetoed：已改为执行层原因 `LIMIT_LOCKED`。
8. 原稿把涨跌停价标为 qfq：已改为 none。
9. 原稿把资金、情绪辅助维度写进卡里：已删除。
**暂停（83a66cd，等 MVP）**：t_leg 配对机制、入场条件中 ctx 字段的用法、时刻类参数类型、vwap 类特征的单位与延迟实测。

## 缺口交叉引用
见 [engine_gaps.md](engine_gaps.md)：ENG-1, ENG-2, ENG-4, RUL-2, DAT-1。

## T-R91 补充复核
本次仅补齐 §17、§18 的候选信号约束与费用出处；`lifecycle: draft`，G7：☐。§22 既有策略阈值、参数范围和步长仍为未验证假设；除上文明确引用的市场规则及费用默认值外，没有补充实测依据，不将其表述为验证结论。不可导入原因和引擎缺口保持原状。

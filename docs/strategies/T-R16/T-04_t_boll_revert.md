# T-04 布林外轨回归T `t_boll_revert` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/T-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `t_boll_revert`；category `intraday_t`；horizons `[intraday_t]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：日线布林带处于收敛状态时，盘中价格触及外轨，更可能是短期噪声，有向中轨回归的倾向；用底仓做反向T。
- falsified_by：1) 盘后统计中，触及外轨后当日回到中轨方向（回补带）的比例不高于基线；2) 扣费后单腿结果中位数 ≤ 0；3) 带宽不在收敛区间时结论与收敛区间相同（说明收敛条件无效）。
- 维度：technical 为 core；sector_market 为 veto（downtrend 时不做 buy_first）；news 由 N-01 系统挂载。

## 4 标的范围
持有合规可卖底仓的主板、创业板、科创板证券，上市满 120 个交易日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.boll_bw20_pct120 | 日 | ratio | qfq | T−1 盘后 | 已注册 |
| f.close_qfq | 日 | 元 | qfq@as_of | T−1 盘后 | 已注册 |
| 布林 %b（拟议，FEA-2） | 日或盘中 | 比值 | qfq | — | 未注册 |
| f.vwap_intraday / f.vwap_dev / f.intraday_sigma | 盘中 1m | 元 / ratio / ratio | none（当日） | 本 bar 结束后 | 已注册；1 分钟历史覆盖未核实（DAT-1） |
预热：日线 140 根有效 K（布林 20 + 120 日分位）+ 当日 30 根 1 分钟 bar；不足时 `insufficient_data`，不产生候选。数据缺失：日线特征缺失 → `insufficient_data`；盘中缺失 → `DATA_STALE`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.boll_bw20_pct120 <= p.bw_th` | 日线收敛（T−1 盘后值） |
| E2 | entry（buy_first） | `f.vwap_intraday <= (ma(f.close_qfq, 20) - p.band_k * std(f.close_qfq, 20)) * (1 + p.touch)` | 盘中均价触及下轨；带由 T−1 及以前的 qfq 收盘计算，口径见 RUL-5 |
| E3 | entry（sell_first） | `f.vwap_intraday >= (ma(f.close_qfq, 20) + p.band_k * std(f.close_qfq, 20)) * (1 - p.touch)` | 触及上轨 |
| C1 | counter | `f.boll_bw20_pct120 > p.bw_th` | 带宽扩张，可能是趋势启动（与 W-02 冲突） |
| X1 | exit（回补） | `between(f.vwap_dev, -p.revert_band, p.revert_band)` | 回到当日均价附近 |
| X2 | exit（止损） | `f.vwap_intraday <= (ma(f.close_qfq, 20) - (p.band_k + p.stop_add) * std(f.close_qfq, 20))` | buy_first 方向继续破位止损（sell_first 对称） |
| X-T | exit（时间） | `ctx.now_hhmm >= p.time_stop_hhmm` | 日终了结 |
- 原稿 `ctx.last_price <= ctx.cost_price_qfq - 1.5 * atr(14)` 把做T单腿止损和持仓成本止损混在一起，已改为基于带宽的 X2。
- 原稿 `ctx.holding_days >= 3` 不适用于日内T，已删除。

## 8–10 执行与仓位
T 腿数量 ≤ `p.t_ratio` × `ctx.sellable_qty`，按整手规则取整；同一证券每天最多 `p.max_t_per_day` 次；一笔 T 结束后持仓数量回到原值，不新增净敞口。日终未回补的腿按 X-T 了结（规则设计；执行配对见 ENG-1）。

## 11 验证（本轮不写 golden）
方法 `fixture`、`trigger_stats` + 盘后重放：触发后回补率、单腿扣费后结果、日终未回补率，均以 `Stat` 输出并标“模拟”；时间切分样本外，`min_n=30`。对照组为不加收敛条件的触轨样本。

## 14 不可执行原因
`NO_POSITION`、`T1_NOT_SELLABLE`、`LIMIT_LOCKED`（buy 或 sell 方向）、`SUSPENDED`、`DATA_STALE`、`NON_TRADING_TIME`；盘后统计模式下只做统计，不产生不可执行原因。

## 15–16 环境与节奏
适用于 range；节奏：盘后重放统计。

## 17 A 股约束
本卡保持 `lifecycle: draft`，G7：☐，当前仍不可导入；下列约束只说明候选信号的可执行边界，不构成荐股或收益承诺。

| 项目 | 本卡约束与出处 |
|---|---|
| 涨跌停（按板块） | 普通主板 10%；创业板、科创板（含 ST/*ST）20%；北交所（含 ST/*ST）30%。来源：config/market_rules.yaml:8、config/market_rules.yaml:10、config/market_rules.yaml:11、config/market_rules.yaml:12。 |
| 主板 ST 历史分段 | 在已建模的 2023-04-10 至 2026-07-05，沪深主板 ST/*ST 涨跌幅限制为 5%，2026-07-06 起为 10%。按交易日和板块取值，早于建模起点的日期标“交易规则未建模”。见 config/market_rules.yaml 的 `modeled_from`、`segments[].price_limit_pct.main_board_st` 及[沪深交易所发布通知与修订说明 O1–O6](../market_rules_check.md)。 |
| 无涨跌幅及不可成交 | 沪深注册制新股前 5 个交易日、北交所新股首日、退市整理期首日按无涨跌幅限制处理，不套普通比例；一字涨停不能买，一字跌停不能卖，执行层记 `LIMIT_LOCKED` 并写明方向，不假定候选信号必然成交。来源：config/market_rules.yaml:13、config/market_rules.yaml:14、config/market_rules.yaml:15、config/market_rules.yaml:16、config/market_rules.yaml:58、config/market_rules.yaml:59；docs/strategies/_template.md:268。 |
| T+1 | 当日买入股份当日不可卖；设计层退出候选信号遇可卖量不足时记 `T1_NOT_SELLABLE`，不能靠回补新股恢复当日可卖量；当前仅盘后统计，不生成运行中的候选信号。来源：config/market_rules.yaml:36；docs/plan.md:1614；docs/strategies/_template.md:230。 |
| ST / 退市整理 | G-01 阻断买入；已有持仓仍须评估退出候选信号并服从 T+1、停牌及跌停约束，不能把排除 ST 当作省略历史比例的理由。来源：docs/strategies/_template.md:236；docs/plan.md:1624；config/market_rules.yaml:36、config/market_rules.yaml:59、config/market_rules.yaml:60。 |
| 停牌 | 记 `SUSPENDED`，候选信号冻结、不假定成交；停牌日不计入成本估算的有效成交额窗口，复牌后重新检查可交易性。来源：config/market_rules.yaml:60、config/market_rules.yaml:49；docs/strategies/_template.md:235、docs/strategies/_template.md:266。 |
| 北交所 30% | 比例用于说明市场约束，本卡仍排除北交所，保持 `boards.bse=false`，不因补充规则扩大扫描范围。来源：config/market_rules.yaml:12；docs/plan.md:4085。 |
| 交易单位 | 沪深主板、创业板买入为 100 股整数倍；科创板单笔买卖至少 200 股，超过部分按 1 股递增的仓库口径仅部分核实，本次仍标“未验证”；零股余额一次性卖出。来源：config/market_rules.yaml:18、config/market_rules.yaml:19、config/market_rules.yaml:20、config/market_rules.yaml:23；docs/plan.md:1619。 |

做T只用 T−1 日及以前形成的合规可卖底仓（`ctx.sellable_qty > 0`），不为做T当日开新仓；无底仓记 `NO_POSITION`，可卖不足记 `T1_NOT_SELLABLE`。`sell_first` 卖出旧股后买回；`buy_first` 也须预留等量可卖旧股用于卖腿，当日新买股份不能充当可卖量。两腿配对语义（ENG-1）未实现，**两腿未配对时不可执行**，保持 `post_close_stats`，不产生运行中的候选信号、草案或通知；回补遇停牌或封板不能假定日终已恢复原持仓（来源：docs/strategies/_template.md:231；docs/strategies/T-R16/engine_gaps.md:11、docs/strategies/T-R16/engine_gaps.md:14；config/market_rules.yaml:58、config/market_rules.yaml:59、config/market_rules.yaml:60）。

## 18 成本与滑点（estimate）
以下为候选信号研究的费用估算口径；有仓库出处不等于已用实际成交验证，费率、滑点及冲击成本校准均保留“未验证”。

| 成本项 | 计算口径与出处 |
|---|---|
| 佣金 | 沪深普通 A 股按买、卖每笔分别估算。实际费率、最低额及所含规费以券商协议为准，均未验证。5 元为仓库建模默认及历史制度背景。含规费佣金中已计的经手费、证管费不再叠加；缺实际收费口径时保留费用缺口。见 config/market_rules.yaml 的 `fees` 与[费用审计 §5 F24–F25](../T-R74/param_audit.md)。 |
| 印花税 | 仅卖出方按成交金额计税。本卡建模期内，2023-04-10 至 2023-08-27 为 0.1%，2023-08-28 起为 0.05%。依据[《印花税法》第三、五条及税目税率表](https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html)和[财政部、税务总局 2023 年第 39 号公告](https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm)。 |
| 过户费 | 中国结算自 2022-04-29 起按成交金额的 0.001% 向买卖双方分别收取，覆盖本卡从 2023-04-10 开始的建模期。此前沪深计费基数和费率按历史有效段另查。[中国结算降费通知](https://www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml)；[历史对照 F06–F10](../T-R74/param_audit.md)。 |
| 基础滑点 | 单边默认 10 bp（0.1%），为估算初值、未验证；不视为真实成交偏差。来源：config/market_rules.yaml:47；docs/plan.md:1621。 |
| 冲击成本 | 参与率 r = 拟成交额 ÷ 近 20 个有效交易日日成交额均值（停牌日不计），拟成交额 = 计划数量 × 参考价；各单边按 r≤0.1%、0.1%<r≤0.5%、0.5%<r≤1%、1%<r≤2%、r>2% 依次计 0/5/15/30/60 bp；最高档标“容量受限”（来源：docs/strategies/_template.md:262）。均为估算初值、未验证、待校准。来源：config/market_rules.yaml:48、config/market_rules.yaml:49、config/market_rules.yaml:50、config/market_rules.yaml:52、config/market_rules.yaml:53、config/market_rules.yaml:54、config/market_rules.yaml:55、config/market_rules.yaml:56；docs/plan.md:1622。 |

每边价格成本率 = 基础滑点 bp + 冲击成本 bp；先除以 10000 并乘该边成交额换算为金额，再将两边金额与两笔佣金、两边过户费、卖出印花税相加得到往返成本，避免金额和 bp 混加或重复扣费（来源：docs/strategies/_template.md:264）。停牌或涨跌停不可成交时不计算冲击成本、不登记成交；均额为零或有效 K 少于 5 根时不做除法，按最高档并标“冲击成本无法可靠估算”（来源：docs/strategies/_template.md:266、docs/strategies/_template.md:267、docs/strategies/_template.md:268）。计划估算只用当时可得的成交额与参考价，不用未来成交补齐；金额或费率缺失时不能形成完整扣费结论（时点约束来源：docs/plan.md:1625）。

本卡 `p.slippage_bp` 默认 10 bp；§22 的可调范围和步长未验证。做T按单腿拟成交额分别计算两腿成本，最低佣金逐笔应用，不得把两腿净额抵消后只算一笔佣金；两腿未完成配对时，不形成完整往返扣费结论（来源：docs/strategies/_template.md:269；config/market_rules.yaml:46；docs/strategies/T-R16/engine_gaps.md:11）。

## 20 冲突
与 W-02（收敛后突破）在带宽扩张时方向相反；与 T-01 同日同证券只记一次T。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| bw_th | float | 0.3 | 0.1 | 0.4 | 0.05 |
| band_k | float | 2.0 | 1.5 | 2.5 | 0.25 |
| touch | float | 0.002 | 0.0 | 0.005 | 0.001 |
| revert_band | float | 0.005 | 0.002 | 0.01 | 0.001 |
| stop_add | float | 0.5 | 0.25 | 1.0 | 0.25 |
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
- FEA-2 布林 %b（可选；不登记时用 ma 和 std 组合，DSL 长度 ≤ 300 字符）
- DAT-1 1 分钟覆盖
- RUL-5 日线 qfq 带与盘中价的口径

## 复核记录（相对 DeepSeek 原稿）
1. 原稿称“只依赖已有特征”，但需要盘中价，DAT-1 未验证，已改正
2. 原稿止损混入持仓成本与 ATR，已改为基于带宽
3. 原稿时间止损按日计，已删除
4. 口径：qfq@as_of 下当日价格不复权，与 T−1 及以前的 qfq 序列可比，但需要裁定（RUL-5）

## T-R91b 补充复核
本次仅补齐 §17、§18 的候选信号约束与费用出处；`lifecycle: draft`，G7：☐。§22 既有策略阈值、参数范围和步长仍为未验证假设；除上文明确引用的市场规则及费用默认值外，没有补充实测依据，不将其表述为验证结论。不可导入原因和引擎缺口保持原状。

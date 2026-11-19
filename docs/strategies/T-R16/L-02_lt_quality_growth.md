# L-02 质量成长 `lt_quality_growth` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/L-02.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `lt_quality_growth`；category `quality`；horizons `[long]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：高 ROE、利润增长、低负债、现金流良好的公司，长期复利更稳定；按月再平衡持有。
- falsified_by：1) PIT 门禁关闭后，样本外滚动 12 个月月度组合扣费超额中位数 ≤ 0；2) 去掉现金流条件后结论不变（说明该条件无效）；3) 高 ROE 组的 ROE 次年均值回归幅度与全市场没有差异。
- 维度：fundamental 为 core；technical 为 auxiliary（不参与入场）；news 由 N-01 系统挂载。

## 4 标的范围
全 A（不含北交所）；上市满 250 日；银行和保险的负债率为 null，处理方式见 RUL-1。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.roe_ttm_pit | 季（PIT） | pct（15 = 15%） | — | 公告日 | declared（DAT-2） |
| f.np_yoy_latest | 事件 | pct | — | plrq 次日 09:30 | declared |
| f.debt_ratio_pit | 季 | ratio（0.6 = 60%） | — | 公告日 | declared；银行和保险为 null |
| f.ocf_to_np_ttm_pit | 季 | ratio | — | 公告日 | declared；归母净利润 ≤ 0 时为 null |
预热：ROE 需要 P 期与 P−4 期；不足时为 null；不足时 `insufficient_data`，不产生候选。数据缺失：任一 PIT 字段为 null（银行和保险的负债率除外，RUL-1）→ `KEY_DATA_MISSING`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.roe_ttm_pit >= p.roe_min` |  |
| E2 | entry | `f.np_yoy_latest >= p.yoy_min` |  |
| E3 | entry | `f.debt_ratio_pit <= p.debt_max` | 原稿写 60，单位应为 ratio 0.6 |
| E4 | entry | `f.ocf_to_np_ttm_pit >= p.ocf_min` |  |
| F1 | filter | `f.list_days >= 250` |  |
| C1 | counter | `f.np_yoy_latest < 0` | 增长转负 |
| I1 | invalidation | `f.roe_ttm_pit < p.roe_exit` | 质量跌破 |
| X1 | exit（止损） | `f.close_qfq <= ctx.cost_price_qfq * (1 - p.stop_pct)` |  |
| X2 | exit | `f.roe_ttm_pit < p.roe_exit or f.ocf_to_np_ttm_pit < p.ocf_exit` |  |
| X3 | exit | `f.np_yoy_latest < p.yoy_exit` |  |
- 原稿“按 rank_pct 合成排序取前 N”属于组合层（ENG-3），不写在卡内规则里。
- 原稿 `f.roe_ttm_pit < 10 for 20 bars`：财报是季度频率，按日 for 20 没有意义，已改为 I1。

## 8–10 执行与仓位
每月第一个交易日盘后出 screen，次日开盘模拟成交；等权，单票上限按 RC2；行业上限与 top-N 属于组合层（ENG-3，拟议）。

## 11 验证（本轮不写 golden）
门禁关闭前只做 `fixture` 和 `post_close_stats`；关闭后做 walk-forward（训练 36 个月 / 测试 12 个月），`min_n` 为 24 个月度截面。

## 14 不可执行原因
`KEY_DATA_MISSING`（PIT 字段为 null 或门禁未关闭）、`SUSPENDED`、`LIMIT_LOCKED`（sell 方向写 direction）、`T1_NOT_SELLABLE`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
不依赖 G-02 择时；月度节奏。

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

本卡 `p.slippage_bp` 的默认值沿上述 10 bp；§22 的可调范围和步长未验证，不代表完成校准。月度再平衡中的每笔买入和卖出分别扣费，不能因预期持有期较长而省略单笔最低佣金或冲击成本。

## 20 冲突
与 L-01 在选股层可能重叠（去重属于 ENG-3）；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| roe_min | float | 15.0 | 10.0 | 25.0 | 1.0 |
| yoy_min | float | 10.0 | 0.0 | 30.0 | 5.0 |
| debt_max | float | 0.6 | 0.4 | 0.8 | 0.05 |
| ocf_min | float | 0.8 | 0.5 | 1.2 | 0.1 |
| roe_exit | float | 10.0 | 5.0 | 15.0 | 1.0 |
| ocf_exit | float | 0.5 | 0.3 | 0.8 | 0.1 |
| yoy_exit | float | -10.0 | -30.0 | 0.0 | 5.0 |
| stop_pct | float | 0.2 | 0.1 | 0.3 | 0.05 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- DAT-2 PIT 门禁
- ENG-3 月度调度、top-N、行业上限
- RUL-1 null 放行语义

## 复核记录（相对 DeepSeek 原稿）
1. 负债率单位已改正（pct → ratio）
2. 按日 for 20 bars 的写法已删除
3. 原稿“ma_trend == 1”与特征单位（pct）不符，已删除
4. 原稿重复写 G-01、N-01 门禁，已删除

## T-R91 补充复核
本次仅补齐 §17、§18 的候选信号约束与费用出处；`lifecycle: draft`，G7：☐。§22 既有策略阈值、参数范围和步长仍为未验证假设；除上文明确引用的市场规则及费用默认值外，没有补充实测依据，不将其表述为验证结论。不可导入原因和引擎缺口保持原状。

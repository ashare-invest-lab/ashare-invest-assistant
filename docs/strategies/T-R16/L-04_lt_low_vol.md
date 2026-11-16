# L-04 低波动 `lt_low_vol` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/L-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `lt_low_vol`；category `low_vol`；horizons `[long]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：低波动股票的风险调整后收益长期不差于高波动股票（低波动异象；本卡没有引用核实过的文献）。
- falsified_by：1) 样本外月度截面低波动组的夏普比率不高于全市场；2) 低波动组超额全部来自行业暴露（如银行），行业中性后消失；3) 换手成本扣除后超额 ≤ 0。
- 维度：technical（波动）为 core；sector_market 为 auxiliary（行业分散）；news 由 N-01 系统挂载。

## 4 标的范围
全 A（不含北交所）；上市满 120 日；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.volatility_20d | 日 | ratio | qfq | T 盘后 | 已注册 |
| f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
| f.sw_l1 | — | — | — | — | 来源待 T003（DAT-3），只用于行业分散 |
预热：20 根有效日 K（≥15）；不足时 `insufficient_data`，不产生候选。数据缺失：波动率缺失 → `insufficient_data`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `rank_pct(f.volatility_20d) <= p.vol_pct` | 全市场截面 |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| C1 | counter | `rank_pct(f.volatility_20d) > 0.5` | 波动上升 |
| I1 | invalidation | `f.amount_20d_avg < p.min_amount * 0.6` | 流动性下降 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 原稿用 `ctx.last_price`，已改 |
| X2 | exit | `rank_pct(f.volatility_20d) > p.vol_exit` |  |
- 原稿 `rank_pct_in(f.sw_l1) <= 0.2` 的参数语义错误（应为 `rank_pct_in(x, group_key)`），行业分散属于组合层（ENG-3、ENG-5）。
- 原稿 `f.is_suspended == 1 for 5 days` 作为失效条件：停牌由 G-01 和执行层处理，已删除。

## 8–10 执行与仓位
每月第一个交易日盘后出 screen，次日开盘模拟成交；等权，单票上限按 RC2；行业上限与 top-N 属于组合层（ENG-3，拟议）。

## 11 验证（本轮不写 golden）
walk-forward 月度截面，`min_n` 为 24；同时报告行业中性前后的结果。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
不择时；月度节奏。

## 17 A 股约束
本卡保持 `lifecycle: draft`，G7：☐，当前仍不可导入；下列约束只说明候选信号的可执行边界，不构成荐股或收益承诺。

| 项目 | 本卡约束与出处 |
|---|---|
| 涨跌停（按板块） | 普通主板 10%；创业板、科创板（含 ST/*ST）20%；北交所（含 ST/*ST）30%。来源：config/market_rules.yaml:8、config/market_rules.yaml:10、config/market_rules.yaml:11、config/market_rules.yaml:12。 |
| 主板 ST 历史分段 | 沪深主板 ST/*ST 在已建模的 2023-04-10 至 2026-07-05 为 5%，2026-07-06 起为 10%，不得把历史 5% 用于全部板块或当前交易日。回看按成交日有效段；2023-04-10 之前标“交易规则未建模”。来源：config/market_rules.yaml:4、config/market_rules.yaml:6、config/market_rules.yaml:9、config/market_rules.yaml:66、config/market_rules.yaml:69、config/market_rules.yaml:126、config/market_rules.yaml:129。 |
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
| 佣金 | 买卖双边各按 `max(单笔成交额 × 用户实际费率, 5 元)` 计算，单笔最低 5 元；实际费率未设置时不得填零，记“未验证”。来源：config/market_rules.yaml:45、config/market_rules.yaml:46；docs/plan.md:1621。 |
| 印花税 | 只计卖出，按实际成交日取有效段：2023-04-10 至 2023-08-27 为 0.1%，2023-08-28 起为 0.05%；更早日期不外推。来源：config/market_rules.yaml:4、config/market_rules.yaml:126、config/market_rules.yaml:163、config/market_rules.yaml:66、config/market_rules.yaml:103、config/market_rules.yaml:43。 |
| 过户费 | 买卖双边各计成交额的 0.001%。来源：config/market_rules.yaml:44、config/market_rules.yaml:104、config/market_rules.yaml:164；docs/plan.md:1621。 |
| 基础滑点 | 单边默认 10 bp（0.1%），为估算初值、未验证；不视为真实成交偏差。来源：config/market_rules.yaml:47；docs/plan.md:1621。 |
| 冲击成本 | 参与率 r = 拟成交额 ÷ 近 20 个有效交易日日成交额均值（停牌日不计），拟成交额 = 计划数量 × 参考价；各单边按 r≤0.1%、0.1%<r≤0.5%、0.5%<r≤1%、1%<r≤2%、r>2% 依次计 0/5/15/30/60 bp；最高档标“容量受限”（来源：docs/strategies/_template.md:262）。均为估算初值、未验证、待校准。来源：config/market_rules.yaml:48、config/market_rules.yaml:49、config/market_rules.yaml:50、config/market_rules.yaml:52、config/market_rules.yaml:53、config/market_rules.yaml:54、config/market_rules.yaml:55、config/market_rules.yaml:56；docs/plan.md:1622。 |

每边价格成本率 = 基础滑点 bp + 冲击成本 bp；先除以 10000 并乘该边成交额换算为金额，再将两边金额与两笔佣金、两边过户费、卖出印花税相加得到往返成本，避免金额和 bp 混加或重复扣费（来源：docs/strategies/_template.md:264）。停牌或涨跌停不可成交时不计算冲击成本、不登记成交；均额为零或有效 K 少于 5 根时不做除法，按最高档并标“冲击成本无法可靠估算”（来源：docs/strategies/_template.md:266、docs/strategies/_template.md:267、docs/strategies/_template.md:268）。计划估算只用当时可得的成交额与参考价，不用未来成交补齐；金额或费率缺失时不能形成完整扣费结论（时点约束来源：docs/plan.md:1625）。

本卡 `p.slippage_bp` 的默认值沿上述 10 bp；§22 的可调范围和步长未验证，不代表完成校准。月度再平衡中的每笔买入和卖出分别扣费，不能因预期持有期较长而省略单笔最低佣金或冲击成本。

## 20 冲突
与 L-03 红利可能重叠（银行）；去重属于 ENG-3。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| vol_pct | float | 0.3 | 0.1 | 0.5 | 0.05 |
| vol_exit | float | 0.7 | 0.5 | 0.9 | 0.05 |
| stop_pct | float | 0.15 | 0.08 | 0.25 | 0.01 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- ENG-3 月度调度、top-N、行业分散
- ENG-5 分组截面函数
- DAT-3 行业来源

## 复核记录（相对 DeepSeek 原稿）
1. `rank_pct_in` 参数用法已改正，并移到组合层
2. 口径混用已改正
3. 停牌失效条件已删除
4. 原稿“可进模板”下调：缺组合层

## T-R91b 补充复核
本次仅补齐 §17、§18 的候选信号约束与费用出处；`lifecycle: draft`，G7：☐。§22 既有策略阈值、参数范围和步长仍为未验证假设；除上文明确引用的市场规则及费用默认值外，没有补充实测依据，不将其表述为验证结论。不可导入原因和引擎缺口保持原状。

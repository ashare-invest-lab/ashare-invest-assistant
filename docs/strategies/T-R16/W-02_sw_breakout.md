# W-02 收敛放量突破 `sw_breakout` — 知识卡 v1（T-R16 首批）

> **当前状态：不可导入**（83a66cd 裁定：本批不补卡/golden，实现 MVP 后再议；文中做T配对、null 与组合约束、新特征等“待定”项一律暂停）。下文“可进入模板”仅表示未来潜力。

> **标签：未来可进入模板，当前不可导入**（所用特征均在 feature_spec 中已注册；DSL 已按白名单复核）。突破位用 `plan.breakout_level_qfq`，实现 MVP 后可用。初稿来自 DeepSeek（`team/reports/deepseek/T-R16/W-02.md`，未核实草稿），本文为复核后版本。阈值均为 hypothesis；来源：通用规则组合，无外部来源；不含收益数字。

## 1 身份
key `sw_breakout`；category `momentum`；horizons `[swing]`（观察窗 3–10 日，最长持有 `p.max_hold` 日）。

## 3 假设与维度
- why_it_works（hypothesis）：布林带宽处于长期低分位，说明波动收敛；此时放量创 20 日收盘新高，往往是新一段波动的起点。量价同时确认可以减少无量假突破。
- falsified_by：① 收敛 + 放量突破的样本中，3 日内跌回突破位 3% 以下的比例与随机突破基准没有差异；② 样本外 10 日扣费超额中位数 ≤ 0；③ 参数邻域（分位阈值 0.1–0.3、放量倍数 1.3–2.0）内结论符号翻转。
- 维度：technical 为 core；sector_market 为 veto（`downtrend`）；news 为 veto（N-01，系统挂载）。原稿把 `f.main_net_20d` 列为辅助：资金类特征未验证，已删除。

## 5 数据（均为日线，T 日盘后可得）
f.close_qfq（qfq@as_of）；f.boll_bw20_pct120；f.amount、f.amount_20d_avg（none，单位元）；f.list_days；f.market_regime。
预热：布林 20 根 + 120 日分位 → **140 根有效日 K**（停牌日不计）；不足时 `insufficient_data`。

## 7 规则
| id | role | expr |
|---|---|---|
| E1 | entry | `f.boll_bw20_pct120 <= p.bw_pct120_th` |
| E2 | entry | `f.close_qfq > ref(highest(f.close_qfq, 20), 1)`（高于前 20 日最高收盘，不含当日） |
| E3 | entry | `f.amount >= f.amount_20d_avg * p.vol_mult` |
| F1 | filter | `f.amount_20d_avg >= p.min_amount` |
| F2 | filter | `f.list_days >= p.min_list_days` |
| V1 | veto | `f.market_regime == 'downtrend'` |
| C1 | counter | `pct_change(f.close_qfq, 1) > 0.095`（突破当日接近涨停，次日成交与追高风险大；主板阈值，创业板和科创板按 market_rules 换算，**待定**） |
| I1 | invalidation | `f.close_qfq < plan.entry_price_qfq * (1 - p.fail_pct) within 3 days`（突破失败） |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` |
| X2 | exit | `f.close_qfq < ma(f.close_qfq, 10) for 2 days` |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold` |
| X4 | exit（时间止损） | `ctx.holding_days >= 3 and ctx.max_r_reached < 0.5` |
- 原稿各处的改动：
  - V1（停牌、ST、上市天数）→ G-01 和 F2 处理。
  - V3（公告）→ N-01 系统挂载，本卡不重复写。
  - V4（`f.limit_locked_up` 作为 veto）→ 改为执行层原因 `LIMIT_LOCKED`。
  - 原稿 `highest(...)[1]` 的下标写法不在 DSL 内 → 改为 `ref(..., 1)`。
  - 原稿 C2/X3 写成 `... not (...) for 3 days`，DSL 语义不清 → 改为 X4。
  - 原稿 X5（公告）→ N-01 处理。
- X5 跌回突破位（实现 MVP 后）：`f.close_qfq < plan.breakout_level_qfq * (1 - p.fail_pct)`（83a66cd 裁定）；本卡在 MVP 前不可导入，不以入场价替代突破位。

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘价模拟入场（出处：docs/plan.md:1283）；信号有效 1 个交易日。止损价截断到涨跌停价之内。仓位按 RC2/RC3 建议。

## 11 验证
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days `[3,10]`；`min_n=30`；基准：中证全指或所属行业指数；对照组为“无收敛条件的 20 日新高”样本。正式卡导入前需补 ≥ 6 个虚构 golden，包括 140 根预热不足和停牌跨越的用例。

## 14 不可执行原因
`LIMIT_LOCKED`（buy 方向：突破次日一字涨停；sell 方向：一字跌停）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–17 环境 / 节奏 / A股约束
适用于 uptrend、range；每日盘后扫描。T+1 规则同 S-01。注册制新股上市前 5 日没有涨跌幅限制，但 F2 已经把这段时间排除在外。整手：科创板 ≥ 200 股、按 1 股递增，其余板块 100 股整数倍。

## 18 成本（estimate）
佣金按买卖分别计收，费率和单笔最低额以券商协议为准。5 元仅作历史或建模参考，实收及费用实现未验证。沪深 A 股按市场和成交日选段：自 2022-04-29 起，过户费买卖每边为成交金额的 0.001%，此前按 F06–F08 核对市场、计费基数和日期；自 2023-08-28 起，卖方印花税为成交金额的 0.05%，此前按 F01–F04 选段。出处：docs/strategies/T-R74/param_audit.md §5.1 F01–F08、F10、F25。`slippage_bp` 15（突破日流动性偏紧，取 S-01 的 1.5 倍）；冲击成本按 plan 2.13 分档。

## 20 冲突
与 W-01（回踩买入）同标的同日都触发时并列展示；与 H-01 并列展示，不合并。

## 22 参数（hypothesis）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| bw_pct120_th | float | 0.2 | 0.05 | 0.4 | 0.05 |
| vol_mult | float | 1.5 | 1.2 | 3.0 | 0.1 |
| fail_pct | float | 0.03 | 0.01 | 0.05 | 0.01 |
| stop_pct | float | 0.05 | 0.03 | 0.10 | 0.01 |
| max_hold | int | 20 | 10 | 40 | 5 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 120 | 60 | 250 | 10 |
| slippage_bp（estimate） | float | 15.0 | 0.0 | 50.0 | 1.0 |

## 复核记录
key 与 name 已改正；category 已归入枚举；下标写法已改为 `ref`；veto 与执行层原因已分开；公告与可交易性交还 G-01、N-01；“未站稳”时间修饰已改写；突破位改用 `plan.breakout_level_qfq`（MVP 后）。

## 缺口交叉引用
见 [engine_gaps.md](engine_gaps.md)：QFQ-2, RUL-3。

## 22A 参数敏感性（T-R89 研究补充）

文档生命周期 `lifecycle: draft`；G7 ☐。保持不可导入，仅描述候选信号，不构成投资建议或收益承诺；不修改原规则、默认值或引擎能力。下表覆盖 §22 全部参数，原取值及范围可追溯，但适用性、扫描结果与影响方向均**未验证**，`sensitivity: 未评估`。范围是待检验的原稿网格，不是有效区间结论；比例为小数、金额为元、时间为交易日。

| 参数 | 原取值 | 合理扫描范围 / 步长（均未验证） | 预期影响方向（未验证，其他条件不变） | 取值与范围出处 |
|---|---|---|---|---|
| bw_pct120_th | 0.20 | 0.05–0.40 / 0.05 | 提高阈值放宽收敛条件，候选信号集合不缩小；可能纳入较高波动事件 | docs/strategies/T-R16/W-02_sw_breakout.md:64 |
| vol_mult | 1.5 | 1.2–3.0 / 0.1 | 提高倍数收紧放量条件，候选信号减少 | docs/strategies/T-R16/W-02_sw_breakout.md:65 |
| fail_pct | 0.03 | 0.01–0.05 / 0.01 | 提高容忍跌幅使突破失败阈值降低，失效判定更晚 | docs/strategies/T-R16/W-02_sw_breakout.md:66 |
| stop_pct | 0.05 | 0.03–0.10 / 0.01 | 提高阈值降低百分比止损价，触发更晚；损失暴露可能增大 | docs/strategies/T-R16/W-02_sw_breakout.md:67 |
| max_hold | 20 | 10–40 / 5 | 增大上限延后时间退出，扩大暴露和标签跨度 | docs/strategies/T-R16/W-02_sw_breakout.md:68 |
| min_amount | 50000000 | 10000000–500000000 / 10000000 | 提高下限减少候选信号，偏向较高流动性 | docs/strategies/T-R16/W-02_sw_breakout.md:69 |
| min_list_days | 120 | 60–250 / 10 | 提高下限排除更多上市时间短的证券 | docs/strategies/T-R16/W-02_sw_breakout.md:70 |
| slippage_bp（estimate） | 15 | 0–50 / 1 | 提高滑点使同一成交路径扣费结果不升，不改变原始候选信号 | docs/strategies/T-R16/W-02_sw_breakout.md:71 |

固定参数没有替代范围依据时仅取原值单点，不编造范围；改变时的机制方向也未验证。特征窗口改变须另开定义，不能沿用旧特征键冒充同一试验。

| 固定项 | 取值 / 本轮范围 | 改变时的预期方向与边界（未验证） | 出处 |
|---|---|---|---|
| 布林、分位窗口 / 预热 | 20根、120日 / 140根；各固定原值 | 延长窗口通常更平滑，响应变慢；提高预热减少可评估样本；分位方向不保证单调 | docs/strategies/T-R16/W-02_sw_breakout.md:16；docs/strategies/T-R16/W-02_sw_breakout.md:17 |
| 突破窗口 / 偏移 | 前20日最高收盘 / 1日；固定原值 | 延长最高价窗口使突破门槛不降，候选信号不增；偏移用于排除当日 | docs/strategies/T-R16/W-02_sw_breakout.md:23 |
| 成交额均值 | 20日；固定20 | 延长窗口通常更平滑，放量比方向取决于近期路径 | docs/strategies/T-R16/W-02_sw_breakout.md:24 |
| C1 近涨停反证 | 1日涨幅 >0.095；仅主板原值 | 提高阈值减少反证；其他板块换算无已定范围，未验证，不套用主板阈值 | docs/strategies/T-R16/W-02_sw_breakout.md:28 |
| I1 观察期 | 3日；固定3 | 延长观察增加可能触发的时间；原入场价参照与突破位参照不可混用 | docs/strategies/T-R16/W-02_sw_breakout.md:29；docs/strategies/T-R16/W-02_sw_breakout.md:41 |
| X2 均线 / 连续确认 | MA10 / 2日；固定原值 | 延长均线响应通常变慢；增加连续日数推迟该退出 | docs/strategies/T-R16/W-02_sw_breakout.md:31 |
| X4 时间 / R门槛 | 持有≥3日且最大R<0.5；固定原值 | 提高时间阈值延后检查；提高R门槛使更多路径符合退出条件 | docs/strategies/T-R16/W-02_sw_breakout.md:33 |
| 有效期 / 成交时点 | 1日 / T+1开盘；固定原值 | 延长有效期增加陈旧暴露；不得使用 T 收盘成交 | docs/strategies/T-R16/W-02_sw_breakout.md:44 |
| 验证周期 / 最少样本 | 3、10日 / 30；固定原值 | 延长周期增加标签重叠；提高样本门槛推迟判定 | docs/strategies/T-R16/W-02_sw_breakout.md:47 |
| 费用与冲击（estimate） | 佣金率、最低额按券商协议，未验证、不扫描，5 元仅作建模参考；税费按 §18 的市场和成交日选段；冲击0/5/15/30/60bp；参与率界0.1%/0.5%/1%/2%，ADV20；冲击档位固定 | 提高费用使扣费结果不升；费率/规模无证据不计算净结果；冲击档位待校准 | docs/strategies/T-R16/W-02_sw_breakout.md:56；docs/strategies/_template.md:253；docs/strategies/_template.md:258；docs/strategies/_template.md:259；docs/strategies/_template.md:260；docs/strategies/_template.md:261；docs/strategies/_template.md:262 |

防过拟合要求（方法有据、本卡效果未验证）：

- **样本外**：按时间滚动5折，训练选参、下一折评估；隔离期 h 覆盖标签持有跨度，跨折标签剔除；最近12个月为只看一次的最终保留集。动态持有期的 h 规则须预先冻结，未冻结不开始扫描。来源：docs/strategies/validation.md:68、docs/strategies/validation.md:151。
- **参数平原**：每参先查原默认值 ±1 step，扩展网格预登记，全部参数组合≤50；不穷举原范围笛卡尔积。邻点结果翻号或较中心下降超过一半即不稳健。原稿带宽0.1–0.3、放量1.3–2.0是另列稳健性窗口，不替换原默认值，也纳入试验预算。来源：docs/strategies/validation.md:141、docs/strategies/validation.md:142、docs/strategies/T-R16/W-02_sw_breakout.md:12。
- **多重比较校正**：登记全部成功及失败试验，参数、窗口、分组构成预先冻结的检验族；统一 BH 校正 q=0.10，报告原始及校正后 p 值；q 为建议初值、未验证。来源：docs/strategies/validation.md:146、docs/strategies/validation.md:147。
- 候选信号仅使用 `available_at ≤ T` 的输入、当时复权及交易制度；T 后结果只供成熟标签检验，不参与 T 的判断或选参。保留当日收敛与突破同时成立的定义，不改成事后择时；来源：docs/strategies/validation.md:21、docs/strategies/validation.md:35、docs/strategies/validation.md:41、docs/strategies/validation.md:190、[T-R71 W-02 §23「审计、差异与未决」](../T-R71/W-02_sw_breakout.md#23-审计差异与未决)。

## 3A 失效条件（T-R89 确定性研究规格）

全部为**未验证**的研究判据。单次候选信号失效、假设失效、数据不足分别记录；命中只触发研究复核，不自动改生命周期，仍 draft、G7 ☐（docs/strategies/validation.md:193）。

| 判据 | 指标与阈值 | 观察窗口与最少样本 | 出处 / 状态 |
|---|---|---|---|
| 单次突破结构失效 | 冻结信号日 T 的突破位 `B=前20个有效日最高收盘`，与判断日价格换算到同一 qfq@as_of；`close_qfq(d)<B×(1−fail_pct)`，默认 fail_pct=0.03 | 最早模拟成交 U=T+1 起前3个交易日内，任一有效收盘满足即记录；至少1次完整候选信号及可比较突破位，触发日数据齐备，并满足140根预热。未满窗口且未触发不能判“未失效” | 突破位：docs/strategies/T-R16/W-02_sw_breakout.md:23、docs/strategies/T-R16/W-02_sw_breakout.md:41；3日与3%：docs/strategies/T-R16/W-02_sw_breakout.md:12；预热：docs/strategies/T-R16/W-02_sw_breakout.md:17；窗口起点的研究展开未验证 |
| 策略假设失效 | 主基准扣费超额中位数 `median(E_10) ≤ 0` | 截至 D 最近120个交易日产生且10日标签已结束的样本外候选信号；去重后完整可成交样本 n≥30 | 10日与零阈值：docs/strategies/T-R16/W-02_sw_breakout.md:12；n：docs/strategies/T-R16/W-02_sw_breakout.md:47；120日借用 docs/strategies/validation.md:122，迁用未验证 |
| 参数稳定性失效 | 中心 `median(E_10)>0`，任一 ±1 step 邻点中位数 ≤0 或 `< 中心中位数×0.5` | 同一上述120日样本外窗口、同一成本及基准；中心及各参评邻点分别 n≥30，缺样本不判通过 | 邻域与一半阈值：docs/strategies/validation.md:142；n：docs/strategies/T-R16/W-02_sw_breakout.md:47；确定性展开未验证 |

结构判据按原稿 §3 的“突破位”假设写成研究量；**不把入场价替代突破位**。原 §7 I1 使用入场价，而 X5 使用突破位，且角色/ctx/plan 限制仍有缺口（[T-R71 W-02 §23「审计、差异与未决」](../T-R71/W-02_sw_breakout.md#23-审计差异与未决)）。本节不偷偷修订原 DSL；QFQ-2、角色及基准口径未核验前结构判据不执行，状态写未验证。

`E_10`：T 盘后候选信号最早在 U=T+1 开盘模拟成交，从 U 开盘至 U+10 开盘的后复权收益，减同区间基准收益及完整往返成本；依据 docs/strategies/T-R16/W-02_sw_breakout.md:44、docs/strategies/validation.md:51、docs/strategies/validation.md:40。主基准沪深300、辅基准中证全指沿 docs/strategies/T-R71/W-02_sw_breakout.md:21，基准覆盖未验证，不代替原行业证伪；固定周期标签与按 §7 退出的研究统计分列。

按证券、候选信号日排序，同证券保留与上一已保留标签区间不重叠且满足3日冷却的首次候选信号；依据 docs/strategies/validation.md:53、docs/strategies/validation.md:131，组合去重规则未验证。仅计 D 时已成熟标签；不可成交不计 n、但单列数量与比例（docs/strategies/validation.md:39）。少于30或成本/基准缺失记“未验证/样本不足”，不能判有效。

原稿“与随机突破基准没有差异”缺随机对照生成方法、种子及等效界值，仍标**未验证**；不以不显著认定等效。R 统计、跨板块近涨停参数及结构位实现仍待核验；止损或结构失效都不保证按阈值成交。

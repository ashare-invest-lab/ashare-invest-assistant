# S-04 断板反包 `st_broken_board` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/S-04.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `st_broken_board`；category `momentum`；horizons `[short]`；risk_level `high`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：连板后首次断板（分歧）后，次日放量收复断板日高点，说明分歧转一致、情绪修复。
- falsified_by：1) 样本外反包次日起 3 日扣费超额中位数 ≤ 0；2) 放量条件与不放量组没有差异；3) downtrend 环境下结论与 uptrend 相同。
- 维度：sentiment 为 core；technical 为 core（收复高点）；capital（成交额）为 auxiliary；sector_market 为 veto；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 60 日。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.is_limit_up_close / f.limit_up_count_20d | 日 | bool / count | none | T 盘后 | 已注册 |
| f.close_qfq / f.high_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
| f.amount / f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
预热：20 根有效日 K；不足时 `insufficient_data`，不产生候选。数据缺失：关键特征缺失 → `insufficient_data`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `ref(f.is_limit_up_close, 2) == true and ref(f.is_limit_up_close, 1) == false and f.limit_up_count_20d >= p.min_boards` | T−2 封板、T−1 断板 |
| E2 | entry | `f.close_qfq > ref(f.high_qfq, 1)` | 收复断板日高点 |
| E3 | entry | `f.amount > f.amount_20d_avg * p.vol_ratio` | 放量 |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.close_qfq >= f.limit_up_price` | 当日已封板，次日可能一字买不进；仍记录统计（口径：limit_up_price 为 none，在 qfq@as_of 当日可比） |
| I1 | invalidation | `f.close_qfq < ref(f.high_qfq, 2) for 2 days` | 跌回断板前区间 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` |  |
| X1b | exit（止损，实现 MVP 后） | `f.close_qfq < plan.breakout_level_qfq` | 断板日高点（QFQ-2） |
| X2 | exit | `f.close_qfq < ma(f.close_qfq, 5)` |  |
| X3 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |
- 原稿用 `ref(f.high_qfq, ctx.holding_days + 1)`（动态偏移），DSL 不支持，已改为 X1b。
- 原稿 E1 只看 T−1 封板、T 断板，与“次日反包”的时序不符，已改为 T−2 封板、T−1 断板、T 反包。

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘模拟入场；有效期 1 个交易日；仓位按 RC2。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [1,3,5]；`min_n=30`。

## 14 不可执行原因
`LIMIT_LOCKED`（两个方向）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 uptrend、range；每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-03 互斥（同标的同日）；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| min_boards | int | 2 | 1 | 5 | 1 |
| vol_ratio | float | 1.5 | 1.2 | 3.0 | 0.1 |
| stop_pct | float | 0.05 | 0.03 | 0.1 | 0.01 |
| max_hold | int | 5 | 3 | 10 | 1 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- QFQ-2 `plan.breakout_level_qfq`（已裁定，未实现）
- RUL-3 按板块换算的近涨停阈值

## 复核记录（相对 DeepSeek 原稿）
1. E1 时序已修正
2. 动态 ref 已删除，改为 QFQ-2
3. 原稿“板块背离降权”在 DSL 中没有降权语义，已删除
4. 原稿 `p_sector_max` 属于组合层，已删除
5. 原稿收盘封板样本被排除，改为记录统计

## 22A 参数敏感性（T-R89 研究补充）

文档生命周期 `lifecycle: draft`；G7 ☐。保持不可导入及高风险草稿定位，仅描述候选信号，不构成投资建议或收益承诺。本节不改变原规则、参数默认值或引擎能力。下表覆盖 §22 全部参数；原值及网格可追溯，但范围合理性、方向及扫描结果均**未验证**，`sensitivity: 未评估`。方向指其他参数不变时的规则变化，不代表收益趋势。比例为小数、时间为交易日。

| 参数 | 原取值 | 合理扫描范围 / 步长（均未验证） | 预期影响方向（未验证） | 取值与范围出处 |
|---|---|---|---|---|
| min_boards | 2 | 1–5 / 1 | 提高门槛减少候选信号，更依赖近期封板经历；计数不等于连续板数 | docs/strategies/T-R16/S-04_st_broken_board.md:65 |
| vol_ratio | 1.5 | 1.2–3.0 / 0.1 | 提高倍数减少放量候选信号，可能增加事件集中度 | docs/strategies/T-R16/S-04_st_broken_board.md:66 |
| stop_pct | 0.05 | 0.03–0.10 / 0.01 | 提高阈值降低百分比止损价，触发更晚；隔夜损失暴露可能扩大 | docs/strategies/T-R16/S-04_st_broken_board.md:67 |
| max_hold | 5 | 3–10 / 1 | 增大上限延后时间退出，扩大隔夜暴露和标签跨度 | docs/strategies/T-R16/S-04_st_broken_board.md:68 |
| slippage_bp（estimate） | 10 | 0–50 / 1 | 提高滑点使同一成交路径扣费结果不升，不改变原始候选信号 | docs/strategies/T-R16/S-04_st_broken_board.md:69 |

固定项同样列入审计；没有替代范围依据的项目仅取原值单点，不虚构上下限。改变方向只是待验证机制，不授权修改特征定义。

| 固定项 | 取值 / 本轮范围 | 改变时的预期方向与边界（未验证） | 出处 |
|---|---|---|---|
| 上市门槛 | 60日；固定60 | 提高门槛排除更多上市时间短的证券 | docs/strategies/T-R16/S-04_st_broken_board.md:15 |
| 封板计数、均额窗口、预热 | 20日、20日、20根；各固定原值 | 延长计数窗使同阈值更易满足，但混入更早事件；均额更平滑；提高预热减少样本 | docs/strategies/T-R16/S-04_st_broken_board.md:20；docs/strategies/T-R16/S-04_st_broken_board.md:22；docs/strategies/T-R16/S-04_st_broken_board.md:23 |
| 事件次序 / 企稳参照 | T−2封板、T−1断板、T收复T−1高点；偏移2/1固定 | 改变偏移即改变事件定义，候选信号数量无单调保证 | docs/strategies/T-R16/S-04_st_broken_board.md:28；docs/strategies/T-R16/S-04_st_broken_board.md:29 |
| I1 高点偏移 / 确认 | 偏移2根、连续2日；固定原值 | 增加连续确认长度通常推迟失效；参照是滚动高点，不是冻结的断板日高点 | docs/strategies/T-R16/S-04_st_broken_board.md:33 |
| X2 均线 | MA5；固定5 | 延长均线通常更平滑，但跌破频率方向依赖路径 | docs/strategies/T-R16/S-04_st_broken_board.md:36 |
| 有效期 / 成交时点 | 1日 / T+1开盘；固定原值 | 延长有效期增加陈旧暴露；不得改用 T 收盘成交 | docs/strategies/T-R16/S-04_st_broken_board.md:42 |
| 验证周期 / 最少样本 | 1、3、5日 / 30；固定原值 | 延长周期增加标签重叠；提高样本门槛推迟判定 | docs/strategies/T-R16/S-04_st_broken_board.md:45 |
| 费用与冲击（estimate） | 佣金费率未给值（未验证、不扫描）；最低5元；卖出税0.05%；双边过户0.001%；冲击0/5/15/30/60bp；参与率界0.1%/0.5%/1%/2%，ADV20；均固定 | 提高费用使扣费结果不升；缺费率/规模证据不计算净结果；冲击档位仍需校准 | docs/strategies/T-R16/S-04_st_broken_board.md:57；docs/strategies/_template.md:253；docs/strategies/_template.md:258；docs/strategies/_template.md:259；docs/strategies/_template.md:260；docs/strategies/_template.md:261；docs/strategies/_template.md:262 |

防过拟合要求（方法可追溯，本卡适用性未验证）：

- **样本外**：时间滚动5折，训练折选参、下一折评估；隔离期 h 覆盖标签持有跨度，跨折标签剔除；最近12个月最终保留集只看一次，改参数后更换保留集。动态退出的 h 计算规则必须预先冻结，否则不开扫。来源：docs/strategies/validation.md:68、docs/strategies/validation.md:151。
- **参数平原**：默认值及每参 ±1 step 邻域优先，扩展网格预登记；全部组合不超过50。邻点结果翻号或较中心下降超过一半即记不稳健；不以单点峰值作为有效性依据。来源：docs/strategies/validation.md:141、docs/strategies/validation.md:142。
- **多重比较校正**：失败试验、参数组合、窗口、分组一并登记，预先固定检验族，统一 BH 校正 q=0.10，报告校正前后 p 值；q 是建议初值、未验证。来源：docs/strategies/validation.md:146、docs/strategies/validation.md:147。
- 只使用 `available_at ≤ T`、qfq@as_of 及当时涨跌停制度；未来结果仅作为到期标签，不能回填候选信号或选参。原稿 §17 的固定 ST 百分比不得跨期使用，依据 docs/strategies/_template.md:232。封板计数按交易日，停牌与无涨跌幅日不得伪算封板；证据缺失向计数传播不足，依据 docs/strategies/T-R71/S-04_st_broken_board.md:190；时点及复权依据 docs/strategies/validation.md:21、docs/strategies/validation.md:35、docs/strategies/validation.md:190。

## 3A 失效条件（T-R89 确定性研究规格）

以下为研究判据，**全部未验证**；单次候选信号结构失效不等于整张卡退役。触发仅记录并复核，生命周期仍 draft，G7 ☐；样本或证据不足时不作通过结论（处置依据 docs/strategies/validation.md:193）。

| 判据 | 指标与阈值 | 观察窗口与最少样本 | 出处 / 状态 |
|---|---|---|---|
| 单次结构失效 | 连续两个有效判断日满足 `close_qfq(d)<high_qfq(d−2)` 且 `close_qfq(d−1)<high_qfq(d−3)`；严格小于 | 每个盘后日检查最近2个有效判断日；至少4根有效日K支持偏移，并同时满足20根预热；缺数据不当作满足 | docs/strategies/T-R16/S-04_st_broken_board.md:33；docs/strategies/T-R16/S-04_st_broken_board.md:23；4根由偏移2及连续2日展开得出，未验证 |
| 策略假设失效 | 主基准扣费超额中位数 `median(E_3) ≤ 0` | 截至 D 最近120个交易日产生且3日标签成熟的样本外候选信号；去重后完整可成交样本 n≥30 | 3日及零阈值：docs/strategies/T-R16/S-04_st_broken_board.md:11；n：docs/strategies/T-R16/S-04_st_broken_board.md:45；120日借用 docs/strategies/validation.md:122，迁用未验证 |
| 参数稳定性失效 | 中心 `median(E_3)>0`，任一 ±1 step 邻点中位数 ≤0 或 `< 中心中位数×0.5` | 同一上述120日样本外窗口；中心及各参评邻点分别 n≥30；固定成本与基准，缺样本即未验证 | 邻域与一半阈值：docs/strategies/validation.md:142；n：docs/strategies/T-R16/S-04_st_broken_board.md:45；确定性展开未验证 |

`E_3`：T 盘后候选信号的最早模拟入场 U=T+1，从 U 开盘至 U+3 开盘的后复权收益，减同区间基准收益及完整往返成本；来源为 docs/strategies/T-R16/S-04_st_broken_board.md:42、docs/strategies/validation.md:51、docs/strategies/validation.md:40。主基准沪深300、辅基准中证全指沿 docs/strategies/T-R71/S-04_st_broken_board.md:21，接入覆盖未验证。固定周期标签与按 §7 退出的研究统计分列。

按证券、候选信号日排序，同证券保留与上一已保留标签区间不重叠且满足3日冷却的首次候选信号；依据 docs/strategies/validation.md:53、docs/strategies/validation.md:131，组合去重规则未验证。标签须在 D 前结束，不能借用未来数据；一字板、停牌等不可成交样本不进 n，但报告数量和比例（docs/strategies/validation.md:39）。少于30或成本/基准缺失，写“未验证/样本不足”，不能判有效。

原稿“放量与不放量组没有差异”“下行与上行结论相同”缺等效界值与分组最少样本，继续标**未验证**，不以 p 值不显著认定相同。I1 的滚动高点判据与 X1b 的冻结断板日高点分别记录；后者依赖 QFQ-2，不据此宣称实现。所有退出仍受 T+1、停牌和涨跌停约束。

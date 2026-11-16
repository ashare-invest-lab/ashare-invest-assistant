# S-02 超跌反弹 `st_oversold_rebound` — 知识卡 v1（T-R16 第二批）

> **当前状态：不可导入**（83a66cd 裁定后，本轮只写知识内容，不补 golden，不实现引擎）。下面的 expr 是设计层规则，**不是**当前可以导入的 schema；标“拟议”的字段、函数、语义在契约中还不存在，不代表现有能力或新的裁定。
> 初稿：DeepSeek（`team/reports/deepseek/T-R16/S-02.md`，未核实草稿），本文为研究员逐条复核后的版本。来源：通用规则组合，无外部来源。阈值均为 hypothesis，不含收益、回测或覆盖率数字。

## 1 身份
key `st_oversold_rebound`；category `reversal`；horizons `[short]`；risk_level `normal`。

## 3 假设、反证与维度
- why_it_works（hypothesis）：短期跌幅过大、RSI 超卖后出现收盘企稳，抛压暂时出清，常见 1–5 日技术性反弹。
- falsified_by：1) 样本外信号后 3 日扣费超额中位数 ≤ 0；2) 企稳确认组与未确认组没有差异（说明企稳条件无效）；3) downtrend 环境下的胜率与 range 相同（说明环境否决无效）。
- 维度：technical 为 core；sector_market 为 veto（downtrend）；news 由 N-01 系统挂载。

## 4 标的范围
主板、创业板、科创板；上市满 `p.min_list_days`；20 日均额 ≥ `p.min_amount`。

## 5 数据（时点 / 单位 / 复权 / 预热）
| 键 | 频率 | 单位 | 复权 | 可得时点 | 状态 |
|---|---|---|---|---|---|
| f.rsi14 | 日 | 0–100 | qfq | T 盘后 | 已注册 |
| f.close_qfq / f.low_qfq / f.high_qfq | 日 | 元 | qfq@as_of | T 盘后 | 已注册 |
| f.amount / f.amount_20d_avg | 日 | CNY | none | T 盘后 | 已注册 |
| f.market_regime | 日 | enum | — | T 盘后 | G-02 |
预热：RSI 预热 28 根；取 30 根有效日 K；不足时 `insufficient_data`，不产生候选。数据缺失：`f.market_regime` 缺失 → 买入方向 `KEY_DATA_MISSING`。

## 7 规则（设计层定稿；未定的部分标 拟议 / 待定）
| id | role | expr | 说明 |
|---|---|---|---|
| E1 | entry | `f.rsi14 < p.rsi_os within 3 days` | 近 3 日出现过超卖 |
| E2 | entry | `pct_change(f.close_qfq, 5) <= -p.drop_5d` | 短期跌幅 |
| E3 | entry | `f.close_qfq > ref(f.high_qfq, 1)` | 收盘收复前日高点，企稳确认 |
| F1 | filter | `f.amount_20d_avg >= p.min_amount and f.list_days >= p.min_list_days` |  |
| V1 | veto | `f.market_regime == 'downtrend'` |  |
| C1 | counter | `f.close_qfq < ref(f.close_qfq, 1) and f.amount > f.amount_20d_avg * 1.5` | 放量续跌 |
| I1 | invalidation | `f.close_qfq < ref(lowest(f.low_qfq, 5), 1)` | 收盘跌破前 5 日最低，反弹失败 |
| X1 | exit（止损） | `f.close_qfq <= plan.entry_price_qfq * (1 - p.stop_pct)` | 当前可用 |
| X1b | exit（止损，实现 MVP 后） | `f.close_qfq < plan.stop_loss_qfq` | 结构止损 = 入场前 5 日最低 qfq（QFQ-1） |
| X2 | exit（止盈） | `f.close_qfq >= plan.entry_price_qfq * (1 + p.tp_pct)` |  |
| X3 | exit | `f.rsi14 > p.rsi_exit and f.close_qfq < ref(f.close_qfq, 1)` | 反弹衰竭 |
| X4 | exit（时间） | `ctx.holding_days >= p.max_hold` |  |

## 8–10 执行与仓位
T 日盘后确认，T+1 开盘价模拟入场，信号有效 1 个交易日；止损价截断到涨跌停价之内；仓位按 RC2/RC3 建议。

## 11 验证（本轮不写 golden）
`fixture`、`trigger_stats`、`tracking_sim`；horizon_days [1,3,5]；`min_n=30`；基准用所属行业指数或中证全指。

## 14 不可执行原因
`LIMIT_LOCKED`（buy：一字涨停；sell：一字跌停，`direction=sell`）、`SUSPENDED`、`T1_NOT_SELLABLE`、`KEY_DATA_MISSING`、`NEW_LISTING`、`ST_OR_DELISTING`。

## 15–16 环境与节奏
适用于 range；uptrend 可用；downtrend 否决。每日盘后扫描。

## 17 A股约束
T+1：当日买入的股份当日不可卖，触发退出时记 `T1_NOT_SELLABLE`，顺延到可卖日。涨跌停价按 market_rules 计算（主板 10%、创业板和科创板 20%、ST 5%；注册制新股上市前 5 日无涨跌幅限制），一字封板按执行层原因 `LIMIT_LOCKED` 处理（写明 direction），不写成 veto。停牌记 `SUSPENDED`，可交易性、ST、退市整理由 G-01 处理，风险公告由 N-01 处理（均由系统挂载，本卡不重复写）。整手：科创板 ≥ 200 股、超出部分按 1 股递增；其余板块 100 股整数倍；零股须一次性卖出。

## 18 成本与滑点（estimate）
佣金按用户费率，单笔最低 5 元，双边计；印花税仅卖出 0.05%；过户费 0.001%（双边）；滑点 `p.slippage_bp`（estimate）；冲击成本按 plan 2.13 分档（0/5/15/30/60bp），参与率 > 2% 标“容量受限”。

## 20 冲突
与 S-01（强势回踩）、W-02（突破）方向相反时并列；与 H-01 并列。 一律并列展示，不合并结论。

## 22 参数（hypothesis；slippage_bp 为 estimate）
| 参数 | type | default | min | max | step |
|---|---|---|---|---|---|
| rsi_os | float | 30.0 | 20.0 | 35.0 | 1.0 |
| drop_5d | float | 0.08 | 0.05 | 0.15 | 0.01 |
| stop_pct | float | 0.03 | 0.02 | 0.05 | 0.005 |
| tp_pct | float | 0.06 | 0.04 | 0.1 | 0.01 |
| rsi_exit | float | 55.0 | 50.0 | 65.0 | 1.0 |
| max_hold | int | 5 | 3 | 10 | 1 |
| min_amount | float | 50000000.0 | 10000000.0 | 500000000.0 | 10000000.0 |
| min_list_days | int | 60 | 30 | 120 | 10 |
| slippage_bp | float | 10.0 | 0.0 | 50.0 | 1.0 |

## 23 当前不可导入原因与引擎需补能力
- QFQ-1 `plan.stop_loss_qfq`（已裁定，未实现，实现 MVP 后）

## 复核记录（相对 DeepSeek 原稿）
1. 原稿 X1 `f.close_qfq < plan.stop_loss` 口径混用，已改为 entry_price_qfq，另加 MVP 后的 stop_loss_qfq
2. 原稿企稳条件“收阳且高于当日最低”几乎每天都成立，已改为收复前日高点
3. 原稿缺少短期跌幅条件，已补 E2
4. 原稿 C1 把风险公告写成 counter，已交给 N-01
5. 原稿仓位参数属于 RC 层，已删除
6. 原稿 I1（跌破入场价 3%）与 X1 重复，已改为跌破前 5 日最低（用 ref 避开包含当日导致恒不成立）

## 22A 参数敏感性（T-R89 研究补充）

文档生命周期 `lifecycle: draft`；G7 ☐。仍不可导入，只描述候选信号的研究条件，不构成投资建议或收益承诺。本节不改变原规则、参数默认值或引擎能力。下表覆盖 §22 全部具名参数；取值及范围有仓库出处，但适用性、扫描结果和影响方向均**未验证**，`sensitivity: 未评估`。范围是原稿允许的研究网格，不表示已找到有效区间。比例用小数、金额用元、时间用交易日；方向指其他参数不变时的规则变化，不推断收益方向。

| 参数 | 原取值 | 合理扫描范围 / 步长（均未验证） | 预期影响方向（未验证） | 取值与范围出处 |
|---|---|---|---|---|
| rsi_os | 30 | 20–35 / 1 | 提高阈值放宽超卖门槛，候选信号集合不缩小；可能纳入较浅回撤 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:66 |
| drop_5d | 0.08 | 0.05–0.15 / 0.01 | 提高阈值要求更深跌幅，候选信号减少，可能更依赖极端行情 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:67 |
| stop_pct | 0.03 | 0.02–0.05 / 0.005 | 提高阈值降低百分比止损价，止损触发更晚；损失暴露可能增大 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:68 |
| tp_pct | 0.06 | 0.04–0.10 / 0.01 | 提高阈值抬高止盈条件，触发更难，可能更多由其他退出条件结束 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:69 |
| rsi_exit | 55 | 50–65 / 1 | 提高阈值收紧 RSI 衰竭退出条件，该退出触发减少 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:70 |
| max_hold | 5 | 3–10 / 1 | 增大上限延后时间退出，扩大隔夜暴露与标签跨度 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:71 |
| min_amount | 50000000 | 10000000–500000000 / 10000000 | 提高下限缩小候选信号集合，偏向较高流动性；容量改善待验证 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:72 |
| min_list_days | 60 | 30–120 / 10 | 提高下限排除更多上市时间短的证券 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:73 |
| slippage_bp（estimate） | 10 | 0–50 / 1 | 提高滑点使同一成交路径的扣费结果不升；不改变原始候选信号 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:74 |

固定参数也纳入审计。没有替代范围出处的项目只做原值单点核对，**不虚构扫描上下限**；另开范围须先登记依据并标未验证。下列“改变时的方向”只说明机制，不授权修改特征定义。

| 固定项 | 取值 / 本轮范围 | 改变时的预期方向与边界（未验证） | 出处 |
|---|---|---|---|
| RSI 周期、预热 | RSI14；预热28根，卡片30根；各固定原值 | 延长周期通常更平滑、反应更慢；提高预热减少可评估样本；不得把预热不足当负例 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:20；docs/strategies/T-R16/S-02_st_oversold_rebound.md:24 |
| 超卖回看、跌幅窗口 | 3日、5日；各固定原值 | 放宽回看可容纳更早的超卖；改变跌幅窗口可能改变方向，需另版特征 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:29；docs/strategies/T-R16/S-02_st_oversold_rebound.md:30 |
| 企稳参照、成交额均值 | 前1日高点、20日均额；各固定原值 | 延长参照不保证候选信号数量单调；均额窗口越长通常反应越慢 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:31；docs/strategies/T-R16/S-02_st_oversold_rebound.md:22 |
| C1 放量续跌 | 前1日收盘；1.5倍均额；各固定原值 | 提高倍数减少该反证出现；不是新入场过滤器 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:34 |
| I1 / 结构止损回看 | 前5日低点、偏移1日；固定原值 | 延长最低价窗口使参照不升，跌破更难；偏移防止包含当日 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:35；docs/strategies/T-R16/S-02_st_oversold_rebound.md:37 |
| 有效期 / 成交时点 | 1日 / T+1开盘；固定原值 | 有效期变长增加陈旧暴露；不得用 T 收盘替代成交 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:43 |
| 验证周期 / 最少样本 | 1、3、5日 / 30；固定原值 | 延长周期增加标签重叠；提高最少样本使判定更晚 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:46 |
| 费用与冲击（estimate） | 佣金费率未给值（未验证、不扫描）；最低5元；卖出税0.05%；双边过户0.001%；冲击0/5/15/30/60bp；参与率界0.1%/0.5%/1%/2%，ADV20；均固定 | 提高费用使扣费结果不升；无费率/规模证据不计算净结果。档位为估算，不把它们当市场事实 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:58；docs/strategies/_template.md:253；docs/strategies/_template.md:258；docs/strategies/_template.md:259；docs/strategies/_template.md:260；docs/strategies/_template.md:261；docs/strategies/_template.md:262 |

防过拟合要求（方法已有出处，落到本卡的效果未验证）：

- **样本外**：按时间滚动5折，只在训练折选择参数；隔离期为标签持有跨度 h，跨折标签剔除；最近12个月最终保留集只看一次，修改后另留保留集。动态退出扫描须预先冻结 h 的计算规则，未冻结不开始扫描。来源：docs/strategies/validation.md:68、docs/strategies/validation.md:151。
- **参数平原**：先固定原默认值，检查每个参数 ±1 个原 step 的邻域；再按预登记网格扩展，组合数总计不超过50，不穷举全部笛卡尔积。邻域结果翻号或较中心下降超过一半即不稳健，不能靠单点最优补救；缺样本记未验证。来源：docs/strategies/validation.md:141、docs/strategies/validation.md:142。
- **多重比较校正**：参数、窗口、分组和失败试验全部记入同一预登记检验族；采用 BH 校正 q=0.10，报告原始与校正后 p 值。q 是建议初值、未验证；未经校正不得作有效性结论。来源：docs/strategies/validation.md:146、docs/strategies/validation.md:147。
- 候选信号只使用 `available_at ≤ T` 的输入及 qfq@as_of；后续结果仅作已成熟标签，不回流当日判断或选参。状态、复权或样本身份不完整时记不足，不补值。来源：docs/strategies/validation.md:21、docs/strategies/validation.md:29、docs/strategies/validation.md:35、docs/strategies/validation.md:190。交易制度按当时有效版本，不把旧稿 §17 的固定 ST 百分比当跨期规则；依据 docs/strategies/_template.md:232。

## 3A 失效条件（T-R89 确定性研究规格）

以下是待执行的研究判据，**全部未验证**。单次候选信号结构失效、策略假设失效和数据不足分开记录；任何研究命中仅进入复核，不改变 draft，不自动退役，G7 ☐（处置依据 docs/strategies/validation.md:193）。

| 判据 | 指标与阈值 | 观察窗口与最少样本 | 出处 / 状态 |
|---|---|---|---|
| 单次结构失效 | 有效盘后日 d，`close_qfq(d) < min(low_qfq(d−5), …, low_qfq(d−1))`；严格小于，等于不算 | 本次候选信号评估或跟踪的每个有效日检查；至少1个有效判断日和此前5根有效日K，同时满足30根卡片预热；缺一项为不足 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:35；docs/strategies/T-R16/S-02_st_oversold_rebound.md:24；1个判断日是该单日表达式的展开，非统计样本；未验证 |
| 策略假设失效 | 主基准扣费超额中位数 `median(E_3) ≤ 0` | 截至复核日 D 最近120个交易日内产生、3日标签已结束的样本外候选信号；去重后可成交完整样本 n≥30 | 零阈值及3日来自 docs/strategies/T-R16/S-02_st_oversold_rebound.md:11；n 来自 docs/strategies/T-R16/S-02_st_oversold_rebound.md:46；120日借用 docs/strategies/validation.md:122 的统计窗口，迁用于本判据未验证 |
| 参数稳定性失效 | 中心 `median(E_3)>0`，任一 ±1 step 邻点中位数 ≤0，或 `< 中心中位数×0.5` | 同一上述120日样本外窗口、同一成本及基准；中心与每个参评邻点各 n≥30；不足则不判通过 | 邻域与下降一半来自 docs/strategies/validation.md:142；本卡样本门槛来自 docs/strategies/T-R16/S-02_st_oversold_rebound.md:46；确定性展开未验证 |

`E_3` 的冻结口径：候选信号在 T 盘后生成，U=T+1 为最早模拟成交日；从 U 开盘至 U+3 开盘的后复权收益，减同区间基准收益，再减完整往返成本。周期端点依据 docs/strategies/validation.md:51，成交依据 docs/strategies/T-R16/S-02_st_oversold_rebound.md:43，成本依据 docs/strategies/validation.md:40。主基准沪深300、辅基准中证全指沿 docs/strategies/T-R71/S-02_st_oversold_rebound.md:21；基准覆盖未验证，不能替代原行业比较。固定周期标签与 §7 实际退出统计分列，不将固定持有视为执行承诺。

按证券、候选信号日排序，同证券只保留与上一已保留标签区间不重叠的首次候选信号，且满足原通用3日冷却；这是对 docs/strategies/validation.md:53、docs/strategies/validation.md:131 的保守组合，具体适用性未验证。只在 D 已知窗口完整且成本/基准齐备时判定；不可成交不计入 n，但单列数量与比例（docs/strategies/validation.md:39）。不足30或缺数据都写“未验证/样本不足”，不得据此判定有效。

原稿“确认组与未确认组没有差异”“环境否决无效”缺等效界值、检验设计及独立样本要求，仍为**未验证**；不得把不显著当作等效。实际策略条件失效不保证可按阈值成交，执行层继续遵守 T+1、停牌及涨跌停约束。

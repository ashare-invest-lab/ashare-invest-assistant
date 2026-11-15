# T-R74｜四卡参数出处审计

## 1. 结论、判定与计数边界

审计对象为 T-R71 的 S-01 v2 对照、S-02、S-04、W-02；仅文档审计和复测设计，不运行行情复测。参数来源不等于有效性证据：只有历史复测明确给出该参数的样本外结果，或制度原文明定，才标「已验证」。原稿、经验、编排决定、指标惯例、数据探针和合成 golden 一律不足以验证策略参数。

已读证据：docs/strategies/T-R16 四源稿及 cards/st_pullback_ma.md；T-R58/param_audit.md §1/2/5、retest_plan.md §6/7/8/11；T-R71 四卡 §3/5/7–11/17/18/22、README.md §5/6；golden/T-R73_README.md 与 check_T-R73.py；feature_spec.md 相关节及既有市场规则核查。T-R58 §1 明列「有回测=0」，四卡 §11 为 window未执行/oos_result未验证；本地 Markdown 证据检索未发现这四卡参数的历史样本外结果。T-R58 的 T-01 方案也不是已完成复测，不能跨策略借用为验证结论。

计数按以下七列表的参数行：不同用途的窗口分别列，同一参数跨规则重复出现只列一次；共同参数逐卡展开，故总数不与 T-R71 README 的79个分组登记项相同。固定向量拆到用途；冲击档表每个分档一行。没有默认数值但必须冻结的佣金、R/计日也保留状态。证券代码、接口编号、合成输入的500日/1拆2/预热80根、数据覆盖起点和纯单位换算常数不是卡阈值，不充当已验证参数。

制度状态仅依据仓库已有规则核查，不新增或在线核法。过户费原发布页待补链；科创板1股递增只有投教明文及条文推理，按严格口径仍未验证。上市30日、长停牌5日、低价2元均为内部闸门，不是交易所强制阈值。四卡 §22 现有状态与本审计一致，无需修改卡正文或状态列。

P 表示 docs/strategies/golden/T-R73_golden.json 中对应 case（卡号-FX1）的 params；F 表示同 case 的 fixed_params；unverified 均为同 case 字段。表中「一致」只表示当前数值/口径相符，不表示历史有效性通过。「仅登记」表示有字段而未参与相应求值；「golden未用」表示未覆盖该参数。敏感性列 A–E 指 §4 最小复测包，原值和网格均非本轮选优结果。无原范围的固定项以原值为单点区间，先做消融或边界核验；新增网格须先预注册，不能编成原稿已有范围。

| 卡 | 参数数 | 已验证 | 未验证 | params核对 |
|---|---:|---:|---:|---|
| S-01 | 78 | 14 | 64 | 9项一致 |
| S-02 | 77 | 14 | 63 | 9项一致 |
| S-04 | 71 | 14 | 57 | 5项一致 |
| W-02 | 83 | 14 | 69 | 8项一致 |

## 2. 逐卡参数明细

### S-01（docs/strategies/T-R71/S-01_st_pullback_ma.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-01 | rs_min | 0.15 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 0.10–0.30；步0.05；A | 未验证 | P.rs_min=0.15；一致 |
| S-01 | touch_pct | 0.01 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 0.0–0.03；步0.005；A | 未验证 | P.touch_pct=0.01；一致 |
| S-01 | shrink_ratio | 0.7 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 0.5–0.9；步0.05；A | 未验证 | P.shrink_ratio=0.7；一致 |
| S-01 | exit_confirm_days | 2 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 1–3；步1；A | 未验证 | P.exit_confirm_days=2；一致（checker 固定2根求值，未读取此键） |
| S-01 | hard_stop_pct | 0.08 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 0.05–0.12；步0.01；A | 未验证 | P.hard_stop_pct=0.08；一致 |
| S-01 | time_stop | 5 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 3–10；步1；A | 未验证 | P.time_stop=5；一致 |
| S-01 | min_amount | 50000000.0 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 10000000.0–500000000.0；步10000000.0；A | 未验证 | P.min_amount=50000000.0；一致 |
| S-01 | min_list_days | 60 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 30–250；步10；A | 未验证 | P.min_list_days=60；一致 |
| S-01 | slippage_bp | 10.0 | docs/strategies/cards/st_pullback_ma.md §strategy-spec（params_schema） | 0.0–50.0；步1.0；C | 未验证 | P.slippage_bp=10.0；一致 |
| S-01 | MA短窗 | 5根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec E2/E3/I1/X1 | 原值；A | 未验证 | F.ma_windows=[5, 10, 20]；一致（对应5） |
| S-01 | MA触及/退出窗 | 10根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec E2/E3/I1/X1 | 原值；A | 未验证 | F.ma_windows=[5, 10, 20]；一致（对应10） |
| S-01 | MA长窗 | 20根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec E2/E3/I1/X1 | 原值；A | 未验证 | F.ma_windows=[5, 10, 20]；一致（对应20） |
| S-01 | 动量窗口 | 20根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec E1 | 原值；A | 未验证 | F.momentum_windows=[5, 20]；一致（20参与；5仅登记） |
| S-01 | 缩量均额窗口 | 5根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec E4 | 原值5；A | 未验证 | golden未用 |
| S-01 | 流动性/反证均额窗口 | 20根有效K | docs/strategies/cards/st_pullback_ma.md §strategy-spec F1/C2 | 原值；A | 未验证 | F.amount_window=20；一致 |
| S-01 | 反证跌幅 | >5% | docs/strategies/cards/st_pullback_ma.md §strategy-spec C1 | 原值；A | 未验证 | F.counter_drop_pct=0.05；一致 |
| S-01 | 反证放量倍数 | >1.5 | docs/strategies/cards/st_pullback_ma.md §strategy-spec C2 | 原值；A | 未验证 | F.counter_amount_mult=1.5；一致 |
| S-01 | 时间止损有利幅度门槛 | <1R；R口径待裁定 | docs/strategies/cards/st_pullback_ma.md §strategy-spec X3 | 原值；A | 未验证 | F.time_r_gate=1.0；一致（仅登记，R未求值） |
| S-01 | 卡预热 | 25根有效K | docs/strategies/cards/st_pullback_ma.md §时点 / 单位 / 复权 / 预热 | 25与更长历史重算；D | 未验证 | F.warmup=25；一致 |
| S-01 | 证伪观察期 | 5交易日 | docs/strategies/cards/st_pullback_ma.md §strategy-card hypothesis.falsified_by | 原值5；E | 未验证 | golden未用 |
| S-01 | 证伪最低跟踪数 | n≥30 | docs/strategies/cards/st_pullback_ma.md §strategy-card hypothesis.falsified_by | 30仅最低披露门槛；E | 未验证 | golden未用 |
| S-01 | 证伪胜率门槛 | <45% | docs/strategies/cards/st_pullback_ma.md §strategy-card hypothesis.falsified_by | 原值45%；E | 未验证 | golden未用 |
| S-01 | 证伪rs_min邻域 | ±0.05 | docs/strategies/cards/st_pullback_ma.md §strategy-card hypothesis.falsified_by | ±0.05；A | 未验证 | golden未用 |
| S-01 | 证伪shrink_ratio邻域 | ±0.1 | docs/strategies/cards/st_pullback_ma.md §strategy-card hypothesis.falsified_by | ±0.1；A | 未验证 | golden未用 |
| S-01 | 候选有效期 | 1交易日 | docs/strategies/T-R71/S-01_st_pullback_ma.md §8/22 | 原值；A | 未验证 | F.valid_for_trading_days=1；一致 |
| S-01 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | docs/strategies/T-R71/S-01_st_pullback_ma.md §5/数据接口依赖（T-R72 A02） | 17:10及实际就绪延迟；D | 未验证 | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-01 | 下一交易日执行偏移 | T+1开盘；最早09:30 | docs/strategies/T-R71/S-01_st_pullback_ma.md §8/9 | 固定偏移；D | 未验证 | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-01 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | docs/strategies/T-R71/S-01_st_pullback_ma.md §5 | 固定公式；D | 未验证 | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-01 | 成交额/成交量复权 | none；amount元、volume股 | docs/strategies/T-R71/S-01_st_pullback_ma.md §5 | 固定单位；D | 未验证 | 一致：原始amount/volume；P/F无键 |
| S-01 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | docs/strategies/T-R71/S-01_st_pullback_ma.md §17 | 0边界/缺失拒绝；D | 未验证 | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-01 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-01_st_pullback_ma.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-01 | F01最低有效覆盖 | 15根/20交易日；S-01自定义有效K均额不走此阈值 | docs/strategies/feature_spec.md §F01 | 15与完整20对照；D | 未验证 | golden未用：F.amount_min_coverage=15 |
| S-01 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | docs/strategies/T-R71/S-01_st_pullback_ma.md §5；docs/strategies/feature_spec.md §F01 | 固定口径；D | 未验证 | 一致：checker S-01不取整，其余1元 |
| S-01 | 环境短均线 | 20根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-01 | 环境长均线 | 60根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-01 | 宽度均值窗口 | 20交易日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_ma=20；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 上行宽度阈值 | >0.5 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_up=0.5；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 下行宽度阈值 | <0.4 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_down=0.4；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 环境防抖 | 连续2日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.regime_confirm_days=2；一致 |
| S-01 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | docs/strategies/feature_spec.md §F25/F50；docs/strategies/T-R71/README.md §6 | 61与完整历史重算；D | 未验证 | golden未用：合成环境额外80根不是卡阈值 |
| S-01 | 环境指数最低覆盖 | 45根/MA60 | docs/strategies/feature_spec.md §F25/F50 | 45与60对照；D | 未验证 | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-01 | 宽度最低覆盖 | 15值/20日 | docs/strategies/feature_spec.md §F25 | 15与20对照；D | 未验证 | golden未用：输入完整；F无独立键 |
| S-01 | 市场宽度小数精度 | 4位 | docs/strategies/feature_spec.md §F24 | 固定精度；D | 未验证 | golden未用作边界：合成值0.5精确 |
| S-01 | 低价门槛 | none<2元阻断 | docs/strategies/T-R71/README.md §6 P14；docs/strategies/catalog.md §3 G-01 | 原值2；B | 未验证 | F.raw_price_floor=2；一致 |
| S-01 | 上市共同闸门 | 不足30交易日阻断 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-01_st_pullback_ma.md §17 | 固定30；B | 未验证 | golden未用：上市均≥500，仅测试卡门槛 |
| S-01 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-01_st_pullback_ma.md §17 | 5日边界/首日；D | 未验证 | golden未用：未覆盖≥5日停牌 |
| S-01 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-01 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 20原值；C | 未验证 | golden未用：unverified.impact，无拟成交额 |
| S-01 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 容量受限阈值 | 参与率>2% | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 原值2%；C | 未验证 | golden未用：无拟成交额 |
| S-01 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | docs/strategies/_template.md §18；docs/strategies/T-R71/S-01_st_pullback_ma.md §18 | 5/0边界；C | 未验证 | golden未用：impact_cost=null |
| S-01 | 同模板证券冷却 | 3交易日且检查持有重叠 | docs/strategies/validation.md §4.2；docs/strategies/T-R71/README.md §6 P09 | 原值3；E | 未验证 | golden未用：每case只跟踪首笔 |
| S-01 | 研究最低样本数 | min_n=30 | docs/strategies/validation.md §4.3；docs/strategies/T-R71/README.md §6 P10 | 30仅披露下限；E | 未验证 | golden未用：4个合成case非历史n |
| S-01 | 参数邻域 | 原网格±1步 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 原网格±1步；A | 未验证 | golden未用：仅默认值 |
| S-01 | 组合预算 | ≤50 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 固定上限50；E | 未验证 | golden未用：未选参 |
| S-01 | 样本外折数 | K=5 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 固定5；E | 未验证 | golden未用：无训练/评估切分 |
| S-01 | 切分隔离期 | embargo=持有期h；动态h未裁定 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 冻结h后划分；E | 未验证 | golden未用：无样本外切分 |
| S-01 | 最终保留期 | 最后12个月 | docs/strategies/validation.md §5.3；docs/strategies/T-R71/README.md §6 P12 | 固定12个月；E | 未验证 | golden未用：非历史保留集 |
| S-01 | 多重检验水平 | BH q=0.10（建议值） | docs/strategies/validation.md §5.2；docs/strategies/T-R71/README.md §6 P13 | 固定q=0.10；E | 未验证 | golden未用：无显著性结果 |
| S-01 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-01 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-01 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-01 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-01 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-01 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-01 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-01 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-01 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | docs/strategies/T-R58/param_audit.md §5 R6；docs/strategies/T-R58/retest_plan.md §6.1 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 现段卖出印花税 | 0.05%，2023-08-28起 | docs/strategies/T-R58/param_audit.md §5 R6 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 过户费 | 双边0.001%（仓库已建模段） | docs/strategies/T-R58/param_audit.md §5 R7（中国结算通知，原页待补链） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 最低佣金 | 每笔每边5元；实际收费仍需核对 | docs/strategies/T-R58/param_audit.md §5 R8（证监发〔2002〕21号） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-01 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-01 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | docs/strategies/market_rules_T-R10.md §1.2 | 1股；待正式规则/接口规范佐证；D | 未验证 | golden未用：无数量账本 |

### S-02（docs/strategies/T-R71/S-02_st_oversold_rebound.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-02 | rsi_os | 30.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 20.0–35.0；步1.0；A | 未验证 | P.rsi_os=30.0；一致 |
| S-02 | drop_5d | 0.08 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 0.05–0.15；步0.01；A | 未验证 | P.drop_5d=0.08；一致 |
| S-02 | stop_pct | 0.03 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 0.02–0.05；步0.005；A | 未验证 | P.stop_pct=0.03；一致 |
| S-02 | tp_pct | 0.06 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 0.04–0.1；步0.01；A | 未验证 | P.tp_pct=0.06；一致 |
| S-02 | rsi_exit | 55.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 50.0–65.0；步1.0；A | 未验证 | P.rsi_exit=55.0；一致 |
| S-02 | max_hold | 5 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 3–10；步1；A | 未验证 | P.max_hold=5；一致 |
| S-02 | min_amount | 50000000.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 10000000.0–500000000.0；步10000000.0；A | 未验证 | P.min_amount=50000000.0；一致 |
| S-02 | min_list_days | 60 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 30–120；步10；A | 未验证 | P.min_list_days=60；一致 |
| S-02 | slippage_bp | 10.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §22 | 0.0–50.0；步1.0；C | 未验证 | P.slippage_bp=10.0；一致 |
| S-02 | RSI周期 | 14 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §5/7 | 原值；A | 未验证 | F.rsi_period=14；一致 |
| S-02 | RSI预热 | 28根有效K | docs/strategies/T-R16/S-02_st_oversold_rebound.md §5 | 原值；D | 未验证 | F.rsi_warmup=28；一致 |
| S-02 | 超卖回看 | 3根有效K | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 E1 | 原值；A | 未验证 | F.rsi_lookback=3；一致 |
| S-02 | 跌幅窗口 | 5根有效K | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 E2 | 原值；A | 未验证 | F.momentum_windows=[5, 20]；一致 |
| S-02 | 失效低点窗口 | 前5根有效K，不含T | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 I1 | 原值；A | 未验证 | F.structure_low_window=5；一致 |
| S-02 | 结构止损低点窗口 | 5根，候选日及之前4根 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 X1b | 原值；A | 未验证 | F.structure_low_window=5；一致 |
| S-02 | 回收高点/衰竭偏移 | 前1根有效K | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 E3/X3 | 原值；A | 未验证 | golden未用 |
| S-02 | 反证放量倍数 | >1.5 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 C1 | 原值；A | 未验证 | F.counter_amount_mult=1.5；一致 |
| S-02 | 卡预热 | 30根有效K | docs/strategies/T-R16/S-02_st_oversold_rebound.md §5 | 原值与更长历史重算；D | 未验证 | F.warmup=30；一致 |
| S-02 | 证伪观察期 | 3交易日 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §3 | 原值；E | 未验证 | golden未用 |
| S-02 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | docs/strategies/feature_spec.md §F01；docs/strategies/T-R71/S-02_st_oversold_rebound.md §5/7 | 原值；A | 未验证 | F.amount_window=20；一致 |
| S-02 | 候选有效期 | 1交易日 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §8/22 | 原值；A | 未验证 | F.valid_for_trading_days=1；一致 |
| S-02 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §5/数据接口依赖（T-R72 A02） | 17:10及实际就绪延迟；D | 未验证 | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-02 | 下一交易日执行偏移 | T+1开盘；最早09:30 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §8/9 | 固定偏移；D | 未验证 | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-02 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §5 | 固定公式；D | 未验证 | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-02 | 成交额/成交量复权 | none；amount元、volume股 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §5 | 固定单位；D | 未验证 | 一致：原始amount/volume；P/F无键 |
| S-02 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §17 | 0边界/缺失拒绝；D | 未验证 | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-02 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-02 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §7/9 | 固定严格比较；D | 未验证 | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| S-02 | F01最低有效覆盖 | 15根/20交易日 | docs/strategies/feature_spec.md §F01 | 15与完整20对照；D | 未验证 | 一致：F.amount_min_coverage=15 |
| S-02 | RSI平滑旧值权重 | 13/14；周期14见专属行 | docs/strategies/feature_spec.md §F20 | 固定公式与起点；D | 未验证 | 一致：checker固定13/14；P/F.rsi_period=14 |
| S-02 | RSI精度/零涨跌边界 | 2位；区间0–100；全平盘null非50 | docs/strategies/feature_spec.md §F20 | 固定口径；D | 未验证 | 一致：F.rsi_period=14；其他边界无键 |
| S-02 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §5；docs/strategies/feature_spec.md §F01 | 固定口径；D | 未验证 | 一致：checker S-01不取整，其余1元 |
| S-02 | 环境短均线 | 20根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-02 | 环境长均线 | 60根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-02 | 宽度均值窗口 | 20交易日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_ma=20；一致 |
| S-02 | 上行宽度阈值 | >0.5 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_up=0.5；一致 |
| S-02 | 下行宽度阈值 | <0.4 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_down=0.4；一致 |
| S-02 | 环境防抖 | 连续2日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.regime_confirm_days=2；一致 |
| S-02 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | docs/strategies/feature_spec.md §F25/F50；docs/strategies/T-R71/README.md §6 | 61与完整历史重算；D | 未验证 | golden未用：合成环境额外80根不是卡阈值 |
| S-02 | 环境指数最低覆盖 | 45根/MA60 | docs/strategies/feature_spec.md §F25/F50 | 45与60对照；D | 未验证 | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-02 | 宽度最低覆盖 | 15值/20日 | docs/strategies/feature_spec.md §F25 | 15与20对照；D | 未验证 | golden未用：输入完整；F无独立键 |
| S-02 | 市场宽度小数精度 | 4位 | docs/strategies/feature_spec.md §F24 | 固定精度；D | 未验证 | golden未用作边界：合成值0.5精确 |
| S-02 | 低价门槛 | none<2元阻断 | docs/strategies/T-R71/README.md §6 P14；docs/strategies/catalog.md §3 G-01 | 原值2；B | 未验证 | F.raw_price_floor=2；一致 |
| S-02 | 上市共同闸门 | 不足30交易日阻断 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-02_st_oversold_rebound.md §17 | 固定30；B | 未验证 | golden未用：上市均≥500，仅测试卡门槛 |
| S-02 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-02_st_oversold_rebound.md §17 | 5日边界/首日；D | 未验证 | golden未用：未覆盖≥5日停牌 |
| S-02 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-02 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 20原值；C | 未验证 | golden未用：unverified.impact，无拟成交额 |
| S-02 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 容量受限阈值 | 参与率>2% | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 原值2%；C | 未验证 | golden未用：无拟成交额 |
| S-02 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | docs/strategies/_template.md §18；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18 | 5/0边界；C | 未验证 | golden未用：impact_cost=null |
| S-02 | 同模板证券冷却 | 3交易日且检查持有重叠 | docs/strategies/validation.md §4.2；docs/strategies/T-R71/README.md §6 P09 | 原值3；E | 未验证 | golden未用：每case只跟踪首笔 |
| S-02 | 研究最低样本数 | min_n=30 | docs/strategies/validation.md §4.3；docs/strategies/T-R71/README.md §6 P10 | 30仅披露下限；E | 未验证 | golden未用：4个合成case非历史n |
| S-02 | 参数邻域 | 原网格±1步 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 原网格±1步；A | 未验证 | golden未用：仅默认值 |
| S-02 | 组合预算 | ≤50 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 固定上限50；E | 未验证 | golden未用：未选参 |
| S-02 | 样本外折数 | K=5 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 固定5；E | 未验证 | golden未用：无训练/评估切分 |
| S-02 | 切分隔离期 | embargo=持有期h；动态h未裁定 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 冻结h后划分；E | 未验证 | golden未用：无样本外切分 |
| S-02 | 最终保留期 | 最后12个月 | docs/strategies/validation.md §5.3；docs/strategies/T-R71/README.md §6 P12 | 固定12个月；E | 未验证 | golden未用：非历史保留集 |
| S-02 | 多重检验水平 | BH q=0.10（建议值） | docs/strategies/validation.md §5.2；docs/strategies/T-R71/README.md §6 P13 | 固定q=0.10；E | 未验证 | golden未用：无显著性结果 |
| S-02 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-02 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-02 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-02 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-02 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-02 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-02 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-02 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-02 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | docs/strategies/T-R58/param_audit.md §5 R6；docs/strategies/T-R58/retest_plan.md §6.1 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 现段卖出印花税 | 0.05%，2023-08-28起 | docs/strategies/T-R58/param_audit.md §5 R6 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 过户费 | 双边0.001%（仓库已建模段） | docs/strategies/T-R58/param_audit.md §5 R7（中国结算通知，原页待补链） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 最低佣金 | 每笔每边5元；实际收费仍需核对 | docs/strategies/T-R58/param_audit.md §5 R8（证监发〔2002〕21号） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-02 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-02 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | docs/strategies/market_rules_T-R10.md §1.2 | 1股；待正式规则/接口规范佐证；D | 未验证 | golden未用：无数量账本 |

### S-04（docs/strategies/T-R71/S-04_st_broken_board.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-04 | min_boards | 2 | docs/strategies/T-R16/S-04_st_broken_board.md §22 | 1–5；步1；A | 未验证 | P.min_boards=2；一致 |
| S-04 | vol_ratio | 1.5 | docs/strategies/T-R16/S-04_st_broken_board.md §22 | 1.2–3.0；步0.1；A | 未验证 | P.vol_ratio=1.5；一致 |
| S-04 | stop_pct | 0.05 | docs/strategies/T-R16/S-04_st_broken_board.md §22 | 0.03–0.1；步0.01；A | 未验证 | P.stop_pct=0.05；一致 |
| S-04 | max_hold | 5 | docs/strategies/T-R16/S-04_st_broken_board.md §22 | 3–10；步1；A | 未验证 | P.max_hold=5；一致 |
| S-04 | slippage_bp | 10.0 | docs/strategies/T-R16/S-04_st_broken_board.md §22 | 0.0–50.0；步1.0；C | 未验证 | P.slippage_bp=10.0；一致 |
| S-04 | 上市天数门槛 | ≥60交易日 | docs/strategies/T-R16/S-04_st_broken_board.md §4 | 原值；A | 未验证 | F.min_list_days=60；一致 |
| S-04 | 封板计数窗口 | 20交易日 | docs/strategies/T-R16/S-04_st_broken_board.md §5/7 E1 | 原值；A | 未验证 | F.limit_count_window=20；一致 |
| S-04 | 封板时序偏移 | T−2 | docs/strategies/T-R16/S-04_st_broken_board.md §7 E1 | 原值；A | 未验证 | golden未用 |
| S-04 | 断板/收复高点偏移 | T−1 | docs/strategies/T-R16/S-04_st_broken_board.md §7 E1/E2/X1b | 原值；A | 未验证 | golden未用 |
| S-04 | 失效高点偏移 | 前第2根有效K，ref(high,2) | docs/strategies/T-R16/S-04_st_broken_board.md §7 I1 | 原值2；A | 未验证 | 一致：checker固定偏移2；P/F无键 |
| S-04 | 失效连续确认 | 2根 | docs/strategies/T-R16/S-04_st_broken_board.md §7 I1 | 原值2；A | 未验证 | 一致：checker固定连续2根；P/F无键 |
| S-04 | 退出均线窗口 | MA5 | docs/strategies/T-R16/S-04_st_broken_board.md §7 X2 | 原值；A | 未验证 | F.ma_windows=[5, 10, 20]；一致（5参与；10/20仅诊断） |
| S-04 | 卡预热 | 20根有效K | docs/strategies/T-R16/S-04_st_broken_board.md §5 | 原值与更长历史重算；D | 未验证 | F.warmup=20；一致 |
| S-04 | 证伪观察期 | 3交易日 | docs/strategies/T-R16/S-04_st_broken_board.md §3 | 原值；E | 未验证 | golden未用 |
| S-04 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | docs/strategies/feature_spec.md §F01；docs/strategies/T-R71/S-04_st_broken_board.md §5/7 | 原值；A | 未验证 | F.amount_window=20；一致 |
| S-04 | 候选有效期 | 1交易日 | docs/strategies/T-R71/S-04_st_broken_board.md §8/22 | 原值；A | 未验证 | F.valid_for_trading_days=1；一致 |
| S-04 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | docs/strategies/T-R71/S-04_st_broken_board.md §5/数据接口依赖（T-R72 A02） | 17:10及实际就绪延迟；D | 未验证 | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-04 | 下一交易日执行偏移 | T+1开盘；最早09:30 | docs/strategies/T-R71/S-04_st_broken_board.md §8/9 | 固定偏移；D | 未验证 | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-04 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | docs/strategies/T-R71/S-04_st_broken_board.md §5 | 固定公式；D | 未验证 | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-04 | 成交额/成交量复权 | none；amount元、volume股 | docs/strategies/T-R71/S-04_st_broken_board.md §5 | 固定单位；D | 未验证 | 一致：原始amount/volume；P/F无键 |
| S-04 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | docs/strategies/T-R71/S-04_st_broken_board.md §17 | 0边界/缺失拒绝；D | 未验证 | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-04 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-04_st_broken_board.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-04 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | docs/strategies/T-R71/S-04_st_broken_board.md §7/9 | 固定严格比较；D | 未验证 | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| S-04 | F01最低有效覆盖 | 15根/20交易日 | docs/strategies/feature_spec.md §F01 | 15与完整20对照；D | 未验证 | 一致：F.amount_min_coverage=15 |
| S-04 | F11最低覆盖 | 15根；任一限价未知整段null | docs/strategies/feature_spec.md §F11 | 15与20；D | 未验证 | F.amount_min_coverage=15；一致（F11无独立键，checker亦用15） |
| S-04 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | docs/strategies/T-R71/S-04_st_broken_board.md §5；docs/strategies/feature_spec.md §F01 | 固定口径；D | 未验证 | 一致：checker S-01不取整，其余1元 |
| S-04 | 环境短均线 | 20根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-04 | 环境长均线 | 60根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| S-04 | 宽度均值窗口 | 20交易日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_ma=20；一致 |
| S-04 | 上行宽度阈值 | >0.5 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_up=0.5；一致 |
| S-04 | 下行宽度阈值 | <0.4 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_down=0.4；一致 |
| S-04 | 环境防抖 | 连续2日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.regime_confirm_days=2；一致 |
| S-04 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | docs/strategies/feature_spec.md §F25/F50；docs/strategies/T-R71/README.md §6 | 61与完整历史重算；D | 未验证 | golden未用：合成环境额外80根不是卡阈值 |
| S-04 | 环境指数最低覆盖 | 45根/MA60 | docs/strategies/feature_spec.md §F25/F50 | 45与60对照；D | 未验证 | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-04 | 宽度最低覆盖 | 15值/20日 | docs/strategies/feature_spec.md §F25 | 15与20对照；D | 未验证 | golden未用：输入完整；F无独立键 |
| S-04 | 市场宽度小数精度 | 4位 | docs/strategies/feature_spec.md §F24 | 固定精度；D | 未验证 | golden未用作边界：合成值0.5精确 |
| S-04 | 低价门槛 | none<2元阻断 | docs/strategies/T-R71/README.md §6 P14；docs/strategies/catalog.md §3 G-01 | 原值2；B | 未验证 | F.raw_price_floor=2；一致 |
| S-04 | 上市共同闸门 | 不足30交易日阻断 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-04_st_broken_board.md §17 | 固定30；B | 未验证 | golden未用：上市均≥500，仅测试卡门槛 |
| S-04 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/S-04_st_broken_board.md §17 | 5日边界/首日；D | 未验证 | golden未用：未覆盖≥5日停牌 |
| S-04 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-04 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 20原值；C | 未验证 | golden未用：unverified.impact，无拟成交额 |
| S-04 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 容量受限阈值 | 参与率>2% | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 原值2%；C | 未验证 | golden未用：无拟成交额 |
| S-04 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | docs/strategies/_template.md §18；docs/strategies/T-R71/S-04_st_broken_board.md §18 | 5/0边界；C | 未验证 | golden未用：impact_cost=null |
| S-04 | 同模板证券冷却 | 3交易日且检查持有重叠 | docs/strategies/validation.md §4.2；docs/strategies/T-R71/README.md §6 P09 | 原值3；E | 未验证 | golden未用：每case只跟踪首笔 |
| S-04 | 研究最低样本数 | min_n=30 | docs/strategies/validation.md §4.3；docs/strategies/T-R71/README.md §6 P10 | 30仅披露下限；E | 未验证 | golden未用：4个合成case非历史n |
| S-04 | 参数邻域 | 原网格±1步 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 原网格±1步；A | 未验证 | golden未用：仅默认值 |
| S-04 | 组合预算 | ≤50 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 固定上限50；E | 未验证 | golden未用：未选参 |
| S-04 | 样本外折数 | K=5 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 固定5；E | 未验证 | golden未用：无训练/评估切分 |
| S-04 | 切分隔离期 | embargo=持有期h；动态h未裁定 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 冻结h后划分；E | 未验证 | golden未用：无样本外切分 |
| S-04 | 最终保留期 | 最后12个月 | docs/strategies/validation.md §5.3；docs/strategies/T-R71/README.md §6 P12 | 固定12个月；E | 未验证 | golden未用：非历史保留集 |
| S-04 | 多重检验水平 | BH q=0.10（建议值） | docs/strategies/validation.md §5.2；docs/strategies/T-R71/README.md §6 P13 | 固定q=0.10；E | 未验证 | golden未用：无显著性结果 |
| S-04 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-04 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-04 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-04 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-04 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-04 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-04 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-04 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-04 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | docs/strategies/T-R58/param_audit.md §5 R6；docs/strategies/T-R58/retest_plan.md §6.1 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 现段卖出印花税 | 0.05%，2023-08-28起 | docs/strategies/T-R58/param_audit.md §5 R6 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 过户费 | 双边0.001%（仓库已建模段） | docs/strategies/T-R58/param_audit.md §5 R7（中国结算通知，原页待补链） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 最低佣金 | 每笔每边5元；实际收费仍需核对 | docs/strategies/T-R58/param_audit.md §5 R8（证监发〔2002〕21号） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-04 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-04 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | docs/strategies/market_rules_T-R10.md §1.2 | 1股；待正式规则/接口规范佐证；D | 未验证 | golden未用：无数量账本 |

### W-02（docs/strategies/T-R71/W-02_sw_breakout.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| W-02 | bw_pct120_th | 0.2 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 0.05–0.4；步0.05；A | 未验证 | P.bw_pct120_th=0.2；一致 |
| W-02 | vol_mult | 1.5 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 1.2–3.0；步0.1；A | 未验证 | P.vol_mult=1.5；一致 |
| W-02 | fail_pct | 0.03 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 0.01–0.05；步0.01；A | 未验证 | P.fail_pct=0.03；一致 |
| W-02 | stop_pct | 0.05 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 0.03–0.10；步0.01；A | 未验证 | P.stop_pct=0.05；一致 |
| W-02 | max_hold | 20 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 10–40；步5；A | 未验证 | P.max_hold=20；一致 |
| W-02 | min_amount | 50000000.0 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 10000000.0–500000000.0；步10000000.0；A | 未验证 | P.min_amount=50000000.0；一致 |
| W-02 | min_list_days | 120 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 60–250；步10；A | 未验证 | P.min_list_days=120；一致 |
| W-02 | slippage_bp | 15.0 | docs/strategies/T-R16/W-02_sw_breakout.md §22 | 0.0–50.0；步1.0；C | 未验证 | P.slippage_bp=15.0；一致 |
| W-02 | 布林窗口 | 20根有效K | docs/strategies/T-R16/W-02_sw_breakout.md §5；docs/strategies/feature_spec.md §F31/F32 | 原值；A | 未验证 | F.boll_window=20；一致 |
| W-02 | 布林倍数 | 2（带宽系数4） | docs/strategies/T-R16/W-02_sw_breakout.md §5；docs/strategies/feature_spec.md §F31/F32 | 原值；A | 未验证 | F.boll_k=2；一致 |
| W-02 | 布林ddof | 0 | docs/strategies/T-R16/W-02_sw_breakout.md §5；docs/strategies/feature_spec.md §F31/F32 | 原值；A | 未验证 | F.boll_ddof=0；一致 |
| W-02 | 带宽时间分位窗口 | 120个非null值，含T | docs/strategies/T-R16/W-02_sw_breakout.md §5；docs/strategies/feature_spec.md §F31/F32 | 原值；A | 未验证 | F.bw_rank_window=120；一致 |
| W-02 | 突破最高收盘窗口 | 前20根有效K，不含T | docs/strategies/T-R16/W-02_sw_breakout.md §7 E2 | 原值；A | 未验证 | F.breakout_window=20；一致 |
| W-02 | 主板近涨停反证 | >9.5%；非主板系数未定 | docs/strategies/T-R16/W-02_sw_breakout.md §7 C1 | 原值；A | 未验证 | F.near_limit_up_pct=0.095；一致 |
| W-02 | 退出均线窗口 | MA10 | docs/strategies/T-R16/W-02_sw_breakout.md §7 X2 | 原值；A | 未验证 | F.ma_windows=[5, 10, 20]；一致 |
| W-02 | 均线退出确认 | 连续2根 | docs/strategies/T-R16/W-02_sw_breakout.md §7 X2 | 原值；A | 未验证 | F.exit_confirm_days=2；一致 |
| W-02 | 时间止损最短持有 | ≥3交易日 | docs/strategies/T-R16/W-02_sw_breakout.md §7 X4 | 原值；A | 未验证 | F.time_r_min_days=3；一致 |
| W-02 | 时间止损有利幅度 | <0.5R；R口径待定 | docs/strategies/T-R16/W-02_sw_breakout.md §7 X4 | 原值；A | 未验证 | F.time_r_gate=0.5；一致（仅登记，R未求值） |
| W-02 | 失效观察期 | 入场后3日内 | docs/strategies/T-R16/W-02_sw_breakout.md §7 I1 | 原值3；A | 未验证 | golden未用 |
| W-02 | 原证伪结构回撤 | 3% | docs/strategies/T-R16/W-02_sw_breakout.md §3 | 原值3%；E | 未验证 | golden未用 |
| W-02 | 证伪分位敏感区间 | 0.1–0.3 | docs/strategies/T-R16/W-02_sw_breakout.md §3 | 0.1–0.3；A | 未验证 | golden未用 |
| W-02 | 证伪放量敏感区间 | 1.3–2.0 | docs/strategies/T-R16/W-02_sw_breakout.md §3 | 1.3–2.0；A | 未验证 | golden未用 |
| W-02 | 卡预热 | 140根有效K | docs/strategies/T-R16/W-02_sw_breakout.md §5 | 原值与更长历史重算；D | 未验证 | F.warmup=140；一致 |
| W-02 | 证伪观察期 | 10交易日 | docs/strategies/T-R16/W-02_sw_breakout.md §3 | 原值；E | 未验证 | golden未用 |
| W-02 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | docs/strategies/feature_spec.md §F01；docs/strategies/T-R71/W-02_sw_breakout.md §5/7 | 原值；A | 未验证 | F.amount_window=20；一致 |
| W-02 | 候选有效期 | 1交易日 | docs/strategies/T-R71/W-02_sw_breakout.md §8/22 | 原值；A | 未验证 | F.valid_for_trading_days=1；一致 |
| W-02 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | docs/strategies/T-R71/W-02_sw_breakout.md §5/数据接口依赖（T-R72 A02） | 17:10及实际就绪延迟；D | 未验证 | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| W-02 | 下一交易日执行偏移 | T+1开盘；最早09:30 | docs/strategies/T-R71/W-02_sw_breakout.md §8/9 | 固定偏移；D | 未验证 | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| W-02 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | docs/strategies/T-R71/W-02_sw_breakout.md §5 | 固定公式；D | 未验证 | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| W-02 | 成交额/成交量复权 | none；amount元、volume股 | docs/strategies/T-R71/W-02_sw_breakout.md §5 | 固定单位；D | 未验证 | 一致：原始amount/volume；P/F无键 |
| W-02 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | docs/strategies/T-R71/W-02_sw_breakout.md §17 | 0边界/缺失拒绝；D | 未验证 | 一致：合成停牌、跌停阻断；不验证排队成交 |
| W-02 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/W-02_sw_breakout.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| W-02 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | docs/strategies/T-R71/W-02_sw_breakout.md §7/9 | 固定严格比较；D | 未验证 | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| W-02 | F01最低有效覆盖 | 15根/20交易日 | docs/strategies/feature_spec.md §F01 | 15与完整20对照；D | 未验证 | 一致：F.amount_min_coverage=15 |
| W-02 | 带宽分位最低覆盖 | 90个（90/120=0.75建议） | docs/strategies/feature_spec.md §F32 | 90与120对照；D | 未验证 | F.bw_min_coverage=90；一致 |
| W-02 | 带宽舍入精度 | 6位 | docs/strategies/feature_spec.md §F31 | 固定精度；D | 未验证 | 一致：checker固定6；P/F无键 |
| W-02 | 分位舍入/同值秩 | 4位；平均秩/n（同值数+1）/2 | docs/strategies/feature_spec.md §F32/1.4 | 固定精度/并列值；D | 未验证 | 一致：checker固定4；P/F无键 |
| W-02 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | docs/strategies/T-R71/W-02_sw_breakout.md §5；docs/strategies/feature_spec.md §F01 | 固定口径；D | 未验证 | 一致：checker S-01不取整，其余1元 |
| W-02 | 环境短均线 | 20根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| W-02 | 环境长均线 | 60根 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.environment_ma=[20, 60]；一致 |
| W-02 | 宽度均值窗口 | 20交易日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_ma=20；一致 |
| W-02 | 上行宽度阈值 | >0.5 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_up=0.5；一致 |
| W-02 | 下行宽度阈值 | <0.4 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.breadth_down=0.4；一致 |
| W-02 | 环境防抖 | 连续2日 | docs/strategies/feature_spec.md §F24/F25/F50 | 原值；B | 未验证 | F.regime_confirm_days=2；一致 |
| W-02 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | docs/strategies/feature_spec.md §F25/F50；docs/strategies/T-R71/README.md §6 | 61与完整历史重算；D | 未验证 | golden未用：合成环境额外80根不是卡阈值 |
| W-02 | 环境指数最低覆盖 | 45根/MA60 | docs/strategies/feature_spec.md §F25/F50 | 45与60对照；D | 未验证 | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| W-02 | 宽度最低覆盖 | 15值/20日 | docs/strategies/feature_spec.md §F25 | 15与20对照；D | 未验证 | golden未用：输入完整；F无独立键 |
| W-02 | 市场宽度小数精度 | 4位 | docs/strategies/feature_spec.md §F24 | 固定精度；D | 未验证 | golden未用作边界：合成值0.5精确 |
| W-02 | 低价门槛 | none<2元阻断 | docs/strategies/T-R71/README.md §6 P14；docs/strategies/catalog.md §3 G-01 | 原值2；B | 未验证 | F.raw_price_floor=2；一致 |
| W-02 | 上市共同闸门 | 不足30交易日阻断 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/W-02_sw_breakout.md §17 | 固定30；B | 未验证 | golden未用：上市均≥500，仅测试卡门槛 |
| W-02 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | docs/strategies/_template.md §7.3；docs/strategies/T-R71/W-02_sw_breakout.md §17 | 5日边界/首日；D | 未验证 | golden未用：未覆盖≥5日停牌 |
| W-02 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| W-02 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 20原值；C | 未验证 | golden未用：unverified.impact，无拟成交额 |
| W-02 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原档表及一档升降压力；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 容量受限阈值 | 参与率>2% | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 原值2%；C | 未验证 | golden未用：无拟成交额 |
| W-02 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | docs/strategies/_template.md §18；docs/strategies/T-R71/W-02_sw_breakout.md §18 | 5/0边界；C | 未验证 | golden未用：impact_cost=null |
| W-02 | 同模板证券冷却 | 3交易日且检查持有重叠 | docs/strategies/validation.md §4.2；docs/strategies/T-R71/README.md §6 P09 | 原值3；E | 未验证 | golden未用：每case只跟踪首笔 |
| W-02 | 研究最低样本数 | min_n=30 | docs/strategies/validation.md §4.3；docs/strategies/T-R71/README.md §6 P10 | 30仅披露下限；E | 未验证 | golden未用：4个合成case非历史n |
| W-02 | 参数邻域 | 原网格±1步 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 原网格±1步；A | 未验证 | golden未用：仅默认值 |
| W-02 | 组合预算 | ≤50 | docs/strategies/validation.md §5.1；docs/strategies/T-R71/README.md §6 P11 | 固定上限50；E | 未验证 | golden未用：未选参 |
| W-02 | 样本外折数 | K=5 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 固定5；E | 未验证 | golden未用：无训练/评估切分 |
| W-02 | 切分隔离期 | embargo=持有期h；动态h未裁定 | docs/strategies/validation.md §2.5；docs/strategies/T-R71/README.md §6 P12 | 冻结h后划分；E | 未验证 | golden未用：无样本外切分 |
| W-02 | 最终保留期 | 最后12个月 | docs/strategies/validation.md §5.3；docs/strategies/T-R71/README.md §6 P12 | 固定12个月；E | 未验证 | golden未用：非历史保留集 |
| W-02 | 多重检验水平 | BH q=0.10（建议值） | docs/strategies/validation.md §5.2；docs/strategies/T-R71/README.md §6 P13 | 固定q=0.10；E | 未验证 | golden未用：无显著性结果 |
| W-02 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| W-02 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| W-02 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| W-02 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| W-02 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| W-02 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| W-02 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| W-02 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| W-02 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | docs/strategies/T-R58/param_audit.md §5 R6；docs/strategies/T-R58/retest_plan.md §6.1 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 现段卖出印花税 | 0.05%，2023-08-28起 | docs/strategies/T-R58/param_audit.md §5 R6 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 过户费 | 双边0.001%（仓库已建模段） | docs/strategies/T-R58/param_audit.md §5 R7（中国结算通知，原页待补链） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 最低佣金 | 每笔每边5元；实际收费仍需核对 | docs/strategies/T-R58/param_audit.md §5 R8（证监发〔2002〕21号） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| W-02 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| W-02 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | docs/strategies/market_rules_T-R10.md §1.2 | 1股；待正式规则/接口规范佐证；D | 未验证 | golden未用：无数量账本 |

## 3. golden 对账结论与未覆盖项

31个 params（S-01/S-02/S-04/W-02分别9/9/5/8项）逐键与卡 §22 default 数值核对一致；**数值不一致项为0**。比例按小数转换，不把5%写成5。下表覆盖四个case各30个 fixed_params 字段，共120个字段位置；「未用」对应 golden未用，其余按 §2 同名用途核对一致。多数F仅作登记，checker实际按常数求值；仅 min_list_days、warmup直接读F，不能据此声称每个F都经过独立参数化检验。exit_confirm_days的P=2也未被求值器读取，当前常数相同，改P后的敏感性尚未测试。

| fixed_params键 | S-01-FX1 | S-02-FX1 | S-04-FX1 | W-02-FX1 |
|---|---|---|---|---|
| min_list_days | 门槛 | 门槛 | 固定门槛 | 门槛 |
| warmup | 卡预热 | 卡预热 | 卡预热 | 卡预热 |
| ma_windows | 5/10/20 | 仅诊断 | 5退出，10/20诊断 | 10退出、20布林，5诊断 |
| exit_confirm_days | 2；P同值但求值硬编码 | 未用 | 未用 | 2；求值硬编码 |
| time_r_gate | 1R仅登记 | 未用 | 未用 | 0.5R仅登记 |
| time_r_min_days | 未用；3不是S-01时间止损 | 未用 | 未用 | 3；X4计时 |
| near_limit_up_pct | 未用 | 未用 | 未用 | 0.095主板C1 |
| counter_drop_pct | 0.05 C1 | 未用 | 未用 | 未用 |
| counter_amount_mult | 1.5 C2 | 1.5 C1 | 未用（E3读P.vol_ratio） | 未用（E3读P.vol_mult） |
| momentum_windows | 20动量；5仅登记 | 5跌幅；20仅登记 | 未用 | 未用 |
| amount_window | 20有效K | 20交易日 | 20交易日 | 20交易日 |
| amount_min_coverage | 未用 | 15 | 15（F11亦同） | 15 |
| rsi_period | 未用 | 14 | 未用 | 未用 |
| rsi_warmup | 未用 | 28 | 未用 | 未用 |
| rsi_lookback | 未用 | 3 | 未用 | 未用 |
| boll_window | 未用 | 未用 | 未用 | 20 |
| boll_k | 未用 | 未用 | 未用 | 2，带宽系数4 |
| boll_ddof | 未用 | 未用 | 未用 | 0 |
| bw_rank_window | 未用 | 未用 | 未用 | 120 |
| bw_min_coverage | 未用 | 未用 | 未用 | 90 |
| breakout_window | 未用 | 未用 | 未用 | 20 |
| limit_count_window | 未用 | 未用 | 20 | 未用 |
| structure_low_window | 未用 | 5（I1/X1b不同端点） | 未用 | 未用 |
| environment_ma | 20/60 F50；F25诊断 | 20/60 F25 | 20/60 F25 | 20/60 F25 |
| breadth_ma | 20仅诊断，未回放RC3 | 20 | 20 | 20 |
| breadth_up | 0.5仅诊断 | 0.5 | 0.5 | 0.5 |
| breadth_down | 0.4仅诊断 | 0.4 | 0.4 | 0.4 |
| regime_confirm_days | 2 | 2 | 2 | 2 |
| raw_price_floor | 2 | 2 | 2 | 2 |
| valid_for_trading_days | 1（按次日开盘语义实现） | 1（按次日开盘语义实现） | 1（按次日开盘语义实现） | 1（按次日开盘语义实现） |

全部F原值：四case相同者沿上表/§2；差异仅min_list_days=60/60/60/120、warmup=25/30/20/140、time_r_gate=1/1/1/0.5。未用字段的共同登记值为exit_confirm_days=2、time_r_min_days=3、near_limit_up_pct=0.095、counter_drop_pct=0.05、counter_amount_mult=1.5、momentum_windows=[5,20]、amount_min_coverage=15、rsi_period=14、rsi_warmup=28、rsi_lookback=3、boll_window=20、boll_k=2、boll_ddof=0、bw_rank_window=120、bw_min_coverage=90、breakout_window=20、limit_count_window=20、structure_low_window=5，不能把这些全都当作该case的策略参数。ma_windows=[5,10,20]含诊断均线；S-04无均额绝对最低值，golden未偷偷加入min_amount。

| unverified键（四case均有） | 审计处理 |
|---|---|
| all_fixed_params | 仍未验证；合成对账不构成历史样本外证据 |
| holding_day_convention | 入场0、按虚构日历含停牌，是夹具约定；原卡未定，不列数值冲突 |
| R | 不造最大R；S-01 X3/W-02 X4到门槛后null；固定R倍数仅登记 |
| commission | 无费率、费用null；不能以无成本结果验证5元或费率 |
| impact | 无拟成交额、冲击null；基础滑点值一致但仅算卖出侧折价，不是往返净收益 |
| N01 | unknown，技术候选不解除产品阻断 |
| industry | 缺申万历史与行业超额，S-01原行业证伪未完成 |
| listing_calendar | 合成500日起递增，不验证实际上市年龄/交易日历覆盖 |
| execution | 可卖与开盘证据为合成值，不证明真实成交、整手或排队 |
| split | 仅合成1拆2（A从1到2），不证明现金分红、数量费用或因子修订 |

其余golden未用/局限已逐行列出：长停牌5日、上市30日闸门、ST历史分段、非主板近涨停、费用/冲击、R、RC3仓位与行业。W-02 I1全null；其3日观察窗登记但未求值。S-01无结构退出且take_profit=null，S-04/W-02无独立止盈；S-02止盈仅tp_pct。四卡 §19不生成分数，源卡中的0.67/0.33展示阈值不属于T-R71规则，未移植。数据接入、G1–G7与生产QFQ派生仍未完成，不因本轮文档验收而升级。

## 4. 未验证参数的最小复测方案（仅设计，不运行）

### 4.1 共用数据、切分和判定

下列研究数值是**待预注册的方案值，不是已验证结论，也不回写卡默认值**。出处框架为 docs/strategies/validation.md §1.4/2.5/4/5/7.2、T-R71/README.md §5/6；费用压力档借 T-R58/retest_plan.md §6.2 的既有研究设定，仍未验证。每一未验证行均由敏感性列A–E覆盖；D只验证计算/执行口径，需与A/B/C的历史样本外研究同时满足，不能单靠算术用例晋级。

需要的数据区间：计划冻结2023-04-10至2026-11-10的完整沪深A股历史（包含期间退市股、历史自选/持仓快照；北交所排除），在2023-04-10之前只取指标预热，不模拟未建模时期的执行。S-01主结果限当时持仓∪自选；无历史快照则不能以今天名单回填，只能报告该范围复测受阻；全市场对照单独披露。三卡按原范围，ST/退市整理/状态未知股票-日阻断并计数；不得整股删掉后来退市的证券。预热至少覆盖最长140根卡窗口、61根环境与固定起点RSI；不足就延期起测并披露，不能削短窗口求过关。

| 依赖（T-R72编号沿四卡§数据接口依赖，未另读接口或样本） | 必须冻结的字段/证据 | 用途 |
|---|---|---|
| B02全历史日线 | code/market/trade_date、OHLC、volume、amount、pre_close、is_suspended、source、data_as_of/available_at/fetched_at、定稿/修订版本 | 全部窗口、价格/额/量、有效K与交易日区别；覆盖分母包括缺口 |
| B03交易日历 | market、trade_date、is_open、公告依据/版本；上市日至研究尾日 | T+1、上市天数、冷却、持有、embargo；不用K根数替代 |
| B06证券状态/历史涨跌停价 | 上市/退市日期、板块、历史ST/退市整理区间、状态available_at、每日参考价与limit_up/down | 分段规则、IPO前5日、封板计数、一字板与成交阻断 |
| B08权息事件 | effective_date、available_at、现金分红/送转、A与因子版本、旧快照、持仓数量和现金变动 | 每T重算qfq@T；跨权息冻结结构位、R和现金账本 |
| B11指数 | 000300/000985日历、OHLC/close、available_at/source/修订版本 | 主辅超额与环境MA；与股票数据同期到齐 |
| B02+B06完整截面 | 每日有效沪深股票集合、pre_close、close、volume、停牌/上市状态 | F24/F25真实完整宽度；不拿当前清单回填 |
| B09/B12补充 | 风险公告首次可见时间；申万一级历史成员及对应收益序列 | N-01产品核验、行业证伪；树/当前成分不能代替收益 |
| 尚待独立来源 | 历史持仓/自选快照、当时可卖数量、开盘成交证据、实际佣金/成交金额 | S-01范围、可卖与成本；B02/B06不能独自证明排队成交 |

切分：在上述共同可用区间内先锁定最后12个月（拟2025-11-11至2026-11-10）作保留集，其前开发段按B03实际交易日等分5个连续块；首块训练，后4块做扩展训练的walk-forward样本外评估。所有参数搜索与±1步邻域只能看当折训练段。交界先purge跨界持仓，再设embargo=h；动态h/顺延无上限时不臆造h，先预注册边界截断：段末仍未退出者记未完成/无法估值，不能借下一段成交，也不能当0收益。h未裁定或未完成头寸无法保守计价，则该折及最终效果结论均为未验证。最终保留集只运行冻结版本一次。

最小网格：具名参数只取表中原网格默认点及可用的±1步，单因素优先；S-01原证伪另核rs_min±0.05/shrink_ratio±0.1。固定窗/阈值无原网格者，首轮冻结原值，与取消对应条件的消融对照（仅研究）；需要搜索新值时另行预注册网格，不冒充原稿范围。每卡训练配置≤50，预先列出且保留全部失败试验。四卡/所有实际尝试的配置、切分与消融共同记入比较族；保留集只检验冻结主假设，不再挑卡或删方向。对日期分块bootstrap的扣费超额检验做BH q=0.10，报告未校正/校正p值、95%区间与试验数；同时披露Holm敏感性，不以两种方法中较有利者择优。

通过标准（方案约定，非现成证据）：各卡最终保留集有效独立信号n≥30、扣费超额中位数>0且日期分块bootstrap 95%下界>0、BH通过；扣费期望>0且>2倍平均往返成本；至少2种环境无显著负期望。walk-forward至少3/4评估块同号，保留集同号；训练邻域不得变号或下降超过一半。样本不足、环境不足、未完成头寸无法估值均记「未验证」，不降低标准。以沪深300为主、中证全指为辅分别报告；S-01另须申万一级行业超额满足其原证伪，不用大盘替代。S-01跟踪5日胜率须≥45%，并附Wilson区间（不把单点胜率当显著性证据）。

防过拟合：冻结数据清单/哈希、源及PIT版本、可得时点、随机种子、参数与全部试验日志；缺数不填0、不得按未来完整度删已成交事件。股票/日期聚类去重，3日冷却后仍purge持有重叠。保留集不参与清洗阈值、环境定义或成本档校准；若曾被查看，标污染并换未来保留段。按板块/年份/环境与退市/未知状态分组，同时报告不可成交、未退出和覆盖缺口；任一硬前视或现金账本错误即不通过。G6触发覆盖与收益研究分别出表，不用文档checker代替后者。

### 4.2 参数包与卡别最小检验

| 包及覆盖的未验证项 | 数据/区间/样本（均继承§4.1） | 方法与成本敏感性 | 通过与防过拟合补充 |
|---|---|---|---|
| A：全部具名策略参数及固定入场/退出/反证/观察窗/有效期 | B02/B03/B06/B08/B11；S-01须历史自选/持仓，行业证伪再需B12 | 默认与原网格±1步；固定值消融；按原持有/退出与固定证伪期分别估计；每配置完整跑C，按共用切分walk-forward/BH | 共用通过标准；不以事后最好持有期替换预注册观察期 |
| B：环境MA/宽度/阈值/防抖、2元/30日闸门 | B11与完整B02+B06截面，B03上市年龄 | 冻结20/60、20、0.5/0.4、2日，逐条件消融并分环境；低价/上市在门槛两侧分组，成本按C | 共用标准；至少2种环境；S-01 F50与F25/RC3分开，不将宽度诊断说成V1触发 |
| C：滑点、佣金、ADV20、五档冲击/2%容量/5根回退 | B02历史额、B03/B06/B08执行账本；预注册拟成交额与实际费率，不调用账户 | 基础滑点0/原值/50bp（均在原范围）；佣金实际费率及0.015%/0.025%/0.03%参考档；冲击原表与整体升一档压力，封顶60bp，另保留0冲击诊断；金额借T-R58 §6.2的1/5/20万元压力档，非卡仓位 | 主费用与高费用压力均正；完整收双边/最低5元/日期税费；若只在部分金额成立，冻结训练得出的适用范围后由保留集验证，不反求边界 |
| D：预热/覆盖/精度、定稿、复权/冻结位、成交/计日、长停牌、科创1股递增 | B02/B03/B06/B08/B11及实际成交/规则证据，重点抽取阈值相等、缺字段、跨除权、ST切换与停牌边界 | 15对20、45对60、90对120及更长历史；数值舍入/平盘/缺因子边界；删去T后事件重算不变；原价现金/股数账本与qfq等价；计日0/1与停牌对照只用于暴露歧义，裁定后冻结 | 所有硬口径断言零差错；数据缺口不冒充覆盖；科创1股须补正式原文/规范才可升级制度状态；成本仍跑C，历史效用仍按A/B判定 |
| E：证伪期/胜率/n、冷却、邻域预算、5块/隔离/保留期/BH | 同A–D；B12行业数据与B03冻结日历；全部试验元数据 | 保持既有研究初值；3/5/10日依卡原证伪，另报固定持有期但不择优；评估有效n与重叠，bootstrap/BH与Holm，成本跑C | 样本足够才判断；研究设计初值本身不能因一次成功而称普适验证，不根据保留集修改统计门槛 |

| 卡 | 最小额外反证与数据重点 | 通过要求（在共用标准外） |
|---|---|---|
| S-01 | B02按有效K算5/20均额、MA5/10/20；趋势/触及/缩量各消融；5日行业超额、5日胜率与原邻域 | 行业证伪完成；邻域不翻转；不把v3截面规则移入v2；无真实历史范围则继续未验证 |
| S-02 | B08固定起点RSI14/28、近3根超卖；5根跌幅、前高确认与不确认组；冻结含候选日5根低点 | 3日扣费超额与企稳组差异支持假设；平盘null、阈值相等、跨除权和X1b顺延全部正确；环境消融有效 |
| S-04 | B06历史封板价、20交易日计数、T−2/T−1时序；放量/不放量组及环境组 | 3日超额支持假设，放量组差异通过校正；计数不是连板；冻结断板日高点、不可卖顺延与I1移动窗口正确 |
| W-02 | 140根预热、20/2/ddof0布林、120分位与90覆盖；当日收敛/突破/放量消融；10日超额与3%回撤 | 原0.1–0.3/1.3–2.0邻域稳定；R/I1/计日和非主板近涨停先裁定，未定部分不生成肯定结果；冻结突破位跨除权正确 |

上述差异检验预先定义效应方向与统计量，加入同一BH比较族；不能只报告组内显著而不检验组间差异。数据接口编号是未来依赖登记，不表示已接入；未取得字段、状态历史、实际成本或成交证据时，先记录阻塞，不以接口路径本身充当样本外证据。

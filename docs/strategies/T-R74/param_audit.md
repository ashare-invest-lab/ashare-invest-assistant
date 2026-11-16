# T-R74｜四卡参数出处审计

## 1. 结论、判定与计数边界

审计对象为 T-R71 的 S-01 v2 对照、S-02、S-04、W-02；仅文档审计和复测设计，不运行行情复测。参数来源不等于有效性证据：只有历史复测明确给出该参数的样本外结果，或制度原文明定，才标「已验证」。原稿、经验、编排决定、指标惯例、数据探针和合成 golden 一律不足以验证策略参数。 T-R93 重核（2026-11-16）：仓库文档及团队报告只作「仓内定义：相对路径:行号」，不能作为外部出处，相关项保留「未验证」。只有逐字核对、附 URL 和访问日期的公开原文才可支持其明确覆盖的事实；论文仅证明有文献采用该取值或方法，对A股有效性仍标「未验证（待复测）」。本轮未将任何完整表项升级为已验证，§1计数保持。lifecycle: draft；G7：☐；输出仅称候选信号。

已读证据：docs/strategies/T-R16 四源稿及 cards/st_pullback_ma.md；T-R58/param_audit.md §1/2/5、retest_plan.md §6/7/8/11；T-R71 四卡 §3/5/7–11/17/18/22、README.md §5/6；golden/T-R73_README.md 与 check_T-R73.py；feature_spec.md 相关节及既有市场规则核查。T-R58 §1 明列「有回测=0」，四卡 §11 为 window未执行/oos_result未验证；本地 Markdown 证据检索未发现这四卡参数的历史样本外结果。T-R58 的 T-01 方案也不是已完成复测，不能跨策略借用为验证结论。

计数按以下七列表的参数行：不同用途的窗口分别列，同一参数跨规则重复出现只列一次；共同参数逐卡展开，故总数不与 T-R71 README 的79个分组登记项相同。固定向量拆到用途；冲击档表每个分档一行。没有默认数值但必须冻结的佣金、R/计日也保留状态。证券代码、接口编号、合成输入的500日/1拆2/预热80根、数据覆盖起点和纯单位换算常数不是卡阈值，不充当已验证参数。§5新增费率历史段及背景按制度证据单列，不增添四卡默认参数，故不计入§2逐卡参数行数。

T-R75于2026-11-15补做费率制度的公开官方原文核对，补齐印花税分段并将最低佣金改为「以用户券商为准、未验证」。同日T-R76通过中国结算通知目录、官方PDF、北交所业务规则页及财政部/发改委政策原文，补齐2012/2015/2022过户费、北交所三段经手费及证管费0.02‰和纳入日期，详见§5；四卡现段过户费恢复已验证，北市过户费前段的起始日仍待补。其余制度状态沿用仓库已有核查，本轮未重新核法。科创板1股递增已逐字核对官网投教表述（URL与访问日期见§2对应行），正式规则明文仍未验证；上市30日、长停牌5日、低价2元仍为内部闸门。四卡正文及§22未在本单修改，费用状态以本审计为准。

P 表示 docs/strategies/golden/T-R73_golden.json 中对应 case（卡号-FX1）的 params；F 表示同 case 的 fixed_params；unverified 均为同 case 字段。表中「一致」只表示当前数值/口径相符，不表示历史有效性通过。「仅登记」表示有字段而未参与相应求值；「golden未用」表示未覆盖该参数。敏感性列 A–E 指 §4 最小复测包，原值和网格均非本轮选优结果。无原范围的固定项以原值为单点区间，先做消融或边界核验；新增网格须先预注册，不能编成原稿已有范围。

| 卡 | 参数数 | 已验证 | 未验证 | params核对 |
|---|---:|---:|---:|---|
| S-01 | 78 | 13 | 65 | 9项一致 |
| S-02 | 77 | 13 | 64 | 9项一致 |
| S-04 | 71 | 13 | 58 | 5项一致 |
| W-02 | 83 | 13 | 70 | 8项一致 |

T-R76计数更正（相对T-R75）：总参数仍309；已验证48→52，未验证261→257。每卡各1项现段过户费恢复已验证，实际最低佣金仍未验证；§5的25项制度段/背景另计已验证15→23、未验证10→2（北市过户费前段起始日、实际最低佣金）。

## 2. 逐卡参数明细

### S-01（docs/strategies/T-R71/S-01_st_pullback_ma.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-01 | rs_min | 0.15 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:96 | 0.10–0.30；步0.05；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.rs_min=0.15；一致 |
| S-01 | touch_pct | 0.01 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:97 | 0.0–0.03；步0.005；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.touch_pct=0.01；一致 |
| S-01 | shrink_ratio | 0.7 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:98 | 0.5–0.9；步0.05；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.shrink_ratio=0.7；一致 |
| S-01 | exit_confirm_days | 2 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:99 | 1–3；步1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.exit_confirm_days=2；一致（checker 固定2根求值，未读取此键） |
| S-01 | hard_stop_pct | 0.08 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:100 | 0.05–0.12；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.hard_stop_pct=0.08；一致 |
| S-01 | time_stop | 5 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:101 | 3–10；步1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.time_stop=5；一致 |
| S-01 | min_amount | 50000000.0 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:102 | 10000000.0–500000000.0；步10000000.0；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_amount=50000000.0；一致 |
| S-01 | min_list_days | 60 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:103 | 30–250；步10；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_list_days=60；一致 |
| S-01 | slippage_bp | 10.0 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:104 | 0.0–50.0；步1.0；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | P.slippage_bp=10.0；一致 |
| S-01 | MA短窗 | 5根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:110 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.ma_windows=[5, 10, 20]；一致（对应5） |
| S-01 | MA触及/退出窗 | 10根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:113；仓内定义：docs/strategies/cards/st_pullback_ma.md:130 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.ma_windows=[5, 10, 20]；一致（对应10） |
| S-01 | MA长窗 | 20根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:110 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.ma_windows=[5, 10, 20]；一致（对应20） |
| S-01 | 动量窗口 | 20根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:107 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.momentum_windows=[5, 20]；一致（20参与；5仅登记） |
| S-01 | 缩量均额窗口 | 5根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:116 | 原值5；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 流动性/反证均额窗口 | 20根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:118；仓内定义：docs/strategies/cards/st_pullback_ma.md:126 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.amount_window=20；一致 |
| S-01 | 反证跌幅 | >5% | 仓内定义：docs/strategies/cards/st_pullback_ma.md:124 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.counter_drop_pct=0.05；一致 |
| S-01 | 反证放量倍数 | >1.5 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:126 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.counter_amount_mult=1.5；一致 |
| S-01 | 时间止损有利幅度门槛 | <1R；R口径待裁定 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:135；仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:94 | 原值；A | 未验证（仅仓内定义）；R口径未裁定、效果未验证（待复测） | F.time_r_gate=1.0；一致（仅登记，R未求值） |
| S-01 | 卡预热 | 25根有效K | 仓内定义：docs/strategies/cards/st_pullback_ma.md:18 | 25与更长历史重算；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.warmup=25；一致 |
| S-01 | 证伪观察期 | 5交易日 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:38 | 原值5；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 证伪最低跟踪数 | n≥30 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:39 | 30仅最低披露门槛；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 证伪胜率门槛 | <45% | 仓内定义：docs/strategies/cards/st_pullback_ma.md:39 | 原值45%；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 证伪rs_min邻域 | ±0.05 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:40 | ±0.05；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 证伪shrink_ratio邻域 | ±0.1 | 仓内定义：docs/strategies/cards/st_pullback_ma.md:40 | ±0.1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-01 | 候选有效期 | 1交易日 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:90 | 原值；A | 未验证（仅仓内定义）；执行与效果未验证（待复测） | F.valid_for_trading_days=1；一致 |
| S-01 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:31 | 17:10及实际就绪延迟；D | 未验证（仅仓内定义）；实际就绪未验证（待复测） | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-01 | 下一交易日执行偏移 | T+1开盘；最早09:30 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:90 | 固定偏移；D | 未验证（仅仓内定义）；执行与效果未验证（待复测） | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-01 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:42 | 固定公式；D | 未验证（仅仓内定义）；历史因子与复测未验证（待复测） | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-01 | 成交额/成交量复权 | none；amount元、volume股 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:35；仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:37 | 固定单位；D | 未验证（仅仓内定义）；源单位与复测未验证（待复测） | 一致：原始amount/volume；P/F无键 |
| S-01 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | 仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:128 | 0边界/缺失拒绝；D | 未验证（仅仓内定义）；真实成交未验证（待复测） | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-01 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-01_st_pullback_ma.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-01 | F01最低有效覆盖 | 15根/20交易日；S-01自定义有效K均额不走此阈值 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/feature_spec.md:121；仓内定义：docs/strategies/T-R71/S-01_st_pullback_ma.md:46 | 15与完整20对照；D | 未验证（仅仓内定义）；覆盖阈值效果未验证（待复测） | golden未用：F.amount_min_coverage=15 |
| S-01 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/cards/st_pullback_ma.md:118；仓内定义：docs/strategies/golden/check_T-R73.py:137 | 固定口径；D | 未验证（仅仓内定义）；实现复测未验证（待复测） | 一致：checker S-01不取整，其余1元 |
| S-01 | 环境短均线 | 20根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-01 | 环境长均线 | 60根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-01 | 宽度均值窗口 | 20交易日 | 仓内定义：docs/strategies/feature_spec.md:317 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_ma=20；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 上行宽度阈值 | >0.5 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_up=0.5；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 下行宽度阈值 | <0.4 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_down=0.4；一致（S-01 V1不用宽度；RC3未回放） |
| S-01 | 环境防抖 | 连续2日 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.regime_confirm_days=2；一致 |
| S-01 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | 仓内定义：docs/strategies/feature_spec.md:334；仓内定义：docs/strategies/T-R71/README.md:107 | 61与完整历史重算；D | 未验证（仅仓内定义）；F25整体预热及效果未验证（待复测） | golden未用：合成环境额外80根不是卡阈值 |
| S-01 | 环境指数最低覆盖 | 45根/MA60 | 仓内定义：docs/strategies/feature_spec.md:327；仓内定义：docs/strategies/feature_spec.md:334 | 45与60对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-01 | 宽度最低覆盖 | 15值/20日 | 仓内定义：docs/strategies/feature_spec.md:327 | 15与20对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：输入完整；F无独立键 |
| S-01 | 市场宽度小数精度 | 4位 | 仓内定义：docs/strategies/feature_spec.md:317 | 固定精度；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用作边界：合成值0.5精确 |
| S-01 | 低价门槛 | none<2元阻断 | 仓内定义：docs/strategies/catalog.md:73 | 原值2；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.raw_price_floor=2；一致 |
| S-01 | 上市共同闸门 | 不足30交易日阻断 | 仓内定义：docs/strategies/_template.md:131 | 固定30；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：上市均≥500，仅测试卡门槛 |
| S-01 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | 仓内定义：docs/strategies/_template.md:128 | 5日边界/首日；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未覆盖≥5日停牌 |
| S-01 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-01_st_pullback_ma.md §18；本文件§5 F24仅核佣金上限3‰，不验证具体费率或最低额 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-01 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | 仓内定义：docs/strategies/_template.md:253 | 20原值；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：unverified.impact，无拟成交额 |
| S-01 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:258 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:259 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:260 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:261 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:262 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 容量受限阈值 | 参与率>2% | 仓内定义：docs/strategies/_template.md:262 | 原值2%；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：无拟成交额 |
| S-01 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | 仓内定义：docs/strategies/_template.md:267；仓内定义：docs/strategies/_template.md:262 | 5/0边界；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-01 | 同模板证券冷却 | 3交易日且检查持有重叠 | 仓内定义：docs/strategies/validation.md:131；仓内定义：docs/strategies/T-R71/README.md:112 | 原值3；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：每case只跟踪首笔 |
| S-01 | 研究最低样本数 | min_n=30 | 仓内定义：docs/strategies/validation.md:44；仓内定义：docs/strategies/validation.md:134 | 30仅披露下限；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：4个合成case非历史n |
| S-01 | 参数邻域 | 原网格±1步 | 仓内定义：docs/strategies/validation.md:142 | 原网格±1步；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：仅默认值 |
| S-01 | 组合预算 | ≤50 | 仓内定义：docs/strategies/validation.md:141 | 固定上限50；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未选参 |
| S-01 | 样本外折数 | K=5 | 仓内定义：docs/strategies/validation.md:68 | 固定5；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无训练/评估切分 |
| S-01 | 切分隔离期 | embargo=持有期h；动态h未裁定 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/T-R71/README.md:115 | 冻结h后划分；E | 未验证（仅仓内定义）；动态h未裁定、效果未验证（待复测） | golden未用：无样本外切分 |
| S-01 | 最终保留期 | 最后12个月 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/validation.md:151 | 固定12个月；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：非历史保留集 |
| S-01 | 多重检验水平 | BH q=0.10（建议值） | 仓内定义：docs/strategies/validation.md:147 | 固定q=0.10；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无显著性结果 |
| S-01 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-01 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-01 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-01 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-01 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-01 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-01 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-01 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-01 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | 本文件§5 F04：《中华人民共和国印花税法》第3/5/20条及税目税率表，税务总局官方全文/附件（取代仅引T-R58 §5 R6） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 现段卖出印花税 | 0.05%，2023-08-28起 | 本文件§5 F05：财政部、税务总局《关于减半征收证券交易印花税的公告》，2023年第39号（补官方原文） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 过户费 | 买、卖各按成交金额0.001%，2022-04-29起 | 本文件§5 F10：中国结算《中国结算关于降低股票交易过户费收费标准的通知》，2022-04-28官方正文HTTP 200，补齐原文后恢复制度验证 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-01 | 最低佣金 | 以用户券商为准；5元仅历史规定/压力参考，实际最低额未核 | 本文件§5 F25：证监发〔2002〕21号原文及效力状态仅作背景；实际券商协议未读取 | 用户实际最低额；5元只作待验证压力档；C | 以用户券商为准、未验证 | golden未用：fees=null |
| S-01 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-01 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-01 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | 仓内定义：docs/strategies/market_rules_T-R10.md:65；仓内定义：docs/strategies/market_rules_T-R10.md:68；上海证券交易所，《第十三期：科创板股票交易规则必知（一）》第6问，https://edu.sse.com.cn/tib/qa/，访问日期 2026-11-16 | 1股；待正式规则/接口规范佐证；D | 未验证（正式规则明文待补）；官网投教表述已核对 | golden未用：无数量账本 |

### S-02（docs/strategies/T-R71/S-02_st_oversold_rebound.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-02 | rsi_os | 30.0 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:66；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.7（期刊第182页，PDF第5页；仅文献采用30阈值；其简单均值并非本卡Wilder递推；不能证明对A股有效） | 20.0–35.0；步1.0；A | 文献采用该取值；A股有效性未验证（待复测） | P.rsi_os=30.0；一致 |
| S-02 | drop_5d | 0.08 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:67 | 0.05–0.15；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.drop_5d=0.08；一致 |
| S-02 | stop_pct | 0.03 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:68 | 0.02–0.05；步0.005；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.stop_pct=0.03；一致 |
| S-02 | tp_pct | 0.06 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:69 | 0.04–0.1；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.tp_pct=0.06；一致 |
| S-02 | rsi_exit | 55.0 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:70 | 50.0–65.0；步1.0；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.rsi_exit=55.0；一致 |
| S-02 | max_hold | 5 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:71 | 3–10；步1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.max_hold=5；一致 |
| S-02 | min_amount | 50000000.0 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:72 | 10000000.0–500000000.0；步10000000.0；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_amount=50000000.0；一致 |
| S-02 | min_list_days | 60 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:73 | 30–120；步10；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_list_days=60；一致 |
| S-02 | slippage_bp | 10.0 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:74 | 0.0–50.0；步1.0；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | P.slippage_bp=10.0；一致 |
| S-02 | RSI周期 | 14 | 仓内定义：docs/strategies/feature_spec.md:281；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.7（期刊第182页，PDF第5页；仅文献采用14日；不证明28根预热；不能证明对A股有效） | 原值；A | 文献采用该取值；A股有效性未验证（待复测） | F.rsi_period=14；一致 |
| S-02 | RSI预热 | 28根有效K | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:24 | 原值；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.rsi_warmup=28；一致 |
| S-02 | 超卖回看 | 3根有效K | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:29 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.rsi_lookback=3；一致 |
| S-02 | 跌幅窗口 | 5根有效K | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:30 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.momentum_windows=[5, 20]；一致 |
| S-02 | 失效低点窗口 | 前5根有效K，不含T | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:35 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.structure_low_window=5；一致 |
| S-02 | 结构止损低点窗口 | 5根，候选日及之前4根 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:88；仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:96 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.structure_low_window=5；一致 |
| S-02 | 回收高点/衰竭偏移 | 前1根有效K | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:31；仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:39 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-02 | 反证放量倍数 | >1.5 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:34 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.counter_amount_mult=1.5；一致 |
| S-02 | 卡预热 | 30根有效K | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:24 | 原值与更长历史重算；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.warmup=30；一致 |
| S-02 | 证伪观察期 | 3交易日 | 仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:11 | 原值；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-02 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:46 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.amount_window=20；一致 |
| S-02 | 候选有效期 | 1交易日 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:92 | 原值；A | 未验证（仅仓内定义）；执行与效果未验证（待复测） | F.valid_for_trading_days=1；一致 |
| S-02 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:31 | 17:10及实际就绪延迟；D | 未验证（仅仓内定义）；实际就绪未验证（待复测） | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-02 | 下一交易日执行偏移 | T+1开盘；最早09:30 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:92 | 固定偏移；D | 未验证（仅仓内定义）；执行与效果未验证（待复测） | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-02 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:42 | 固定公式；D | 未验证（仅仓内定义）；历史因子与复测未验证（待复测） | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-02 | 成交额/成交量复权 | none；amount元、volume股 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:35；仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:37 | 固定单位；D | 未验证（仅仓内定义）；源单位与复测未验证（待复测） | 一致：原始amount/volume；P/F无键 |
| S-02 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:132 | 0边界/缺失拒绝；D | 未验证（仅仓内定义）；真实成交未验证（待复测） | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-02 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-02_st_oversold_rebound.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-02 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | 仓内定义：docs/strategies/T-R71/S-02_st_oversold_rebound.md:100 | 固定严格比较；D | 未验证（仅仓内定义）；派生与执行未验证（待复测） | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| S-02 | F01最低有效覆盖 | 15根/20交易日 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/feature_spec.md:121 | 15与完整20对照；D | 未验证（仅仓内定义）；覆盖阈值效果未验证（待复测） | 一致：F.amount_min_coverage=15 |
| S-02 | RSI平滑旧值权重 | 13/14；周期14见专属行 | 仓内定义：docs/strategies/feature_spec.md:281 | 固定公式与起点；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：checker固定13/14；P/F.rsi_period=14 |
| S-02 | RSI精度/零涨跌边界 | 2位；区间0–100；全平盘null非50 | 仓内定义：docs/strategies/feature_spec.md:281 | 固定口径；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：F.rsi_period=14；其他边界无键 |
| S-02 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/cards/st_pullback_ma.md:118；仓内定义：docs/strategies/golden/check_T-R73.py:137 | 固定口径；D | 未验证（仅仓内定义）；实现复测未验证（待复测） | 一致：checker S-01不取整，其余1元 |
| S-02 | 环境短均线 | 20根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-02 | 环境长均线 | 60根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-02 | 宽度均值窗口 | 20交易日 | 仓内定义：docs/strategies/feature_spec.md:317 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_ma=20；一致 |
| S-02 | 上行宽度阈值 | >0.5 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_up=0.5；一致 |
| S-02 | 下行宽度阈值 | <0.4 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_down=0.4；一致 |
| S-02 | 环境防抖 | 连续2日 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.regime_confirm_days=2；一致 |
| S-02 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | 仓内定义：docs/strategies/feature_spec.md:334；仓内定义：docs/strategies/T-R71/README.md:107 | 61与完整历史重算；D | 未验证（仅仓内定义）；F25整体预热及效果未验证（待复测） | golden未用：合成环境额外80根不是卡阈值 |
| S-02 | 环境指数最低覆盖 | 45根/MA60 | 仓内定义：docs/strategies/feature_spec.md:327；仓内定义：docs/strategies/feature_spec.md:334 | 45与60对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-02 | 宽度最低覆盖 | 15值/20日 | 仓内定义：docs/strategies/feature_spec.md:327 | 15与20对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：输入完整；F无独立键 |
| S-02 | 市场宽度小数精度 | 4位 | 仓内定义：docs/strategies/feature_spec.md:317 | 固定精度；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用作边界：合成值0.5精确 |
| S-02 | 低价门槛 | none<2元阻断 | 仓内定义：docs/strategies/catalog.md:73 | 原值2；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.raw_price_floor=2；一致 |
| S-02 | 上市共同闸门 | 不足30交易日阻断 | 仓内定义：docs/strategies/_template.md:131 | 固定30；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：上市均≥500，仅测试卡门槛 |
| S-02 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | 仓内定义：docs/strategies/_template.md:128 | 5日边界/首日；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未覆盖≥5日停牌 |
| S-02 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-02_st_oversold_rebound.md §18；本文件§5 F24仅核佣金上限3‰，不验证具体费率或最低额 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-02 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | 仓内定义：docs/strategies/_template.md:253 | 20原值；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：unverified.impact，无拟成交额 |
| S-02 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:258 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:259 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:260 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:261 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:262 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 容量受限阈值 | 参与率>2% | 仓内定义：docs/strategies/_template.md:262 | 原值2%；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：无拟成交额 |
| S-02 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | 仓内定义：docs/strategies/_template.md:267；仓内定义：docs/strategies/_template.md:262 | 5/0边界；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-02 | 同模板证券冷却 | 3交易日且检查持有重叠 | 仓内定义：docs/strategies/validation.md:131；仓内定义：docs/strategies/T-R71/README.md:112 | 原值3；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：每case只跟踪首笔 |
| S-02 | 研究最低样本数 | min_n=30 | 仓内定义：docs/strategies/validation.md:44；仓内定义：docs/strategies/validation.md:134 | 30仅披露下限；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：4个合成case非历史n |
| S-02 | 参数邻域 | 原网格±1步 | 仓内定义：docs/strategies/validation.md:142 | 原网格±1步；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：仅默认值 |
| S-02 | 组合预算 | ≤50 | 仓内定义：docs/strategies/validation.md:141 | 固定上限50；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未选参 |
| S-02 | 样本外折数 | K=5 | 仓内定义：docs/strategies/validation.md:68 | 固定5；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无训练/评估切分 |
| S-02 | 切分隔离期 | embargo=持有期h；动态h未裁定 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/T-R71/README.md:115 | 冻结h后划分；E | 未验证（仅仓内定义）；动态h未裁定、效果未验证（待复测） | golden未用：无样本外切分 |
| S-02 | 最终保留期 | 最后12个月 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/validation.md:151 | 固定12个月；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：非历史保留集 |
| S-02 | 多重检验水平 | BH q=0.10（建议值） | 仓内定义：docs/strategies/validation.md:147 | 固定q=0.10；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无显著性结果 |
| S-02 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-02 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-02 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-02 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-02 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-02 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-02 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-02 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-02 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | 本文件§5 F04：《中华人民共和国印花税法》第3/5/20条及税目税率表，税务总局官方全文/附件（取代仅引T-R58 §5 R6） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 现段卖出印花税 | 0.05%，2023-08-28起 | 本文件§5 F05：财政部、税务总局《关于减半征收证券交易印花税的公告》，2023年第39号（补官方原文） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 过户费 | 买、卖各按成交金额0.001%，2022-04-29起 | 本文件§5 F10：中国结算《中国结算关于降低股票交易过户费收费标准的通知》，2022-04-28官方正文HTTP 200，补齐原文后恢复制度验证 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-02 | 最低佣金 | 以用户券商为准；5元仅历史规定/压力参考，实际最低额未核 | 本文件§5 F25：证监发〔2002〕21号原文及效力状态仅作背景；实际券商协议未读取 | 用户实际最低额；5元只作待验证压力档；C | 以用户券商为准、未验证 | golden未用：fees=null |
| S-02 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-02 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-02 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | 仓内定义：docs/strategies/market_rules_T-R10.md:65；仓内定义：docs/strategies/market_rules_T-R10.md:68；上海证券交易所，《第十三期：科创板股票交易规则必知（一）》第6问，https://edu.sse.com.cn/tib/qa/，访问日期 2026-11-16 | 1股；待正式规则/接口规范佐证；D | 未验证（正式规则明文待补）；官网投教表述已核对 | golden未用：无数量账本 |

### S-04（docs/strategies/T-R71/S-04_st_broken_board.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| S-04 | min_boards | 2 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:65 | 1–5；步1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_boards=2；一致 |
| S-04 | vol_ratio | 1.5 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:66 | 1.2–3.0；步0.1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.vol_ratio=1.5；一致 |
| S-04 | stop_pct | 0.05 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:67 | 0.03–0.1；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.stop_pct=0.05；一致 |
| S-04 | max_hold | 5 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:68 | 3–10；步1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.max_hold=5；一致 |
| S-04 | slippage_bp | 10.0 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:69 | 0.0–50.0；步1.0；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | P.slippage_bp=10.0；一致 |
| S-04 | 上市天数门槛 | ≥60交易日 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:15；仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:27 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.min_list_days=60；一致 |
| S-04 | 封板计数窗口 | 20交易日 | 仓内定义：docs/strategies/feature_spec.md:212 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.limit_count_window=20；一致 |
| S-04 | 封板时序偏移 | T−2 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:28 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-04 | 断板/收复高点偏移 | T−1 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:28；仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:29；仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:35 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-04 | 失效高点偏移 | 前第2根有效K，ref(high,2) | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:33 | 原值2；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：checker固定偏移2；P/F无键 |
| S-04 | 失效连续确认 | 2根 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:33 | 原值2；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：checker固定连续2根；P/F无键 |
| S-04 | 退出均线窗口 | MA5 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:36 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.ma_windows=[5, 10, 20]；一致（5参与；10/20仅诊断） |
| S-04 | 卡预热 | 20根有效K | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:23 | 原值与更长历史重算；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.warmup=20；一致 |
| S-04 | 证伪观察期 | 3交易日 | 仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:11 | 原值；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| S-04 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:46 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.amount_window=20；一致 |
| S-04 | 候选有效期 | 1交易日 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:91 | 原值；A | 未验证（仅仓内定义）；执行与效果未验证（待复测） | F.valid_for_trading_days=1；一致 |
| S-04 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:31 | 17:10及实际就绪延迟；D | 未验证（仅仓内定义）；实际就绪未验证（待复测） | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| S-04 | 下一交易日执行偏移 | T+1开盘；最早09:30 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:91 | 固定偏移；D | 未验证（仅仓内定义）；执行与效果未验证（待复测） | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| S-04 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:42 | 固定公式；D | 未验证（仅仓内定义）；历史因子与复测未验证（待复测） | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| S-04 | 成交额/成交量复权 | none；amount元、volume股 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:35；仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:37 | 固定单位；D | 未验证（仅仓内定义）；源单位与复测未验证（待复测） | 一致：原始amount/volume；P/F无键 |
| S-04 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:131 | 0边界/缺失拒绝；D | 未验证（仅仓内定义）；真实成交未验证（待复测） | 一致：合成停牌、跌停阻断；不验证排队成交 |
| S-04 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/S-04_st_broken_board.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| S-04 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | 仓内定义：docs/strategies/T-R71/S-04_st_broken_board.md:99 | 固定严格比较；D | 未验证（仅仓内定义）；派生与执行未验证（待复测） | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| S-04 | F01最低有效覆盖 | 15根/20交易日 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/feature_spec.md:121 | 15与完整20对照；D | 未验证（仅仓内定义）；覆盖阈值效果未验证（待复测） | 一致：F.amount_min_coverage=15 |
| S-04 | F11最低覆盖 | 15根；任一限价未知整段null | 仓内定义：docs/strategies/feature_spec.md:215 | 15与20；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.amount_min_coverage=15；一致（F11无独立键，checker亦用15） |
| S-04 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/cards/st_pullback_ma.md:118；仓内定义：docs/strategies/golden/check_T-R73.py:137 | 固定口径；D | 未验证（仅仓内定义）；实现复测未验证（待复测） | 一致：checker S-01不取整，其余1元 |
| S-04 | 环境短均线 | 20根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-04 | 环境长均线 | 60根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| S-04 | 宽度均值窗口 | 20交易日 | 仓内定义：docs/strategies/feature_spec.md:317 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_ma=20；一致 |
| S-04 | 上行宽度阈值 | >0.5 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_up=0.5；一致 |
| S-04 | 下行宽度阈值 | <0.4 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_down=0.4；一致 |
| S-04 | 环境防抖 | 连续2日 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.regime_confirm_days=2；一致 |
| S-04 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | 仓内定义：docs/strategies/feature_spec.md:334；仓内定义：docs/strategies/T-R71/README.md:107 | 61与完整历史重算；D | 未验证（仅仓内定义）；F25整体预热及效果未验证（待复测） | golden未用：合成环境额外80根不是卡阈值 |
| S-04 | 环境指数最低覆盖 | 45根/MA60 | 仓内定义：docs/strategies/feature_spec.md:327；仓内定义：docs/strategies/feature_spec.md:334 | 45与60对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| S-04 | 宽度最低覆盖 | 15值/20日 | 仓内定义：docs/strategies/feature_spec.md:327 | 15与20对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：输入完整；F无独立键 |
| S-04 | 市场宽度小数精度 | 4位 | 仓内定义：docs/strategies/feature_spec.md:317 | 固定精度；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用作边界：合成值0.5精确 |
| S-04 | 低价门槛 | none<2元阻断 | 仓内定义：docs/strategies/catalog.md:73 | 原值2；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.raw_price_floor=2；一致 |
| S-04 | 上市共同闸门 | 不足30交易日阻断 | 仓内定义：docs/strategies/_template.md:131 | 固定30；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：上市均≥500，仅测试卡门槛 |
| S-04 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | 仓内定义：docs/strategies/_template.md:128 | 5日边界/首日；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未覆盖≥5日停牌 |
| S-04 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/S-04_st_broken_board.md §18；本文件§5 F24仅核佣金上限3‰，不验证具体费率或最低额 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| S-04 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | 仓内定义：docs/strategies/_template.md:253 | 20原值；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：unverified.impact，无拟成交额 |
| S-04 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:258 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:259 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:260 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:261 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:262 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 容量受限阈值 | 参与率>2% | 仓内定义：docs/strategies/_template.md:262 | 原值2%；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：无拟成交额 |
| S-04 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | 仓内定义：docs/strategies/_template.md:267；仓内定义：docs/strategies/_template.md:262 | 5/0边界；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| S-04 | 同模板证券冷却 | 3交易日且检查持有重叠 | 仓内定义：docs/strategies/validation.md:131；仓内定义：docs/strategies/T-R71/README.md:112 | 原值3；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：每case只跟踪首笔 |
| S-04 | 研究最低样本数 | min_n=30 | 仓内定义：docs/strategies/validation.md:44；仓内定义：docs/strategies/validation.md:134 | 30仅披露下限；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：4个合成case非历史n |
| S-04 | 参数邻域 | 原网格±1步 | 仓内定义：docs/strategies/validation.md:142 | 原网格±1步；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：仅默认值 |
| S-04 | 组合预算 | ≤50 | 仓内定义：docs/strategies/validation.md:141 | 固定上限50；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未选参 |
| S-04 | 样本外折数 | K=5 | 仓内定义：docs/strategies/validation.md:68 | 固定5；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无训练/评估切分 |
| S-04 | 切分隔离期 | embargo=持有期h；动态h未裁定 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/T-R71/README.md:115 | 冻结h后划分；E | 未验证（仅仓内定义）；动态h未裁定、效果未验证（待复测） | golden未用：无样本外切分 |
| S-04 | 最终保留期 | 最后12个月 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/validation.md:151 | 固定12个月；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：非历史保留集 |
| S-04 | 多重检验水平 | BH q=0.10（建议值） | 仓内定义：docs/strategies/validation.md:147 | 固定q=0.10；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无显著性结果 |
| S-04 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| S-04 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| S-04 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-04 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| S-04 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-04 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| S-04 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| S-04 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| S-04 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | 本文件§5 F04：《中华人民共和国印花税法》第3/5/20条及税目税率表，税务总局官方全文/附件（取代仅引T-R58 §5 R6） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 现段卖出印花税 | 0.05%，2023-08-28起 | 本文件§5 F05：财政部、税务总局《关于减半征收证券交易印花税的公告》，2023年第39号（补官方原文） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 过户费 | 买、卖各按成交金额0.001%，2022-04-29起 | 本文件§5 F10：中国结算《中国结算关于降低股票交易过户费收费标准的通知》，2022-04-28官方正文HTTP 200，补齐原文后恢复制度验证 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| S-04 | 最低佣金 | 以用户券商为准；5元仅历史规定/压力参考，实际最低额未核 | 本文件§5 F25：证监发〔2002〕21号原文及效力状态仅作背景；实际券商协议未读取 | 用户实际最低额；5元只作待验证压力档；C | 以用户券商为准、未验证 | golden未用：fees=null |
| S-04 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-04 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| S-04 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | 仓内定义：docs/strategies/market_rules_T-R10.md:65；仓内定义：docs/strategies/market_rules_T-R10.md:68；上海证券交易所，《第十三期：科创板股票交易规则必知（一）》第6问，https://edu.sse.com.cn/tib/qa/，访问日期 2026-11-16 | 1股；待正式规则/接口规范佐证；D | 未验证（正式规则明文待补）；官网投教表述已核对 | golden未用：无数量账本 |

### W-02（docs/strategies/T-R71/W-02_sw_breakout.md）

| 卡 | 参数 | 值 | 出处（仓库路径＋节） | 敏感性区间/复测包 | 状态 | golden 对照 |
|---|---|---|---|---|---|---|
| W-02 | bw_pct120_th | 0.2 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:64 | 0.05–0.4；步0.05；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.bw_pct120_th=0.2；一致 |
| W-02 | vol_mult | 1.5 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:65 | 1.2–3.0；步0.1；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.vol_mult=1.5；一致 |
| W-02 | fail_pct | 0.03 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:66 | 0.01–0.05；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.fail_pct=0.03；一致 |
| W-02 | stop_pct | 0.05 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:67 | 0.03–0.10；步0.01；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.stop_pct=0.05；一致 |
| W-02 | max_hold | 20 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:68 | 10–40；步5；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.max_hold=20；一致 |
| W-02 | min_amount | 50000000.0 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:69 | 10000000.0–500000000.0；步10000000.0；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_amount=50000000.0；一致 |
| W-02 | min_list_days | 120 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:70 | 60–250；步10；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | P.min_list_days=120；一致 |
| W-02 | slippage_bp | 15.0 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:71 | 0.0–50.0；步1.0；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | P.slippage_bp=15.0；一致 |
| W-02 | 布林窗口 | 20根有效K | 仓内定义：docs/strategies/feature_spec.md:381；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.8（期刊第182–183页，PDF第5–6页；仅文献采用20日；不证明有效K及120日分位；不能证明对A股有效） | 原值；A | 文献采用该取值；A股有效性未验证（待复测） | F.boll_window=20；一致 |
| W-02 | 布林倍数 | 2（带宽系数4） | 仓内定义：docs/strategies/feature_spec.md:381；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.8（期刊第182–183页，PDF第5–6页；仅文献采用2倍标准差；带宽系数4及ddof=0另据仓库；不能证明对A股有效） | 原值；A | 文献采用该取值；A股有效性未验证（待复测） | F.boll_k=2；一致 |
| W-02 | 布林ddof | 0 | 仓内定义：docs/strategies/feature_spec.md:381 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.boll_ddof=0；一致 |
| W-02 | 带宽时间分位窗口 | 120个非null值，含T | 仓内定义：docs/strategies/feature_spec.md:388 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.bw_rank_window=120；一致 |
| W-02 | 突破最高收盘窗口 | 前20根有效K，不含T | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:23 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breakout_window=20；一致 |
| W-02 | 主板近涨停反证 | >9.5%；非主板系数未定 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:28 | 原值；A | 未验证（仅仓内定义）；非主板换算及效果未验证（待复测） | F.near_limit_up_pct=0.095；一致 |
| W-02 | 退出均线窗口 | MA10 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:31 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.ma_windows=[5, 10, 20]；一致 |
| W-02 | 均线退出确认 | 连续2根 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:31 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.exit_confirm_days=2；一致 |
| W-02 | 时间止损最短持有 | ≥3交易日 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:33 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.time_r_min_days=3；一致 |
| W-02 | 时间止损有利幅度 | <0.5R；R口径待定 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:33；仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:95 | 原值；A | 未验证（仅仓内定义）；R口径未裁定、效果未验证（待复测） | F.time_r_gate=0.5；一致（仅登记，R未求值） |
| W-02 | 失效观察期 | 入场后3日内 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:29 | 原值3；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| W-02 | 原证伪结构回撤 | 3% | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:12 | 原值3%；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| W-02 | 证伪分位敏感区间 | 0.1–0.3 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:12 | 0.1–0.3；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| W-02 | 证伪放量敏感区间 | 1.3–2.0 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:12 | 1.3–2.0；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| W-02 | 卡预热 | 140根有效K | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:17 | 原值与更长历史重算；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.warmup=140；一致 |
| W-02 | 证伪观察期 | 10交易日 | 仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:12 | 原值；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用 |
| W-02 | 流动性均额窗口 | 20交易日内有效K均额，非最近20根 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:46 | 原值；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.amount_window=20；一致 |
| W-02 | 候选有效期 | 1交易日 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:91 | 原值；A | 未验证（仅仓内定义）；执行与效果未验证（待复测） | F.valid_for_trading_days=1；一致 |
| W-02 | 信号定稿下限 | 北京时间17:10且实际定稿/依赖就绪后 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:31 | 17:10及实际就绪延迟；D | 未验证（仅仓内定义）；实际就绪未验证（待复测） | golden未用（合成输入17:10、求值17:15，不验证此下限） |
| W-02 | 下一交易日执行偏移 | T+1开盘；最早09:30 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:91 | 固定偏移；D | 未验证（仅仓内定义）；执行与效果未验证（待复测） | 一致：expect.trade为次日开盘/阻断顺延；P/F无键 |
| W-02 | 复权锚点/因子缺口 | qfq@T=raw(d)×A(d)/A(T)；缺因子不补1 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:42 | 固定公式；D | 未验证（仅仓内定义）；历史因子与复测未验证（待复测） | 一致：unverified.split仅1拆2；复杂权息golden未用 |
| W-02 | 成交额/成交量复权 | none；amount元、volume股 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:35；仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:37 | 固定单位；D | 未验证（仅仓内定义）；源单位与复测未验证（待复测） | 一致：原始amount/volume；P/F无键 |
| W-02 | 零量/一字板成交边界 | volume>0且none四价相等；停牌/不可卖不成交 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:131 | 0边界/缺失拒绝；D | 未验证（仅仓内定义）；真实成交未验证（待复测） | 一致：合成停牌、跌停阻断；不验证排队成交 |
| W-02 | 入场计日起点 | 未裁定 | docs/strategies/T-R71/W-02_sw_breakout.md §9 | 0/1及含/不含停牌仅语义对照；D | 未验证 | golden未用作裁定：unverified.holding_day_convention入场0、含停牌 |
| W-02 | 冻结结构触发/执行 | 严格收盘<阈值；下一可卖日开盘 | 仓内定义：docs/strategies/T-R71/W-02_sw_breakout.md:99 | 固定严格比较；D | 未验证（仅仓内定义）；派生与执行未验证（待复测） | 一致：expect.trade冻结L_raw+s、相等不触发与顺延 |
| W-02 | F01最低有效覆盖 | 15根/20交易日 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/feature_spec.md:121 | 15与完整20对照；D | 未验证（仅仓内定义）；覆盖阈值效果未验证（待复测） | 一致：F.amount_min_coverage=15 |
| W-02 | 带宽分位最低覆盖 | 90个（90/120=0.75建议） | 仓内定义：docs/strategies/feature_spec.md:389；仓内定义：docs/strategies/feature_spec.md:53 | 90与120对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.bw_min_coverage=90；一致 |
| W-02 | 带宽舍入精度 | 6位 | 仓内定义：docs/strategies/feature_spec.md:381 | 固定精度；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：checker固定6；P/F无键 |
| W-02 | 分位舍入/同值秩 | 4位；平均秩/n（同值数+1）/2 | 仓内定义：docs/strategies/feature_spec.md:388；仓内定义：docs/strategies/feature_spec.md:80 | 固定精度/并列值；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | 一致：checker固定4；P/F无键 |
| W-02 | 均额舍入精度 | S-01有效K原均值；其余F01取整1元 | 仓内定义：docs/strategies/feature_spec.md:118；仓内定义：docs/strategies/cards/st_pullback_ma.md:118；仓内定义：docs/strategies/golden/check_T-R73.py:137 | 固定口径；D | 未验证（仅仓内定义）；实现复测未验证（待复测） | 一致：checker S-01不取整，其余1元 |
| W-02 | 环境短均线 | 20根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| W-02 | 环境长均线 | 60根 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.environment_ma=[20, 60]；一致 |
| W-02 | 宽度均值窗口 | 20交易日 | 仓内定义：docs/strategies/feature_spec.md:317 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_ma=20；一致 |
| W-02 | 上行宽度阈值 | >0.5 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_up=0.5；一致 |
| W-02 | 下行宽度阈值 | <0.4 | 仓内定义：docs/strategies/feature_spec.md:324 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.breadth_down=0.4；一致 |
| W-02 | 环境防抖 | 连续2日 | 仓内定义：docs/strategies/feature_spec.md:324；仓内定义：docs/strategies/feature_spec.md:331 | 原值；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.regime_confirm_days=2；一致 |
| W-02 | 环境预热 | F50为61根（最低45+1）；F25整体预热未定 | 仓内定义：docs/strategies/feature_spec.md:334；仓内定义：docs/strategies/T-R71/README.md:107 | 61与完整历史重算；D | 未验证（仅仓内定义）；F25整体预热及效果未验证（待复测） | golden未用：合成环境额外80根不是卡阈值 |
| W-02 | 环境指数最低覆盖 | 45根/MA60 | 仓内定义：docs/strategies/feature_spec.md:327；仓内定义：docs/strategies/feature_spec.md:334 | 45与60对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：F仅有environment_ma=[20,60]，输入完整 |
| W-02 | 宽度最低覆盖 | 15值/20日 | 仓内定义：docs/strategies/feature_spec.md:327 | 15与20对照；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：输入完整；F无独立键 |
| W-02 | 市场宽度小数精度 | 4位 | 仓内定义：docs/strategies/feature_spec.md:317 | 固定精度；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用作边界：合成值0.5精确 |
| W-02 | 低价门槛 | none<2元阻断 | 仓内定义：docs/strategies/catalog.md:73 | 原值2；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | F.raw_price_floor=2；一致 |
| W-02 | 上市共同闸门 | 不足30交易日阻断 | 仓内定义：docs/strategies/_template.md:131 | 固定30；B | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：上市均≥500，仅测试卡门槛 |
| W-02 | 长停牌复牌入场闸门 | 停牌≥5交易日；复牌首1日阻断入场 | 仓内定义：docs/strategies/_template.md:128 | 5日边界/首日；D | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未覆盖≥5日停牌 |
| W-02 | 佣金费率 | 未冻结；无默认数值 | docs/strategies/T-R71/README.md §6 P06；docs/strategies/T-R71/W-02_sw_breakout.md §18；本文件§5 F24仅核佣金上限3‰，不验证具体费率或最低额 | 实际费率；方案参考0.015%/0.025%/0.03%（非卡默认）；C | 未验证 | golden未用：unverified.commission，fees=null |
| W-02 | 冲击ADV窗口 | 最近20根有效K；拟成交额/ADV | 仓内定义：docs/strategies/_template.md:253 | 20原值；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：unverified.impact，无拟成交额 |
| W-02 | 冲击分档 ≤0.1% | 0bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:258 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤0.5% | 5bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:259 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤1% | 15bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:260 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 冲击分档 ≤2% | 30bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:261 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 冲击分档 >2% | 60bp（逐档按前一上界排除） | 仓内定义：docs/strategies/_template.md:262 | 原档表及一档升降压力；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 容量受限阈值 | 参与率>2% | 仓内定义：docs/strategies/_template.md:262 | 原值2%；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：无拟成交额 |
| W-02 | 冲击回退最低覆盖 | 有效K<5或ADV=0取60bp | 仓内定义：docs/strategies/_template.md:267；仓内定义：docs/strategies/_template.md:262 | 5/0边界；C | 未验证（仅仓内定义）；成本校准未验证（待复测） | golden未用：impact_cost=null |
| W-02 | 同模板证券冷却 | 3交易日且检查持有重叠 | 仓内定义：docs/strategies/validation.md:131；仓内定义：docs/strategies/T-R71/README.md:112 | 原值3；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：每case只跟踪首笔 |
| W-02 | 研究最低样本数 | min_n=30 | 仓内定义：docs/strategies/validation.md:44；仓内定义：docs/strategies/validation.md:134 | 30仅披露下限；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：4个合成case非历史n |
| W-02 | 参数邻域 | 原网格±1步 | 仓内定义：docs/strategies/validation.md:142 | 原网格±1步；A | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：仅默认值 |
| W-02 | 组合预算 | ≤50 | 仓内定义：docs/strategies/validation.md:141 | 固定上限50；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：未选参 |
| W-02 | 样本外折数 | K=5 | 仓内定义：docs/strategies/validation.md:68 | 固定5；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无训练/评估切分 |
| W-02 | 切分隔离期 | embargo=持有期h；动态h未裁定 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/T-R71/README.md:115 | 冻结h后划分；E | 未验证（仅仓内定义）；动态h未裁定、效果未验证（待复测） | golden未用：无样本外切分 |
| W-02 | 最终保留期 | 最后12个月 | 仓内定义：docs/strategies/validation.md:68；仓内定义：docs/strategies/validation.md:151 | 固定12个月；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：非历史保留集 |
| W-02 | 多重检验水平 | BH q=0.10（建议值） | 仓内定义：docs/strategies/validation.md:147 | 固定q=0.10；E | 未验证（仅仓内定义）；A股有效性未验证（待复测） | golden未用：无显著性结果 |
| W-02 | 股票可卖偏移 | T+1；本卡信号T、买T+1、最早卖T+2 | docs/strategies/T-R58/param_audit.md §5 R1 | 制度固定，按有效日分段 | 已验证 | 一致：合成可卖证据及次日约束；P/F无键 |
| W-02 | 主板普通涨跌幅 | ±10% | docs/strategies/T-R58/param_audit.md §5 R2 | 制度固定，按有效日分段 | 已验证 | 一致：合成limit_up/down=pre_close×1.1/0.9 |
| W-02 | 创业板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2/5.2；docs/strategies/T-R58/param_audit.md §5 R3 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| W-02 | 科创板涨跌幅 | ±20%（含风险警示） | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R4 | 制度固定，按有效日分段 | 已验证 | golden未用：仅普通主板 |
| W-02 | 主板ST历史幅度 | ±5%，2023-04-10至2026-07-05 | docs/strategies/market_rules_check.md §5.2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| W-02 | 主板ST现段幅度 | ±10%，2026-07-06起 | docs/strategies/market_rules_check.md §1/2；docs/strategies/T-R58/param_audit.md §5 R5 | 制度固定，按有效日分段 | 已验证 | golden未用：非ST |
| W-02 | 注册制新股无涨跌幅期 | 上市前5交易日 | docs/strategies/market_rules_check.md §5.2 | 制度固定，按有效日分段 | 已验证 | golden未用：上市已满500虚构交易日 |
| W-02 | 价格最小变动/限价舍入 | 0.01元；ROUND_HALF_UP | docs/strategies/market_rules_check.md §3 M2/6 | 制度固定，按有效日分段 | 已验证 | 一致：checker固定0.01；P/F无键 |
| W-02 | 历史卖出印花税 | 0.1%，2023-04-10至2023-08-27 | 本文件§5 F04：《中华人民共和国印花税法》第3/5/20条及税目税率表，税务总局官方全文/附件（取代仅引T-R58 §5 R6） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 现段卖出印花税 | 0.05%，2023-08-28起 | 本文件§5 F05：财政部、税务总局《关于减半征收证券交易印花税的公告》，2023年第39号（补官方原文） | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 过户费 | 买、卖各按成交金额0.001%，2022-04-29起 | 本文件§5 F10：中国结算《中国结算关于降低股票交易过户费收费标准的通知》，2022-04-28官方正文HTTP 200，补齐原文后恢复制度验证 | 制度固定，按有效日分段 | 已验证 | golden未用：fees=null |
| W-02 | 最低佣金 | 以用户券商为准；5元仅历史规定/压力参考，实际最低额未核 | 本文件§5 F25：证监发〔2002〕21号原文及效力状态仅作背景；实际券商协议未读取 | 用户实际最低额；5元只作待验证压力档；C | 以用户券商为准、未验证 | golden未用：fees=null |
| W-02 | 普通/创业板整手 | 买入100股整数倍；不足100股余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| W-02 | 科创板最小申报/零股界 | 200股；不足200余量一次卖出 | docs/strategies/market_rules_T-R10.md §1.1/2.1 | 制度固定，按有效日分段 | 已验证 | golden未用：无数量账本 |
| W-02 | 科创板申报递增 | 200股以上递增1股（仅部分核实） | 仓内定义：docs/strategies/market_rules_T-R10.md:65；仓内定义：docs/strategies/market_rules_T-R10.md:68；上海证券交易所，《第十三期：科创板股票交易规则必知（一）》第6问，https://edu.sse.com.cn/tib/qa/，访问日期 2026-11-16 | 1股；待正式规则/接口规范佐证；D | 未验证（正式规则明文待补）；官网投教表述已核对 | golden未用：无数量账本 |

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

下列研究数值是**待预注册的方案值，不是已验证结论，也不回写卡默认值**。仓内方案框架为 docs/strategies/validation.md §1.4/2.5/4/5/7.2、T-R71/README.md §5/6；费用压力档借 仓内定义：docs/strategies/T-R58/retest_plan.md:210 的既有研究设定，仅属仓内定义，方案取值依据及适用性仍未验证（待复测）。每一未验证行均由敏感性列A–E覆盖；D只验证计算/执行口径，需与A/B/C的历史样本外研究同时满足，不能单靠算术用例晋级。

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
| C：滑点、佣金、ADV20、五档冲击/2%容量/5根回退 | B02历史额、B03/B06/B08执行账本；预注册拟成交额与实际费率，不调用账户 | 基础滑点0/原值/50bp（均在原范围）；佣金实际费率及0.015%/0.025%/0.03%参考档；冲击原表与整体升一档压力，封顶60bp，另保留0冲击诊断；金额借T-R58 §6.2的1/5/20万元压力档，非卡仓位 | 主费用与高费用压力均正；完整收双边佣金及用户券商实际最低额、按日期分段税费；最低额未冻结时只报压力情景，不给实际净收益结论；若只在部分金额成立，冻结训练得出的适用范围后由保留集验证，不反求边界 |
| D：预热/覆盖/精度、定稿、复权/冻结位、成交/计日、长停牌、科创1股递增 | B02/B03/B06/B08/B11及实际成交/规则证据，重点抽取阈值相等、缺字段、跨除权、ST切换与停牌边界 | 15对20、45对60、90对120及更长历史；数值舍入/平盘/缺因子边界；删去T后事件重算不变；原价现金/股数账本与qfq等价；计日0/1与停牌对照只用于暴露歧义，裁定后冻结 | 所有硬口径断言零差错；数据缺口不冒充覆盖；科创1股须补正式原文/规范才可升级制度状态；成本仍跑C，历史效用仍按A/B判定 |
| E：证伪期/胜率/n、冷却、邻域预算、5块/隔离/保留期/BH | 同A–D；B12行业数据与B03冻结日历；全部试验元数据 | 保持既有研究初值；3/5/10日依卡原证伪，另报固定持有期但不择优；评估有效n与重叠，bootstrap/BH与Holm，成本跑C | 样本足够才判断；研究设计初值本身不能因一次成功而称普适验证，不根据保留集修改统计门槛 |

| 卡 | 最小额外反证与数据重点 | 通过要求（在共用标准外） |
|---|---|---|
| S-01 | B02按有效K算5/20均额、MA5/10/20；趋势/触及/缩量各消融；5日行业超额、5日胜率与原邻域 | 行业证伪完成；邻域不翻转；不把v3截面规则移入v2；无真实历史范围则继续未验证 |
| S-02 | B08固定起点RSI14/28、近3根超卖；5根跌幅、前高确认与不确认组；冻结含候选日5根低点 | 3日扣费超额与企稳组差异支持假设；平盘null、阈值相等、跨除权和X1b顺延全部正确；环境消融有效 |
| S-04 | B06历史封板价、20交易日计数、T−2/T−1时序；放量/不放量组及环境组 | 3日超额支持假设，放量组差异通过校正；计数不是连板；冻结断板日高点、不可卖顺延与I1移动窗口正确 |
| W-02 | 140根预热、20/2/ddof0布林、120分位与90覆盖；当日收敛/突破/放量消融；10日超额与3%回撤 | 原0.1–0.3/1.3–2.0邻域稳定；R/I1/计日和非主板近涨停先裁定，未定部分不生成肯定结果；冻结突破位跨除权正确 |

上述差异检验预先定义效应方向与统计量，加入同一BH比较族；不能只报告组内显著而不检验组间差异。数据接口编号是未来依赖登记，不表示已接入；未取得字段、状态历史、实际成本或成交证据时，先记录阻塞，不以接口路径本身充当样本外证据。

## 5. T-R75/T-R76｜费率与交易成本制度原文核对（2026-11-15）

### 5.1 口径与逐项证据

仅采用财政部、税务总局、中国结算、沪深北交易所、全国股转、证监会及gov.cn政策库的官方域名；发改委原文位于ndrc.gov.cn。没有以媒体、券商转载或搜索摘要替代原文。下面「已验证」只验证所列制度值/历史适用段，不验证策略有效性、用户实收、完整费用实现或样本外表现。抓取用公开网页GET及curl，不带账户鉴权；HTTP 4xx/5xx即使curl退出0也记失败。文号未在成功原文中显示的写「页面未列」，原文失败者写「待补」，不猜文号。

本表为人民币A股普通竞价交易基准；每边费率指买方、卖方各自计收，并非往返总额；除明确注明成交面额的历史段外，按各自成交金额计费。成交面额与成交金额不可混用。B股、基金、协议转让、大宗交易、优先股、跨境额外收费不直接套用本表；例如深交所2023通知明确A股大宗经手费另下浮30%。2016-05-01价税分离不等于投资者价税合计费率再次下降，上交所官方回顾明确价税合计不超过原标准；本表不另造一个投资者费率段。历史起点尚未核实的前标准只作待核背景，不向更早日期外推；北市补证也不改变四卡排除北交所的研究范围。

| 编号/项目 | 费率数值与计费基数/方向 | 生效日及适用段 | 官方原文标题、发布机构、文号 | 官方URL | 抓取结果及适用说明 | 状态 |
|---|---|---|---|---|---|---|
| F01 印花税：2008年初承接段 | 成交金额3‰=0.3%，买卖双方分别缴纳 | 2007-05-30起；本次覆盖2008-01-01至2008-04-23 | 《关于调整证券（股票）交易印花税税率的通知》；财政部、国家税务总局；财税〔2007〕84号 | [官方原文/尝试入口](https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812176/200705/c1194505/content.html) | 成功，HTTP 200；该税率已被后续调整替代 | 已验证 |
| F02 印花税：2008年第一次调整 | 成交金额1‰=0.1%，买卖双方分别缴纳 | 2008-04-24至2008-09-18 | 《关于做好调整证券交易印花税税率相关工作的通知》；上海证券交易所（执行财政部、国家税务总局决定）；页面未列文号；发布2008-04-23 | [官方原文/尝试入口](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988181.shtml) | 成功，HTTP 200；按历史区间适用 | 已验证 |
| F03 印花税：2008年第二次调整 | 卖方1‰=0.1%；买方0 | 2008-09-19至2022-06-30（随后由法律承接） | 《关于做好调整证券交易印花税税率相关工作的通知》；上海证券交易所（执行财政部、国家税务总局决定）；页面未列文号；发布2008-09-18 | [官方原文/尝试入口](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988239.shtml) | 成功，HTTP 200；只引用上交所自己的执行通知，未冒充财政部原通知 | 已验证 |
| F04 印花税：法律承接段 | 证券交易成交金额1‰=0.1%，只向出让方征收 | 2022-07-01起；未减半段至2023-08-27；四卡建模截取2023-04-10起 | 《中华人民共和国印花税法》；全国人大常委会通过，国家主席公布；税务总局官网收录全文；中华人民共和国主席令第89号；2021-06-10通过 | [官方原文/尝试入口](https://fgk.chinatax.gov.cn/zcfgk/c100009/c5193058/content.html) | 成功，HTTP 200；第3/5/20条及税率表，附件图另核见下文 | 已验证 |
| F05 印花税：减半段 | 1‰×1/2=0.5‰=0.05%，卖方；买方0 | 2023-08-28起 | 《关于减半征收证券交易印花税的公告》；财政部、税务总局；财政部 税务总局公告2023年第39号；发布2023-08-27 | [官方原文/尝试入口](https://www.mof.gov.cn/jrttts/202308/t20230828_3904235.htm) | 成功，HTTP 200；公告写减半，0.05%由F04税率换算 | 已验证 |
| F06 过户费：2012年第一次下调 | 中国结算收取的沪市A股按成交面额0.5‰→0.375‰；深市按成交金额0.0255‰维持；双向口径结合F07核对 | 2012-06-01至2012-08-31；更早段起点未核 | 《关于调整A股交易过户费收费标准的通知》；中国证券登记结算有限责任公司；原文未列文号；落款2012-04-30 | [官方PDF](https://www.chinaclear.cn/old_files/1335773025208.pdf) | 成功，HTTP 200；1页PDF正文；沪市基数为面额，所列为中国结算收费部分，非含证券公司留存的全部历史实收 | 已验证 |
| F07 过户费：2012年第二次下调 | 中国结算在沪市向买卖双方各按成交面额0.375‰→0.3‰；深市按成交金额0.0255‰维持 | 2012-09-01至2015-07-31 | 《关于进一步调整A股交易过户费收费标准有关事项的通知》；中国证券登记结算有限责任公司；原文未列文号；落款2012-08-02 | [官方PDF](https://www.chinaclear.cn/old_files/1343899420865.pdf) | 成功，HTTP 200；1页PDF正文第1/2条；证券公司收取并留存的沪市过户费另同比下降20%，不将其与本行中国结算部分混同 | 已验证 |
| F08 过户费：统一金额计费 | 沪深A股统一按成交金额0.02‰=0.002%，买卖各收；替代沪市成交面值0.3‰、深市成交金额0.0255‰ | 2015-08-01至2022-04-28 | 《关于调整A股交易过户费收费标准有关事项的通知》；中国证券登记结算有限责任公司；页面未列文号；落款/发布2015-07-09 | [官方正文](https://www.chinaclear.cn/zdjs/gszb/201507/59ccd4176d2645f8b60b2d30fc3631bf.shtml) | 成功，HTTP 200；首段及第1条明确生效日、双向费率、证券经营机构不予留存；不用页面生成时间2023-05-08替代发文日 | 已验证 |
| F09 过户费：北市下调前（数值已核、起始日待补） | 北京市场A股/挂牌股份按成交金额0.025‰=0.0025%，买卖各收 | 2022-04-28通知列示的调整前标准；北市适用起始日未核，不外推为开市即适用 | 《中国结算关于降低股票交易过户费收费标准的通知》（调整前标准）；中国证券登记结算有限责任公司；页面未列文号；落款/发布2022-04-28 | 中国证券登记结算有限责任公司，《中国结算关于降低股票交易过户费收费标准的通知》，https://www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml，访问日期 2026-11-16 | 成功，HTTP 200，仅核到调整前数值；2021业务指南引用动态收费表，未给0.025‰及其起始日，完整历史段仍不晋级 | 未验证（起始日待补）；官方通知仅确认调整前数值 |
| F10 过户费：统一下调 | 沪深北A股/挂牌股份按成交金额0.01‰=0.001%，买卖各收；沪深由0.02‰、北市由0.025‰下调 | 2022-04-29起 | 《中国结算关于降低股票交易过户费收费标准的通知》；中国证券登记结算有限责任公司；页面未列文号；落款/发布2022-04-28 | [官方正文](https://www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml) | 成功，HTTP 200；原文明确生效日及沪深北统一双向费率；替换T-R75无法取得正文的另一URL | 已验证 |
| F11 上交所经手费：2012年第一次下调 | 成交金额0.11‰→0.087‰=0.0087%，买卖各收 | 2012-06-01至2012-08-31 | 《上海证券交易所调整部分收费标准的通知》；上海证券交易所；页面未列文号；发布2012-04-30 | [官方原文/尝试入口](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988543.shtml) | 成功，HTTP 200；历史段；双向口径与F12前标准衔接 | 已验证 |
| F12 上交所经手费：2012年第二次下调 | 成交金额0.087‰→0.0696‰=0.00696%，买卖各收 | 2012-09-01至2015-07-31 | 《关于上海证券交易所继续降低A股证券交易经手费标准的通知》；上海证券交易所；页面未列文号；发布2012-08-02 | [官方原文/尝试入口](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988591.shtml) | 成功，HTTP 200；历史段 | 已验证 |
| F13 上交所经手费：2015年下调 | 成交金额0.0696‰→0.0487‰=0.00487%，买卖各收 | 2015-08-01至2023-08-27 | 《沪、深证券交易所和中国证券登记结算公司负责人就降低A股交易结算收费标准答记者问》；上交所官网发布三方联合答问；无文号；发布2015-07-01 | [官方原文/尝试入口](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988866.shtml) | 成功，HTTP 200；明确8月1日实施；这是联合答问原文，未冒充单独收费通知 | 已验证 |
| F14 上交所经手费：2023年下调 | A股成交金额0.0487‰→0.0341‰=0.00341%，买卖各收 | 2023-08-28起 | 《上海证券交易所收费管理规则适用指引第1号——收费项目及标准（2023年8月修订）》；上海证券交易所；上证发〔2023〕137号，吸收136号调整；发布2023-08-18 | [官方原文/尝试入口](https://www.sse.com.cn/lawandrules/sselawsrules2025/charge/c/c_20250610_10781461.shtml) | 成功，HTTP 200；正式附件第3.1.1条另抓取核实；原136号旧链接404，改用现行137号原文 | 已验证 |
| F15 深交所经手费：2012年第一次下调 | 交易所部分按成交金额0.122‰→0.087‰=0.0087%，买卖各收；旧0.1475‰中另含中国结算0.0255‰ | 2012-06-01至2012-08-31 | 《深圳证券交易所关于调整部分收费标准的通知》；深圳证券交易所；页面未列文号；发布2012-04-30 | [官方原文/尝试入口](https://www.szse.cn/disclosure/notice/general/t20120429_500932.html) | 成功，HTTP 200；不能把含结算费的0.1475‰误当纯经手费 | 已验证 |
| F16 深交所经手费：2012年第二次下调 | 成交金额0.087‰→0.0696‰=0.00696%，买卖各收 | 2012-09-01至2015-07-31 | 《关于调整深圳市场A股交易经手费收费标准的通知》；深圳证券交易所；页面未列文号；发布2012-08-02 | [官方原文/尝试入口](https://www.szse.cn/aboutus/trends/news/t20120802_518315.html) | 成功，HTTP 200；双向口径与F17前标准衔接 | 已验证 |
| F17 深交所经手费：2015年下调 | A股成交金额0.0696‰→0.0487‰=0.00487%，买卖各收 | 2015-08-01至2023-08-27 | 《关于调整部分证券品种收费标准的通知》；深圳证券交易所；深证会〔2015〕233号；发布2015-07-29 | [官方原文/尝试入口](https://www.szse.cn/www/lawrules/rule/all/t20190326_565731.html) | 成功，HTTP 200；发布日期按正文，不按迁移URL中的20190326 | 已验证 |
| F18 深交所经手费：2023年下调 | A股成交金额0.0487‰→0.0341‰=0.00341%，买卖各收 | 2023-08-28起 | 《关于下调股票交易经手费收费标准的通知》；深圳证券交易所；深证上〔2023〕768号；发布2023-08-18 | [官方原文/尝试入口](https://www.szse.cn/disclosure/notice/t20230818_602805.html) | 成功，首次curl rc=28连接超时；网页读取成功，curl复抓HTTP 200 | 已验证 |
| F19 北交所经手费：开市段 | 普通股成交金额0.5‰=0.05%，买卖各收 | 2021-11-15至2022-11-30 | 《关于发布〈北京证券交易所业务收费管理办法〉的公告》及附表；北京证券交易所；北证公告〔2021〕49号；发布2021-11-12 | [官方业务规则正文](https://www.bse.cn/scgl_list/200011013.html) | 成功，HTTP 200；匿名Cookie配合curl -L跟随302后取得全文/附表；实施日期2021-11-15，页面标已被修改，仅用于本历史段 | 已验证 |
| F20 北交所经手费：2022年下调 | 成交金额0.5‰→0.25‰=0.025%，买卖各收 | 2022-12-01至2023-08-27 | 《关于下调交易经手费标准的公告》；北京证券交易所；北证公告〔2022〕37号；发布2022-11-18 | [官方业务规则正文](https://www.bse.cn/scgl_list/200013827.html) | 成功，HTTP 200；匿名Cookie配合curl -L取得正文收费表及实施日期；页面标已被修改，仅用于本历史段 | 已验证 |
| F21 北交所经手费：2023年下调 | 成交金额0.25‰→0.125‰=0.0125%，买卖各收 | 2023-08-28起 | 《关于下调股票交易经手费收费标准的通知》；北京证券交易所；北证公告〔2023〕54号；发布2023-08-18 | [官方业务规则正文](https://www.bse.cn/scgl_list/200018104.html) | 成功，HTTP 200；匿名Cookie配合curl -L取得正文收费表及实施日期；页面标现行有效 | 已验证 |
| F22 证管费：沪深降费 | 股票成交金额0.04‰→0.02‰=0.002%；清算按买卖各边核算 | 2012-01-01起；2012-09-01调整清算参数，1至8月多收部分另退 | 《关于调整上海证券市场证券交易监管费收费标准的通知》；上海证券交易所、中国结算上海分公司；收费主体为中国证监会；页面未列本通知文号；引用会计部函〔2012〕403号转发发改价格〔2012〕2119号 | [官方原文/尝试入口](https://www.sse.com.cn/lawandrules/guide/other/c/c_20230116_5312163.shtml) | 成功，HTTP 200；只确认该次降费原文和日期，不把清算调整日当生效日 | 已验证 |
| F23 证管费：北市纳入及收费标准 | 中国证监会向北京证券交易所按股票交易额0.02‰=0.002%收取；现行清单写股票年交易额；投资者按边代收另须结合费表/协议 | 自北交所开市日2021-11-15起纳入；不把2021年12月政策落款日或2022年公示日当纳入日 | 《财政部 发展改革委关于证券期货业、银行业和保险业监管费有关问题的通知》财税〔2021〕65号（2021-12-02）；《国家发展改革委 财政部关于银行业、保险业和证券期货业监管费收费标准有关问题的通知》发改价格〔2021〕1947号（2021-12-30）；沪深基准见发改价格规〔2018〕917号；《中国证监会及下属单位综合性涉企收费目录清单》由中国证券监督管理委员会发布，无文号 | [财政部65号正文](https://szs.mof.gov.cn/zt/mlqd_8464/zcgd/202112/t20211214_3774393.htm)、[发改委1947号正文](https://www.ndrc.gov.cn/xwdt/tzgg/202201/t20220107_1311591.html)、[917号正文](https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/201806/t20180627_960950.html)；清单PDF及开市日证据见§5.2 | 均成功，HTTP 200；65号第1条自开市日起纳入，1947号第2条按沪深同标准，917号第1（一）条0.02‰；证监会PDF第1页另核沪深北同费率 | 已验证 |
| F24 佣金上限（背景） | 证券交易金额3‰=0.3%为上限；包含代收证管费及交易所手续费，非实际费率 | 2002-05-01起；文件级适用状态见下文 | 《关于调整证券交易佣金收取标准的通知》；中国证监会、国家发展计划委员会、国家税务总局；证监发〔2002〕21号；发布2002-04-04 | [官方原文/尝试入口](https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/200202/c1209808/content.html) | 成功，HTTP 200；第1/6/8条；仅验证监管上限背景，不验证用户协议 | 已验证 |
| F25 最低佣金（用户协议参数） | 实际最低额以用户券商为准；历史文件为A股每笔不足5元按5元收取，5元不晋级卡参数 | 历史规定2002-05-01起；用户协议生效日、实际最低额未核 | 《关于调整证券交易佣金收取标准的通知（历史起点5元背景）》；中国证监会、国家发展计划委员会、国家税务总局；证监发〔2002〕21号；不是用户协议 | [官方原文/尝试入口](https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/200202/c1209808/content.html) | 官方历史正文成功，HTTP 200；实际协议未读取/未验证 | 以用户券商为准、未验证 |

### 5.2 附件、失败尝试与出处更正

- F04税率附件：税务总局广东站所载[《中华人民共和国印花税法》全文](https://guangdong.chinatax.gov.cn/gdsw/zjfg/2023-03/06/content_1f02a0e8bc254856aa0cc68a8cae0c74.shtml)及[税率表第二页图片](https://guangdong.chinatax.gov.cn/gdsw/zjfg/2023-03/06/1f02a0e8bc254856aa0cc68a8cae0c74/images/20211126154316_0.jpg)均HTTP 200；实际打开图片确认证券交易为「成交金额的千分之一」。不是从网页上传日期推导生效日。
- F13联合答问为2015-07-01的拟实施口径；另抓取上交所[《减费降负促活力 上交所减免部分项目收费》](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20180731_4604157.shtml)，HTTP 200，其2018-07-31原文回顾明确2012-06-01为0.0087%、2012-09-01为0.00696%、2015-08-01为0.00487%，据此核对实际历史衔接，不单凭拟调整答问确认实施。
- F14正式附件：[2023年8月收费指引DOCX](https://www.sse.com.cn/lawandrules/sselawsrules2025/charge/c/10781461/files/6ead9e7d60e14272a19cd75b622dd2ef.docx)HTTP 200，解包读取第3.1.1条确认A股竞价按0.00341%双向收取；[136号原旧链接](https://www.sse.com.cn/lawandrules/sselawsrules/charge/c/c_20230818_5725373.shtml)HTTP 404，因此更正为137号正文及其附件，另以[上交所原发布新闻](https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20230818_5725378.shtml)核对0.00487%→0.00341%，不把新闻标题写成通知标题。
- T-R76从中国结算[通知公告目录](https://www.chinaclear.cn/zdjs/xtzgg/center_flist.shtml)进入分页，2012年两通知分别直接链接至F06/F07的官方PDF。F06英文站附件也取得HTTP 200，但英文将沪市基数写成“trading value”，故基数以中文PDF的「成交面额」为准。F06/F07只验证中国结算收费部分；2012年第二份通知另明定证券公司留存部分同比下调，不能把表内单项直接当完整历史实收。
- F08/F10由官方目录重新定位到表中正文，均HTTP 200；T-R75使用的2015/2022另一组URL仍重定向首页后500。新正文未列文号，按「页面未列文号」记录，不用转载补猜。F08正文和目录均给2015-07-09，忽略迁移生成时间；F10确认为2022-04-28发文、4月29日起执行。
- F09仅补齐0.025‰双向的调整前数值；[2021年北交所登记结算业务指南发布通知](https://www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea.shtml)及其[官方附件](https://www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea/files/20211102171747707.pdf)均HTTP 200，通知定2021-11-15施行，但附件第六章仅引用官网动态收费表，不能据此推定0.025‰的适用起点。[2021年部分业务规则修订通知](https://www.chinaclear.cn/zdjs/gszb/202110/4d4cde3008f141a29e76def19a80b57f.shtml)及其附件也未补出该起点；当前收费表已更新为0.01‰。因此F09整段仍为「未验证（官方原文待补）」，不伪称数值仍未取到。
- F19/F20/F21先以浏览器UA重试仍有302循环，curl UA则403；改为浏览器UA、启用新建匿名Cookie会话并以`curl -L --tlsv1.2`跟随302后，三份业务规则正文均HTTP 200，实际读取元数据、正文及收费表。F20/F21改链至业务规则栏目，不再只依赖新闻页或搜索索引；F19/F20的「已被修改」与历史段验证不冲突。
- F23的[证监会官方收费清单PDF](https://www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/%E4%B8%AD%E5%9B%BD%E8%AF%81%E7%9B%91%E4%BC%9A%E5%8F%8A%E4%B8%8B%E5%B1%9E%E5%8D%95%E4%BD%8D%E7%BB%BC%E5%90%88%E6%80%A7%E6%B6%89%E4%BC%81%E6%94%B6%E8%B4%B9%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf)本轮以浏览器UA、`curl -L --tlsv1.2`取得HTTP 200；PDF为5页图像，渲染查看第1页，确认向沪深北按股票年交易额0.02‰收取及所引政策。65号/1947号/917号正文也均HTTP 200，构成纳入时间及数值的证据链；[证监会《对十三届全国人大五次会议第7147号建议的答复》](https://www.csrc.gov.cn/csrc/c101800/c7161925/content.shtml)HTTP 200确认北交所于2021-11-15开市。[北京市政府政策库的1947号全文](https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202202/t20220228_2617699.html)也HTTP 200。纳入日期来自“自开市之日”，不是从清单发布日期倒推。
- F24/F25[税务总局公报正文](https://www.chinatax.gov.cn/chinatax/n810341/n810765/n812203/200202/c1209808/content.html)HTTP 200，核到第1条上限3‰及起点5元、第6条券商自行制定标准、第8条2002-05-01起执行；[证监会法规库](https://neris.csrc.gov.cn/falvfagui/rdqsHeader/mainbody?navbarId=2&secFutrsLawId=b25a17fb262742f2aea99515380cf3bb)HTTP 200，元数据明确文件级「现行有效」，发文日2002-04-04、实施日2002-05-01、失效日期空。正文包含动态模板，未用模板确认条文；条文以税务总局公报为准。不能将文件误写成已整体失效，也不能用文件级有效推定用户当前5元实收已核实。

原出处更正记录：四卡历史印花税原只指向T-R58 §5 R6，现补F04的官方全文/附件，0.1%不变；减半段补财政部2023年第39号的财政部原页，0.05%不变。原过户费借T-R58 §5 R7的非本次认可域名转载交叉核对，T-R75已撤销该依据及状态；T-R76以F10中国结算官方通知重新验证0.001%及2022-04-29生效，恢复四卡对应行状态。原最低佣金把历史规定视为实际收费制度固定值，现撤销该状态，改为「以用户券商为准、未验证」；5元只保留历史背景/待验证压力档。经手费、证管费、佣金上限原§2未单列，本节补制度证据，不声称原卡已实现这些分段。

### 5.2.1 T-R76逐URL请求记录

以下为本轮实际发出的全部curl请求，按URL合并重复UA重试；B=Chrome浏览器UA，C=curl/8.0，K=Mozilla/5.0并启用本轮新建匿名Cookie会话。均使用`-L --tlsv1.2`，最多跟随8次重定向，不携带账户鉴权。HTTP 200仅表示取得响应，目录、脚本、当前费表和大事记不自动成为历史制度证据。000表示未取得HTTP响应；rc=35为TLS意外EOF，rc=47为302循环达到重定向上限。

| URL | UA与HTTP/rc（各次结果） | 正文用途或失败原因 |
|---|---|---|
| [szs.mof.gov.cn/zt/mlqd_8464/zcgd/202112/t20211214_3774393.htm](http://szs.mof.gov.cn/zt/mlqd_8464/zcgd/202112/t20211214_3774393.htm) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [www.chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml](http://www.chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml](https://chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml) | B: HTTP 000 / rc=35 | TLS握手意外EOF |
| [www.chinaclear.cn/english/](https://www.chinaclear.cn/english/) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml](https://www.chinaclear.cn/zdjs/gszb/202204/f89e788c65a241e88e7f0d0348de586f.shtml) | B: HTTP 500 / rc=0；C: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.bse.cn/scgl_list/200011013.html](http://www.bse.cn/scgl_list/200011013.html) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202202/t20220228_2617699.html](https://www.beijing.gov.cn/zhengce/zhengcefagui/qtwj/202202/t20220228_2617699.html) | B: HTTP 200 / rc=0 | 政府政策库1947号全文 |
| [www.bse.cn/scgl_list/200011013.html](https://www.bse.cn/scgl_list/200011013.html) | B: HTTP 302 / rc=47；C: HTTP 403 / rc=0；K: HTTP 200 / rc=0 | 302重定向循环，未取得正文；访问被拒，未取得正文；F19正文、附表及实施日期 |
| [www.bse.cn/important_news/200013817.html](http://www.bse.cn/important_news/200013817.html) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [www.chinaclear.cn/zdjs/gszb/201507/9aeee4d21a6f47f5b3741637993b004b.shtml](https://www.chinaclear.cn/zdjs/gszb/201507/9aeee4d21a6f47f5b3741637993b004b.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.bse.cn/important_news/200018086.html](https://www.bse.cn/important_news/200018086.html) | B: HTTP 302 / rc=47；C: HTTP 403 / rc=0 | 302重定向循环，未取得正文；访问被拒，未取得正文 |
| [www.bse.cn/important_news/200018086.html](http://www.bse.cn/important_news/200018086.html) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [bse.cn/scgl_list/200011013.html](https://bse.cn/scgl_list/200011013.html) | B: HTTP 000 / rc=35 | TLS握手意外EOF |
| [www.bse.cn/important_news/200013817.html](https://www.bse.cn/important_news/200013817.html) | B: HTTP 302 / rc=47；C: HTTP 403 / rc=0 | 302重定向循环，未取得正文；访问被拒，未取得正文 |
| [www.chinaclear.cn/zdjs/](https://www.chinaclear.cn/zdjs/) | B: HTTP 200 / rc=0 | 公开栏目/正文辅助定位，不单独证明历史费率 |
| [szs.mof.gov.cn/zt/mlqd_8464/zcgd/202112/t20211214_3774393.htm](https://szs.mof.gov.cn/zt/mlqd_8464/zcgd/202112/t20211214_3774393.htm) | B: HTTP 200 / rc=0 | F23自开市日起征收 |
| [bse.cn/important_news/200013817.html](https://bse.cn/important_news/200013817.html) | B: HTTP 000 / rc=35 | TLS握手意外EOF |
| [www.neeq.com.cn/](https://www.neeq.com.cn/) | B: HTTP 200 / rc=0 | 公开栏目/正文辅助定位，不单独证明历史费率 |
| [bse.cn/important_news/200018086.html](https://bse.cn/important_news/200018086.html) | B: HTTP 000 / rc=35 | TLS握手意外EOF |
| [www.chinaclear.cn/zdjs/wywtz/service_flist.shtml](https://www.chinaclear.cn/zdjs/wywtz/service_flist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/fywgz/law_flist.shtml](https://www.chinaclear.cn/zdjs/fywgz/law_flist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml](https://www.chinaclear.cn/zdjs/fbzyls/service_tlist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/english/anno/media_list.shtml](https://www.chinaclear.cn/english/anno/media_list.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.neeq.com.cn/important_news/200013817.html](https://www.neeq.com.cn/important_news/200013817.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.bse.cn/fee.html](https://www.bse.cn/fee.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.bse.cn/business_rules.html](https://www.bse.cn/business_rules.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.neeq.com.cn/m/important_news/200013817.html](https://www.neeq.com.cn/m/important_news/200013817.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.chinaclear.cn/zdjs/yfzywgz/law_flist.shtml](https://www.chinaclear.cn/zdjs/yfzywgz/law_flist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/english/005/legal_tlist.shtml](https://www.chinaclear.cn/english/005/legal_tlist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.neeq.com.cn/scgl_list/200011013.html](https://www.neeq.com.cn/scgl_list/200011013.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.neeq.com.cn/important_news/200018086.html](https://www.neeq.com.cn/important_news/200018086.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.chinaclear.cn/zdjs/dsj/about_dsj.shtml](https://www.chinaclear.cn/zdjs/dsj/about_dsj.shtml) | B: HTTP 200 / rc=0 | 公司大事记；不代替制度通知 |
| [www.bse.cn/m/scgl_list/200011013.html](https://www.bse.cn/m/scgl_list/200011013.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.bse.cn/scgl_list/200013827.html](https://www.bse.cn/scgl_list/200013827.html) | B: HTTP 302 / rc=47；K: HTTP 200 / rc=0 | 302重定向循环，未取得正文；F20正文、费表及实施日期 |
| [www.bse.cn/m/important_news/200018086.html](https://www.bse.cn/m/important_news/200018086.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.bse.cn/scgl_list/200018104.html](https://www.bse.cn/scgl_list/200018104.html) | B: HTTP 302 / rc=47；K: HTTP 200 / rc=0 | 302重定向循环，未取得正文；F21正文、费表及实施日期 |
| [www.bse.cn/scgl_list/200011013.html?from=rules](https://www.bse.cn/scgl_list/200011013.html?from=rules) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.bse.cn/m/important_news/200013817.html](https://www.bse.cn/m/important_news/200013817.html) | B: HTTP 302 / rc=47 | 302重定向循环，未取得正文 |
| [www.chinaclear.cn/zdjs/xhtml/js/page.js](https://www.chinaclear.cn/zdjs/xhtml/js/page.js) | B: HTTP 200 / rc=0 | 网页导航/分页辅助脚本，不是费率证据 |
| [www.chinaclear.cn/zdjs/xhtml/js/service.js](https://www.chinaclear.cn/zdjs/xhtml/js/service.js) | B: HTTP 200 / rc=0 | 网页导航/分页辅助脚本，不是费率证据 |
| [www.chinaclear.cn/english/xhtml/js/media.js](https://www.chinaclear.cn/english/xhtml/js/media.js) | B: HTTP 404 / rc=0 | 该候选资源不存在 |
| [www.chinaclear.cn/english/005/legal_tlist/code_0.shtml](https://www.chinaclear.cn/english/005/legal_tlist/code_0.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.chinaclear.cn/zdjs/wywtz/service_flist/code_0.shtml](https://www.chinaclear.cn/zdjs/wywtz/service_flist/code_0.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.chinaclear.cn/english/anno/media_list/code_0.shtml](https://www.chinaclear.cn/english/anno/media_list/code_0.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_0.shtml](https://www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_0.shtml) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文；302→500，最终 http://www.chinaclear.cn/ |
| [www.chinaclear.cn/zdjs/fbzyls/service_tlist/code_0.shtml](https://www.chinaclear.cn/zdjs/fbzyls/service_tlist/code_0.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/中国证监会及下属单位综合性涉企收费目录清单.pdf](http://www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/%E4%B8%AD%E5%9B%BD%E8%AF%81%E7%9B%91%E4%BC%9A%E5%8F%8A%E4%B8%8B%E5%B1%9E%E5%8D%95%E4%BD%8D%E7%BB%BC%E5%90%88%E6%80%A7%E6%B6%89%E4%BC%81%E6%94%B6%E8%B4%B9%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf) | B: HTTP 500 / rc=0 | 服务器错误，未取得目标正文 |
| [csrc.gov.cn/csrc/c101982/c7572057/7572057/files/中国证监会及下属单位综合性涉企收费目录清单.pdf](https://csrc.gov.cn/csrc/c101982/c7572057/7572057/files/%E4%B8%AD%E5%9B%BD%E8%AF%81%E7%9B%91%E4%BC%9A%E5%8F%8A%E4%B8%8B%E5%B1%9E%E5%8D%95%E4%BD%8D%E7%BB%BC%E5%90%88%E6%80%A7%E6%B6%89%E4%BC%81%E6%94%B6%E8%B4%B9%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf) | B: HTTP 000 / rc=35 | TLS握手意外EOF |
| [www.csrc.gov.cn/csrc/c101982/c7572057/content.shtml](https://www.csrc.gov.cn/csrc/c101982/c7572057/content.shtml) | B: HTTP 200 / rc=0 | 公开栏目/正文辅助定位，不单独证明历史费率 |
| [www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/中国证监会及下属单位综合性涉企收费目录清单.pdf?download=1](https://www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/%E4%B8%AD%E5%9B%BD%E8%AF%81%E7%9B%91%E4%BC%9A%E5%8F%8A%E4%B8%8B%E5%B1%9E%E5%8D%95%E4%BD%8D%E7%BB%BC%E5%90%88%E6%80%A7%E6%B6%89%E4%BC%81%E6%94%B6%E8%B4%B9%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf?download=1) | B: HTTP 200 / rc=0 | 同一F23清单PDF参数变体 |
| [www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/中国证监会及下属单位综合性涉企收费目录清单.pdf](https://www.csrc.gov.cn/csrc/c101982/c7572057/7572057/files/%E4%B8%AD%E5%9B%BD%E8%AF%81%E7%9B%91%E4%BC%9A%E5%8F%8A%E4%B8%8B%E5%B1%9E%E5%8D%95%E4%BD%8D%E7%BB%BC%E5%90%88%E6%80%A7%E6%B6%89%E4%BC%81%E6%94%B6%E8%B4%B9%E7%9B%AE%E5%BD%95%E6%B8%85%E5%8D%95.pdf) | B: HTTP 200 / rc=0 | F23清单PDF第1页，沪深北0.02‰ |
| [www.chinaclear.cn/english/anno/media_list/code_1.shtml](https://www.chinaclear.cn/english/anno/media_list/code_1.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/wywtz/service_flist/code_1.shtml](https://www.chinaclear.cn/zdjs/wywtz/service_flist/code_1.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/english/005/legal_tlist/code_1.shtml](https://www.chinaclear.cn/english/005/legal_tlist/code_1.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_1.shtml](https://www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_1.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.ndrc.gov.cn/xxgk/zcfb/ghxwj/201806/t20180627_960950.html](https://www.ndrc.gov.cn/xxgk/zcfb/ghxwj/201806/t20180627_960950.html) | B: HTTP 200 / rc=0 | F23所接沪深标准0.02‰ |
| [www.ndrc.gov.cn/xwdt/tzgg/202201/t20220107_1311591.html](https://www.ndrc.gov.cn/xwdt/tzgg/202201/t20220107_1311591.html) | B: HTTP 200 / rc=0 | F23沪深北同标准 |
| [www.chinaclear.cn/zdjs/fbzyls/202512/cbcf7d603e7444b382ce7ca8017105b8/files/北京市场证券登记结算业务收费及代收税费一览表.pdf](https://www.chinaclear.cn/zdjs/fbzyls/202512/cbcf7d603e7444b382ce7ca8017105b8/files/%E5%8C%97%E4%BA%AC%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf) | B: HTTP 200 / rc=0 | 现行北市过户费0.01‰；不证明F09历史起始 |
| [www.chinaclear.cn/zdjs/fbzyls/202512/922adc26c2ff4865930c7fb77688bb8a/files/上海市场证券登记结算业务收费及代收税费一览表.pdf](https://www.chinaclear.cn/zdjs/fbzyls/202512/922adc26c2ff4865930c7fb77688bb8a/files/%E4%B8%8A%E6%B5%B7%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf) | B: HTTP 200 / rc=0 | 现行沪市收费表，不倒推历史起始 |
| [www.chinaclear.cn/zdjs/fbzyls/202512/a59388fbfa714c5fa546784891a42e30/files/深圳市场证券登记结算业务收费及代收税费一览表.pdf](https://www.chinaclear.cn/zdjs/fbzyls/202512/a59388fbfa714c5fa546784891a42e30/files/%E6%B7%B1%E5%9C%B3%E5%B8%82%E5%9C%BA%E8%AF%81%E5%88%B8%E7%99%BB%E8%AE%B0%E7%BB%93%E7%AE%97%E4%B8%9A%E5%8A%A1%E6%94%B6%E8%B4%B9%E5%8F%8A%E4%BB%A3%E6%94%B6%E7%A8%8E%E8%B4%B9%E4%B8%80%E8%A7%88%E8%A1%A8.pdf) | B: HTTP 200 / rc=0 | 现行深市收费表，不倒推历史起始 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_1_31.shtml](https://www.chinaclear.cn/zdjs/yfzywgz/law_flist/code_1_31.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/editor_file/20130807152120317.pdf](https://www.chinaclear.cn/zdjs/editor_file/20130807152120317.pdf) | B: HTTP 200 / rc=0 | F06英文通知；面额基数仍以中文为准 |
| [www.csrc.gov.cn/csrc/c101800/c7161925/content.shtml](https://www.csrc.gov.cn/csrc/c101800/c7161925/content.shtml) | B: HTTP 200 / rc=0 | 开市日2021-11-15 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_25.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_25.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_55.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_55.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_40.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_40.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/gszb/center_list.shtml](https://www.chinaclear.cn/zdjs/gszb/center_list.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/gszb/center_list/code_2.shtml](https://www.chinaclear.cn/zdjs/gszb/center_list/code_2.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_14.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_14.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_33.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_33.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/old_files/1343899420865.pdf](https://www.chinaclear.cn/old_files/1343899420865.pdf) | B: HTTP 200 / rc=0 | F07中文通知PDF |
| [www.chinaclear.cn/old_files/1335773025208.pdf](https://www.chinaclear.cn/old_files/1335773025208.pdf) | B: HTTP 200 / rc=0 | F06中文通知PDF |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_16.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_16.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_32.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_32.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_31.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_31.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_15.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_15.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml](https://www.chinaclear.cn/zdjs/gszb/202204/837e3c5031104aa099d6597ba381342a.shtml) | B: HTTP 200 / rc=0 | F09调整前数值、F10新标准及生效日；F09起始未给 |
| [www.chinaclear.cn/zdjs/gszb/201507/59ccd4176d2645f8b60b2d30fc3631bf.shtml](https://www.chinaclear.cn/zdjs/gszb/201507/59ccd4176d2645f8b60b2d30fc3631bf.shtml) | B: HTTP 200 / rc=0 | F08正文及发文/生效日 |
| [www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_18.shtml](https://www.chinaclear.cn/zdjs/xtzgg/center_flist/code_1_18.shtml) | B: HTTP 200 / rc=0 | 官方栏目/分页，用于定位；不凭目录晋级 |
| [www.chinaclear.cn/zdjs/gszb/202110/4d4cde3008f141a29e76def19a80b57f.shtml](https://www.chinaclear.cn/zdjs/gszb/202110/4d4cde3008f141a29e76def19a80b57f.shtml) | B: HTTP 200 / rc=0 | 2021修订通知，未给F09费率起始 |
| [www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea.shtml](https://www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea.shtml) | B: HTTP 200 / rc=0 | 2021指南发布通知，未给F09费率起始 |
| [www.chinaclear.cn/zdjs/gszb/202110/4d4cde3008f141a29e76def19a80b57f/files/20211030215050662.pdf](https://www.chinaclear.cn/zdjs/gszb/202110/4d4cde3008f141a29e76def19a80b57f/files/20211030215050662.pdf) | B: HTTP 200 / rc=0 | 2021修订条款未补F09费率起始 |
| [www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea/files/20211102171747707.pdf](https://www.chinaclear.cn/zdjs/bjsjjsfgs/202110/662502f2ba8a4867bb284509fb88f9ea/files/20211102171747707.pdf) | B: HTTP 200 / rc=0 | 2021指南仅引用动态收费表，未列F09起始 |

网页读取工具另尝试F19/F20/F21旧原页，均报重定向循环；财政部65号网页读取先报超时，随后上表curl取得200。T-R75失败记录不等同于本轮仍失败；本轮成功须以正文核读为准。

### 5.3 成本模型边界与计数

佣金不得重复记费：证监发〔2002〕21号的佣金口径包括代收证管费、交易所手续费；若输入含规费佣金，不再叠加相同经手费和证管费。若输入净佣金，须先冻结券商协议的含费范围、最低额作用对象与按边计收口径，再拆分核算，不能把法规上限当推荐费率。0.015%/0.025%/0.03%均为未验证的仓内研究参考档（仓内定义：docs/strategies/T-R58/retest_plan.md:210；适用性未验证（待复测）），无统一制度原文或生效日；实际佣金费率和最低额按用户券商协议，仍未冻结，不读取账户/协议验证。

滑点10/10/10/15bp（S-01/S-02/S-04/W-02）、0–50bp压力范围、ADV20、参与率≤0.1%/≤0.5%/≤1%/≤2%/>2%对应0/5/15/30/60bp、参与率>2%容量闸门、有效K<5或ADV=0回退60bp，均是内部交易成本模型参数，没有官方制度生效日；仅有仓内定义（仓内定义：docs/strategies/cards/st_pullback_ma.md:104；仓内定义：docs/strategies/T-R16/S-02_st_oversold_rebound.md:74；仓内定义：docs/strategies/T-R16/S-04_st_broken_board.md:69；仓内定义：docs/strategies/T-R16/W-02_sw_breakout.md:71；仓内定义：docs/strategies/_template.md:253；仓内定义：docs/strategies/_template.md:258；仓内定义：docs/strategies/_template.md:259；仓内定义：docs/strategies/_template.md:260；仓内定义：docs/strategies/_template.md:261；仓内定义：docs/strategies/_template.md:262；仓内定义：docs/strategies/_template.md:267），保留§2的成本校准未验证（待复测）状态，不能通过补税费原文升级。

逐卡309项计数仅按§2七列表参数行：S-01为78项/已验证13/未验证65，S-02为77/13/64，S-04为71/13/58，W-02为83/13/70；相对T-R75，合计已验证48→52、未验证261→257，仅四卡各1项现段过户费恢复验证。最低佣金的「以用户券商为准、未验证」及带待补后缀的状态均计入未验证。§5单列25项历史段/背景，已验证15→23、未验证10→2：F06/F07/F08/F10/F19/F20/F21/F23共8行升级，F09起始日和F25实际最低佣金未验证；与309项不同计数边界，不能相加冒充四卡参数总数。

本轮只修订本文件，不增删策略身份、范围文件或horizon，P2N-R10已登记本路径且不存上述参数计数，因此无需同步登记。任何费率原文补齐后也仍需按真实成交日和券商协议冻结费用，并完成历史样本外研究；本轮不运行行情复测。

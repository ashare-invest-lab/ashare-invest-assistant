# T-R71｜S-02 短线·超跌企稳反弹候选草稿

## 0. 定位与使用边界

lifecycle: draft。当前状态：不可导入。按 docs/strategies/_template.md §0–§24 编排为文字研究草稿，不使用正式导入围栏。仅收敛既有卡，不登记新策略版本，不替换源卡。所有规则均待复测，输出统一称“候选信号”。 G7：☐。

## 1. 身份

研究引用 key：`st_oversold_rebound`；card_id：S-02；category：momentum；horizons：[short]；risk_level：normal；mount_policy：user（仅未来设计）。来源：docs/strategies/T-R16/S-02_st_oversold_rebound.md §1。本稿版本仅为 T-R71 草稿，不填可导入 version_no。

## 2. 来源

内部思想来源：docs/strategies/T-R16/S-02_st_oversold_rebound.md §3、§7、§22；kind：internal；license_status：idea_only；许可证与外部文献核实状态：待核实，不复用外部代码。目录交叉核对：docs/strategies/catalog.md §3 S-02。本轮没有新增策略机制，因此不补造公开出处。

## 3. 假设、反证与维度

短期下跌且 RSI 曾超卖的股票，收盘收复前日高点可能表示抛压暂缓。熊市中的反弹可能继续下跌，收盘企稳也可能仅是一日噪声。必须检验企稳条件和环境否决是否有增量。

沿原稿 §3：信号后 3 日扣费超额中位数不为正；企稳组与未企稳组没有差异；下行与震荡环境的胜率相同。基准及未知环境样本要单列。

编排者 11-14 裁定：主基准为沪深300（000300），辅基准为中证全指（000985），接口依据为团队报告 T-R72 §7 B11；基准选择已确定，数据接入与覆盖仍未验证。行业超额待 B12 接入后使用申万一级；在历史成员与对应行业收益齐备并核验前，所有行业超额相关项一律标“未验证”，大盘超额不能代替原行业超额证伪。

维度：technical/core；sector_market/veto（F25，含市场宽度）。epistemic：机制和 §22 全部策略参数为 hypothesis，滑点与冲击为 estimate；原始数据、规则是否命中为 fact。参数有出处不代表有效性得到验证。

## 4. 标的范围

沪深主板、创业板、科创板；上市天数和 20 日均额门槛见 §22。 ST、退市整理、停牌、北交所、新股与状态未知的处理见 §17。没有历史行业分类，不做行业内选股或行业分散的隐含假设。

## 5. 数据需求

所有决策数据截点为北京时间 T 日收盘；日线以北京时间 17:10 后确认的定稿版本为准，信号生成时点不早于 17:10 且不早于实际定稿与全部依赖就绪时点；17:10 只是预计完成时间，不能代替数据就绪检查（团队报告 T-R72 §7 A02）。任一输入包含 T 后行情或 T 后才可见的事件则拒绝该输入；保留 data_as_of、available_at、fetched_at、source、因子版本及快照标识。历史回填不能伪装为当时已在线取得的快照。

| 输入/字段或派生键 | 频率 | 复权与单位 | 预热/用途 | 出处与就绪度 |
|---|---|---|---|---|
| code、trade_date、open/high/low/close、volume、amount、pre_close、is_suspended、source | daily | 输入 none；价格元、volume 股、amount 元 | 本卡 30 根有效日 K；字段到齐后可得 | market.daily_bars（任务数据契约）；tdx hsjday 仅在源适配与校验完成后作对照，不能覆盖缺失标记 |
| f.rsi14、f.close_qfq、f.low_qfq、f.high_qfq；f.amount、f.amount_20d_avg；f.market_regime（F25）。RSI 按 Wilder 固定起点重算。 | daily | 计算价格 qfq@as_of（B08 权息事件逐日复权）；额 none；状态 none；字段名口径见下文 | 本卡预热见 §22；环境另需指数预热 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §5、§7；部分可派生，尚未复测 |
| gbbq 权息事件及因子版本 | event，按 T 截断 | 价格转换为 qfq@as_of（B08 权息事件逐日复权）；额量不复权 | 覆盖指标起点至 T；不固定猜事件根数 | docs/strategies/feature_spec.md §1.3；事件可见时点、复杂公司行为与源一致性待验证 |
| 上市日、ST 生效区间、上市状态/退市整理区间、终止名单及交易日历 | event/daily | none | 上市年龄按交易日历；状态须覆盖所有决策日 | docs/strategies/T-R65/README.md §①、§②、§③；仅已知子集，unknown 剔除且计数 |
| 主基准沪深300（000300）及辅基准中证全指（000985）OHLC/收盘 | daily | none | F50 为61根；F25整体预热待复测，见 docs/strategies/T-R71/README.md §6 共用参数登记 | 团队报告 T-R72 §7 B11；接口及 tdx 对照的接入/覆盖未验证；本轮不调用接口 |
| hf-1min（2022 年起）、tdx-min 的时间、OHLC、volume、amount、source | 1m，可选校验 | none | 不参与入场预热；仅≤T 已收完 bar 可校验伪停牌，执行回放与决策输入隔离 | 本次不把分钟覆盖假定为全市场可交易性证明；源适配待验证 |

团队报告 T-A159「*_qfq 口径裁定」及条件 C1：以晚于信号日（如最新日）为锚的前复权仅可用于展示，不得用于候选信号或回测。*_qfq 指 qfq@as_of：以信号日 T 为锚、逐日重算、只用当时可见且已生效的权息因子，等同团队报告 T-R72 §7 B08 权息事件逐日复权，可用于候选信号、指标与回测，字段名不改。历史日 d 的价格为 raw(d)×A(d)/A(T)，T 日值等于不复权价；因子事件日期须≤T 且 available_at≤as_of，缺因子记缺口，不补 1。回测须每个历史 T 独立调用 prepare 或等价重算，不得复用末日锚定序列、拼接不同锚点末值算指标，或用后续修订的因子回写过去候选信号。同一因子版本下，固定基准 hfq 与 qfq@T 仅差正比例常数，比值、均线和结构位同尺度比较等价；绝对元价阈值（如低于 2 元）、一字板与涨跌停价一律用不复权价（none）。收盘、均线、入场价和结构止损/止盈阈值按同一 qfq@T 尺度比较。成交及费用按实际不复权价记账；入场价折算后用于同尺度比较，R 统计仍须核验现金分红、送转股数、持仓权重及费用账本，不直接混减复权价差与不复权每股费用。冻结 source、因子版本及旧快照；事件可见性或复杂权息证据缺失时标“未验证”并阻断相关求值。

字段口径依据团队报告 T-A159：保留 f.*_qfq、plan.entry_price_qfq、ctx.cost_price_qfq、ctx.highest_close_since_entry_qfq 等现有名称，均按 qfq@as_of 使用；成交日价格按 A(成交日)/A(T) 折算。plan.stop_loss_qfq、plan.breakout_level_qfq 的 QFQ-1/QFQ-2 派生尚未实现，持久化与换算要求见三张相关卡的 §7、§9；字段口径裁定不代表派生已经实现。

S-02/S-04/W-02 的 amount_20d_avg 按 feature_spec 的交易日窗口，不能偷换为 S-01 的最近有效 K 均额。F01 的 15 根覆盖门槛、F11 的 15 根及任一涨停价未知则整段 null、F32 的 90 个带宽值等边界均沿 docs/strategies/feature_spec.md §F01、§F11、§F32；覆盖边界出处已证实（docs/strategies/feature_spec.md:121；docs/strategies/feature_spec.md:215；docs/strategies/feature_spec.md:389；docs/strategies/feature_spec.md:53）；建议阈值的 A 股有效性仍未验证（待复测），见 README §6。关键字段缺失不填零、不前值填充，不生成可执行计划。

## 数据接口依赖（T-R72 P1 对照）

逐项对照 B01–B12，共 12 条（含不依赖/可选项），不表示 12 项均为入场必需。路径仅是后端接入建议；本轮只读团队报告，不调用接口。“我方现状”限本卡与 README 已有证据，给定输入或已有探针均不等于已入库；无法确认的链路/覆盖写“未验证”。

| 依赖项 | 麦蕊接口（路径模板，licence 写 `<LICENCE>`） | 对应 T-R72 编号（B0x/A0x） | 我方现状（已入库/部分/未接，依据） | 缺失时的降级或失效后果 |
|---|---|---|---|---|
| 北交所历史：不依赖 | `/bj/history/{code}.BJ/{period}/{adj}/<LICENCE>?st={ST}&et={ET}` | 团队报告 T-R72 §7 B01；团队报告 T-R72 §7 A33 | 未接：本卡 §4、§17 排除北交所；本轮未验证接口覆盖 | 不依赖：入场池及 F24 宽度池均排除北交所（本卡 §6、README §3 所引 feature_spec §F24）。hslt 仅 sh/sz，不能据其推断京市覆盖；未来扩池须另接 B01 并审计旧新码。 |
| 沪深全历史日线/复权：规则必需 | `/hsstock/history/{code}.{market}/{period}/{adj}/<LICENCE>` | 团队报告 T-R72 §7 B02；团队报告 T-R72 §7 A02；团队报告 T-R72 §7 A20 | 部分：本卡 §5、README §3 只给定 market.daily_bars/tdx 输入；全历史覆盖及麦蕊定稿链未验证 | 缺日或不足 30 根有效 K 时不计算本卡 固定起点 Wilder RSI、超卖跌幅与收复前高，环境另需预热。不设 st/et 即请求全历史，不代表每股历史齐全；不用固定三年窗口冒充全历史。period=d，adj=n 取原价，复权沿 §5 的 qfq@as_of（B08 权息事件逐日复权）；其他复权只作核验，不回写历史信号。 |
| 交易日历：共同前置 | `/tcalendar/list/{year}/<LICENCE>` | 团队报告 T-R72 §7 B03 | 未验证：本卡 §5 需要日历，README §5 尚要求冻结；未证明已入库 | 无法确认 T+1、上市年龄、交易日窗口及持有日计数则阻断相关求值；不得用自然日或已有 K 线根数替代。 |
| 全市场快照：可选校验 | `/hsrl/ssjy/all/<LICENCE>`；`/hsrl/real/all/<LICENCE>` | 团队报告 T-R72 §7 B04；团队报告 T-R72 §7 A33 | 未验证：本卡 §6、README §3 以历史日 K 重算宽度，未声明快照已入库 | 不依赖该快照接口生成历史信号；缺失时用经审计的完整沪深日 K 与 pre_close 重算宽度，覆盖不足记 unknown。快照只校验当日截面，按主数据筛沪深 A 股并去重，不替代定稿日线或退市股历史。 |
| 多股快照：可选校验 | `/hsrl/ssjy_more/<LICENCE>?stock_codes={codes_csv}` | 团队报告 T-R72 §7 B05 | 未验证：本卡 §5、README §3 未给定该源 | 不依赖：仅可核对持仓/自选的当日收盘状态；缺失时保留定稿日 K，状态无法核验则阻断相关标的。stock_codes 每批不超过 20；不得用当前快照回填过去。 |
| 基础信息/历史涨跌停价：执行前置 | `/hsstock/instrument/{code}.{market}/<LICENCE>`；`/hsstock/stopprice/history/{code}.{market}/<LICENCE>?st={ST}&et={ET}` | 团队报告 T-R72 §7 B06 | 部分：本卡 §5、§17 及 README §3 的 T-R65/pre_close 仅已知子集；麦蕊链路未验证 | 缺上市日/状态/前收参考价或历史价格边界则对应规则 unknown、不生成可执行计划。既有本地规则仅在有效段、状态与 pre_close 齐全时核验；不以昨收或 gbbq 猜补除权日限价。 |
| 财务三表 PIT/每股指标：不依赖 | `/hsstock/financial/{table}/{code}.{market}/<LICENCE>?st={ST}&et={ET}` | 团队报告 T-R72 §7 B07；团队报告 T-R72 §7 A37 | 未验证：本卡 §5、§7 无财务字段；README §2 将财务型候选延后 | 不依赖：本卡不使用质量、估值、成长财务过滤，缺失不改变既有技术规则。table=income,balance,cashflow,pershareindex；未来引入须按下述 plrq 约束，禁止用 jzrq 回填。 |
| 股本/股东/分红：权息前置，股东不依赖 | `/hsstock/financial/{capital,topholder,flowholder,hm}/{code}.{market}/<LICENCE>`；`/hscp/jnfh/{code}/<LICENCE>` | 团队报告 T-R72 §7 B08；团队报告 T-R72 §7 A37 | 部分：本卡 §5、README §3 已给定 gbbq；事件可见性及麦蕊链路未验证 | 复权必须有截至 T 可见且已生效的权息证据；可继续用经验证 gbbq，不能假设近年分红接口覆盖全部复杂权息。两源均无法核验则 qfq@as_of（B08 权息事件逐日复权）失效、阻断相关求值；不依赖股东排名/估值分母，不据缺失另改规则。 |
| 公告/问董秘：产品否决前置 | `/hsstock/{announcement,interactiveqa}/{code}/<LICENCE>?st={ST}&et={ET}&lt={N}` | 团队报告 T-R72 §7 B09 | 未接：本卡 §14、README §4 明确本轮无公告输入，N-01 为 unknown | 技术候选可登记；公告风险未核验时 N-01 保持 unknown、买入草案由 KEY_DATA_MISSING 阻断。公告只有日期保守次交易日生效；问董秘不依赖且不能替代风险公告正文。 |
| 资金流：不依赖 | `/hsstock/history/transaction/{code}/<LICENCE>?st={ST}&et={ET}`；`/hsstock/history/transaction/{YYYYMMDD}/{code}/<LICENCE>` | 团队报告 T-R72 §7 B10 | 未验证：本卡 §5、§7 无资金流输入；README §2 将 W-03 延后 | 不依赖：本卡使用成交额量价条件，缺失不影响原规则，不以成交额冒称净流入，也不把资金流缺日补零。 |
| 指数基准/环境：规则及验证前置 | `/hsindex/list/<LICENCE>`；`/hsindex/history/{index}.{market}/{period}/<LICENCE>`；`/hsindex/real/time/{index}.{market}/<LICENCE>` | 团队报告 T-R72 §7 B11；团队报告 T-R72 §7 A02 | 未验证：本卡 §5、§11 和 README §3、§7 的 tdx 指数仍待确认；麦蕊链路未验证 | F25（指数加完整沪深宽度） 所需日线缺失则环境 unknown，不能默认震荡；记录缺口并按本卡 §7、§14 处理。指数列表核代码/市场/证券类型，历史 period=d、路径无 adj；实时接口不替代定稿日线。主基准沪深300（000300）、辅基准中证全指（000985）；选择依据为编排者 11-14 裁定，接入/覆盖未验证；行业超额仍未验证。 |
| 行业概念板块：验证对照 | `/hszg/list/<LICENCE>`；`/hszg/{gg,zg}/{code}/<LICENCE>`；`/hslt/{sectorslist,primarylist}/<LICENCE>`；`/hslt/sectors/{primary_name}/<LICENCE>` | 团队报告 T-R72 §7 B12 | 未接：本卡 §3、§4、§11 与 README §3、§5 明示行业历史/基准缺失 | 本卡入场不依赖行业板块；§11 的行业对照/分组及行业超额均未验证；待 B12 接入后用申万一级，主辅大盘基准按 §3，不能冒称行业超额已完成验证。 B12 只有树/成分/列表不等于行业收益序列已齐，仍需历史成员与对应指数日线；按当日有效成员留存，禁用当前成分回填。sectors 参数取编码后的一级板块名称；不新增行业选股、分散约束。 |

时点硬约束：日线及指数以北京时间 17:10 后的定稿版本为准；信号生成时间不早于 17:10、不早于实际定稿和依赖齐全时点。团队报告 T-R72 §7 A02 指出早批行可能未被晚批覆盖，必须核定稿标志与修订版本，不能仅看拉取时间。晚数据未就绪则等待；若错过次日执行窗口，本次候选过期，不沿用旧信号。

财务字段一律按 plrq（披露日）对齐，只用 plrq ≤ 信号日的数据；jzrq 仅为截止日，禁止用 jzrq 回填到过去信号日，防止未来函数。还须保证首次可见时间/available_at 不晚于信号生成时刻，保留原版本和修订版本；晚披露、次日 0 点更新或只有日期无法证明当时可见时，保守到下一交易日可见后使用。此约束也适用于 B08 的财务类字段；权息另需除权生效日及事件可见时点双重截断。官方未保证修订历史完整，PIT 仍未验证（团队报告 T-R72 §7 B07；团队报告 T-R72 §7 A37）。本卡不据此新增财务过滤。

## 6. 选股与环境

不新增 top-N、排名、行业约束或打分阈值。按 §4 范围逐标的求值；生产全市场扫描能力不由本文建立。F25 指数加宽度口径；完整公式见 docs/strategies/feature_spec.md §F24、§F25。 指数来源或宽度缺失时记录 unknown，不默认为 range。宽度只能从≤T 的全市场日 K 和 pre_close 本地重算，源的 pc 涨跌幅字段与 pre_close 价格字段必须区分；截面不完整时不声称完整环境判断。

## 7. 规则清单

全部 eval_time 为 daily_close（含未实现退出的设计求值时点）。下表是研究语义，status 为 to_quantify（待复测及执行契约核对），不是可导入 DSL；参数值与固定常数逐项见 §22。

| ID | 角色 | 候选条件 | 出处 |
|---|---|---|---|
| E1/E2/E3 | 入场 | 截至 T 的近 3 根有效 K 曾出现 RSI14<rsi_os；5 根有效 K 累计涨幅≤−drop_5d；T 收盘高于前一根有效 K 高点；三项全部满足。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| F1 | 过滤 | amount_20d_avg≥min_amount 且上市交易日数≥min_list_days。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| V1 | 否决 | F25 为下行状态时否决；宽度或指数缺失不得默认震荡。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| C1 | 反证 | 收盘低于前一根收盘，且成交额>amount_20d_avg×1.5。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| I1 | 失效 | 收盘跌破截至前一根有效 K 的 5 根最低价，窗口不含 T。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| X1/X2 | 退出 | 收盘≤同口径入场价×(1−stop_pct)；或收盘≥同口径入场价×(1+tp_pct)。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| X3/X4 | 退出 | RSI14>rsi_exit 且收盘低于前一根收盘；或持有≥max_hold。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |
| X1b | 退出·待实现 | 结构低点止损：入场候选日冻结入场前 5 根有效 K 的最低价（即候选日及之前 4 根）；后续收盘严格低于该位才触发，执行及顺延见 §9。plan.stop_loss_qfq 持久化为「不复权价位 L_raw + 冻结日 s」，每个 T 按 L_raw(s)×A(s)/A(T) 换算，与 qfq@T 收盘比较（本卡阈值为 L_raw(s)×A(s)/A(T)）；禁止存某日 qfq 数值后跨除权日直接比较。QFQ-1 派生尚未实现。 | docs/strategies/T-R16/S-02_st_oversold_rebound.md §7 |

## 8. 入场

T 日盘后确认所有核心条件及过滤；无否决且关键输入完整才记录入场候选信号。最早 T+1 09:30 执行，模拟参考为 T+1 开盘；信号仅次一交易日有效，过期重新计算，不用 T 收盘价成交。T+1 价格只用于执行，不事后修改 T 条件。来源：docs/strategies/T-R16/S-02_st_oversold_rebound.md §8–10；docs/strategies/_template.md §7.2。

## 9. 退出与止损

比例止损 stop_pct；比例止盈 tp_pct；RSI 反弹衰竭；max_hold 时间退出。X1b 结构止损冻结入场候选日及之前 4 根有效 K 的最低价，共 5 根，含候选日、不含实际入场日及未来 K；按下述不复权价位与冻结日持久化，逐日换算、不滚动重选锚点。原入场前 5 根窗口出处为原稿 §7 X1b；本轮明确冻结时点及执行规则。QFQ-1 派生未实现，字段口径见团队报告 T-A159，输入不足则记未验证，不以比例止损代替。 入场成本、结构锚点、持有天数、可卖量以及最大 R 仅从模拟账本截至 T 的状态派生，不假设存在真实账户持仓。R 的日内/收盘最高有利幅度定义及持有首日计数待裁定，未明确时该条件记 unknown，不通过未来最高价补齐。其他退出仍收盘确认、下一可卖交易日执行；结构止损触发后按下述规则保留待执行指令，没有可卖量时记录阻断原因。

结构位存储与换算（团队报告 T-A159 条件 C2）：plan.stop_loss_qfq 持久化为「不复权价位 L_raw + 冻结日 s」，每个 T 按 L_raw(s)×A(s)/A(T) 换算，与 qfq@T 收盘比较（本卡阈值为 L_raw(s)×A(s)/A(T)）；禁止存某日 qfq 数值后跨除权日直接比较。QFQ-1 派生尚未实现。s 为入场候选信号冻结日；先将原定窗口内各价格换算到 qfq@s 同一尺度，再按原规则选定结构位，记录为 s 日不复权尺度的 L_raw(s) 及 s，不能直接对跨除权窗口的不复权价格取极值。后续 T 只用截至该时点可见的同一因子版本作换算；缺失则记未验证并阻断结构位判断，不复用 s 日 qfq 数值，不重选窗口。

结构止损执行规则（编排者 11-14 裁定）：设 T 为退出候选信号日，仅当 T 日收盘价严格低于本卡结构止损阈值时触发（S-02/S-04 为冻结结构位，W-02 为冻结突破位×(1−fail_pct)）；收盘等于阈值或仅盘中跌破均不触发。两者按 §5 的同一复权口径比较。触发后最早 T+1 开盘卖出，参考执行价为执行日实际未复权开盘价，卖出滑点及冲击成本从该参考价扣减，佣金、过户费、印花税另按本卡 §18 计入；不得按结构位或止损阈值假定成交。若 T+1 停牌、跌停无法卖出或无可卖量，保留该退出指令，逐日顺延至第一个有可卖量且开盘可成交的交易日，使用该日实际开盘价及 §18 成本口径；当日开盘不可成交即继续顺延，不改为盘中成交。连续多日一字跌停期间均不记成交，逐日记录阻断；价格后来回到结构位上方也不撤销已触发指令。复牌首日若开盘可成交且有可卖量即执行，不受入场预热阻断；若仍跌停无法卖出则继续顺延。开盘成交证据或价格边界未知时记未验证，不假定成交；样本结束仍不可卖的列为未完成退出。

## 10. 仓位

沿 docs/strategies/T-R16/S-02_st_oversold_rebound.md §8–10 引用 RC2/RC3，取规则限制与用户配置较严者。不自行填单票百分比、杠杆、并发持仓数或示例本金；无配置时只给候选信号，数量与费用为 unknown。RC3 仍依赖 F25，不能因 S-01 用 F50 就把 RC3 也改成 F50。无行业历史时不声称 RC4 行业上限得到验证。来源：docs/strategies/feature_spec.md §F25；docs/strategies/_template.md §10。

## 11. 验证与待验证项

当前 validation_summary：window 未执行；oos_result 未验证；trade_log_ref 为 null；无收益、触发率或覆盖率实测。先核日 K 来源覆盖、历史退市股、ST/上市状态覆盖、交易日历与 qfq@as_of（B08 权息事件逐日复权），再做原规则的 fixtures、触发/覆盖统计和可成交性分解。研究统计与产品 G6 区分，G6 不计算收益。来源：docs/strategies/validation.md §0、§1、§4.1；docs/strategies/card_promotion_gates.md §3.6。

复测需覆盖满足、不满足、缺数据、环境分歧、停牌或涨跌停、可卖量为零等场景，具体夹具尚未编写。主基准沪深300（000300）与辅基准中证全指（000985）分别统计并注明 B11 数据版本，接入与覆盖未验证；行业超额一律“未验证”，待 B12 接入后按申万一级历史成员及对应指数收益核验，不能以主辅大盘结果充当行业结果。样本外与参数邻域方案见 README §5，不在本稿声称门槛通过。

## 12–13. 运行与复盘

系统字段留空；没有运行态、实盘跟踪或复盘结果。

## 14. 不可执行原因与解除条件

KEY_DATA_MISSING / DATA_STALE：对应字段与≤T 可见性证据补齐且快照新鲜后重新求值；SUSPENDED：入场须真实复牌且满足复牌预热规则，已触发的退出在复牌首日开盘可成交且有可卖量即执行；LIMIT_LOCKED：在有效交易日确认相应方向可成交；T1_NOT_SELLABLE：下一交易日有可卖量后重新检查；NEW_LISTING：同时满足上市年龄和预热；ST_OR_DELISTING：状态明确且不再阻断买入。公告未提供，N-01 记 unknown，按 docs/strategies/catalog.md §3 N-01 阻断买入计划草案、卖出方向不受影响；ST 数据不能替代风险公告。研究候选信号不等于产品草案可执行。

## 15. 适用环境与失效风险

原稿主要假设为震荡环境，上行可用，下行否决。大盘未知、趋势突变、隔夜跳空、流动性恶化均需单列。反证与失效须和候选信号并列展示，不承诺止损能按阈值成交。

## 16. 周期与扫描节奏

每天 T 日收盘后、数据齐全后计算一次；持有期参数不等于信号有效期；策略周期保持 §1 声明。跨源行情不逐行混拼，不用“最后写入的一行”择优，复测先冻结 source 与数据版本。

## 17. A 股交易约束

买入发生在 T+1，当天买入部分最早 T+2 才可卖。以后每个交易日收盘重新计算其他退出候选信号；已触发的结构止损按 §9 保留并顺延，最早下一交易日开盘执行；止损比例不代表盘中可成交价。来源：docs/strategies/_template.md §7.2、§17。

一字涨停不可买、一字跌停不可卖，停牌不成交；开盘仍封在相应涨跌停且无法确认排队成交的订单，不假定开盘价可成交。全天一字板由 none 四价相等且 volume>0 判断；仅收盘封板不等于一字板，T+1 全天高低价只能用于事后成交归因，不得回填 T 的候选名单。无成交或未知成交的事件单列，不能算作成功成交。来源：docs/strategies/feature_spec.md §F39/F40；docs/strategies/_template.md §18；docs/strategies/validation.md §1.4。

普通主板涨跌幅 10%；创业板、科创板（含风险警示）20%；主板 ST/*ST 在 2026-07-06 前为 5%，当日起为 10%。ST 和退市整理阻断买入，持仓变 ST 仍评估退出；不能因入场排除 ST 就省略历史涨跌幅分段。北交所排除。来源：docs/strategies/_template.md §17；config/market_rules.yaml §segments（各 effective_from）。规则未建模的 2023-04-10 之前不作执行复测依据，分钟数据从 2022 年起不等于交易规则也覆盖到 2022。

涨跌停价按成交日有效段、当日 pre_close 和 0.01 元 ROUND_HALF_UP 计算，含不足一价位及最低价格边界；除权日 pre_close 必须是可核对的参考价。pre_close 无效、状态未知或校验冲突则限价未知，不以昨天 close 或 gbbq 推值补缺。来源：docs/strategies/feature_spec.md §F35/F36。止损/止盈的展示和申报价需截断至执行日合法涨跌停区间；截断不能解释为阈值处一定能成交。来源：docs/strategies/_template.md §7.3、§17。

停牌日不补值，伪停牌按缺失；复牌若此前停牌≥5 个交易日，首个复牌交易日阻断入场，退出继续求值。上市不足 30 个交易日买入阻断，各卡上市门槛与预热还需满足；注册制上市前 5 日无涨跌幅，不进波动类窗口。来源：docs/strategies/_template.md §7.3。G-01 另含 none 价格低于2元的买入阻断（初值出处已证实；A 股有效性未验证（待复测），出处：docs/strategies/catalog.md:73；共用登记 P14），使用实际 none 价格比较。上市年龄按日历从上市日计，不能以已回填 K 线根数代替。来源：docs/strategies/feature_spec.md §F13。

沪深主板/创业板买入为 100 股整数倍；科创板单笔买卖≥200 股，200 以上按 1 股递增为“部分核实”口径；不足申报单位的卖出余额须一次性申报，且不得超过可卖量。单笔数量上限沿 config/market_rules.yaml §segments.lot，不在本稿重新设值。来源：docs/strategies/market_rules_T-R10.md §1.1–§1.3、§2.1–§2.2。

## 18. 成本与滑点

佣金双边分别按 max(单笔成交额×实际费率，5 元) 计算。实际费率未知，记“未验证、待复测”，不默认填零；复测费率需冻结。最低佣金出处：config/market_rules.yaml §segments.fees.commission_min_yuan；双边口径：docs/strategies/_template.md §18。

印花税按实际卖出交易日分段：2023-04-10 至 2023-08-27 为 0.1%；2023-08-28 起为 0.05%，仅卖出计。过户费在仓库已建模区间为双边 0.001%；更早日期不外推。来源：config/market_rules.yaml §segments（2023-04-10、2023-08-28、2026-07-06）.fees。

单边基础滑点见 §22（estimate，取值出处已证实：docs/strategies/T-R16/S-02_st_oversold_rebound.md:74；成本校准未验证（待复测））；单边冲击成本按拟成交额/最近 20 根有效 K 平均成交额，参与率≤0.1%/0.5%/1%/2%/其余分别取 0/5/15/30/60 bp；大于 2% 标容量受限。均额为零或有效 K 少于 5 根按最高档；不可成交不计算冲击成本。整个档表为 estimate，档表及回退口径出处已证实，成本校准未验证（待复测），不据此宣称收益。往返总成本为两边滑点及冲击成本、两笔佣金、两边过户费及卖出印花税之和。来源：docs/strategies/_template.md:252；docs/strategies/_template.md:253；docs/strategies/_template.md:258；docs/strategies/_template.md:259；docs/strategies/_template.md:260；docs/strategies/_template.md:261；docs/strategies/_template.md:262；docs/strategies/_template.md:266；docs/strategies/_template.md:267；docs/strategies/_template.md:268。

T 的计划成本使用≤T 的 ADV 和参考金额；回放中成交日真实成交额、税率及滑点只属于执行账本。T+1 的实际开盘不能参与 T 的入场规则。仓位金额未知时不生成精确费用数字。共用参数登记见 docs/strategies/T-R71/README.md §6。

## 19. 信号强度与置信度

暂不生成 score、confidence 或跨卡合成结论，未验证的置信分数不能充当通过门槛。

## 20. 冲突与互斥

同标的多卡结论并列展示，不合并动作。涉及原稿互斥的部分仍待执行契约核对；不通过自动选一张卡来回避风险。

## 21. 个人适配

不设置经验、资金或风险偏好阈值；仅研究草稿，不形成个人适配判断。

## 22. 参数与敏感性

表中 default 仅照录原值，min/max/step 只保留原网格，均不自动生效；没有经过本轮选择。slippage_bp 为 estimate，其余具名参数为 hypothesis。固定规则参数也属待检验假设或口径，不因写成常数而省略出处。 本节“取值出处已证实”只确认原值、网格或方法有据，不代表 A 股有效性、数据就绪或门禁通过；论文只证明有文献采用该取值或方法。

| 参数 | 类型 | 原 default | 原范围 | 原 step | 出处（相对路径:行号／公开文献） | 状态 |
|---|---|---|---|---|---|---|
| rsi_os | float | 30.0 | 20.0–35.0 | 1.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:66；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.7 | 取值出处已证实；A 股有效性未验证（待复测）；文献仅采用阈值30，不证明本卡网格或组合有效 |
| drop_5d | float | 0.08 | 0.05–0.15 | 0.01 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:67 | 取值出处已证实；A 股有效性未验证（待复测） |
| stop_pct | float | 0.03 | 0.02–0.05 | 0.005 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:68 | 取值出处已证实；A 股有效性未验证（待复测） |
| tp_pct | float | 0.06 | 0.04–0.1 | 0.01 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:69 | 取值出处已证实；A 股有效性未验证（待复测） |
| rsi_exit | float | 55.0 | 50.0–65.0 | 1.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:70 | 取值出处已证实；A 股有效性未验证（待复测） |
| max_hold | int | 5 | 3–10 | 1 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:71 | 取值出处已证实；A 股有效性未验证（待复测） |
| min_amount | float | 50000000.0 | 10000000.0–500000000.0 | 10000000.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:72 | 取值出处已证实；A 股有效性未验证（待复测） |
| min_list_days | int | 60 | 30–120 | 10 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:73 | 取值出处已证实；A 股有效性未验证（待复测） |
| slippage_bp | float | 10.0 | 0.0–50.0 | 1.0 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:74 | 取值出处已证实；成本校准未验证（待复测） |

| 固定参数登记项 | 原值/含义 | 出处（相对路径:行号／公开文献） | 状态 |
|---|---|---|---|
| RSI 周期/预热 | 14/28 根有效日 K | docs/strategies/T-R16/S-02_st_oversold_rebound.md:24；docs/strategies/feature_spec.md:281；docs/strategies/feature_spec.md:284；Dirk F. Gerritsen，Are chartists artists? The determinants and profitability of recommendations based on technical analysis，https://research-portal.uu.nl/ws/files/23204603/chartists.pdf，访问日期 2026-11-16，§2.1.7 | 取值出处已证实；A 股有效性未验证（待复测）；文献仅采用14日，非本卡 Wilder 递推及28根预热依据 |
| 超卖回看窗口 | 3 根有效日 K | docs/strategies/T-R16/S-02_st_oversold_rebound.md:29 | 取值出处已证实；A 股有效性未验证（待复测） |
| 跌幅/结构低点窗口 | 5 根有效日 K | docs/strategies/T-R16/S-02_st_oversold_rebound.md:30；docs/strategies/T-R16/S-02_st_oversold_rebound.md:35；docs/strategies/T-R16/S-02_st_oversold_rebound.md:37 | 取值出处已证实；A 股有效性未验证（待复测） |
| 回收高点/衰竭偏移 | 前 1 根有效日 K | docs/strategies/T-R16/S-02_st_oversold_rebound.md:31；docs/strategies/T-R16/S-02_st_oversold_rebound.md:39 | 取值出处已证实；A 股有效性未验证（待复测） |
| 反证放量倍数 | 1.5 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:34 | 取值出处已证实；A 股有效性未验证（待复测） |
| 卡预热 | 30 根有效日 K | docs/strategies/T-R16/S-02_st_oversold_rebound.md:24 | 取值出处已证实；A 股有效性未验证（待复测） |
| 候选有效期 | 1 个交易日 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:43 | 取值出处已证实；A 股有效性未验证（待复测） |
| 原证伪窗口 | 3 个交易日 | docs/strategies/T-R16/S-02_st_oversold_rebound.md:11 | 取值出处已证实；A 股有效性未验证（待复测） |

敏感性：先只测试原值与原网格内单因素邻域，结果未评估；不添加自拟阈值。逐卡具名参数 9 项、固定参数组 8 项，A 股有效性均未验证（待复测）；共用环境/成本/研究参数只在 README §6 计一次。

## 23. 审计、差异与未决

F25 保留宽度，不能偷换成 F50；全市场回填、退市股和除权日 pre_close 口径均影响宽度。RSI 全平盘为 null，不补成 50。结构止损按 §9 裁定；plan.entry_price_qfq、plan.stop_loss_qfq 按团队报告 T-A159 的 qfq@as_of 口径，派生实现未验证。 T-R71 只形成可审阅文字草稿；lifecycle 始终为 draft。G1–G7 未执行，本次文档 checker 的通过不能替代它们。来源：docs/strategies/card_promotion_gates.md §0、§3、§4。

## 24. 合规文案

本文输出仅称“候选信号”，用于检查既定规则，不构成投资建议或收益承诺。交易决策与风险由使用者自行承担。反证、失效条件与执行限制必须同时展示。来源：docs/strategies/_template.md §24。

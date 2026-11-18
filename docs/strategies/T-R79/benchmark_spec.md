# T-R79｜模拟跟踪真实基准口径卡

状态：draft；日期：2026-11-15；核对基线：`origin/main = 95967e1`。本文是后端实施规格草案，不代表真实数据验证、接口上线或策略晋级。仅研究候选信号；模拟不代表实际收益，不构成荐股或收益承诺。

## 1. 范围、依据与引擎盘点

只定义 tracking 的 T+1/5/20 同期基准与超额。候选条件、实际成交账本、F50 环境判定和模拟观察分别留证；T+1 收盘是观察估值，不表示当天新买股份可以卖出。本文不改变四卡策略周期，也不把 RC5 的周期映射变成基准选择规则。

引用缩写：E=`src/backend/app/tracking/engine.py`，S=`src/backend/app/tracking/service.py`，W=`src/backend/app/tracking/worker.py`，A=`src/backend/app/tracking/api.py`，M=`src/backend/app/tracking/models.py`；下表行号均为上述基线。契约优先于实现；下文标“draft 新增”的实现设计不能当成仓库已有能力；D01–D08均已由T-A190裁定，裁定口径不等于运行时已验收。

| 核对项 | 当前实际行为与缺口 | 证据 |
|---|---|---|
| 基准身份 | 只读 `000300.SH`；没有 000985 辅基准或行业基准选择器 | S:245、S:388；M:24 |
| 行情来源 | 直接查 `market.daily_bars` 的 code、adj_type=none、日期及 fetched_at；不筛 source，不保留 source/版本/停牌字段；把 fetched_at 映射 first_seen_at 并直接设 is_final=true；指数单位特判仅涵盖 000300.SH | S:55–95 |
| 时间窗口 | 北京时间，按 T 后第 h 个开市日到期；逐自然日日历有缺口即无法定到期日；非盘中从下一交易日 09:30 入场，目标日 15:00 估值 | E:23–44、E:141–175 |
| 个股收益 | 入场 open_qfq、退出 close_qfq；同次 prepare 的 as_of；缺端点或因子记 `qfq_prices_or_factors`，不默认因子=1 | E:242–253；S:246–254 |
| 指数/超额 | 指数入场日 open、到期日 close（none）；只检查端点，不要求中间开市日齐全；`excess_pct=return_pct-benchmark_return_pct` | E:267–284 |
| 盘中 | 寻找紧邻分钟槽，但总记 `minute_qfq_bridge_unverified`；benchmark_minutes 参数存在而未使用，service 未传指数分钟序列，盘中不计算收益 | E:156–167、E:235–240；S:313–329 |
| 停牌/路径 | 入场停牌等有独立状态；个股路径中间缺收盘会跳过并记 `qfq_path_missing_sessions`；服务丢弃行情行停牌字段，真实停牌识别依赖独立 facts，尚有接线风险 | E:198–234、E:292–330；S:78–85、S:250–255 |
| 状态 | 个股收益及可成交性齐备即可 complete，基准仍可能 null；缺失失效监控总记 `invalidation_monitor_not_connected`。complete 不等于基准/整链验证通过 | E:321–343 |
| 证据冻结 | 原始股票、分钟、主基准、as_of、生成/观测摘要入结果快照；证据 provider=SYSTEM，不是上游来源；未冻结日历本体、指数目录版本或真实 source | S:346–358；E:178–195 |
| 修订重算 | 所有非 pending 结果被跳过；与契约要求 unavailable 到期后 5 个交易日内每日重算有差异；仍有钳制到期日结束的旧实现，已与T-A190 D04裁定不符 | S:232–242；`docs/api-contract.md` §7.11.3 T-A33(1) |
| worker/API | worker 遍历已有建议调用 run_one，不是指数采集器；GET 只读；策略聚合按版本/周期去重，均值、方向率各自取非 null 样本；没有辅基准统计 | W:19–45；A:22–28、A:72–134 |
| 汇总边界 | 均值 n<5 为 null，n<30 small_sample；盈亏比只用 buy/add/hold 的非零毛收益；实现未按动作/置信度分组，策略 API 也未汇总每条 result 的全部 gap | S:171–195、S:431–440；A:97–134 |

已读依据及其约束：

| 文件 §节 | 本卡采用的边界 |
|---|---|
| `docs/plan.md` §2.8、§2.8.1、§9 问题14/C(7) | 主基准沪深300；同入场时点；1/5/20；动作方向定义与 hold 初值；不可成交/被动 hold 排除 |
| `docs/api-contract.md` §3、§5.1、§7.4、§7.11.3 T-A27/T-A33 | 单条观测与 Stat 分开，唯一键、缺数语义、精度、冻结及补算期；契约优先 |
| `docs/contracts/daily-bars-source.md` §6 Q6、§7⑥、§8.2 | 基准不随股票采集范围自动具备，指数接口/主数据未闭合；旧 §0 是历史盘点，不能代替今天代码 |
| `docs/contracts/multi-source-ingest.md` §2.1–§2.6、§3.1、§3.4、§4 | none 存储、显式来源、权息快照、不得用缺行推断停牌；库存整行替换不等于历史结果可以改写；stock 资格的导入器不能自动接指数 |
| `docs/contracts/trading-calendar-exrights.md` §2–§6、§8、§11 | 主源日历及自然日覆盖；指数只核对日历；权息 available_at 与版本未验证，缺因子不补1 |
| `docs/strategies/T-R71/README.md` §3–§6、P1 共同前置 | 11-14 既有裁定：主000300、辅000985分别统计；source/版本冻结；17:10 后实际定稿，不把预计完成时刻当就绪 |
| `docs/strategies/T-R71/S-01_st_pullback_ma.md` §5/§11 | 主辅指数均 none；B11 接入未验证；原行业超额证伪不能用大盘替代 |
| `docs/strategies/T-R71/S-02_st_oversold_rebound.md` §5/§11 | 同主辅基准；行业对照未验证；候选与后续观察数据隔离 |
| `docs/strategies/T-R71/S-04_st_broken_board.md` §5/§11 | 同主辅基准；不可成交须计数，不能倒删候选样本 |
| `docs/strategies/T-R71/W-02_sw_breakout.md` §5/§11 | 同主辅基准；不能因 swing 周期换指数或缩短既定窗口 |
| 团队 `reports/T-R72.md` §7 B11/B12/A02 | B11 指数列表/历史/实时；B12 树和成员不等于历史行业收益；本单仅读报告及其公开文档存档 |
| `docs/strategies/feature_spec.md` §F50、§F26/F27 | F50 固定000300.SH、none，已有64根探针不证明完整覆盖；环境 MA 预热不施加给端点收益；行业历史仍缺 |

## 2. 输出约定与合成输入

R01–R22 是本卡全部行为规则，每条附【虚构】用例；除 §8 官方元数据外，任何价格、日期编号和统计数字均为合成，不是实测。D0=T；D1…D20 是已验证日历中严格晚于 T 的开市日，不代表连续自然日。中间所有自然日均显式给出开/休市。通常设 D0 17:20 生成候选、D_h 17:20 评估；每行均有定稿和可见性证据，除非用例主动删去。

逻辑输出包采用以下字段供实施映射，**不是现行 API 已有 schema**：主槽映射现有 `benchmark_*`/`excess_pct`；辅槽、行业槽及 metadata 按T-A190 D02仅留关联唯一观测键的内部研究包，对外扩展暂缓。不要复制现有观测为三条、导致样本翻倍。

| 字段 | 类型与含义 |
|---|---|
| observation_key | `(suggestion_id, strategy_version_id, horizon_days)`；同版本多实例仍一条 |
| window | `signal_at, entry_at, exit_at, as_of, sessions, calendar_version`；日历未知时 entry/exit 可为 null |
| benchmark_slots | `primary/secondary/industry` 三槽；各含 `benchmark_id, benchmark_code, status, entry_points, exit_points, benchmark_return_pct, excess_pct, benchmark_window_complete, gap_keys`；完整性独立于端点可算性，见R12 |
| status | 内部取 `pending/complete/unavailable`；基准 complete 只表示该槽输入可计算，不改变个股 state；行业固定 unavailable 至 B12 核验 |
| basis | `price_index, adjust=none, unit=index_points, formula=arithmetic_difference, cost_applied=false, dividend_bias=true` |
| provenance | `source, source_endpoint_template, source_symbol, source_market, security_type=index, data_version, content_sha256, directory_version, methodology_version`；端点与逐日行引用可解析 |
| times/quality | 每行 `trade_date, data_as_of, available_at, first_seen_at, fetched_at, is_final, finality_evidence_id, row_revision`；时间均带时区 |

非数值结果使用 JSON null；成功零收益可以为 `"0.0000"`。受影响数值 null 必列缺口码和日期/字段证据。码无优先级覆盖，独立检查产生的码去重、字典序输出；无法确定日期的检查不猜日期。原有 Gap.reason 沿实现为 no_source，细分语义用 Gap.key；本文新增键均是 draft，未声称已在 API 实现。全局元数据不可信会阻断该槽；已知局部缺数可保留可信端点，收益/超额依规则置 null。股票收益可保留且单独带其自身缺口。

## 3. 身份、选择与数据来源

### R01 主辅固定、行业隔离

沿 T-R71 README §3 及四卡 §11：主=沪深300 `CSI:000300:price`，辅=中证全指 `CSI:000985:price`；指数身份与供应商市场后缀分开。所有 h=1/5/20 均分别计算，不取表现更好者，不取平均，不用辅槽补主槽。T-A190 D01已裁定：板块/周期不触发换基准。B12 未接入，行业收益/行业超额=null，`industry_benchmark_unverified`；不能直接把当前行业成员用于过去。

【虚构】个股收益4%，主指数2%、辅指数3%：主超额2个百分点，辅超额1个百分点，行业=null+`industry_benchmark_unverified`。把同一候选从 short 分组移到 swing 分组，主辅身份不变；主缺数时主超额=null，不能拿辅超额1填入。

### R02 价格指数、分红偏差与费用

沿 E:267–282、F50 的 none，以及 §8 O1–O4：本卡使用价格指数点位，不给指数应用个股 qfq 因子；币种人民币是编制信息，点位单位仍为 index_points。仓库本次核对的 tracking/契约链没有可用全收益指数接线；官方存在全收益系列不等于已有数据源。个股 qfq 与价格指数相比的超额**含分红口径偏差**，不得称总回报超额/纯 alpha，偏差大小未验证。保留 `dividend_bias=true`、提示键 `benchmark_total_return_unavailable`，不因这条限定抹掉合法价格指数收益。当前毛收益不扣费用，cost_applied=false；成本研究须另列，不能默认真实成本为0。T-R79b的H00300/H00985系列存在性出处及尚缺证据见§7 U07，未新增全收益接线就绪结论。

【虚构】同窗个股 qfq 100→102，价格指数1000→990：2%−(−1%)=3个百分点。另给一条仅用于解释的合成全收益1000→1000，比较值为2个百分点，相差1个百分点；不得拿这条合成序列替换主基准。指数点位1000→1000是真实输入相等产生0%，不是缺数补0。

### R03 B11 字段与身份校验

只把团队 T-R72 §7 B11 的 `/hsindex/list` 与 `/hsindex/history/{index}.{market}/d` 作为待接入路由模板，不记录含证书的实际 URL，不发请求。字段依据：团队归档 `reports/codex/T-R72/web/txt/hszsdata.txt`「沪深主要指数列表接口」「历史分时交易」：dm/mc/jys 对应源代码/名称/市场，t/o/h/l/c/v/a/pc 对应交易日期/OHLC/量/额/前收；本卡收益只使用 o、c。指数 v/a 单位未核，不借股票 v×100 规则，非收益必需字段可空且不得参与计算。

日线 t 规范化为北京 trade_date，接受合法日期或时间部分为00:00:00的日期；不把该零点当 available_at。OHLC 用有限 Decimal 且均>0、low≤open/close≤high；异常行拒绝，`benchmark_invalid_bar`。供应商缺 o 时不能用 pc 或 T 收盘补开盘。dm、jys、名称/类型及冻结目录必须能唯一映射编制方身份；同号股票不允许。000300.SH 有 F50 的目录探针出处；000985 的源后缀及全历史映射仍未验证，未核则 `benchmark_identity_unverified`，不按数字前缀猜 SH/SZ。按T-A190 D05，指数适配、身份映射、定稿/可见性审计与版本保存及available_at归采集适配层，跟踪层只消费冻结包，worker/GET不负责外呼；真实B11接入暂缓。本段完整校验组合尚未运行时验收（U01）。T-R79b已核官方代码及路透/彭博表示，见§7 U01；未把它们当作B11后缀的验证。

【虚构】已冻结映射 IDX-A→CSI:000300:price，t=D1 00:00:00、o=1000、h=1020、l=995、c=1010：得到D1日线与1%收益，available_at仍来自独立证据。将类型改为stock则全槽=null+`benchmark_identity_unverified`；改o=0则拒行+`benchmark_invalid_bar`，不能输出无穷收益。

### R04 同源整段与版本冻结

沿 T-R71 README §3、四卡 §16、多源契 §4：候选产生时冻结主辅角色和选源策略；**未来尚未到达的行不在 T 伪造冻结**。评估时各序列以一个可审计 source、数据快照 data_version 读取全窗，在快照内逐行保留修订和可见时点；个股与指数可有不同源，但该来源组合也须登记。辅指数独立冻结。tdx 仅独立对照，不能填进 mairui 的缺日；主源未具备整窗则给缺口。data_version 是快照标识，不要求所有日线同一 fetched_at；同一时刻多版本无法唯一选择则拒绝。无版本/hash 为 `benchmark_version_unverified`；混源为 `benchmark_source_mixed`。严格整窗单源快照检查是 draft 新增（U05），库存源优先级不能代替它。

【虚构】mairui-v1 有D1开1000、D5收1040，D3只在tdx-v7存在；禁止拼成完整窗，正式基准=null+`benchmark_source_mixed`（若输入未拼、仅缺日，则端点收益仍为4%，缺日只影响R12完整性字段并列逐日gap）。若完整tdx-v7独立对照得3%，也不能覆盖主槽空值。源名相同但版本/hash均缺→null+`benchmark_version_unverified`。

## 4. 日历、窗口与可见性

### R05 唯一日历与完整自然日

沿 E:34–44、PN-03 §2–§3：统一 Asia/Shanghai；采用 DS merged_calendar 所定义的业务日历与冻结版本，2026-08-07及以前为HF metadata、之后为config日历；重叠一致并核sha，指数日集合只核对。交易日数量不以股票有效K、指数有行日或周一至周五计。T至目标日的所有自然日须覆盖；不足h个已知后续开市日、自然日缺口→`calendar_not_covered`，due=null，收益/基准/超额=null，结果层 unavailable；兼容现行服务可无观测行、在顶层列该gap，不能假报pending。版本/hash或重叠冲突→`calendar_version_unverified`，停止整个窗口。T-R79b补充的交易所休市通知只作核对参照，未验证合并日历的实库覆盖，见§7 U03。

【虚构】自然日C0至C7全部覆盖，开市C0/C1/C3/C4/C6/C7，其余休市；T=C0，则T+1=C1、T+5=C7。删除休市C2这一条也必须due=null+`calendar_not_covered`，不是跳过C2继续。两个日历把C4分别记开/休→null+`calendar_version_unverified`。

### R06 盘后入场与各期限估值

沿 plan §2.8、E:141–154/274–282：正式盘后样本的T是候选创建时刻的北京日期，entry=D1 09:30，exit=D_h 15:00。股票用同一评价as_of的qfq open(D1)和close(D_h)，指数用none open(D1)和close(D_h)。h=1为同日开到收；h=5/20均从D1开开始，绝非T收盘到D_h收盘，也不是D1之后再数h日。不开盘成交证明与观察价格分开，按R11处理不可成交；T+1观察不主张T+0卖出。

【虚构】T收盘股票9、指数900；D1开股票10、指数1000；D1/D5/D20收股票11/12/9、指数1010/1040/1100。三窗股票=10%/20%/−10%，基准=1%/4%/10%，超额=9/16/−20个百分点。T收9与900不入公式，隔夜跳空未算入。T恰15:00按现有E:27–31不属于盘中，但源未定稿时仍不能生成合规盘后候选（R09）。

### R07 盘中边界不降格为日线

沿 E:156–167、E:235–240、api-contract §7.11.3：盘中候选必须同一下一分钟槽的股票/指数开盘，目标仍D_h收盘，不改用日开、T收或下一个“有数据”的分钟。秒非零向上取整分钟，END标签等于槽起点+1分钟；午休移13:00，15:00及以后移下一交易日09:30。当前 raw/qfq 衔接和指数分钟未验证，保留 unavailable，股票/基准/超额=null+`minute_qfq_bridge_unverified`，指数加 `benchmark_minute_unverified`；缺紧邻槽另记 `next_minute_bar`。按T-A190 D08，盘中真实计算继续unavailable，直至同槽指数开盘与个股qfq桥证据齐备，不因这套槽规则存在而开通。官方实时发布频率的适用边界见§7 U09，不能代替下一分钟开盘及qfq桥证据。

【虚构】D0 10:00:30候选→槽10:01、END=10:02；仅有10:03标签不能后移入场。即使给出同槽股票10/退出11、指数1000/退出1020，算术可得10%与2%，正式输出仍为null及上述未验证码。11:30候选→13:00槽；14:59:30→D1 09:30槽，均不能用早一分钟。

### R08 信号时钟与观察时钟隔离

按T-A190 D04及api-contract §7.11.3 T-A33(1)：signal_as_of=候选生成时刻，信号只看当时已经可见且数据日期≤T的输入；首次评估的观察as_of为实际运行时点，unavailable在到期后第1–5个开市日以该次实际补算时点为as_of产生观察修订（见R13）。行情日期始终≤到期日D_h，观察窗口仍为D1…D_h。所有输入版本的available_at、首次本地可用时刻first_seen_at均须≤该次as_of，按带时区瞬时比较（等号有效）；交易日收盘时刻也须≤as_of，不用fetched_at推翻首次可见记录。任一可见时点无可验证来源或无时区→`benchmark_availability_unverified`；晚于该次as_of→`benchmark_not_visible`；股票因子同样缺口，不补1。每次修订冻结实际as_of、输入及算法/日历/source/数据版本，旧版可重放；两端qfq使用同一次as_of的因子和同一锚。晚到值只能进入其实际可见后的新修订，不得写成旧时点已知，也不能回写T候选。

【虚构】D5 17:20评估，D5收1040在17:19可见→可算4%；available_at恰17:20也允许；17:21才可见→基准/超额=null+`benchmark_not_visible`。只有fetched_at=17:19而available_at未知→null+`benchmark_availability_unverified`。D5才知的因子可用于D5观察的同尺度两端，不能加入D0候选特征。

【虚构】另给拆分窗口：股票raw入场10、末端5，已核累计因子A(D1)=1、A(D5)=2，D5观察锚=2，则qfq两端分别10×1/2=5、5×2/2=5，收益0%；指数1000→1020得2%，超额−2个百分点。若因子D6才可见，D5评估不得使用该转换，股票/超额=null+`qfq_prices_or_factors`；若该条unavailable在D6补算，则须按D6实际as_of重新冻结同锚两端，D5旧版仍null；不能误算raw收益−50%。

### R09 定稿证据

沿 T-R71四卡 §5、README P1共同前置、T-R72 §7 A02及B11存档：指数日线预计17:10完成；17:10是最早采用门槛，不是保证完成。draft 适配器须保存is_final及可核验定稿证据，不得照当前S:84凭“已收盘”直接置true。在日历已到15:00但数据尚未定稿时为unavailable，相关数值=null+`benchmark_not_final`；不把实时/分钟聚合顶替正式指数日线。历史回填定稿还须满足R08的首次可见限制。§7 U02所引官方每日发布规则不证明17:10定稿，现有17:10依据仍是T-R72路由资料。

【虚构】D5 15:00已到期，日线c=1040、is_final=false→null+`benchmark_not_final`；17:10仍false，结果相同。17:18证据齐备且as_of=17:20→4%。17:09即宣称final的行不满足本路由17:10门槛，仍拒绝采用；不误报pending。

### R10 休市与末端未到

沿 E:34–44/168–169、PN-03 §3：已知休市日不消耗h，也不要求指数行，不生成休市日0收益。known due且run_at<exit_at→status=pending，基准/超额=null+`tracking_window_not_matured`（draft说明码）；run_at=exit_at已到期，再检查定稿/可见性。非开市日创建的候选沿现引擎取其日期之后第h个开市日，不倒移信号日期；这不放宽四卡盘后生成前提。

【虚构】D1后有连续2个明确休市自然日，D5仍为第5个开市日；休市无行不报指数缺日。已知D5到期，D4的价格1030不得提前算3%，输出pending/null+`tracking_window_not_matured`；D5 15:00刚到但未定稿按R09。休市日候选的下一个开市日为D1，起点仍为其开盘，不拿上个开市日收盘。

### R11 个股停牌不冻结基准

沿 plan §2.8.1、PN-03 §5、api-contract §7.11.3：个股窗口仍按市场日历走，指数独立计算整窗；中间停牌不缩短窗口、不冻结指数、不延期退出估值。入场明确停牌→个股untradable；被动hold/forced_hold/wait沿原排除规则；基准齐全仍可给描述性基准收益，但超额/方向统计排除。末日停牌且无可用qfq收盘→股票/超额=null+`qfq_prices_or_factors`，基准可算；中间停牌但两端齐备可算区间收益，路径另保留缺日gap，不填股票价格。不凭缺行或零量推断停牌，状态未知按原tradability缺口处理。

【虚构】D1开股票10、D5收11，D2/D3明确停牌；主指数D1开1000、D5收1040且5日日线齐：股票10%、基准4%、超额6个百分点，路径另记 `qfq_path_missing_sessions`。若D5收缺，股票/超额=null、基准仍4%；若D1明确停牌，则untradable、有效n=0，基准4%只作对照。

## 5. 缺数、历史身份与修订

### R12 指数缺日与完整性

按团队报告 `T-A190.md` D03裁定及B01修正：**端点可算性与整窗完整性分开报告**。窗口由R05的已验证日历确定；可信同源同版、定稿且PIT可见（`available_at≤as_of`，并满足R08其余时点要求）的入场open与末端close两端齐备，即正常计算正式 `benchmark_return_pct`，个股收益可算且满足其余规则时正常计算 `excess_pct`。中间缺日或非端点OHLC缺项不得清空这些端点收益。

完整性独立按同一日历的入场至末端开市日逐日检查唯一、有效、定稿、可见的OHLC：确认齐备才记 `benchmark_window_complete=true`；缺日或非端点OHLC缺项记 `benchmark_window_complete=false`（不完整），按受影响日期逐日列 `benchmark_daily_missing:<D>`，缺字段保留null及字段证据；无法核实完整性则记 `benchmark_window_complete=unavailable` 并保留相应gap。两端可算不代表整窗已验证。日内异常、未定稿、不可见仍分别按R03/R09/R08的码报告；影响端点有效性时阻断相应收益，仅影响中间行时报告完整性不可用及日期证据，不额外否决可信端点。

缺任一端点 → `benchmark_return_pct/excess_pct=null` + `benchmark_prices`；缺整行另列该日 `benchmark_daily_missing:<D>`。不补0、不跨日借值、不插值。缺日历而无法确定窗口时不算，收益/超额为null，按R05报告calendar gap，不猜窗口或缺日日期。

【虚构】已验证日历的D1开1000、D5收1040，两端均满足上述要求，但D3无行：正式输出 `R_b=4%`，个股收益若为10%则正式超额为6个百分点；`benchmark_window_complete=false`（不完整）+ `benchmark_daily_missing:D3`，不得宣称整窗已验证。删D5行后，正式基准/超额=null + `benchmark_prices`，另保留D3/D5逐日缺口。D3若实际为明确休市，则不属于期内开市集，D1…D5定义随R05重算，不能将原D5当第5个开市日不变。

### R13 数据修订、冻结与补算

按T-A190 D04及api-contract §7.11.3 T-A33(1)：首次评估as_of为实际运行时点；仅unavailable在到期后第1–5个开市日每日按实际补算时点产生观察修订，as_of=该次实际补算时点。available_at、first_seen_at均须≤该次as_of（带时区瞬时比较），行情日期≤到期日D_h，两端qfq同锚。每次修订冻结实际as_of、输入、算法/日历/source/数据版本，保留旧版及其摘要以供重放；晚到值不得倒填为旧as_of已知。complete/untradable/excluded的单条结果冻结，同一容器内另一条unavailable补算不得改写这些结果。股票complete而缺基准仍冻结，新增基准对照仅进独立研究包，不替换正式观测。第5个开市日末次补算后仍缺则冻结；日历未知不推进5日、不推断已过补算期；第5日作业具体钟点「未验证」，不另造常量。重放使用原as_of、输入及全部版本，版本缺失或摘要不符→该重放请求null+`benchmark_version_unavailable`，原结果保留，不伪造旧值。

【虚构】D5为到期日，首次实际评估D5 17:20时股票因子和指数末端尚不可见，结果unavailable、相关值null。D6为到期后第1个开市日，D5行情1000→1040及股票同锚因子在D6 17:19可见且first_seen_at=D6 17:19，实际补算D6 17:20以该时点为新as_of，可得基准4%；D5旧版仍null。若某输入D6 17:21才可见，本次仍拒绝，留待期内后续实际补算；D6行情不得替代D5末端。另有已complete的v1基准4%，即使D6新v2将D5收盘改为1050，v1仍4%，v2的5%仅独立研究对照；股票complete而基准null的行也不得解冻。同一容器内untradable/excluded不变。D10为到期后第5个开市日，当日末次作业仍缺→冻结unavailable，D11不再补算；本例未设D10作业钟点，日历缺覆盖则不推进计数。v1遗失→重放null+`benchmark_version_unavailable`，不是取v2。

### R14 发布前历史与更名

§8官方基日不等于发布日。按T-A190 D06：窗口起点早于该指数发布日，即使有回溯点位，也不进入真实模拟基准，null+`benchmark_prelaunch`；发布日当天仍须有真实日开/收和可见证据，不能用基点1000补开盘。窗口覆盖更名/代码变更须有编制方连续性说明、有效区间、源目录映射和可见版本；只改名称且证明同系列、同点位尺度者可续算，缺证明→null+`benchmark_identity_history_unverified`。不自动换成ETF、继任指数或按基点比例重标；T-A190 D06已裁定：发布前回溯仅可另包标注事后可得，不混入正式PIT统计。§7 U08的基日/发布日期和其他系列更名实例只核公开事实，不证明本系列连续性。

【虚构】假设指数发布L日、基日B<L；窗口B→L即使给1000→1040也为null+`benchmark_prelaunch`，不冒称当时可跟踪。L日有效open1000、close1010→1%。合成更名X→Y有连续性凭证且点位1000→1020→2%；删除凭证则null+`benchmark_identity_history_unverified`，不能按名称相似推断。

## 6. 公式、动作与统计

### R15 收益和超额公式

令P0/P1为同as_of的个股qfq入场/估值价，I0/I1为同源同版指数点位：`R_s=100×(P1/P0−1)`，`R_b=100×(I1/I0−1)`，`E=R_s−R_b`。收益单位pct（1表示1%），超额为百分点；选简单差是为了沿用E:47–58/278–282及F27相对收益差口径，兼容既有方向门槛。几何相对收益 `100×((1+R_s/100)/(1+R_b/100)−1)`不写入excess_pct，不做复利/年化解释。公式有实现出处，预测有效性未验证。

【虚构】P0=10、P1=11，I0=1000、I1=1020：R_s=10%、R_b=2%、E=8个百分点；几何值=7.8431%，不是本字段。I0缺或非正→R_b/E=null及R03/R12码；R_s仍可保留10%。

### R16 精度与零边界

沿E:47–58/331–340、api-contract §7.11.3 T-A27：Decimal运算精度64，先算未舍入的R_s/R_b及差，再各存4位ROUND_HALF_UP，展示2位；方向用未舍入的差，不能从展示值倒推。汇总沿当前实现使用存储的单条4位数，再舍入聚合4位；不把百分点再乘100。负零展示规范化为0（draft展示约定，不改变符号判断）。

【虚构】股票100→100.00004、指数1000→1000：未舍入E=0.00004个百分点，buy方向true；存E=0.0000，展示0.00，不能据此改判false。1.23445按half-up存1.2345；缺数null不得格式化为0.0000。

### R17 动作方向与排除

沿plan §2.8/C(7)、E:76–83/198–234：buy/add取主E>0，sell/reduce取主E<0，收益本身不反号；hold用|主E|≤(h=1:1、h=5:2、h=20:5)个百分点；wait不计方向。hold门槛为初值、未验证/待校准；T+1 hold仅展示，不进入健康度。主E缺→方向null，辅E不替代；untradable/excluded/pending/unavailable不进入方向n。无可核实tradability/forced_hold时仍按现有缺口阻断个股完成，不从收益推断可成交。

【虚构】主E=−2：sell正确，股票收益若−3%仍记−3%；h=5 hold在−2边界正确，−2.0001错误；h=1/20边界分别1/5正确。buy在E=0错误；wait在E=8也为方向null、n不增加。主缺而辅E=+1→buy方向null。

### R18 统计集合与样本数

沿api-contract §7.11.3 T-A27(3)、S:138–168、A:72–106：按唯一观测键去重，同版本实例取created_at最早、并列id最小，其他实例入证据；按T-A190 D07，“策略版本×期限×动作×生成时置信度”为必选组合，scope隔离，主辅统计再分槽，不能混合1/5/20。置信度取生成快照原标签，未知单列，不猜分桶。内部再按benchmark身份/来源与版本口径/窗口模式留分组，拒绝跨口径混算，不因数据版本不同把每条记录误当独立统计口径；新增对外字段暂缓至响应契约明确。主基准有效集是股票state=complete且主E非null；辅基准用自身有效集。比较主辅时另报共同有效集n，不拿不同n暗示可比。各槽各报有效n，收益、基准收益、超额、方向各自报n及排除/待到期/缺数据计数；另报主辅配对n和配对集基准均值，零收益是有效样本，缺数不进入相关n。

【虚构】6条同h候选，其中一条wait、其余5条主E均有值，辅仅4条有值；主n=5、辅n=4、共同n=4。给第1条增加第二实例，主n仍5；另有h=20的3条不并入h=5的5条。4条缺基准但个股可算的记录，计入个股收益n，不计超额n。

### R19 均值、胜率和小样本

沿S:431–440、A:97–120和契约§5.1/§7.11.3：`avg_excess=sum(E_i)/n_excess`，`avg_return=sum(R_s,i)/n_return`；新增独立基准均值`sum(R_b,i)/n_benchmark`仅在与超额配对的有效集内报告（draft）。方向胜率`sum(bool)/n_direction`用0…1比例。每项n<5→value=null，n<30→small_sample=true；n≥30仅解除样本不足标记，不代表有效性验证。draft为统计null补 `tracking_stat_n_lt_5` 说明键。无权重、无年化、无跨窗复利；每条观测等权且不能把观察数当独立交易数。scope=site仍只匿名聚合。

【虚构】同口径5条E=[2,−1,0,3,1]：均值=5/5=1.0000个百分点；buy方向[真,假,假,真,真]，胜率=3/5=0.6000，small_sample=true。只有前4条时均值=null+`tracking_stat_n_lt_5`且n=4，不能输出1；30条均为1时均值1、small_sample=false。无样本n=0同样null。

### R20 其余既有统计不伪装为基准表现

沿api-contract §7.11.3 T-A27(1)(2)、S:171–195、A:110–122：盈亏比仍取有效buy/add/hold非零股票毛收益，盈利均值÷亏损均值绝对值；n<5为null，无亏损为null+`no_losing_samples`，有亏损无盈利且n≥5为0。MDD/runup是个股qfq收盘路径统计，不是指数或超额回撤；中间缺日跳过并列gap，缺端点则两项null。当前max_loss_streak是按API建议创建顺序遍历complete的负股票收益，零或正收益清零，不是RC5超额方向失败序列；本卡不增设指数路径统计或重定义该字段。

【虚构】5条买入毛收益[4,2,−1,−3,−2]，盈利均值3、亏损绝对均值2，盈亏比1.5000；5条全盈利→null+`no_losing_samples`，5条全亏→0。路径[10,12,9,11]：MDD=−25%、runup=20%；删除12那日则路径[10,9,11]产生−10%/10%并列路径缺日gap，不能称完整路径。创建顺序收益[−1,−2,0,−3]的max_loss_streak=2。

### R21 状态和缺口传播

沿E:322–343及api-contract §7.11.3：基准端点不可算只影响该槽的收益/超额/方向，股票complete可保留；整窗缺日/非端点缺项按R12独立报告完整性与gap，保留可信端点收益；有缺口时总体data_status至少partial。主辅均缺不等于股票收益0；只有缺可计算股票价格/可成交性时才使股票unavailable。按R05日历未知与R10未到期分流，随后验证身份/源版本、定稿可见性，分别检查端点公式与逐日完整性；多种独立缺口并列。辅槽失败不抹掉主槽；行业未验证始终显示，不能把行业缺口藏在主槽complete之后。新增全局/逐槽gap聚合是draft，A当前仅收集盈亏比gap的局限需实施修复。

【虚构】股票收益10%且可成交，主缺D5、辅收益3%：股票state=complete，主R_b/E/方向=null+`benchmark_daily_missing:D5`/`benchmark_prices`，辅E=7，行业=null+`industry_benchmark_unverified`，总体partial。若股票也缺qfq端点，state=unavailable、股票/双槽超额=null，但已有辅R_b=3%可以保留。

### R22 重放身份与实现验收边界

沿S:34–39/346–376、api-contract §7.11.3：结果证据需包含输入摘要、算法版本、calendar_version、各槽目录/源/数据版本、as_of、定稿/可见时点、缺日清单；固定这些输入的重放须产生相同数值和缺口。任何对照版本不得写回候选信号快照。GET只读不补拉。未完成真实source、日历和qfq的验证时，报告用“未验证”，文档checker成功不解除数据门槛；本文字段接线/合成案例尚非运行时验收。

【虚构】冻结包v1两次得到主4.0000%、缺口列表相同→重放一致；将日历版本替换v2后即使仍4.0000%，也不是同一输入重放；未核验摘要时输出null+`benchmark_version_unverified`。GET调用两次只返回冻结包，采集次数始终0。

## 7. 参数出处登记及未验证计数

计数按登记项/组合一行计一次，不按重复出现的数值或缺口次数计。官方元数据六值分别列于§8，不计未验证；已有规则的代码出处只证明实现，不证明真实链路。下表P01–P05有既有裁定/实现出处；U01–U12共12项，T-R79c累计计数为 **已验证 0／部分核实 11／未验证 1**（三类互斥，合计12）：沿用T-R79b的6项公开事实部分核实，新增U04/U05/U06/U10/U12共5项部分源码核实；U11仅取值来源已核，校准问题仍归未验证。部分核实项的整项状态仍为「未验证」，因此尚未整项验证的总数仍为12。包含尚无值的映射/版本参数，不填任意默认值。每项适用用例已在规则列给出。

T-R79b公开查证/访问日期统一为2026-11-15。公开出处仅采纳编制方、交易所官方原文；网页HTTP成功不等于正文或数据已核实。单张日期是资料截至日，编制规则只有年月时仅记录版本月，均不冒充精确发布日期。公开原文只能核实其明确覆盖的部分，不能证明仓库接线、历史可见性或策略有效性。下列B01–B10是本节的公开出处，O1–O4沿用§8。

| ID | 参数/口径组 | 值与出处 | 核对状态/用例 |
|---|---|---|---|
| P01 | 主辅身份 | 000300/000985；T-R71 README §3、四卡§11 | 既有裁定；R01 |
| P02 | h、时区、日入场/估值 | 1/5/20、Asia/Shanghai、09:30/15:00；plan §2.8、E:23–44/154 | 既有口径；R05/R06/R10 |
| P03 | 收益差与精度 | 简单差、Decimal64、4位half-up/展示2位；E:47–58/278–282、契约T-A27 | 既有实现/裁定；R15/R16 |
| P04 | Stat显示阈值 | n<5空、n<30不足；契约§5.1/§7.11.3、S:431–440 | 既有口径；R19 |
| P05 | unavailable重算期 | 到期后5个交易日；契约T-A33(1) | 既有裁定、代码未遵守；R13 |
| U01 | B11源身份/字段适配 | 000985源代码/市场映射、OHLC解析校验；T-R72 B11、F50只证明000300小样本。**已核部分**：O3明确官方代码000985；O4分别列指数代码000985、路透.CSI000985、彭博SH000985。**仍未验证部分**：B11的dm/jys及SH/SZ后缀、历史目录映射、字段解析；官方代码表示不是供应商适配凭证，需脱敏目录样本、字段说明及后端映射验收。 | 未验证（部分核实）；R03；O3/O4日期与短摘录见本节出处表 |
| U02 | 定稿/可见性参数 | 预计17:10据T-R72 A02及B11存档。**已核部分**：B01 §2.5支持收盘指数在指数交易日每日发布，§2.1仅说明异常由编制方视情况处理。**仍未验证部分**：精确收盘行情发布时间、17:10最终定稿保证、错误重发政策原文、实际final证据及available_at/first_seen语义；需来源方发布时间/修订通知及逐行首次入库审计。除数修正不等于已发布行情纠错。 | 未验证（部分核实）；R08/R09；补查词「收盘 发布时间 17:10」「指数管理基本规则 重新计算 错误 六个月」，站点csindex.com.cn、sse.com.cn，2026-11-15；未取得足以证明剩余部分的官方原文 |
| U03 | 完整日历版本 | PN-03 §2已定合并来源/边界。**已核部分**：B02–B06是上交所2012/2023/2026、深交所2024/2026休市通知，可作对应年份核对参照。**仍未验证部分**：2012年以来沪深逐年通知集合与临时变更尚未齐备，更未逐日比对实库；真实覆盖/sha/重叠一致性未知。需逐年原通知及补充通知清单、自然日对账、合并版本hash和边界重叠报告。 | 未验证（部分核实）；R05；检索站点sse.com.cn、szse.cn，词「2012年 全年/部分节假日 休市安排」「2013–2025 休市安排」「2026年 部分节假日休市安排」，2026-11-15；深交所2012原通知未取得，不能以转载补证 |
| U04 | 个股qfq因子/可成交事实 | **已核实（源码）的部分**：同一cutoff筛可见因子并锚定qfq、缺因子不补1；停牌/涨跌停/forced_hold及未知事实分流，详C04的代码与测试。**仍未验证部分**：真实因子与复杂权息事件对账、版本/首次可见、停复牌及持仓事实接线。公开出处不适用；需实库对账及后端验收。 | 未验证（部分源码核实）；R08/R11/R21；C04；SQL Q01/Q02 |
| U05 | 单源整窗快照 | **已核实（源码）的部分**：生成/观测/结果摘要校验、算法版本和原始价格输入快照、完成后保留旧结果，详C05。**仍未验证部分**：读取未筛source，快照未冻结日历本体/目录版本及整窗来源manifest；单源data_version/hash重放与混源拒绝未实现验收。T-R71 §3禁止混拼，严格拒绝组合仍为本卡draft，外层hash不证明上游来源。 | 未验证（部分源码核实）；R04/R22；C05；SQL Q03/Q05 |
| U06 | 指数端点与完整性报告 | **已核实（源码）的部分**：当前指数只取可见且final的两端，缺基准不抹掉可算股票收益，详C06。**D03已裁定：端点与完整性分开**（T-A190 D03），中间缺日/非端点OHLC缺项不清空可信端点收益。**仍未验证部分**：缺后端整窗/缺日用例与实库覆盖，尚未验收完整性字段、逐日gap及端点收益并存；官方每日发布不证明整窗已验证。 | 未验证（部分源码核实）；R12；D03；C06；SQL Q04 |
| U07 | 全收益及分红偏差 | **已核部分**：O2/O4第2页明确H00300/H00985全收益系列；B09/B10的2018-01单张各自列出基日2004-12-31、发布日期2005-04-08/2011-08-02；B01 §2.2/§3.2.1区分分红处理。**仍未验证部分**：仓库接入、入场开盘点位及偏差量化无证据。需全收益来源接线、端点可得性核对和同窗价格/全收益实测对照；旧单张仅用于身份日期，不代表现行样本/编制规则。 | 未验证（部分核实）；R02；查csindex.com.cn，词「H00300 H00985 基日 发布 全收益」并访问两条H代码详情页，2026-11-15；详情页仅返回JS壳，日期改由B09/B10官方PDF核实 |
| U08 | 发布前/更名映射政策 | **已核部分**：O2/O4价格指数基日均2004-12-31，发布日分别2005-04-08/2011-08-02；B07为更名且编制方法不变的官方实例。**仍未验证部分**：该实例不证明000300/000985历史目录连续性；未取得两指数发布前回溯数据的完整可见性说明，D06已裁定回溯数据不得充当当时真实可见基准。仍需编制方具体变更/连续性文件、带有效期源目录及回溯数据说明以验收。 | 未验证（部分核实）；R14；D06；查csindex.com.cn、sse.com.cn，词「历史回溯 数据 发布前」「指数更名 代码保持不变」「上证市值100 名称变更」，2026-11-15 |
| U09 | 盘中分钟/复权衔接 | E:235–240已有缺口。**已核部分**：B01 §2.5及O1 §12.3说明实时频率以行情系统接口为准，未给统一固定秒数。**仍未验证部分**：B11分钟槽START/END、下一分钟开盘定义、跨午休/日界处理及个股qfq桥全链。需对应接口版本、时间标签样本及股票/指数同槽后端验收。 | 未验证（部分核实）；R07；D08；查csindex.com.cn、sse.com.cn，词「指数 实时 行情 发布频率」「指数 分钟 开盘」，2026-11-15；实时发布不证明分钟OHLC已接入 |
| U10 | 实际观察as_of与迟到补算 | **已核实（源码）的部分**：C10记录旧实现钳制到期日结束、非pending跳过等缺口，不是目标口径。**D04已裁定**：首次评估及第1–5个开市日的unavailable修订均以实际运行/补算时点为as_of；available_at、first_seen_at≤该次as_of（带时区瞬时比较），行情日期≤D_h、两端qfq同锚；冻结实际as_of、输入及算法/日历/source/数据版本，旧版可重放且不倒填可见时点。complete/untradable/excluded逐条冻结，股票complete缺基准不解冻，新增对照仅研究包；日历未知不推进5日，第5日作业具体钟点「未验证」。**仍未验证部分**：整项验收仍需逐版重放证据。G1→T-B171 承接补算窗口、当前指针与终态冻结；G2→T-B173 承接逐版本可见性、定稿及快照留证。依据为 [#230 契约 §1、§2、§4.1、§5](../../contracts/tracking-benchmark-pit-and-groups.md)。 | 未验证（部分源码核实）；R08/R13；D04；C10；SQL Q05/Q06 |
| U11 | hold方向阈值校准 | **取值来源已核实（源码）**：1/2/5个百分点为E:16常量，沿plan §2.8.1/§9 C(7)，E:76–83用闭区间判断；边界测试只证实执行这些初值（C11）。**T-R80结论：证据不足，校准有效性仍未验证**。公开日线无真实hold建议样本；2015–2026-11-10全量T信息基线带内率为42.01%/35.87%/40.48%，n=11,333,902/11,259,954/11,063,413（h=1/5/20）；OOS−IS为−4.60/−2.12/−1.01个百分点。仅说明初值未出现全样本近0%/100%的退化，不证明建议正确率或跨年度稳定有效。不复权、ST不可识别、快照覆盖及日线开盘成交证据不足等限制见[离线复测](README.md#t-r80u11离线校准检验)。需真实样本、版本/状态分层、时间外留出及审批；Q07只盘点样本数量。不是交易所阈值，初值不变。 | 未验证（证据不足）；R17；C11；SQL Q07（样本盘点） |
| U12 | 辅槽/分组与展示扩展 | **已核实（源码）的部分**：同版本实例择最早/并列id最小，按版本/周期/scope隔离，均值/超额/方向分别取非null n，n<5空/n<30不足，详C12。**仍未验证部分**：辅槽、metadata/源版本分组、共同配对n、额外统计gap和负零展示仍为draft，无完整实现/测试证据；按已裁定D02/D07完成字段设计和后端/展示验收；策略版本×期限×动作×生成时置信度为必选组合，各槽各报有效n，对外新增字段暂缓。G3→T-B174 承接按生成快照绑定分组、当前结果去重和逐指标有效 n，验收依据为 [#230 契约 §3、§4.2](../../contracts/tracking-benchmark-pit-and-groups.md)。辅槽及配对统计仍待验收。 | 未验证（部分源码核实）；R16/R18/R19/R21/R22；D02/D07；C12；SQL Q07 |

### T-R79c内部项源码核证（2026-11-15）

核对当前分支`0609313`的源码、测试定义和契约；本节涉及的tracking、pipeline、模型及两个测试文件与本地`origin/main=95967e1`无差异，未刷新远端。**“已核实（源码）”只证明实现逻辑及仓库测试所声明的断言，不证明真实数据链路、实库状态或参数有效性。** 本次仅读测试源码，未运行下列会建库/连库的后端测试；文档checker通过也不等于这些测试已在本次执行。

为保留整项问题的原范围，五项拆为已核逻辑与未验证链路/扩展，整项仍为「未验证（部分源码核实）」；U11的目标是校准，取值出处不能减少待校准项，单列「未验证」。源码历史核证不代表目标口径；D01–D08已按T-A190同步至§9。

**C04 → U04：因子/可成交事实，部分源码核实。** 规范边界：`docs/contracts/trading-calendar-exrights.md:35–41,47`，事件版本/可见性缺失仍阻断，不以registered_at自动替代available_at。

- 已核实（源码）：`src/backend/app/features/pipeline.py:151–164,198–215`按因子date/available_at筛选、无因子返回None、价格乘当日因子/锚定因子；`src/backend/app/tracking/engine.py:242–253`同cutoff取入场open_qfq及退出close_qfq，缺端点记gap。`src/backend/app/tracking/service.py:243–254`从观测快照读取factors/facts并过滤事实时点，`:270–312`校验生成时绑定账户及holding可见性后才定forced_hold；`src/backend/app/tracking/engine.py:198–234,322–330`对停牌/涨跌停、被动hold及未知事实分流。
- 对应测试：`src/backend/selfchecks/test_p2n03_tracking.py:155`的`test_real_calendar_boundaries_entry_reference_independent_qfq_and_benchmark`（1/5/20及虚构拆股）；`:211`的`test_untradable_excluded_unknown_never_enter_valid_n`（停牌、涨跌停、forced、未知）；`:243`的`test_missing_benchmark_factors_calendar_and_future_knowledge`（未来因子不可用）。这些合成断言不覆盖复杂权息真实性；账户/holding绑定检查的源码存在也不等于真实接线验收。
- 仍未验证：`src/backend/app/tracking/service.py:78–85`没有保留行情行is_suspended，facts独立输入是否完整未知；新建的权息事件表并不等于已接入tracking因子。需逐事件因子/版本/首次可见对账、停复牌及forced_hold绑定的实库验收。只读草稿[Q01/Q02](readonly_checks.sql)检查事件库存、因子/事实结构与可见性，不能自动重建可信因子。

**C05 → U05：快照/重放，部分源码核实。** 规范边界：`docs/strategies/T-R71/README.md:42,44`要求冻结source/因子版本，不逐行跨源择优。

- 已核实（源码）：`src/backend/app/tracking/service.py:34–39,110–116,204–216`定义canonical摘要并拒绝观测/生成摘要不符；`:346–376`保存算法版本、生成/观测摘要、原始股票/分钟/主基准及as_of，`:421–427`读结果时验hash。`src/backend/app/tracking/service.py:232–237`跳过冻结结果或未到期pending；这是保留旧结果，并非重算验证。
- 对应测试：`src/backend/selfchecks/test_p2n03_tracking.py:405`的`test_actual_p1_worker_tracking_snapshots_api_replay_pit_and_ownership`在合成行情被修改后断言API内容和snapshot_id不变（`:428–443`）；`:602`的`test_pending_wall_clock_replay_keeps_same_rows_and_snapshot_ids`覆盖pending。`src/backend/selfchecks/test_ta27_tracking.py:179`的`test_actual_worker_multiple_instances_earliest_then_uuid_and_frozen`在`:254–261`断言算法版本及原始股票first_seen_at≤cutoff；这些测试未单独构造摘要篡改反例，摘要拒绝分支的依据是上述源码，不外推测试覆盖。
- 仍未验证：`src/backend/app/tracking/service.py:55–95`未筛source且丢掉source等字段；`:346–358`没有日历本体、指数目录/来源版本manifest。`src/backend/app/db/tables/market.py:379`主键为code/trade_date/adj_type，不能当作多修订历史。SQL Q03/Q05只能盘点当前来源与快照结构；单一source/合法hash形状不证明整窗同版重放或混源拒绝。

**C06 → U06：指数完整性，部分源码核实。** 规范边界：`docs/api-contract.md:1288`规定缺基准相关结果为空；**D03已裁定：端点与完整性分开**（T-A190 D03），R12不再以中间缺日/非端点OHLC缺项阻断可信端点收益。

- 已核实（源码）：`src/backend/app/tracking/engine.py:267–284`先筛final/first_seen/收盘时刻，再仅用入场日open及到期日close；`:326–330`股票complete不依赖基准非空。`src/backend/app/tracking/service.py:68–84`只收四价正数且已收盘的行，直接赋is_final=true；这不是上游定稿证据，也没有独立的整窗完整性报告。
- 对应测试：`src/backend/selfchecks/test_p2n03_tracking.py:155`的`test_real_calendar_boundaries_entry_reference_independent_qfq_and_benchmark`覆盖可见两端的1/5/20计算；`:243`的`test_missing_benchmark_factors_calendar_and_future_knowledge`断言全缺基准时股票可complete、超额/方向为空；`:478`的`test_benchmark_future_revision_is_not_historical_knowledge`断言晚可见基准被排除。这些端点用例不能证明整窗完整性报告已通过。
- 仍未验证：缺后端整窗/缺日用例与实库覆盖；须专门覆盖两端齐/中间缺日、非端点OHLC缺项、缺任一端点及非法OHLC，分别核对收益与完整性/gap。SQL Q04只相对于库存日历和指定source诊断覆盖。日历版本、首次可见、真实final须另验；空集不能通过。

**C10 → U10：截止/补算，部分源码核实。**

- 已核实（源码）：`src/backend/app/tracking/engine.py:168–175`和`src/backend/app/tracking/service.py:232–242`仍钳制到期日结束（已废止的旧口径，待后端修复）；后者跳过非pending。`src/backend/app/tracking/engine.py:267–272`拒绝晚可见指数行。`src/backend/app/tracking/service.py:377–384`把含unavailable的非pending结果也映射为done，故后续作业会跳过它。
- 对应测试：`src/backend/selfchecks/test_p2n03_tracking.py:478`的`test_benchmark_future_revision_is_not_historical_knowledge`证明合成晚可见行不可用；`:405`的`test_actual_p1_worker_tracking_snapshots_api_replay_pit_and_ownership`证明已完成结果不因后续行情变化而改写；`:602`的`test_pending_wall_clock_replay_keeps_same_rows_and_snapshot_ids`证明未到期重复作业不增快照。这些测试没有覆盖unavailable在到期后逐日重算成功。
- 仍未验证：`docs/api-contract.md:1301–1303`要求unavailable在到期后5个交易日每日重算；D04已裁定实际补算as_of与逐结果冻结，当前服务行为存在差异，不能标整项已核实。SQL Q05/Q06核对现存as_of/状态/快照结构；单次SELECT不能证明五日作业历史、可见时点未倒填及原版重算确定性，仍需跨日审计与后端重放验收。

**C11 → U11：仅取值来源已核，校准仍未验证。**

- 取值来源已核实（源码）：`src/backend/app/tracking/engine.py:16,76–83`固定1/2/5个百分点并用≤判断，规范来源为`docs/plan.md:1277,4084`（§2.8.1及§9 C(7)初值；沿原约定累计n≥30后由管理员复核分布，不能将n≥30等同校准有效）。`src/backend/selfchecks/test_p2n03_tracking.py:544`的`test_hold_band_exact_inclusive_and_epsilon_outside`对三个周期、正负两侧测试恰等于和超过0.000001；`:202`的`test_six_actions_direction_not_inverted`补动作分支。测试只证明执行既定常量，没有校准结果。
- 复测要求：先冻结真实候选产生时的hold样本/策略版本、主基准、as_of及可成交排除口径，分别对1/5/20与市场状态分层；按时间切分校准集/留出集，窗口相互重叠时隔离跨集合重叠并按证券/日期簇处理依赖。预先固定评价指标和阈值比较方案，报告各层n、缺失/排除数、留出集带内率/误判率及置信区间、邻近阈值敏感性和跨阶段稳定性；不足样本不下有效性结论，完成审批留证后才可评价校准。Q07只统计可用hold数量，不能得出阈值合理或晋级结论；本单不调整初值。

**C12 → U12：现有分组/样本统计，部分源码核实。** 规范边界：`docs/api-contract.md:1289–1290,1299`的Stat、匿名scope及唯一观测键；主辅身份见`docs/strategies/T-R71/README.md:40`。

- 已核实（源码）：`src/backend/app/tracking/service.py:138–168`同版本实例按创建时间、并列UUID择一；`src/backend/app/tracking/api.py:63–106`隔离scope/版本、去重建议×版本×周期，再对complete分别收集收益/方向/超额非null集；`:115–126`输出分周期Stat。`src/backend/app/tracking/service.py:431–440`均值n<5空/n<30不足，统计未乘反动作收益。
- 对应测试：`src/backend/selfchecks/test_ta27_tracking.py:179`的`test_actual_worker_multiple_instances_earliest_then_uuid_and_frozen`断言择最早/并列最小、other_instance留证及各周期n=1，`:274–285`核mine/site计数与匿名输出；`src/backend/selfchecks/test_p2n03_tracking.py:503`的`test_actual_multiple_strategy_versions_are_independently_persisted`断言两版本独立且单建议各周期n=2；`:269`的`test_stat_thresholds_and_no_auto_feedback`覆盖n=0/4/5/29/30；`:567`的`test_api_empty_anonymous_foreign_unknown_version_and_no_get_side_effect`覆盖空集、匿名和GET无副作用。并非辅槽/配对n测试。
- 仍未验证：`src/backend/app/tracking/models.py:24–29`只有单个benchmark字段组；`src/backend/app/tracking/service.py:245,388`固定000300.SH；`src/backend/app/tracking/api.py:97–134`未按来源版本/动作/置信度分组且只聚合盈亏比gap。按已裁定D02/D07，辅槽/metadata仅内部包；策略版本×期限×动作×生成时置信度必选分组、逐槽有效n、共同有效集n、额外统计gap及负零展示仍需完整验收。Q07只能复核一个快照的分组n，不能代替API跨建议去重或辅槽验收。

只读核对入口：[readonly_checks.sql](readonly_checks.sql)，Q01–Q07共7条，逐条列了迁移/模型出处、参数和期望判读。**草稿，未执行；仅供运维在本地栈只读执行，执行需另行授权。** 没有为尚不存在的来源版本列、辅槽表或因子表编造SQL；只读查询不能代替D03口径的后端验收、D04补算/冻结口径的后端验收或U11样本外复测。

### 本次公开出处及短摘录

短摘录逐条不超过60字；表格字段摘录按原列名和值记录，不将它们拼成原文完整句。日期列区分文档发布日、版本月和资料截至日；未知日期不从URL路径猜测。

| 编号 | 官方原文URL | 发布日期或可核日期 | 原文短摘录及支持范围 |
|---|---|---|---|
| O3/O4 | [中证全指编制方案][r79b-o3]、[中证全指单张][r79b-o4] | O3版本2023-12 V1.2（发布日未标）；O4截至2026-10-30（发布日未标） | O3：「指数代码：000985」。O4字段：「路透代码 .CSI000985」「彭博代码 SH000985」；不能推导B11后缀。 |
| O2/O4 | [沪深300单张][r79b-o2]、[中证全指单张][r79b-o4] | 两单张截至2026-10-30（发布日未标） | 第2页字段分别为「全收益指数 代码 H00300」「全收益指数 代码 H00985」；仅核系列存在。 |
| B01 | [中证指数有限公司股票指数计算规则][r79b-b01] | 版本2024-07 V1.1（具体发布日未标）；B08现行栏目附件也收录此版本 | §2.5：「指数发布频率为指数交易日每日发布。」；实时频率按接口定义，分红处理见§2.2/§3.2.1。未载17:10或本库首次可见时间。 |
| B02 | [上交所2012年全年休市通知][r79b-b02] | 2011-12-23 | 「另外，3月31日（星期六）、4月1日（星期日）为周末休市。」支持调休周末仍休市，不能只排法定假日。 |
| B03 | [上交所2023年全年休市通知][r79b-b03] | 2022-12-27 | 「另外，10月7日（星期六）、10月8日（星期日）为周末休市。」仅作该年参照。 |
| B04 | [深交所2024年部分节假日休市通知][r79b-b04] | 2023-12-26 | 「节假日期间清算交收事宜，按照中国证券登记结算有限责任公司的有关安排进行。」休市与清算安排须区分。 |
| B05 | [上交所2026年部分节假日休市通知][r79b-b05] | 2025-12-22 | 「另外，1月4日（星期日）为周末休市。」仅作2026年日历参照。 |
| B06 | [深交所2026年部分节假日休市通知][r79b-b06] | 2025-12-22（网页日期） | 「另外，1月4日（星期日）为周末休市。」与沪市对应条款一致不代表全历史覆盖已验证。 |
| B07 | [上证市值100指数名称变更公告][r79b-b07] | 2012-08-20；更名生效2012-09-04 | 「指数编制方法没有变化。」仅证明公告指定系列的更名事实，不外推至本卡两指数。 |
| B08 | [上交所指数计算与修正栏目][r79b-b08]及[股票指数规则合订附件][r79b-b08pdf] | 栏目列示2025-11-14；附件中计算规则仍标2024-07 V1.1 | 计算规则§2.5：「指数更新频率以中证指数通、交易所或其他第三方行情发布系统接口定义为准。」不声称实时频率为固定3秒或5秒。 |
| B09 | [沪深300全收益指数单张][r79b-b09] | 资料月份2018-01（单张发布日未标）；指数发布日期2005-04-08 | 字段：「指数代码 H00300」「发布日期 2005年4月8日」「基日 2004年12月31日」。 |
| B10 | [中证全指全收益指数单张][r79b-b10] | 资料月份2018-01（单张发布日未标）；指数发布日期2011-08-02 | 字段：「指数代码 H00985」「发布日期 2011年8月2日」「基日 2004年12月31日」。 |

[r79b-b09]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H00300factsheet.pdf
[r79b-b10]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/H00985factsheet.pdf
[r79b-o2]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300factsheet.pdf
[r79b-o3]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175438-000985_Index_Methodology_cn.pdf
[r79b-o4]: https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000985factsheet.pdf
[r79b-b01]: https://oss-ch.csindex.com.cn/contract/cms_add/20240726155028-%E3%80%8A%E4%B8%AD%E8%AF%81%E6%8C%87%E6%95%B0%E6%9C%89%E9%99%90%E5%85%AC%E5%8F%B8%E8%82%A1%E7%A5%A8%E6%8C%87%E6%95%B0%E8%AE%A1%E7%AE%97%E8%A7%84%E5%88%99%E3%80%8B.pdf
[r79b-b02]: https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988508.shtml
[r79b-b03]: https://www.sse.com.cn/disclosure/announcement/general/c/c_20221227_5714458.shtml
[r79b-b04]: https://www.szse.cn/disclosure/notice/t20231226_605108.html
[r79b-b05]: https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml
[r79b-b06]: https://investor.szse.cn/disclosure/notice/general/t20251222_618087.html
[r79b-b07]: https://www.sse.com.cn/aboutus/mediacenter/hotandd/c/c_20150912_3988598.shtml
[r79b-b08]: https://www.sse.com.cn/market/sseindex/calculation/
[r79b-b08pdf]: https://www.sse.com.cn/market/sseindex/calculation/c/10798408/files/b23afc2067304f9393e17bd06b253ced.pdf

没有引入指数收益容差、交易日推测比例、插值天数或缺数率放行阈值；无出处的精确取值不启用。价格指数的研究含义与真实执行收益不能合并。

## 8. 官方元数据核对记录

核对日2026-11-15，仅访问公开中证网页/PDF；没有请求任何麦蕊接口。URL为编制方原站资料；单张为本次读取所示2026-10-30版、编制方案为链接内2023年版本，不声称核验其全部现行编制规则。这里只记录身份元数据与价格/全收益区分，不保存成分股或真实行情。

| 指数 | 基日 | 基点 | 发布日 | 依据 |
|---|---|---|---|---|
| 沪深300（000300） | 2004-12-31 | 1000点 | 2005-04-08 | O1 §1/§4.1，O2 第1页基本信息 |
| 中证全指（000985） | 2004-12-31 | 1000点 | 2011-08-02 | O3 §一/§二，O4 第1页基本信息 |

- O1：[沪深300编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300_Index_Methodology_cn.pdf)，2023-09版；§4.6/§5.2.1区分价格、全收益/净收益及分红处理，支持R02的偏差提示。
- O2：[沪深300指数单张](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000300factsheet.pdf)，第1页身份元数据；第2页将全收益/净收益列为衍生系列。
- O3：[中证全指编制方案](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/20231208175438-000985_Index_Methodology_cn.pdf)，2023-12、V1.2；§一/§二核代码、基日/基点。
- O4：[中证全指指数单张](https://oss-ch.csindex.com.cn/static/html/csindex/public/uploads/indices/detail/files/zh_CN/000985factsheet.pdf)，第1页核发布日；第2页另列全收益/净收益系列，不能把000985价格点位标为全收益。

这些事实不证明B11路由后缀、库覆盖、分钟开盘、历史可见性或全收益数据已接入；这些仍按U01/U02/U07/U09处理。R14【虚构】用例说明发布日前后准入，不将基点当真实开盘报价。

## 9. 裁定登记（8条；均已由T-A190裁定）

| ID | 裁定状态与内容 | 本draft落实口径（对应规则/用例） |
|---|---|---|
| D01 | 已裁定（T-A190 D01）：主辅固定 | 主沪深300、辅中证全指，板块/周期不换基准；辅槽不补主槽、行业缺口不以大盘替代；R01 |
| D02 | 已裁定（T-A190 D02）：现API保留主槽 | 辅槽、行业槽、完整metadata留关联唯一观测键的内部研究包；对外扩展暂缓，不重复观测，GET只读、site匿名聚合；R01/R18/R21 |
| D03 | 已裁定（T-A190 D03）：端点与完整性分开 | 可信同源同版、定稿且PIT可见的两端齐则正式计算收益/超额；中间缺日/非端点缺项只影响完整性字段及逐日gap，不宣称整窗已验证；缺端点则null+`benchmark_prices`，缺日历按R05不算；R12 |
| D04 | 已裁定（T-A190 D04）：实际as_of补算与逐结果冻结 | 首次评估及到期后第1–5个开市日unavailable修订均冻结实际运行/补算as_of、输入、算法/日历/source/数据版本；available_at、first_seen_at≤该次as_of（带时区瞬时比较），行情日期≤D_h、两端qfq同锚；旧版可重放，不把晚到值写成旧时点已知。complete/untradable/excluded逐条冻结，股票complete缺基准仍冻结，新增对照仅研究包；日历未知不推进5日，第5日作业具体钟点「未验证」；R08/R13 |
| D05 | 已裁定（T-A190 D05）：采集适配层负责指数输入 | 指数适配、身份映射、定稿/可见性审计与版本保存/available_at归采集适配层，跟踪层只消费冻结包；真实B11接入暂缓，无可核验映射/时点/source/version/is_final则该槽null/unavailable，17:10不是定稿保证；R03/R04/R08/R09 |
| D06 | 已裁定（T-A190 D06）：发布前回溯不得当时可见 | 发布前或更名未核均null；同系列/尺度及历史映射连续性证据齐全才续接；事后回溯另包，不混正式PIT统计；R14 |
| D07 | 已裁定（T-A190 D07）：必选组合及逐槽有效n | 策略版本×期限×动作×生成时置信度必选分组，置信度取生成快照原标签，未知单列；各槽各报有效n，另报主辅配对n、配对集基准均值；源/版本口径及窗口模式隔离，不将每条数据版本当独立统计口径；新增对外字段暂缓，n<5空/n<30小样本；hold初值1/2/5不变且校准未验证；R18/R19/R20 |
| D08 | 已裁定（T-A190 D08）：盘中收益继续unavailable | 同一紧邻分钟槽指数开盘与个股qfq桥均有可核验证据前保留缺口，不用日开、前收或后一个有数据分钟替代；R07 |

后端可按R01–R22及已裁定D01–D08建立离线合成验收；实现/证据未验证部分继续保留缺口。真实基准就绪至少需要B11身份/定稿/版本链、同日历窗口及独立完整性报告、个股同as_of qfq及可成交性证据；本单只交付规格与文档检查，不报告这些真实门槛已通过。

## 10. 变更记录

- T-R79d（2026-11-15）：按T-A190 D03/B01修R12，端点可算性与整窗完整性分开报告，同步U06/C06、D03及相关引用；本次修订限于B01，lifecycle保持draft。后继分工为 G1→T-B171（补算与冻结）、G2→T-B173（基准输入版本与可见性）、G3→T-B174（生成时置信度分组），见 [#230 契约 §0、§4](../../contracts/tracking-benchmark-pit-and-groups.md)。[T-R79d 原始提交](https://github.com/ashare-invest-lab/ashare-invest-assistant/commit/1274b79339e31d6cb018c8bfd9640ad114a44d55)只写“G02–G04等缺口”。G04 的原始定义、是否误号及承接单尚待确认。[治理复核记录](https://github.com/ashare-invest-lab/ashare-invest-assistant/pull/210#issuecomment-6910646080)。

- T-R84（2026-11-15）：按#210评审及T-A190 D04改为实际运行/补算as_of、逐结果冻结与旧版重放，同步R08/R13虚构例/U10/C10/D04和只读Q06；补D05采集适配层职责、D07必选组合与逐槽有效n，同步D01–D08裁定状态；U11临时目录改平台默认，lifecycle保持draft。

# T-R79｜模拟跟踪真实基准口径卡

状态：draft；日期：2026-11-15；核对基线：`origin/main = 95967e1`。本文是后端实施规格草案，不代表真实数据验证、接口上线或策略晋级。仅研究候选信号；模拟不代表实际收益，不构成荐股或收益承诺。

## 1. 范围、依据与引擎盘点

只定义 tracking 的 T+1/5/20 同期基准与超额。候选条件、实际成交账本、F50 环境判定和模拟观察分别留证；T+1 收盘是观察估值，不表示当天新买股份可以卖出。本文不改变四卡策略周期，也不把 RC5 的周期映射变成基准选择规则。

引用缩写：E=`src/backend/app/tracking/engine.py`，S=`src/backend/app/tracking/service.py`，W=`src/backend/app/tracking/worker.py`，A=`src/backend/app/tracking/api.py`，M=`src/backend/app/tracking/models.py`；下表行号均为上述基线。契约优先于实现；下文标“draft 新增”的规则不能当成仓库已有裁定。

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
| 修订重算 | 所有非 pending 结果被跳过；与契约要求 unavailable 到期后 5 个交易日内每日重算有差异；截止时刻又被钳制在到期日结束 | S:232–242；`docs/api-contract.md` §7.11.3 T-A33(1) |
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

逻辑输出包采用以下字段供实施映射，**不是现行 API 已有 schema**：主槽映射现有 `benchmark_*`/`excess_pct`；辅槽、行业槽及 metadata 暂留内部草稿证据，接口承载待 D02。不要复制现有观测为三条、导致样本翻倍。

| 字段 | 类型与含义 |
|---|---|
| observation_key | `(suggestion_id, strategy_version_id, horizon_days)`；同版本多实例仍一条 |
| window | `signal_at, entry_at, exit_at, as_of, sessions, calendar_version`；日历未知时 entry/exit 可为 null |
| benchmark_slots | `primary/secondary/industry` 三槽；各含 `benchmark_id, benchmark_code, status, entry_points, exit_points, benchmark_return_pct, excess_pct, gap_keys` |
| status | 内部取 `pending/complete/unavailable`；基准 complete 只表示该槽输入可计算，不改变个股 state；行业固定 unavailable 至 B12 核验 |
| basis | `price_index, adjust=none, unit=index_points, formula=arithmetic_difference, cost_applied=false, dividend_bias=true` |
| provenance | `source, source_endpoint_template, source_symbol, source_market, security_type=index, data_version, content_sha256, directory_version, methodology_version`；端点与逐日行引用可解析 |
| times/quality | 每行 `trade_date, data_as_of, available_at, first_seen_at, fetched_at, is_final, finality_evidence_id, row_revision`；时间均带时区 |

非数值结果使用 JSON null；成功零收益可以为 `"0.0000"`。受影响数值 null 必列缺口码和日期/字段证据。码无优先级覆盖，独立检查产生的码去重、字典序输出；无法确定日期的检查不猜日期。原有 Gap.reason 沿实现为 no_source，细分语义用 Gap.key；本文新增键均是 draft，未声称已在 API 实现。全局元数据不可信会阻断该槽；已知局部缺数可保留可信端点，收益/超额依规则置 null。股票收益可保留且单独带其自身缺口。

## 3. 身份、选择与数据来源

### R01 主辅固定、行业隔离

沿 T-R71 README §3 及四卡 §11：主=沪深300 `CSI:000300:price`，辅=中证全指 `CSI:000985:price`；指数身份与供应商市场后缀分开。所有 h=1/5/20 均分别计算，不取表现更好者，不取平均，不用辅槽补主槽。按板块/周期切换无既有裁定，列 D01，当前无切换。B12 未接入，行业收益/行业超额=null，`industry_benchmark_unverified`；不能直接把当前行业成员用于过去。

【虚构】个股收益4%，主指数2%、辅指数3%：主超额2个百分点，辅超额1个百分点，行业=null+`industry_benchmark_unverified`。把同一候选从 short 分组移到 swing 分组，主辅身份不变；主缺数时主超额=null，不能拿辅超额1填入。

### R02 价格指数、分红偏差与费用

沿 E:267–282、F50 的 none，以及 §8 O1–O4：本卡使用价格指数点位，不给指数应用个股 qfq 因子；币种人民币是编制信息，点位单位仍为 index_points。仓库本次核对的 tracking/契约链没有可用全收益指数接线；官方存在全收益系列不等于已有数据源。个股 qfq 与价格指数相比的超额**含分红口径偏差**，不得称总回报超额/纯 alpha，偏差大小未验证。保留 `dividend_bias=true`、提示键 `benchmark_total_return_unavailable`，不因这条限定抹掉合法价格指数收益。当前毛收益不扣费用，cost_applied=false；成本研究须另列，不能默认真实成本为0。

【虚构】同窗个股 qfq 100→102，价格指数1000→990：2%−(−1%)=3个百分点。另给一条仅用于解释的合成全收益1000→1000，比较值为2个百分点，相差1个百分点；不得拿这条合成序列替换主基准。指数点位1000→1000是真实输入相等产生0%，不是缺数补0。

### R03 B11 字段与身份校验

只把团队 T-R72 §7 B11 的 `/hsindex/list` 与 `/hsindex/history/{index}.{market}/d` 作为待接入路由模板，不记录含证书的实际 URL，不发请求。字段依据：团队归档 `reports/codex/T-R72/web/txt/hszsdata.txt`「沪深主要指数列表接口」「历史分时交易」：dm/mc/jys 对应源代码/名称/市场，t/o/h/l/c/v/a/pc 对应交易日期/OHLC/量/额/前收；本卡收益只使用 o、c。指数 v/a 单位未核，不借股票 v×100 规则，非收益必需字段可空且不得参与计算。

日线 t 规范化为北京 trade_date，接受合法日期或时间部分为00:00:00的日期；不把该零点当 available_at。OHLC 用有限 Decimal 且均>0、low≤open/close≤high；异常行拒绝，`benchmark_invalid_bar`。供应商缺 o 时不能用 pc 或 T 收盘补开盘。dm、jys、名称/类型及冻结目录必须能唯一映射编制方身份；同号股票不允许。000300.SH 有 F50 的目录探针出处；000985 的源后缀及全历史映射仍未验证，未核则 `benchmark_identity_unverified`，不按数字前缀猜 SH/SZ。本段新增完整校验组合属 draft（U01）。

【虚构】已冻结映射 IDX-A→CSI:000300:price，t=D1 00:00:00、o=1000、h=1020、l=995、c=1010：得到D1日线与1%收益，available_at仍来自独立证据。将类型改为stock则全槽=null+`benchmark_identity_unverified`；改o=0则拒行+`benchmark_invalid_bar`，不能输出无穷收益。

### R04 同源整段与版本冻结

沿 T-R71 README §3、四卡 §16、多源契 §4：候选产生时冻结主辅角色和选源策略；**未来尚未到达的行不在 T 伪造冻结**。评估时各序列以一个可审计 source、数据快照 data_version 读取全窗，在快照内逐行保留修订和可见时点；个股与指数可有不同源，但该来源组合也须登记。辅指数独立冻结。tdx 仅独立对照，不能填进 mairui 的缺日；主源未具备整窗则给缺口。data_version 是快照标识，不要求所有日线同一 fetched_at；同一时刻多版本无法唯一选择则拒绝。无版本/hash 为 `benchmark_version_unverified`；混源为 `benchmark_source_mixed`。严格整窗单源快照检查是 draft 新增（U05），库存源优先级不能代替它。

【虚构】mairui-v1 有D1开1000、D5收1040，D3只在tdx-v7存在；禁止拼成完整窗，正式基准=null+`benchmark_source_mixed`（若输入未拼、仅缺日，则R12缺日码）。若完整tdx-v7独立对照得3%，也不能覆盖主槽空值。源名相同但版本/hash均缺→null+`benchmark_version_unverified`。

## 4. 日历、窗口与可见性

### R05 唯一日历与完整自然日

沿 E:34–44、PN-03 §2–§3：统一 Asia/Shanghai；采用 DS merged_calendar 所定义的业务日历与冻结版本，2026-08-07及以前为HF metadata、之后为config日历；重叠一致并核sha，指数日集合只核对。交易日数量不以股票有效K、指数有行日或周一至周五计。T至目标日的所有自然日须覆盖；不足h个已知后续开市日、自然日缺口→`calendar_not_covered`，due=null，收益/基准/超额=null，结果层 unavailable；兼容现行服务可无观测行、在顶层列该gap，不能假报pending。版本/hash或重叠冲突→`calendar_version_unverified`，停止整个窗口。

【虚构】自然日C0至C7全部覆盖，开市C0/C1/C3/C4/C6/C7，其余休市；T=C0，则T+1=C1、T+5=C7。删除休市C2这一条也必须due=null+`calendar_not_covered`，不是跳过C2继续。两个日历把C4分别记开/休→null+`calendar_version_unverified`。

### R06 盘后入场与各期限估值

沿 plan §2.8、E:141–154/274–282：正式盘后样本的T是候选创建时刻的北京日期，entry=D1 09:30，exit=D_h 15:00。股票用同一评价as_of的qfq open(D1)和close(D_h)，指数用none open(D1)和close(D_h)。h=1为同日开到收；h=5/20均从D1开开始，绝非T收盘到D_h收盘，也不是D1之后再数h日。不开盘成交证明与观察价格分开，按R11处理不可成交；T+1观察不主张T+0卖出。

【虚构】T收盘股票9、指数900；D1开股票10、指数1000；D1/D5/D20收股票11/12/9、指数1010/1040/1100。三窗股票=10%/20%/−10%，基准=1%/4%/10%，超额=9/16/−20个百分点。T收9与900不入公式，隔夜跳空未算入。T恰15:00按现有E:27–31不属于盘中，但源未定稿时仍不能生成合规盘后候选（R09）。

### R07 盘中边界不降格为日线

沿 E:156–167、E:235–240、api-contract §7.11.3：盘中候选必须同一下一分钟槽的股票/指数开盘，目标仍D_h收盘，不改用日开、T收或下一个“有数据”的分钟。秒非零向上取整分钟，END标签等于槽起点+1分钟；午休移13:00，15:00及以后移下一交易日09:30。当前 raw/qfq 衔接和指数分钟未验证，保留 unavailable，股票/基准/超额=null+`minute_qfq_bridge_unverified`，指数加 `benchmark_minute_unverified`；缺紧邻槽另记 `next_minute_bar`。盘中真实计算待D08，不因这套槽规则存在而开通。

【虚构】D0 10:00:30候选→槽10:01、END=10:02；仅有10:03标签不能后移入场。即使给出同槽股票10/退出11、指数1000/退出1020，算术可得10%与2%，正式输出仍为null及上述未验证码。11:30候选→13:00槽；14:59:30→D1 09:30槽，均不能用早一分钟。

### R08 信号时钟与观察时钟隔离

沿 S:238–254、E:171–175、T-R71 README §3、PN-03 §4：signal_as_of=候选生成时刻，信号只看当时已经可见且数据日期≤T的输入；观察截止 `as_of=min(run_at, D_h 23:59:59.999999+08:00)`，仅观察窗口使用D1…D_h已发生行情。所有输入版本须 available_at≤各自as_of，且首次本地可用时刻first_seen_at≤as_of；交易日收盘时刻≤as_of，不用fetched_at推翻首次可见记录。available_at无可验证来源或无时区→`benchmark_availability_unverified`；晚于as_of→`benchmark_not_visible`；股票因子同样缺口，不补1。观察同一as_of转换两端qfq，不能把它回写T候选。

【虚构】D5 17:20评估，D5收1040在17:19可见→可算4%；available_at恰17:20也允许；17:21才可见→基准/超额=null+`benchmark_not_visible`。只有fetched_at=17:19而available_at未知→null+`benchmark_availability_unverified`。D5才知的因子可用于D5观察的同尺度两端，不能加入D0候选特征。

【虚构】另给拆分窗口：股票raw入场10、末端5，已核累计因子A(D1)=1、A(D5)=2，D5观察锚=2，则qfq两端分别10×1/2=5、5×2/2=5，收益0%；指数1000→1020得2%，超额−2个百分点。若因子D6才可见，D5不得使用该转换，股票/超额=null+`qfq_prices_or_factors`；不能误算raw收益−50%。

### R09 定稿证据

沿 T-R71四卡 §5、README P1共同前置、T-R72 §7 A02及B11存档：指数日线预计17:10完成；17:10是最早采用门槛，不是保证完成。draft 适配器须保存is_final及可核验定稿证据，不得照当前S:84凭“已收盘”直接置true。在日历已到15:00但数据尚未定稿时为unavailable，相关数值=null+`benchmark_not_final`；不把实时/分钟聚合顶替正式指数日线。历史回填定稿还须满足R08的首次可见限制。

【虚构】D5 15:00已到期，日线c=1040、is_final=false→null+`benchmark_not_final`；17:10仍false，结果相同。17:18证据齐备且as_of=17:20→4%。17:09即宣称final的行不满足本路由17:10门槛，仍拒绝采用；不误报pending。

### R10 休市与末端未到

沿 E:34–44/168–169、PN-03 §3：已知休市日不消耗h，也不要求指数行，不生成休市日0收益。known due且run_at<exit_at→status=pending，基准/超额=null+`tracking_window_not_matured`（draft说明码）；run_at=exit_at已到期，再检查定稿/可见性。非开市日创建的候选沿现引擎取其日期之后第h个开市日，不倒移信号日期；这不放宽四卡盘后生成前提。

【虚构】D1后有连续2个明确休市自然日，D5仍为第5个开市日；休市无行不报指数缺日。已知D5到期，D4的价格1030不得提前算3%，输出pending/null+`tracking_window_not_matured`；D5 15:00刚到但未定稿按R09。休市日候选的下一个开市日为D1，起点仍为其开盘，不拿上个开市日收盘。

### R11 个股停牌不冻结基准

沿 plan §2.8.1、PN-03 §5、api-contract §7.11.3：个股窗口仍按市场日历走，指数独立计算整窗；中间停牌不缩短窗口、不冻结指数、不延期退出估值。入场明确停牌→个股untradable；被动hold/forced_hold/wait沿原排除规则；基准齐全仍可给描述性基准收益，但超额/方向统计排除。末日停牌且无可用qfq收盘→股票/超额=null+`qfq_prices_or_factors`，基准可算；中间停牌但两端齐备可算区间收益，路径另保留缺日gap，不填股票价格。不凭缺行或零量推断停牌，状态未知按原tradability缺口处理。

【虚构】D1开股票10、D5收11，D2/D3明确停牌；主指数D1开1000、D5收1040且5日日线齐：股票10%、基准4%、超额6个百分点，路径另记 `qfq_path_missing_sessions`。若D5收缺，股票/超额=null、基准仍4%；若D1明确停牌，则untradable、有效n=0，基准4%只作对照。

## 5. 缺数、历史身份与修订

### R12 指数缺日与完整性

沿T-R71 §5/§11的完整对齐要求，**draft新增保守规则**：每个入场至末端开市日均须有唯一、有效、定稿、可见的指数OHLC；完整性按同一日历检查，不能以两端有值宣称整窗已核验。任何缺日→该槽benchmark_return_pct/excess_pct=null，`benchmark_daily_missing:<D>`；缺入口open/末端close另列 `benchmark_prices`（兼容已有键）。日内异常/未定稿/不可见分别用R03/R08/R09的码，并计入不可用日期，不能补0、前值或插值。端点算术候选可写诊断evidence，不能写正式收益字段。此严于现E端点实现，需D03裁定。

【虚构】D1开1000、D5收1040但D3无行：端点诊断为4%，正式基准/超额=null+`benchmark_daily_missing:D3`；删D5行还加 `benchmark_prices`。D3若实际为明确休市，则不属于期内开市集，完整D1…D5定义随R05重算，不能将原D5当第5个开市日不变。

### R13 数据修订、冻结与补算

沿api-contract §7.11.3 T-A33(1)、PN-03 §4/§6：complete/untradable/excluded冻结；unavailable在到期后第1…5个开市日每日尝试，末次后仍缺则冻结，日历未知不推进期限。重放必须用原source/快照/日历/算法版本，旧值不被新版覆盖。版本缺失或摘要不符→该重放请求null+`benchmark_version_unavailable`，保留原结果原样，不伪造旧值。正式补算仍遵守R08截止，迟到版本不能倒填available_at；“补齐已在截止前可见但当次读取失败的资料”可重算，真正截止后才可见的修订保持null+`benchmark_revision_after_asof`。契约补算与现有截止冲突待D04，本文不擅自延长as_of。只缺基准但股票complete的现存行也不能越过冻结条款偷偷改写。

【虚构】v1已冻结1000→1040=4%，D6新版v2改成1050=5%：重放v1仍4%，新版本只作带独立版本号的修订对照。原unavailable在D6恢复了available_at=D5 17:19的v1，可得4%；若v2首次可见D6，则旧截止结果仍null+`benchmark_revision_after_asof`。D10（到期后第5开市日）仍缺→冻结unavailable；D11不再补算。若v1遗失→重放null+`benchmark_version_unavailable`，不是取v2的5%。

### R14 发布前历史与更名

§8官方基日不等于发布日。draft保守默认：窗口起点早于该指数发布日，即使有回溯点位，也不进入真实模拟基准，null+`benchmark_prelaunch`；发布日当天仍须有真实日开/收和可见证据，不能用基点1000补开盘。窗口覆盖更名/代码变更须有编制方连续性说明、有效区间、源目录映射和可见版本；只改名称且证明同系列、同点位尺度者可续算，缺证明→null+`benchmark_identity_history_unverified`。不自动换成ETF、继任指数或按基点比例重标；历史回溯研究/更名映射政策待D06。

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

沿api-contract §7.11.3 T-A27(3)、S:138–168、A:72–106：按唯一观测键去重，同版本实例取created_at最早、并列id最小，其他实例入证据；按策略版本、h、scope分组，主辅统计再分槽，不能混合1/5/20。draft扩展分组再固定benchmark身份/源版本组合/窗口模式，拒绝跨口径混算；动作/置信度切片按plan §2.8列D07，未知标签单列，不猜分桶。主基准有效集是股票state=complete且主E非null；辅基准用自身有效集。比较主辅时另报共同有效集n，不拿不同n暗示可比。收益、超额、方向各自报n及排除/待到期/缺数据计数；零收益是有效样本。

【虚构】6条同h候选，其中一条wait、其余5条主E均有值，辅仅4条有值；主n=5、辅n=4、共同n=4。给第1条增加第二实例，主n仍5；另有h=20的3条不并入h=5的5条。4条缺基准但个股可算的记录，计入个股收益n，不计超额n。

### R19 均值、胜率和小样本

沿S:431–440、A:97–120和契约§5.1/§7.11.3：`avg_excess=sum(E_i)/n_excess`，`avg_return=sum(R_s,i)/n_return`；新增独立基准均值`sum(R_b,i)/n_benchmark`仅在与超额配对的有效集内报告（draft）。方向胜率`sum(bool)/n_direction`用0…1比例。每项n<5→value=null，n<30→small_sample=true；n≥30仅解除样本不足标记，不代表有效性验证。draft为统计null补 `tracking_stat_n_lt_5` 说明键。无权重、无年化、无跨窗复利；每条观测等权且不能把观察数当独立交易数。scope=site仍只匿名聚合。

【虚构】同口径5条E=[2,−1,0,3,1]：均值=5/5=1.0000个百分点；buy方向[真,假,假,真,真]，胜率=3/5=0.6000，small_sample=true。只有前4条时均值=null+`tracking_stat_n_lt_5`且n=4，不能输出1；30条均为1时均值1、small_sample=false。无样本n=0同样null。

### R20 其余既有统计不伪装为基准表现

沿api-contract §7.11.3 T-A27(1)(2)、S:171–195、A:110–122：盈亏比仍取有效buy/add/hold非零股票毛收益，盈利均值÷亏损均值绝对值；n<5为null，无亏损为null+`no_losing_samples`，有亏损无盈利且n≥5为0。MDD/runup是个股qfq收盘路径统计，不是指数或超额回撤；中间缺日跳过并列gap，缺端点则两项null。当前max_loss_streak是按API建议创建顺序遍历complete的负股票收益，零或正收益清零，不是RC5超额方向失败序列；本卡不增设指数路径统计或重定义该字段。

【虚构】5条买入毛收益[4,2,−1,−3,−2]，盈利均值3、亏损绝对均值2，盈亏比1.5000；5条全盈利→null+`no_losing_samples`，5条全亏→0。路径[10,12,9,11]：MDD=−25%、runup=20%；删除12那日则路径[10,9,11]产生−10%/10%并列路径缺日gap，不能称完整路径。创建顺序收益[−1,−2,0,−3]的max_loss_streak=2。

### R21 状态和缺口传播

沿E:322–343及api-contract §7.11.3：缺基准只影响该槽的收益/超额/方向，股票complete可保留；总体data_status至少partial。主辅均缺不等于股票收益0；只有缺可计算股票价格/可成交性时才使股票unavailable。按R05日历未知与R10未到期分流，随后依次验证身份/源版本、定稿可见性、逐日日线、公式；多种独立缺口并列。辅槽失败不抹掉主槽；行业未验证始终显示，不能把行业缺口藏在主槽complete之后。新增全局/逐槽gap聚合是draft，A当前仅收集盈亏比gap的局限需实施修复。

【虚构】股票收益10%且可成交，主缺D5、辅收益3%：股票state=complete，主R_b/E/方向=null+`benchmark_daily_missing:D5`/`benchmark_prices`，辅E=7，行业=null+`industry_benchmark_unverified`，总体partial。若股票也缺qfq端点，state=unavailable、股票/双槽超额=null，但已有辅R_b=3%可以保留。

### R22 重放身份与实现验收边界

沿S:34–39/346–376、api-contract §7.11.3：结果证据需包含输入摘要、算法版本、calendar_version、各槽目录/源/数据版本、as_of、定稿/可见时点、缺日清单；固定这些输入的重放须产生相同数值和缺口。任何对照版本不得写回候选信号快照。GET只读不补拉。未完成真实source、日历和qfq的验证时，报告用“未验证”，文档checker成功不解除数据门槛；本文字段接线/合成案例尚非运行时验收。

【虚构】冻结包v1两次得到主4.0000%、缺口列表相同→重放一致；将日历版本替换v2后即使仍4.0000%，也不是同一输入重放；未核验摘要时输出null+`benchmark_version_unverified`。GET调用两次只返回冻结包，采集次数始终0。

## 7. 参数出处登记及未验证计数

计数按登记项/组合一行计一次，不按重复出现的数值或缺口次数计。官方元数据六值分别列于§8，不计未验证；已有规则的代码出处只证明实现，不证明真实链路。下表P01–P05有既有裁定/实现出处；U01–U12共 **12项未验证参数或口径组**，包含尚无值的映射/版本参数，不填任意默认值。每项适用用例已在规则列给出。

| ID | 参数/口径组 | 值与出处 | 核对状态/用例 |
|---|---|---|---|
| P01 | 主辅身份 | 000300/000985；T-R71 README §3、四卡§11 | 既有裁定；R01 |
| P02 | h、时区、日入场/估值 | 1/5/20、Asia/Shanghai、09:30/15:00；plan §2.8、E:23–44/154 | 既有口径；R05/R06/R10 |
| P03 | 收益差与精度 | 简单差、Decimal64、4位half-up/展示2位；E:47–58/278–282、契约T-A27 | 既有实现/裁定；R15/R16 |
| P04 | Stat显示阈值 | n<5空、n<30不足；契约§5.1/§7.11.3、S:431–440 | 既有口径；R19 |
| P05 | unavailable重算期 | 到期后5个交易日；契约T-A33(1) | 既有裁定、代码未遵守；R13 |
| U01 | B11源身份/字段适配 | 000985源代码/市场映射、OHLC解析校验；T-R72 B11、F50只证明000300小样本 | 未验证；R03 |
| U02 | 定稿/可见性参数 | 预计17:10据T-R72 A02及B11存档；实际final证据、available_at/first_seen语义未知 | 未验证；R08/R09 |
| U03 | 完整日历版本 | PN-03 §2已定合并来源/边界；真实覆盖/sha/重叠一致性未知 | 未验证；R05 |
| U04 | 个股qfq因子/可成交事实 | PN-03 §4、T-R71 §3；事件版本、时点、复杂权息、停牌事实接线未知 | 未验证；R08/R11/R21 |
| U05 | 单源整窗快照 | T-R71 §3禁止混拼；具体data_version/manifest实现及严格拒绝组合为本卡draft | 未验证；R04/R22 |
| U06 | 指数完整性门槛 | 整窗每开市日OHLC齐备为本卡保守建议，现E只要求两端 | 未验证；R12；D03 |
| U07 | 全收益及分红偏差 | 官方有系列；仓库接入、开盘点位和偏差量化无证据 | 未验证；R02 |
| U08 | 发布前/更名映射政策 | 官方元数据可核，历史连续性与回溯样本准入策略未定 | 未验证；R14；D06 |
| U09 | 盘中分钟/复权衔接 | E:235–240已有缺口；指数同分钟开盘语义和全链未核 | 未验证；R07；D08 |
| U10 | 固定观察截止与迟到补算 | S:238–242钳制末日；契约T-A33未明确晚到可见时钟 | 未验证；R13；D04 |
| U11 | hold方向阈值校准 | 1/2/5个百分点沿plan §9 C(7)，均初值待校准 | 未验证（不是无出处）；R17 |
| U12 | 辅槽/分组与展示扩展 | 本卡metadata、源版本分组、配对n、额外统计gap及负零显示是draft新增 | 未验证；R16/R18/R19/R21/R22；D02/D07 |

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

## 9. 待裁定清单（8条）

| ID | 歧义/需要决定的内容 | 本draft确定的保守输出（对应规则/用例） |
|---|---|---|
| D01 | 是否曾需按板块或周期切换主辅；未找到此类裁定 | 不切换，不把RC5周期映射当换指数条件；R01 |
| D02 | 现API单benchmark字段如何承载辅槽、行业槽、gap与版本metadata | 主槽兼容；新增槽仅内部研究包，不改API、不重复观测；R01/R18/R21 |
| D03 | 完整对齐是否阻断端点已齐但中间缺日的收益 | 本卡正式槽null+缺日码，端点值仅诊断；现实现差异明确；R12 |
| D04 | unavailable五日补算与到期日截止如何协调；股票complete但基准缺失是否允许新观察版本 | 不倒填可见时点、不改冻结行；仅恢复截止前可见版本可补，真正迟到仍null；R08/R13 |
| D05 | B11指数目录/市场映射、采集资格、版本保存及available_at责任方 | 无可核验映射/时点/source/version则受影响槽null；不复用stock过滤器；R03/R04/R08 |
| D06 | 是否允许发布前回溯历史；更名连续性证明及历史目录版本如何留存 | 发布前或更名未核均null；仅证据完整的同系列续接；R14 |
| D07 | plan的动作/置信度分组如何对接现API；源版本分组、配对n和基准均值是否入接口 | 内部按已知标签分组，未知单列；不合并源版本，不外推置信桶；R18/R19/R20 |
| D08 | 盘中指数下一分钟开盘及股票qfq桥何时具备核验依据 | 原分钟缺口继续阻断，不用日线替代；R07 |

后端可按R01–R22建立离线合成验收，未决项按上表保守输出。真实基准就绪至少需要B11身份/定稿/版本链、同日历全窗、个股同as_of qfq及可成交性证据；本单只交付规格与文档检查，不报告这些真实门槛已通过。

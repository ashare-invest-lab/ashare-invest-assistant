# T-A209：市场概览接线与三个占位页排序、契约、拆单

基线：2026-11-16，本 worktree HEAD 与本地 origin/main 均为 `1490926ebaeb4683b4a9c2fa56e8060626bd36a5`，未联网更新。已读任务全文及末节扩项、T-A136、T-A210。
执行范围：按本任务明确的“只读代码、只写本报告”约束处理末尾通用“自己改代码”要求；仅交付方案和文档验收，不改代码、不提交、不 push、不联网、不读环境文件/密钥/用户电脑、不调麦蕊。docs PR 由用户后续处理。
下文“增量/草案”是建议，非已生效接口、已验证数据或新增执行授权；文件路径相对 worktree，外部报告为 `/workspace/team/reports/`。参数只引用现有来源；缺证统一登记 U1–U7，计 **7 组未验证**，不是全文关键词出现次数。

## 1. 总排序

| 序 | 项 | 价值 | 依赖 | 风险 | 拆单数 |
| --- | --- | --- | --- | --- | ---: |
| 1 | ①市场概览/日报市场环境与宽度 | 修复两个固定未接线入口，并统一今日关注、终端市场环境 | 本人缓存、全市场收盘快照、F24/F25、日历 | 样本冒充全市场、混时点、F50 冒充 F25、只存不推边界 | 11 |
| 2 | ②/restrictions 禁投·冷静期·屏蔽 | 把现有阻断原因变成可管理闭环 | 限制表、候选原因与状态事件 | 删除后仍阻断、重复限制误解除、跨用户操作 | 6 |
| 3 | ③/reviews 复盘 | 串联计划版本、实际成交、结果和经验 | 不可变版本、本人交易与收盘证据；指标口径 U5 | 模拟冒充实绩、费用漏算、事后数据污染原判断 | 8 |
| 4 | ④/discover 发现 | 先恢复策略入口，再提供有覆盖说明的缓存筛选 | 策略库、PIT 截面与筛选支持范围 U6 | 空结果被误认无机会、全市场范围扩张、跨策略综合评分 | 6 |

理由：①命中主线现有页面和日报固定缺口（`docs/plan.md` §0A；T-A210 G01）；②已存在表和阻断读取，闭环收益大且不依赖行情供应商；③需先厘清真实结果口径；④在 `docs/plan.md` §2.4 已规定入口并入策略库，完整筛选又尚无本版 API，优先级最后。价值排序不是串行阻塞：②及④入口跳转可在①数据准备期间先交付。
共 **31 单**；M/R/V/D 为本文依赖别名，正式建议单号均留给编排者，未冒充已派单。每单净增上限含代码、测试、迁移、契约与生成文件；达到上限前再拆，不能把测试排除在额度外。

## 2. 共用约定与现状

- API 基础路径 `/api/v1`；时间含时区、输出北京时间；金额/价格/百分比为十进制字符串；数量家数为整数。来源：`docs/api-contract.md` §1、§1.1、§1.2、§3。
- 缺口返回 `gaps:[{key,reason,message}]`，其中 `reason` 使用 **gap_reason** 现有枚举，不新增同义字段或 `not_wired` 枚举。固定未接线→`no_source`；尚未到数据发布点→`not_yet_published`；有故障证据→`upstream_error`；有配额延期事实→`quota_deferred`；本人证书不可用→`data_licence_unavailable`；缺用户输入→`user_input_missing`。没有投递任务就不能返回 `pending`。
- 不伪造、不插值、不前视；未知字段为 null，未知列表为空并解释缺口；业务上确实无记录则空列表且无缺口。数据时点取实际参与响应的最早非空值，全空为 null，不用请求/生成时间替代（API §1.1 A-12）。保留旧数据时标 stale 与旧交易日；部分缺失标 partial；全部行情缺失标 unavailable。
- 通用错误：`400 VALIDATION_ERROR/INVALID_CURSOR`（分页端点）、`401 AUTH_REQUIRED`、`403 ACCOUNT_NOT_APPROVED`、`404 NOT_FOUND`（本人资源不存在与他人资源同形）；创建复用 §1 的 Idempotency-Key，异体同键 `409 IDEMPOTENCY_CONFLICT`；通用限流沿 §4。真实服务故障走错误体，不伪装成成功空集。
- `src/backend/app/aggregates/service.py:market` 固定空；`src/backend/app/reports/service.py:build` 固定 market gap；`today`、`terminal` 的 regime 也固定 null。T-A210 G01 属代码确认的未接线，不承诺其原始“87 项”全部随本方案消失。
- #185 相关链：`src/backend/app/api/v1/quotes.py:parse_codes` 校验 1–200 个代码；`src/backend/app/marketdata/quotes_read.py:read_quotes`→`_daily_closes`；`src/backend/app/aggregates/service.py:terminal` 批量复用。当前没有“实时优先”的生产读分支。
- `_daily_closes` 只读 source=mairui、本人 active licence、adj_type=none、非停牌、完整 OHLC、已收盘且 fetched_at≤now 的最近行；15:00 前不取当日收盘，输出 stale、t=该日15:00，amount/volume 仍 null。无有效证书时旧价也不返回（API §1.1 T-A173）。因此不能遍历 `/quotes` 拼全市场宽度，也不能把旧收盘改标 fresh。
- `docs/contracts/daily-bars-source.md` 是日线专门契约；与 API §1.1/§7.3 联读。其 §9.6 已裁定全市场日线只存不推；`daily-bars-tdx.md` §1/§4 排除通达信进入 owned/日报/today。T-A136 是成本历史估算，不覆盖之后这些裁定。

## 3. ①市场概览、日报市场环境与宽度

### 3.1 来源、参数和口径

| 输入/参数 | 候选来源与出处 | 使用边界 |
| --- | --- | --- |
| 指数清单；price/change_pct/amount/t | 清单由后端配置（API §7.3 `/market/overview`）；麦蕊实时候选 `/hsindex/real/time/{code}`（plan §2.5.2 板块与大盘）；日线候选 `/hsindex/history/000300.SH/d`（feature_spec F50） | 不把指数清单写死为本报告样例；实时字段映射、单位、指数实际覆盖未验证 U1；缺哪只就保留该只 null/gap。 |
| 沪深股票涨跌家数、上涨占比 | `/hsrl/ssjy/all`；`docs/strategies/feature_spec.md` F24：d 日沪深 stock、有成交、剔除北交所与非股票；上涨用快照 pc>0、平盘不算上涨、停牌不进分母 | 快照 pc 是涨跌幅%，日线 pc 是前收，不能同名直连。盘中数为暂态；收盘 F24 在15:05后，4位小数 ratio；单位与实际定版仍未验证 U1。 |
| 跌/平、成交额 | 同一批已验证快照中 pc<0/pc=0；两市成交额按上述股票范围累加 cje（T-A136 §2 字段清单、MarketPage 的“两市成交额”） | 本方案按 F24 统一沪深范围，不称沪深北全 A；主数据在观察时点的资格和快照覆盖未验证 U2；不得使用固定5577作分母。 |
| 涨停/跌停家数 | `docs/plan.md` §2.5.2 情绪：`/hslt/ztgc/{date}`、`/hslt/dtgc/{date}`；§2.13 交易规则与 feature_spec 的涨跌停价字段 | 只采用同日同范围已验证封板事实；盘中当前封板与盘后收盘封板分开；不以统一±10%猜涨跌停。具体缓存字段/覆盖未验证 U4。 |
| regime、参考仓位区间 | F25（feature_spec）：指数 MA20/MA60＋20日宽度、连续2日防抖；有效指数不足45根或宽度不足15值→null；正式阈值由 G-02 定；区间取 RC3 `regime_ranges`（API §5.3、plan §6.1） | F25正式参数/可运行产物未验证 U3；不套用示例阈值，不用仅指数的 F50替代；缺 F25时区间也为null，RC3仍按缺失处理。 |
| 本地日线库 | `src/backend/app/marketdata/daily_bars.py:upsert_daily_bars`、`daily_universe`；`src/backend/app/marketdata/daily_snapshot.py:build_owned_snapshot` | 可复用本人合格指数/日线读取条件，不能用持仓∪自选当市场样本；全市场回算宽度须另行变更源契约§9.6，本轮主方案采用独立市场快照，不全库扫描。 |
| 通达信本地 | `docs/contracts/daily-bars-tdx.md` §2–§4：none、tdx_local、pre_close/is_suspended=null，股票价÷100、量=股、额=float32元 | 仅离线研究/核对；不能作为本方案日报市场环境的自动回退。无前收不能用昨收冒充除权参考价，无行不推断停牌。本次不读实际文件。 |
| 成本与采集频率 | T-A136 §2：旧样本5577只×727日约405万行、逐只history约5577次；ssjy/all候选每分钟最多1次；源契约§8.3/§9.6校正为N×ceil(W/k) | 只作取舍依据，不当当前容量事实或外呼授权；盘中轮询间隔沿现有配置/plan §0A.3，不新增任意TTL；全市场快照由ingest形成，GET不拉取。 |

盘中：按市场日历 `src/backend/app/aggregates/calendar.py:market_clock`，只返回同一采集批的实测快照；指数允许独立时点但必须披露。缺实时批次可显示上一完整收盘批（stale、旧 observed_date），不得把每股不同旧交易日凑成“今日宽度”。regime 为最近已确认的盘后 F25，盘中不另造分类器。
收盘：F24 的15:05是来源规格的可得下限，不等于自动认定终值；需来源完成事实及 fetched_at。owned 日线现有17:10终值/17:30知识截止见 `daily_snapshot.py:build_owned_snapshot`；不能拿 quotes 的15:00判定替代。日报生成时冻结已知市场批，晚到数据只在新 revision 使用，旧日报保持原貌。
缺数：有效股票资格/停牌状态/快照覆盖不足时，breadth、turnover_total不输出全市场估计；gap key按 `market.indices.<code>`、`market.breadth`、`market.limit_counts`、`market.regime` 分项。现有 breadth 子字段均不可空，涨跌停缺一个时整个旧 breadth=null；可用覆盖计数仍披露，不把未知涨跌停写0。缺口与真实0须有不同夹具。

### 3.2 契约草案与受影响入口

- 保留 `GET /market/overview` 无业务请求参数、弱ETag；既有响应字段为 trade_date/session/indices[{security_code,name,price,change_pct,amount,t}]/breadth{up,down,flat,limit_up,limit_down}|null/regime/regime_position_range/turnover_total/DataStatusBlock（API §7.3）。
- **增量**：新增 `basis:{snapshot_id:uuid|null, observed_date:date|null, mode:"intraday"|"close"|null, scope:string, eligible:int|null, observed:int|null, trading:int|null, suspended:int|null, missing:int|null, source:string|null}`。字段为本草案，用来显式表达F24样本与旧批次；scope固定解释为沪深股票口径，不是可请求任意市场的参数；source保留真实端点/来源标签，不扩充data_provider枚举。
- eligible=该观察日资格池；observed=有可解释观察的成员；trading=确认有成交成员；suspended=确认停牌成员；missing=eligible−observed；缺资格池时这些依赖计数为null，不算覆盖率。不得把无成交但停牌状态未知者归入平盘；资格/有成交判据来自F24，原始字段未核实前计入缺口。
- **内部增量**：在已有 `data_snapshots`（purpose=report）存独立市场schema、owner/licence、批次/来源时点、资格证据、计数与F25证据；读取按本人证书隔离。借用表不借用 owned instruments；日报只引用聚合结果，不把全市场代码加入stocks/today.focus。来源：`src/backend/app/db/tables/reviews.py` data_snapshots；源契约§9.6。
- `DailyReport.market` 新增 basis 和 DataStatusBlock；旧 breadth无flat，继续按现有形状映射；summary沿TextWithEvidence、证据加入日报evidence并使用市场专属ID前缀。旧存档只做只读缺省投影，basis/data_as_of不得用当下补造。日报顶层时点纳入实际市场输入。
- `/today.market`、`/terminal.account` 保留原字段，统一读取同一F25与本人RC3设置；新增同形basis仅用于市场来源说明。旧固定market gap只在对应输入已补齐时移除；account.pnl_day、六维未接线缺口不随之删除。
- 本方案没有改动源契约§9.6为“全市场日线进入日报”：拟新增的是独立快照聚合读取；未来若改用历史全市场日线回算，应先修订该节与TDX边界，不能在报表service暗加全库查询。T-A210 G11、G15及其他六维未接线另列后续范围，不塞入本单。
- 错误沿共用约定；日历缺覆盖保留 `503 CALENDAR_NOT_COVERED`，规则时段缺失保留 `503 MAINTENANCE`（market_clock）；行情/证书缺数为200+gap，不用409、503替代。`/daily-reports/{date}`无完成版仍404；没有队列就不返回generating/pending。

| 受影响入口 | 逐入口验收 |
| --- | --- |
| `/market`、`/market/overview` → GET概览 | 同批计数与basis对账；全空/部分/旧收盘/有效0均正确；宽度分母0不画NaN条；ETag不变304；切指数图仅向bars取真实已有频率，不由日K合成1m。 |
| GET `/daily-reports/{date}`、列表；`/daily-reports`、`/:date`、旧`/reports`别名 | 同日市场值等于冻结批；列表regime与详情同版本；晚到/重跑仅新revision变；旧报告不读当前市场补值；top-level时点含market；summary引用证据可解析。 |
| GET `/today`、页面 `/today` | market共享F25/区间；缺口汇总按真实分项；全市场成员不出现在focus；证书A与B隔离。 |
| GET `/terminal`、页面 `/terminal` | 顶部市场环境与同批概览一致；无账户时account仍null；rows继续走本人quotes回退；不得给旧收盘贴实时标签。 |
| GET `/quotes`；指数 GET `/securities/{code}/bars`；市场板块面板 | 回归证书失效全空、旧收盘stale、未来fetched_at排除；1m缺数照实；`/market/sector-flows`保持独立盘后来源，不用宽度替换资金流。 |
| REPORT构建、owned snapshot、RC3 | Q4股票集合不扩大；tdx_local不进入新增市场输入；F50存在/F25缺失时仍未知；缺市场不改变已有风控门控逻辑。 |

### 3.3 拆单（11）

| 别名｜建议单号 | 范围/净增上限 | 依赖 | 验收 |
| --- | --- | --- | --- |
| M1｜T-B待编排者编号-M1 | 后端市场快照schema、basis与契约增量，300行 | 本草案 | 本人/证书、来源时点、空值均可序列化；旧响应可投影。 |
| M2｜T-B待编排者编号-M2 | 后端可信采集完成适配器，350行 | M1；U1/U2/U4 | 输入显式批次/来源事实；无网络；缺字段拒绝对应产物；不改真实调度开关。 |
| M3｜T-B待编排者编号-M3 | 后端宽度、成交额计算，320行 | M2 | 资格过滤、停牌、缺成员、涨跌停缺口；不以样本外推。 |
| M4｜T-B待编排者编号-M4 | 后端收盘冻结、按时点选批，280行 | M3 | 同批去重；早到非终值、晚到不可前视；重读旧批稳定。 |
| M5｜T-B待编排者编号-M5 | 后端F25产物接入、RC3区间读取，300行 | M4；U3 | 未裁定参数保持gap；正式口径冻结后测预热、防抖；无F50替代。 |
| M6｜T-B待编排者编号-M6 | 后端概览/today/terminal市场读取，320行 | M4/M5 | 三入口同源同值、200缺口、503日历、ETag与账户空值。 |
| M7｜T-B待编排者编号-M7 | 后端日报冻结、旧版投影与时点，300行 | M4/M5 | 新revision有真实证据，旧body不变；全市场股票不进入stocks。 |
| M8｜T-F待编排者编号-M8 | 前端市场basis/缺口/零分母展示，260行 | M1/M6 | 两条市场路由一致；部分/旧批标签准确，图表缺频率不造数。 |
| M9｜T-F待编排者编号-M9 | 前端日报/today/terminal来源联动，280行 | M6/M7 | 入口矩阵中的环境/区间/证据/旧报告均可读。 |
| M10｜T-B待编排者编号-M10 | 后端隔离合成测试，380行 | M2–M7 | 两用户、未来时点、收盘边界、缺成员、无F25、revision、只存不推及无外呼。 |
| M11｜T-F待编排者编号-M11 | 前端夹具与交互测试，300行 | M8/M9 | 全空/部分/0/旧批、别名、旧日报、图表请求、无NaN。 |

## 4. ②/restrictions 禁投·冷静期·屏蔽

来源：API §7.5定义kind=blocklist/cooling_off/mute、target_type=security/strategy/instance、target_id、until、reason；`src/backend/app/db/tables/signals.py` user_restrictions已有id/user_id/created_at/removed_at。证券目标来自 `src/backend/app/master/search.py:search`；策略可见性来自 `src/backend/app/api/v1/strategy_cards.py:visible`；实例按本人归属校验。不需要麦蕊、通达信或日线参数。
盘中/收盘：同一限制事实均按服务端时刻判断，until≤now失效（`src/backend/app/signals/service.py:write_candidate` 当前用content.created_at）；用户明确until不换算成自然日N。自动止损后冷静期的“默认关闭、N=3交易日”仅来自plan §6.1/问题31，非本页默认启用项；这次先交付手动管理。
已确认实现缺口：write_candidate读取限制时没有removed_at过滤，且只按target_id集合匹配；软删除接入必须同步修正removed_at和target_type匹配，否则删后仍拦截。名单删除只能重新检查关联原因，不能无条件解除所有同代码原因（API §6.1、§9 v0.2.9验收5）。
缺数：限制列表真实为空=200 items[]、gaps[]；目标名称缺主数据，保留target_id、name=null、no_source；重查证据缺失时保留active原因并返回gap，不假定已恢复可执行。无行情证书不影响名单管理，不返回行情许可证gap。没有插值/前视；历史展示使用原创建/删除时间，不套用今日名单重写旧信号。

**契约草案**：补全既有 GET/POST `/restrictions`、DELETE `/restrictions/{id}`，不另建第二套控制接口。
- GET请求 `kind?、target_type?、limit、cursor`；默认未删除，按created_at desc/id desc（API §1.2）；响应 `{items:[Restriction],next_cursor,gaps}`。Restriction沿上述字段增id/created_at/removed_at/name/status（active/expired；草案派生展示，不落新状态枚举）；until=null不擅自补到期日。
- POST请求严格沿§7.5六字段；201返回Restriction+gaps；不接收user_id。cooling_off须有未来until，否则400 VALIDATION_ERROR（本草案补齐有效性约束，以plan“冷静期结束”语义为据）；blocklist/mute保留现有until可空能力。
- DELETE建议200 `{id,removed_at,recheck:{released_reason_ids:uuid[],remaining_reason_ids:uuid[]},gaps}`（既有契约未规定响应体，本次增量）；重复删除同一本人记录返回相同删除时间、不重复事件；仅解除已证实无其他有效限制的原因。未完成重查不能返回“已解除”。
- 错误除共用项外：目标不可见/不存在同404；字段组合无效400。`POST /non-executable-reasons/{id}/release` 对BLOCKLISTED/USER_MUTED继续409 REASON_NOT_MANUALLY_RELEASABLE（`src/backend/app/api/v1/candidate_signals.py:release_reason`），引导名单页；cooling_off按时间条件重查，不绕过机器条件。
- 入口验收：`/restrictions`增删筛选及过期展示；`/candidate-signals/:id`名单解除跳转、重复限制仍阻断；`/candidate-signals?tab=released`与`/today.released_reasons`只出现确实解除的事件；`/terminal`原因计数刷新一致；新候选不再命中removed记录；旧建议归档不被覆写。

| 别名｜建议单号 | 范围/净增上限 | 依赖 | 验收 |
| --- | --- | --- | --- |
| R1｜T-B待编排者编号-R1 | 后端GET/POST与归属校验，350行 | §7.5、本草案 | 三类×三目标合法组合、分页、幂等、跨用户404。 |
| R2｜T-B待编排者编号-R2 | 后端DELETE、限制匹配修正，300行 | R1 | removed_at/target_type正确；重复删除不增事件。 |
| R3｜T-B待编排者编号-R3 | 后端删除/到期原因重查及事件，380行 | R2 | 同目标多限制保留阻断；最后一条解除；终态信号不复活；缺证据gap。 |
| R4｜T-F待编排者编号-R4 | 前端替换占位及增删/到期/跳转，350行 | R1–R3 | 入口验收逐项通过；不以删除成功等同可交易。 |
| R5｜T-B待编排者编号-R5 | 后端测试，340行 | R1–R3 | 所有者隔离、到期边界、重复限制、软删回归、机器原因拒手动解除。 |
| R6｜T-F待编排者编号-R6 | 前端测试，230行 | R4 | 错误、空列表、重查gap、相关计数与解除页刷新。 |

## 5. ③/reviews 复盘

来源：`docs/plan.md` §2.4能力5要求计划版本→成交→后续结果、判断/执行/市场环境归因、经验标签；API §7.8只列GET/POST骨架。`src/backend/app/db/tables/reviews.py` reviews/review_versions已有period_start/end、plan_id、plan_version_ids、trade_ids、outcome_metrics、attribution、lessons、tags、snapshot_id；无需借用 `strategy/reviews.py` 的晋级审核对象。
实际计划从 `src/backend/app/plans/service.py:owned`、`project_version`读取本人版本；成交来自本人已确认导入（plan §2.4能力5、API §7.2）。麦蕊仅作为已入本地库且本人可见的日线/基准证据，参数none、pre_close、source_licence_id/fetched_at约束沿第3节；通达信仍仅研究，不自动补本人的正式复盘收益。
收益/基准/超额/回撤的业务目标有出处（plan能力5），但实际成交复盘的费用、现金流、分红、未平仓处理及行业基准映射尚未有本次确认的统一公式，未验证 U5；参数未定前返回null+gap，不借用模拟跟踪数充当实绩。`src/backend/app/tracking/service.py:view`可复用本人模拟结果展示；`instrument`直接查日线不构成所有者隔离证明，不能原样套用到新增复盘。
盘中只展示记录事实和最近完成的收盘结果，开放期间标未完成；收盘按period_end及知识截止冻结。计划当时快照与事后结果快照分开：后续实际成交是复盘证据，不反写成当时预测；只在结果截止后可见的数据才能参与相应revision，不用未来修订回填旧版本。缺成交/标注为user_input_missing，缺价格/基准/公式为no_source，结果期未结束为not_yet_published；无证书只影响行情派生字段，仍返回用户笔记和计划。

**契约草案**（所有新字段/子路由均为§7.8增量）：
- GET `/reviews?security_code=&plan_id=&limit=&cursor=` → `{items:[{id,plan_id,security_code,name,period_start,period_end,current_version_no,created_at,DataStatusBlock}],next_cursor}`；GET `/reviews/{id}`→头＋current_version＋timeline，均按本人过滤。
- POST `/reviews`：`{plan_id:uuid|null,security_code:string|null,period_start:date,period_end:date,plan_version_ids:uuid[],trade_ids:uuid[],lessons:string|null,tags:string[],judgement:[{condition_text:string,fulfilled:boolean|null,note:string|null}]}`；judgement只存用户对计划条件的兑现标注（plan能力5），不能传计算指标为“事实”；201返回完整复盘。plan与证券至少一项，日期有序、关联版本/成交归属一致，否则400；具体数值指标由服务端计算。
- GET `/reviews/{id}/versions?limit=&cursor=`、GET `/reviews/{id}/versions/{version_no}`；POST `/reviews/{id}/versions`同内容字段加base_version_no→201新不可变版本；并发base不符→409 VERSION_CONFLICT（API §4）。原版本不开放PATCH/DELETE，未开放的方法405。
- version：`{id,version_no,plan_version_ids,trade_ids,snapshot_id,lessons,tags,attribution:{judgement,execution,market},outcome_metrics:{holding_return,benchmark_return,excess_return,max_drawdown},created_at,DataStatusBlock}`。各指标沿API §5.1 Stat结构；U5未定时value=null、n为真实可用样本数、window为period、small_sample沿§5.1阈值，不伪造样本量。attribution.judgement保留用户标注，execution/market为TextWithEvidence数组；timeline元素 `{kind,at,resource_id,version_no:null|int,evidence_ids}`，证据附在详情evidence[]中。
- 受影响入口验收：浏览器 `/reviews`列表/新建、`/reviews/:id`详情及版本切换均显示空值原因；计划详情深链携带固定plan_version_id；`/portfolio`成交引用能定位实际trade_id；建议tracking入口清楚标“模拟”，不得计入实际成交；历史版本重读不随当前日线/计划变化；市场归因引用该复盘期间冻结数据，缺市场环境不阻止保存手写经验。

| 别名｜建议单号 | 范围/净增上限 | 依赖 | 验收 |
| --- | --- | --- | --- |
| V1｜T-B待编排者编号-V1 | 后端复盘模型、列表/详情/版本读取，330行 | 已有表、契约草案 | 仅本人、稳定分页、旧版本不可变、空指标可解析。 |
| V2｜T-B待编排者编号-V2 | 后端创建与版本保存，380行 | V1 | 关联归属、幂等、base冲突、快照冻结、手写结论区分事实。 |
| V3｜T-B待编排者编号-V3 | 后端计划/成交时间线与三分归因证据，350行 | V2 | 不按证券粗匹配别人的成交；无证据项保持未知；双时点不混。 |
| V4｜T-B待编排者编号-V4 | 后端结果指标适配，350行 | V3；U5 | 仅实现已定公式；费用/基准缺项null；模拟不混实际；未结束不出终值。 |
| V5｜T-F待编排者编号-V5 | 前端列表、创建和版本入口，330行 | V1/V2 | 替换占位、复用计划/证券选择；保存返回真实版本号。 |
| V6｜T-F待编排者编号-V6 | 前端时间线、归因、结果和差异，350行 | V3/V4/V5 | 原貌与当前对照明确、缺口可读、实际/模拟标识明确。 |
| V7｜T-B待编排者编号-V7 | 后端隔离测试，380行 | V1–V4 | 跨用户、并发保存、迟到日线、未结束期间、真实缺费用、旧版本哈希不变。 |
| V8｜T-F待编排者编号-V8 | 前端入口与版本测试，260行 | V5/V6 | 列表空态、深链版本、null/gap、错误保存不丢用户输入。 |

## 6. ④/discover 发现

先交付入口：按plan §2.4将 `/discover` 跳转 `/strategies`，移出PLACEHOLDERS，不做另一套策略库。现有 `src/backend/app/api/v1/strategy_cards.py:strategy_list`支持horizon/lifecycle/risk_level、limit/cursor，响应Page含id/key/name/horizons/risk_level/current_version/health；security_code适配目前503 MAINTENANCE(applicability_evaluator_pending)，不能伪装已支持。
完整发现另做下面缓存筛选草案：plan能力2规定按单一策略筛选、可进入股票/研究候选；API §7.7A明确本版没有 `/factor/screen`、POST candidates不接受strategy_screen。本方案不把目录跳转宣称为完成筛选，新增筛选接口需编排者按草案单独落契约。
来源：策略规则与可见版本来自strategy_list/visible；因子/证券资格按策略声明和观察日期的本人缓存，`src/backend/app/signals/screen.py:screen_membership`仅可复用成员资格诊断，不能当全市场扫描器。全市场截面缓存的生产与支持特征矩阵未验证 U6；麦蕊 `/factor/screen`仅是plan能力2候选源，参数/返回映射未验证 U6，不在HTTP读请求实调。通达信及全市场本地日线受源契约§9.6约束：新增研究筛选读用途是显式契约增量，不能自动进日报/analyze/owned；所需特征不能从OHLC得到时保持gap。
盘中不以当日未完成日K筛选“收盘条件”；首版只用指定trade_date的已完成缓存截面，保留fetched_at≤快照知识截止；没有当日完整截面时返回缺口，不悄悄换到上一日。历史成分/状态不足（U2）不以当前上市名单回看。缺某规则输入时该证券结果为unknown，缺全体源时无匹配列表但has_gaps=true；0命中且全覆盖才可称“无匹配”。

**契约草案**：入口跳转无新API；筛选新增POST `/strategy-screens`与GET `/strategy-screens/{id}`，不占用未定义的供应商同名接口。
- POST请求 `{strategy_version_id:uuid,trade_date:date}`；范围由该版本声明，客户端不传任意表达式、owner、全市场开关；只读已有缓存计算并冻结，201返回与GET同形结果，不承诺任务入队。未来日期400，未知/他人策略404，不支持的规则范围400 VALIDATION_ERROR{issue:not_supported}（支持矩阵依U6；`screen_membership`已有诊断为依据）。
- 响应 `{id,strategy_version_id,trade_date,snapshot_id,coverage:{scope,eligible,observed,unknown},matched:[{security_code,name,rule_results,evidence_ids}],next_cursor,evidence,has_gaps,DataStatusBlock}`；matched只包含规则真值已确认的记录，不输出跨策略综合分/推荐排名；覆盖不明时计数null。POST返回默认第一页，GET支持limit/cursor，依据API §1.2，按security_code稳定分页；完整结果在服务端冻结，不能每页重算。rule_results/evidence数组结构沿API §5.1 RuleRef/Evidence。
- 数据不足=201/200+no_source，证书不可用=unavailable+data_licence_unavailable，正式收盘截面尚未生成=not_yet_published；已有明确采集故障才upstream_error。POST只计算缓存，不自动调用麦蕊；无依据不得显示pending。空策略目录是合法空集，不制造行情gap。
- 受影响入口验收：`/discover`与`/strategies`不重复页面；版本详情可启动支持的筛选；结果页缺源≠0命中、跨页不漏重；结果只深链 `/stocks/:code`，后续手动研究仍走现有from_stock；`POST /candidates origin=strategy_screen`保持400，不绕过现有契约；`/today`、日报、owned集合在研究筛选前后相同。

| 别名｜建议单号 | 范围/净增上限 | 依赖 | 验收 |
| --- | --- | --- | --- |
| D1｜T-F待编排者编号-D1 | 前端discover跳转、策略库入口，100行 | plan§2.4 | 移除占位、链接有效、不显示尚未具备的筛选结果。 |
| D2｜T-B待编排者编号-D2 | 后端筛选契约/支持矩阵/快照读适配，350行 | U2/U6；源契约研究读增量 | 仅本人可见证据；unsupported明确报错；日线与因子不互相冒充。 |
| D3｜T-B待编排者编号-D3 | 后端缓存规则筛选、冻结/分页端点，380行 | D2 | 同版本同截面、unknown和0命中不同；不入队不出网。 |
| D4｜T-F待编排者编号-D4 | 前端启动筛选、覆盖/结果/股票深链，350行 | D1/D3 | 展示固定交易日、缺口及来源，不输出综合排名。 |
| D5｜T-B待编排者编号-D5 | 后端测试，340行 | D2/D3 | PIT、跨用户、未来日期、unsupported、缺源/0命中、稳定分页及研究边界。 |
| D6｜T-F待编排者编号-D6 | 前端入口与筛选测试，250行 | D1/D4 | 跳转、错误/空/gap、分页、股票入口与候选来源约束。 |

## 7. 可复用点与验证缺口

直接复用：`src/backend/app/aggregates/calendar.py:market_clock`（日历）；`src/backend/app/marketdata/daily_snapshot.py:active_licence_id`（本人证书）；`src/backend/app/marketdata/quotes_read.py:_daily_closes`（旧收盘过滤范式）；`src/backend/app/aggregates/service.py:select_account`（账户归属）；`src/backend/app/api/v1/aggregates.py:response`（弱ETag）；`src/backend/app/reports/service.py:canonical`、`latest`、`build`（不可变日报）；`src/backend/app/api/v1/daily_reports.py:project_component_clock`（旧档时点投影）。
有条件复用：`src/backend/app/ingest/owned_quotes.py:record_quote`已有时点/所有者校验，但仅单股price/prev_close/停牌，不含宽度/成交额，不能直接当市场批次；`src/backend/app/plans/service.py:release_closed_plan_reasons`可借事务锁/事件模式，但其谓词只针对计划关闭，不能直接解除名单原因；`src/backend/app/signals/service.py:transition`与`add_reason`可复用事件模型；`src/backend/app/research/content.py:write_snapshot`可借快照哈希存储范式；复盘与筛选各自保留purpose/schema，不混用候选对象。
前端复用：`src/frontend/src/api/marketQueries.ts` useMarketOverview/useQuote、`src/frontend/src/pages/market/MarketPage.tsx` MarketPage/BreadthPanel/RegimePanel；`src/frontend/src/components/common.tsx` DataStatusTag/GapNote/ErrorBox/Loading；路由入口以 `src/frontend/src/app/routes.tsx` 为准。

| 编号 | 未验证内容与关闭条件 | 影响 |
| --- | --- | --- |
| U1 | 麦蕊指数/全市场快照字段、pc/cje单位、批次一致性及15:05终值；需已有授权采集的脱敏证据逐字段核验，本次不实调 | M2/M3/M4实源接入；离线适配器可先做 |
| U2 | 历史时点资格池、成交/停牌事实和全量覆盖；需冻结主数据及源批次对账，不能用当前名单补历史 | 市场覆盖、历史筛选 |
| U3 | F25正式G-02参数、运行门禁及可用历史产物；feature_spec明说示例阈值非正式，须按卡版本核对 | regime/区间保持null；不阻塞指数展示 |
| U4 | 涨跌停来源字段、时点、沪深范围与特殊交易制度覆盖；需与规则和源缓存核对 | 旧breadth整体可用性 |
| U5 | 实际复盘收益/费用/现金流/分红/未平仓、行业基准及样本口径；需形成有依据的指标定义和手算样例 | V4结果指标；不阻塞笔记与时间线 |
| U6 | 策略筛选支持矩阵、完整截面缓存生产、研究日线读取范围；需版本级字段与已有生产读链映射 | D2/D3；不阻塞discover跳转 |
| U7 | 现场数据覆盖、当前成本与原87项缺口对应关系；没有本次现场输入，T-A136数字只是旧估算、T-A210未收到原87条 | 不承诺上线即消除所有缺口或实时容量 |

## 8. 本次验收

仅运行静态、只读验收；不导入应用、不启动服务/pytest（避免隐式环境读取与缓存写入），不连数据库。已核对任务扩项、四项排序、31行拆单、每单上限≤400、七组未验证、引用文件/函数存在；报告≤250行；worktree未改、无暂存变更。
复核命令（在本worktree执行；Python只读指定报告及其中显式引用的源码/文档）：
```bash
python3 -B - <<'PY'
from pathlib import Path
import re
p = Path('/workspace/team/reports/T-A209.md'); s = p.read_text()
assert len(s.splitlines()) <= 250
rows = re.findall(r'^\| ([MRVD]\d+)｜T-[BF]待编排者编号-\1 \|[^\n]*?(\d+)行 \|', s, re.M)
assert len(rows) == 31 and all(int(n) <= 400 for _, n in rows)
assert [sum(k.startswith(x) for k, _ in rows) for x in 'MRVD'] == [11, 6, 8, 6]
assert len(re.findall(r'^\| U[1-7] \|', s, re.M)) == 7
for file, func in set(re.findall(r'`(src/[^`:\s]+\.py):([A-Za-z_]\w*)`', s)):
    assert re.search(r'\bdef ' + re.escape(func) + r'\s*\(', Path(file).read_text()), (file, func)
print('PASS：报告行数、31单额度/分组、7组未验证、源码函数引用。')
PY
git diff --exit-code
git diff --cached --exit-code
git status --porcelain
```
验收边界：以上只证明方案完整性和代码只读范围，不是31张未来实施单的功能验收；实源、运行时数据和U1–U7未解决。没有执行任何真实行情验收。

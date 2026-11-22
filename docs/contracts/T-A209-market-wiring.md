# T-A209：盘中实时/分时采集、市场接线与占位页排序、契约、拆单

基线：2026-11-16，本次只读 HEAD=`41b88982f964b4b1285486e6c88aeaede7112654`，未联网更新。原①–④沿用既有方案；新增依据 `/workspace/team/reports/T-O111.md`、`/workspace/team/tasks/BACKLOG-1116-gaps.md`（两者为团队内部机路径，公开仓库不可达，佐证原件由团队留存）与本地源码，现场事实仅指 T-O111 的观察窗口。
执行范围：按本任务明确的“只读代码、只写本报告”约束处理末尾通用“自己改代码”要求；仅修改 `docs/contracts/T-A209-market-wiring.md`，交付方案和文档验收，不改代码、不提交、不 push、不联网、不读环境文件/密钥/用户电脑、不调麦蕊。docs PR 由用户后续处理。
下文“增量/草案”是建议，非已生效接口、已验证数据或新增执行授权；文件路径相对 worktree，外部报告为 `/workspace/team/reports/`。参数只引用现有来源；缺证统一登记 U1–U10，计 **10 组未验证**，不是全文关键词出现次数。

## 0. ⓪盘中实时/分时采集

### 0.1 现状、来源与频率/限速

T-O111 的四类症状同源：ingest/signal-rt 盘中链路占位，实时快照与麦蕊分钟线未生产；#185 已含于现场版本，升级不能自动补齐采集。backlog B0 明确把本项列首；A2 的 T-B185 是读侧修复，不能与 PR #185 混为同一任务。
本地复核：`src/backend/app/workers/ingest.py` 已有 IngestCore、主数据/日线 tick，但未接盘中快照/分钟任务；`src/backend/app/workers/signal_rt.py:tick` 与 `src/backend/app/intraday/consumer.py` 仅 test 环境消费。不是所有模块都没代码，也不能把日志“占位”或心跳健康当作实时采集完成。
麦蕊实时/分时能力**只引** `docs/mairui-fit-matrix.md`（下称矩阵）与 `docs/mairui-verified.md`；后者首段明确为未实调、实测栏待填的财务模板，不能证明实时能力。其他代码/契约仅证明本系统规则，不证明供应商能力。

| 数据/频率 | 出处与实现边界 |
| --- | --- |
| 个股实时快照 | 矩阵§1“自选”：`/hsstock/real/time`、`/hsrl/ssjy_more`，多股≤20；仅1只/1窗口测得延迟中位约7秒，不是 SLA。字段、价量额单位、累计口径、ETF覆盖未验证 U8；不猜字段映射。 |
| 1分钟不复权 | 矩阵§1“自选”、§5 N4：`/hsstock/pro/latest/.../1/n`，部分/未实测；分钟线不复权，5分钟传 f 曾返回503。请求参数、时间戳、单位、完整分钟判据及盘后补齐能力未验证 U8；不能据此宣称1m已可生产。 |
| 全市场快照 | 矩阵§1“日报”提及 `/hsrl/ssjy/all` 与收盘样本；矩阵§2限1次/分钟。盘中全量覆盖/批次/终值未验证 U1/U2；只作为①市场快照的独立任务，不把本人股票池当全市场，不额外承诺备用端点。 |
| 系统目标频率 | `config/realtime.yaml`：快照15秒/轮，全市场60秒，Pro Tier-1 60秒、Tier-2 300秒；stale阈值缺省为2×快照间隔。均是配置目标，非实测供应商刷新频率；股票池按 plan§0A.3 本人持仓∪自选、重点关注分层、剔除有证据的停牌/退市，不扩全市场分钟采集。 |
| 配额与单出口 | 矩阵§2：钻石版6000次/分钟、全市场1次/分钟，同证书60秒超过2个IP报429/103；不是允许团队使用双出口。`config/ingest.yaml` 每证书默认预算3000、P0份额0.7、盘中P2为0；按实际档位/剩余额度排队，不能以文档上限许诺池容量。 |

实现沿 `src/backend/app/ingest/scheduler.py` 的每证书 P0 队列/DRR、`core.py` 的预算及状态机、`egress.py` 的 `single_egress`/`mairui_get` 租约与出口守卫；只有 ingest 可外呼，signal-rt 只消费可信完成事实。沿现有 HALT、暂停、失效证书、限流与无重试拒绝路径，不能照旧 plan 的自动恢复描述绕过当前守卫；重放重复任务须幂等，不重复计量或发事件（API§7.11.5；上述源码）。

### 0.2 时段、存储、口径与缺数

- 时段只用 `src/backend/app/aggregates/calendar.py:market_clock` 和 `config/market_rules.yaml` 生效段（北京时间），不以工作日猜日历。09:15–09:25 开盘集合竞价按 plan§0A.3 不刷新/不改变建议，展示上一收盘并标注；这只是本系统策略，供应商竞价能力在允许资料中未验证 U8。09:25–09:30 为 pre_open；09:30–11:30、13:00–14:57 连续交易，14:57–15:00 单列 closing_auction，不能当普通分钟完整性证据；竞价分钟未核实就保留缺口。
- 午休11:30–13:00、闭市/非交易日不继续排连续交易拉取；午休保留上午最后实测时点，不能刷新时间伪装 fresh。收盘后依据上一交易时段收盘判断新鲜度（API§7.9 `/admin/ingest/status`、plan§0A.3）；日历缺覆盖或规则缺段按现有503失败关闭。停牌须有带时点的事实，剔除采集/计算候选；没有bar不等于停牌，禁止补平价零量K（矩阵§1“风控·停牌”、plan§0A.3、API§1.1）。
- 存储增量按 plan§2.1B/§3.3 与 `src/backend/app/db/tables/market.py`：热缓存键带 licence_id；`quotes_snapshot` 保存可追溯快照，分钟规范化写 `minute_bars source=mairui`，保留行情时点与 fetched_at。现有快照缺证书列、分钟主键仍(code,ts)，须先补来源/证书隔离键与迁移，再接读写，不能不同证书覆盖同一分钟；旧无归属行不冒领，缺字段不落伪值（U9）。
- 保留按已有来源分别列出：plan§0A.3 热缓存TTL 3分钟；§3.3快照当日+近5日，`realtime_quotes` 分钟降采样10个交易日；`deploy/db/timescale/policies.conf` 对后者配21日历日、7天后压缩，分钟配1095日；但 `docs/contracts/intraday-bars.md` §2.2保守默认“不自动删除”、持仓自选推荐3年。表名映射、交易日/日历日及清理优先级未验证 U10；不混称同一保留期，不自动启用新增删除任务，先裁定再做离线清理预览。PG只接麦蕊盘中分钟，TDX/HF离线历史仍走文件目录（该契约§1.2/§3.4）。
- 盘中快照量额与分钟bar量额不得互换；累计/单根语义先核 U8。1m使用Bar结束时间（库列注释），仅返回 ts≤观察时刻且 fetched_at≤知识截止的真实行；迟到修正不回填旧信号/日报。15:00只是时段结束，不能将最后盘中快照改标“正式日线”；矩阵§1/§2的约17:10是文档完成时间，实际定稿仍未验证 U1，日报沿 `daily_snapshot.py` 17:30截止与冻结版本规则。
- 缺数沿共用 `gap_reason`：未接线/无可用行→no_source；真实已排程且尚待发布→not_yet_published；有配额延期→quota_deferred；有故障事实→upstream_error；证书不可用→data_licence_unavailable。缺字段null、保留真0（公共Bar必需量额例外：省根留缺口，见 §0.3 量额结构）；旧数据stale、部分缺失partial、全缺unavailable；不伪造、不插值、不前视。停牌细分枚举尚未落契约时用no_source并解释停牌事实（backlog A2b）；不新造 suspended/not_wired，不把未入队说成pending。
- 与 #185：`src/backend/app/marketdata/quotes_read.py:read_quotes` 当前只回退本人合格日线，量额null、恒stale；拟先校验证书，再优先本人可用实时缓存（过期仍标stale），无可用实时才走现有日线过滤，最后null/gap；GET不触发上游。实时与日线整项选源，不能拼实时价＋旧日量额。T-B185若先补日线量额，须标收盘口径，不能提升为实时fresh；terminal统一复用读取器，保留其他未接线gap（API§1.1 T-A173、§7.3、T-O111建议1/2）。

### 0.3 契约增量与逐入口验收

草案仅在本文件：沿用 QuoteItem/Bar/DataStatusBlock，给 `/quotes` item 和 `/terminal`、`/today` 行quote追加同形 `basis:{mode:"intraday"|"close"|null,trade_date:date|null,source:string|null}`，来源为上述盘中/收盘区别与T-O111“标注收盘口径”要求；t保留行情时间，data_as_of沿API§1.1，不使用请求时刻。内部完成记录增来源端点、证书、观察/采集时间、批次与规范化版本，依据plan§3.3、owned_quotes时点校验；不暴露证书或原始载荷。U8未核字段保持null，不增加臆测单位默认值。
量额结构（闭合治理 B2 及复审 7043101556，口径同 PR 评论 7012015464）：公共 `Bar.volume/amount` 维持不可空十进制字符串（API §5.1 `Bar`）；必需量额未知的根 K 不落库、不返回，走既有 gaps 缺口结构，真零输出 `"0"`，不以 null 或 0 充当未知。`TerminalRow.quote.amount`（`/terminal`、`/today` 复用）在现行正式契约已为 `string(decimal) | null`（可空化首见 2a7f70fc，经 #221（docs/T-A193）以合并提交 3eda9506 首入主线，非 947b70ca/T-A198——后者父提交 1cf82758 已含可空；核读自本次修订时点 main@76a6826c §5.1；本票基线 1490926e 同处尚为不可空 `string(decimal)`，复审所引 :625 即该基线旧文），实现 `aggregates/models.py` 同形，故「沿用可空 amount」以现行 main 为据，不指基线旧文。`/quotes` 行量额现行正式契约未标可空、读取器已按 null 输出属实现先行；量额可空化与 `TerminalQuote` 新增 `volume: string(decimal) | null`（单位股）一并列为待并入正式 API 契约的草案增量，均须在 I7/I8 实施前先修订 `docs/api-contract.md` 相应条目并入正式版本，不得先改代码后补契约，不以实现 null 冒充正式能力。三入口行量额与价格整项同源同批，实时批缺量额则该行量额 null 并计缺口，不用实时价拼旧日量额；旧响应/旧归档可缺新增键，读取按缺省投影、缺值不补零。M1 与 #276 只验证市场 basis/投影，不提前实现本条。
`src/backend/app/aggregates/t_view.py:today_bars` 当前未过滤证书/fetched_at且空量额转0，历史量缓存亦须纳入证书和知识截止；草案要求接入本人证书、时点过滤、空量额传播至指标gap。`service.py` 的scheduled=False只在确有排程凭据时替换；管理状态补既有heartbeat/freshness，不另造健康枚举（API§7.9/§7.10）。

| 受影响入口 | 离线逐入口验收（不能以容器healthy替代） |
| --- | --- |
| ingest / 队列 / signal-rt | 回放“排程→P0→规范化→隔离存储→完成记录→消费”；重复/乱序不重复信号；空模式/非live/暂停/HALT/租约缺失均0外呼，signal-rt不取源、不因采集完成自动晋级策略。 |
| GET `/quotes` | 1–200代码校验；实时→旧实时stale→日线stale→null各夹具；证书失效优先全空；A/B隔离、未来fetched_at排除、整项同口径、GET无入队/外呼。 |
| GET `/terminal`、页面 `/terminal` | 行价/量/额/时间/basis与quotes同源；真实0、null、盘中/收盘标签可辨；既有account.pnl_day/市场环境缺口不随行情成功消失。 |
| GET `/today`、页面 `/today` | quote同上；t_view仅本人mairui、当日可见分钟；缺量额不算0/VWAP，历史不足仍gap；真实排程才pending；午休、停牌、跨日、T+1可卖量均回归。 |
| GET `/securities/{code}/bars`；`/stocks/:code`、终端/市场图表 | 1m仅真实已完成bar、none口径；断点留空不插值，不用日K合成分钟；相同时间不同证书/来源不串读，缺频率保留gap；既有5m读规则沿intraday-bars§2.2。 |
| GET `/admin/ingest/status`、`/health/ready`、页面 `/admin/ingest` | heartbeat共用判定，租约缺失leader=null；freshness六行按API既有顺序/阈值；队列/错误/预算来自真实记录，不以心跳冒充行情新鲜。 |
| `/market/overview`、日报读取/构建 | ⓪只交付①M2可消费的独立快照完成记录，未完成M单仍保留市场gap；分钟摘要沿intraday-bars§3.5冻结，晚到仅新revision，未确认终值不冒充收盘，owned集合不扩大。 |
| `/signals`、通知/SSE、today/terminal事件刷新 | 沿现有事件类型和Consumer，可信证书内事实、去重、防抖和数据不足不发信号；无未验证做T阈值；断线按既有轮询读取，不让GET拉源（plan§0A.3、intraday-bars§3.3/§3.5）。 |

### 0.4 拆单（16，含用户切 live 1步）


单号对齐（2026-11-21，S12-DOC-ALIGN）：I1–I15 已按 T-A209 编号裁定（2026-11-16 团队编号文件）落定，下表建议单号列同步替换为实号；I3（T-B197）对应 #323 已于 2026-11-21 15:49:42 MST 合入 `a861679d`（离线 P0 计划器：默认关闭、零外呼、零 timer；5 文件 +399/−10），实施范围以该合入为准，本表仅登记编号与验收口径；I16 切 live 仍须用户本人批准。R/ V/ D 系列尚未编号，保持占位。
默认 **dry-run/录制回放与离线夹具测试**；“录制”只使用既有授权脱敏材料，本轮不采新样本。下列I1–I15只开发和离线验收，测试替身拦截网络且不加载环境/证书。**切 live（真调麦蕊、开盘中定时任务上线）属硬红线，须用户本人批准，单列I16且不由团队执行**（本次用户指令、backlog B0、intraday-bars红线）。现有 `src/backend/app/ingest/mode.py:verification_is_offline` 仅控制证书验证且空模式按live处理，不能充当新增盘中任务的默认离线保证；I4/I9须交付默认禁用的生产接线及显式启用门控，I16前不激活。不得仅删除test守卫或改MAIRUI_MODE就自动上线；部署长期授权不等于切live授权。

| 别名｜建议单号 | 范围/净增上限（均含测试） | 依赖 | 验收 |
| --- | --- | --- | --- |
| I1｜T-B195 | 契约/字段证据清单、规范化夹具，300行 | 本节；U8逐项标识 | 未验证字段不能冒充已核实；basis及空值可序列化。 |
| I2｜T-B196 | 快照/分钟归属键迁移及存储适配，380行 | I1；处理U9 | 两证书同分钟不覆盖，旧无归属行隔离、回滚拒丢数据。 |
| I3｜T-B197 | 日历、股票池分层、P0排程，350行 | I1 | 时段边界/停牌/休市、预算不足与重放去重；默认不启定时器。 |
| I4｜T-B198 | 盘中任务接已有出口/租约/预算守卫，350行 | I3 | dry-run只产计划；回放无socket；暂停/HALT/失效/无租约拒绝。 |
| I5｜T-B199 | 快照规范化、缓存/完成记录，380行 | I2/I4；U8字段证据 | 空量额不补0，真实时点、幂等；全市场适配另依U1/U2归M2。 |
| I6｜T-B200 | 1m规范化、幂等入库与迟到处理，380行 | I2/I4；U8分钟证据 | 只写mairui，重复/乱序/未完成bar/单位未知均有夹具。 |
| I7｜T-B201 | quotes/terminal实时优先与日线回退，350行 | I5；核对T-B185交付 | #185过滤不退化；失效证书全空、量额不混源、basis一致。 |
| I8｜T-B202 | bars/today证书时点隔离、空值与排程，380行 | I3/I6/I7 | 当前/历史缓存隔离，未知量额不算0，未排程不pending。 |
| I9｜T-B203 | 可信完成事实接signal-rt消费，350行 | I5/I6 | 离线端到端、防重复事件；仍保持生产禁用，不自动开启策略。 |
| I10｜T-B204 | 缓存过期、保留/降采样预览，300行 | I2/I5/I6；U10裁定 | 按来源/证书/时间边界预览；未裁定无自动删除。 |
| I11｜T-B205 | 管理心跳/租约/六类新鲜度，350行 | I3–I6；核对T-B185交付 | ready与admin同判；没有采集不报fresh，计数不造。 |
| I12｜T-B206 | 日报分钟摘要冻结读取，300行 | I6/I8 | 仅本人mairui；晚到不改旧revision，缺源有gap。 |
| I13｜T-F65 | quote basis与逐入口缺数展示，350行 | I7/I8/I11/I12 | 终端/today/个股/管理/日报旧响应兼容，盘中与收盘可辨。 |
| I14｜T-B207 | 离线集成验收矩阵与回放，380行 | I2–I12 | 双证书、竞价/午休/收盘、迟到、限流/HALT、断点、0外呼。 |
| I15｜T-F66 | 前端夹具、旧响应及轮询回归，300行 | I13/I14 | 逐入口null/0/stale/pending、标签、断线重连及空图。 |
| I16｜用户步骤-I16 | 切 live（非团队实施单），0行 | I14/I15；U1/U2/U8–U10相关阻断关闭；用户本人批准 | 由用户本人决定并执行真调/开盘中定时任务上线；未批准保持禁用，不能记为已验收。 |

## 1. 总排序

| 序 | 项 | 价值 | 依赖 | 风险 | 拆单数 |
| --- | --- | --- | --- | --- | ---: |
| 1 | ⓪盘中实时/分时采集 | 修复终端量额、盘中过期与关注页分时缺源的根因 | 本人证书、日历、P0队列/出口守卫；U8–U10 | 单出口、串证书、伪实时、未获准切live | 16 |
| 2 | ①市场概览/日报市场环境与宽度 | 修复两个固定未接线入口，并统一今日关注、终端市场环境 | 本人缓存、全市场收盘快照、F24/F25、日历 | 样本冒充全市场、混时点、F50 冒充 F25、只存不推边界 | 11 |
| 3 | ②/restrictions 禁投·冷静期·屏蔽 | 把现有阻断原因变成可管理闭环 | 限制表、候选原因与状态事件 | 删除后仍阻断、重复限制误解除、跨用户操作 | 6 |
| 4 | ③/reviews 复盘 | 串联计划版本、实际成交、结果和经验 | 不可变版本、本人交易与收盘证据；指标口径 U5 | 模拟冒充实绩、费用漏算、事后数据污染原判断 | 8 |
| 5 | ④/discover 发现 | 先恢复策略入口，再提供有覆盖说明的缓存筛选 | 策略库、PIT 截面与筛选支持范围 U6 | 空结果被误认无机会、全市场范围扩张、跨策略综合评分 | 6 |

理由：⓪由backlog B0指定首位，消除T-O111同源缺口并给①提供采集基础；①命中主线现有页面和日报固定缺口（`docs/plan.md` §0A；T-A210 G01）；②已存在表和阻断读取，闭环收益大且不依赖行情供应商；③需先厘清真实结果口径；④在 `docs/plan.md` §2.4 已规定入口并入策略库，完整筛选又尚无本版 API，优先级最后。价值排序不是串行阻塞：②及④入口跳转可在①数据准备期间先交付。
共 **47 单/步骤**（⓪16，原①–④合计31；含用户I16，团队实施46单）；I/M/R/V/D 为本文依赖别名；正式建议单号中 I/M 已按 2026-11-16 编号裁定落定（见 §0.4/§3.3 对齐注），R/V/D 仍留给编排者，未冒充已派单。每单≤400行净增，上限含代码、测试、迁移、契约与生成文件；达到上限前再拆，不能把测试排除在额度外。

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
| 指数清单；price/change_pct/amount/t | 清单由后端配置（API §7.3 `/market/overview`）；矩阵§1只支持指数日线候选 `/hsindex/history/000300.SH/d`；指数实时端点在两份允许资料中未验证 U1 | 不把指数清单写死为本报告样例；实时字段映射、单位、指数实际覆盖未验证 U1；缺哪只就保留该只 null/gap。 |
| 沪深股票涨跌家数、上涨占比 | `/hsrl/ssjy/all`见矩阵§1；字段映射未验证 U1；计算规则来自 `docs/strategies/feature_spec.md` F24：d 日沪深 stock、有成交、剔除北交所与非股票；上涨用快照 pc>0、平盘不算上涨、停牌不进分母 | 快照pc/日线pc语义须逐字段核验（U1），不能同名直连。盘中数为暂态；收盘 F24 在15:05后，4位小数 ratio；单位与实际定版仍未验证 U1。 |
| 跌/平、成交额 | 同一批已验证快照中 pc<0/pc=0；两市成交额按上述股票范围累加 cje（页面需求见MarketPage；cje映射/单位在允许资料中未验证 U1） | 本方案按 F24 统一沪深范围，不称沪深北全 A；主数据在观察时点的资格和快照覆盖未验证 U2；不得使用固定5577作分母。 |
| 涨停/跌停家数 | 矩阵§5 N6提及涨停股池约30天回溯；实时涨跌停端点/字段在允许资料中未验证 U4；计算规则见plan§2.13与feature_spec | 只采用同日同范围已验证封板事实；盘中当前封板与盘后收盘封板分开；不以统一±10%猜涨跌停。具体缓存字段/覆盖未验证 U4。 |
| regime、参考仓位区间 | F25（feature_spec）：指数 MA20/MA60＋20日宽度、连续2日防抖；有效指数不足45根或宽度不足15值→null；正式阈值由 G-02 定；区间取 RC3 `regime_ranges`（API §5.3、plan §6.1） | F25正式参数/可运行产物未验证 U3；不套用示例阈值，不用仅指数的 F50替代；缺 F25时区间也为null，RC3仍按缺失处理。 |
| 本地日线库 | `src/backend/app/marketdata/daily_bars.py:upsert_daily_bars`、`daily_universe`；`src/backend/app/marketdata/daily_snapshot.py:build_owned_snapshot` | 可复用本人合格指数/日线读取条件，不能用持仓∪自选当市场样本；全市场回算宽度须另行变更源契约§9.6，本轮主方案采用独立市场快照，不全库扫描。 |
| 通达信本地 | `docs/contracts/daily-bars-tdx.md` §2–§4：none、tdx_local、pre_close/is_suspended=null，股票价÷100、量=股、额=float32元 | 仅离线研究/核对；不能作为本方案日报市场环境的自动回退。无前收不能用昨收冒充除权参考价，无行不推断停牌。本次不读实际文件。 |
| 成本与采集频率 | T-A136 §2：旧样本5577只×727日约405万行、逐只history约5577次；ssjy/all候选限1次/分钟（矩阵§2）；源契约§8.3/§9.6校正为N×ceil(W/k) | 只作取舍依据，不当当前容量事实或外呼授权；盘中轮询间隔沿现有配置/plan §0A.3，不新增任意TTL；全市场快照由ingest形成，GET不拉取。 |

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
单号对齐（2026-11-21，S12-DOC-ALIGN）：M1–M11 已按 T-A209 编号裁定落定（M1 T-B187、M2 T-B188、M3 T-B189、M4 T-B190、M5 T-B191、M6 T-B192、M7 T-B193、M8 T-F61、M9 T-F62、M10 T-B194、M11 T-F63），下表同步替换。M1（T-B187）已由 #312 合入 8bb1673f：API v0.2.11 四处 `MarketBasis`、内部市场快照 schema 与日报旧档只读投影已入主线，无快照时 `basis=null`，未新增采集/写入/市场读取（M2/M6/M7、I7/I8、U1–U4 仍待后续单）。


| 别名｜建议单号 | 范围/净增上限 | 依赖 | 验收 |
| --- | --- | --- | --- |
| M1｜T-B187 | 后端市场快照schema、basis与契约增量，300行 | 本草案 | 本人/证书、来源时点、空值均可序列化；旧响应可投影。 |
| M2｜T-B188 | 后端可信采集完成适配器，350行 | M1、I4/I5；U1/U2/U4 | 输入显式批次/来源事实；无网络；缺字段拒绝对应产物；不改真实调度开关。 |
| M3｜T-B189 | 后端宽度、成交额计算，320行 | M2 | 资格过滤、停牌、缺成员、涨跌停缺口；不以样本外推。 |
| M4｜T-B190 | 后端收盘冻结、按时点选批，280行 | M3 | 同批去重；早到非终值、晚到不可前视；重读旧批稳定。 |
| M5｜T-B191 | 后端F25产物接入、RC3区间读取，300行 | M4；U3 | 未裁定参数保持gap；正式口径冻结后测预热、防抖；无F50替代。 |
| M6｜T-B192 | 后端概览/today/terminal市场读取，320行 | M4/M5 | 三入口同源同值、200缺口、503日历、ETag与账户空值。 |
| M7｜T-B193 | 后端日报冻结、旧版投影与时点，300行 | M4/M5 | 新revision有真实证据，旧body不变；全市场股票不进入stocks。 |
| M8｜T-F61 | 前端市场basis/缺口/零分母展示，260行 | M1/M6 | 两条市场路由一致；部分/旧批标签准确，图表缺频率不造数。 |
| M9｜T-F62 | 前端日报/today/terminal来源联动，280行 | M6/M7 | 入口矩阵中的环境/区间/证据/旧报告均可读。 |
| M10｜T-B194 | 后端隔离合成测试，380行 | M2–M7 | 两用户、未来时点、收盘边界、缺成员、无F25、revision、只存不推及无外呼。 |
| M11｜T-F63 | 前端夹具与交互测试，300行 | M8/M9 | 全空/部分/0/旧批、别名、旧日报、图表请求、无NaN。 |

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
| U7 | T-O111只证明其观察窗口，当前运行数据未复查；backlog末项给出87项分类18未做/69未验证，未逐项重验；T-A136成本是旧估算 | 不承诺上线消除所有缺口或容量 |
| U8 | 实时/1m完整字段、单位、累计/单根量额、结束时点/修订/盘后补齐、竞价及ETF覆盖；需允许资料补入既有授权脱敏证据，缺失继续标未验证，不能自行实调 | I1/I5/I6与live；离线假数据仅证实现，不证能力 |
| U9 | 快照/分钟来源证书键与旧数据兼容、读侧知识截止、完成记录对接；以源码及离线迁移/双证书夹具关闭，现场状态不据此宣称已修 | I2/I8/I9与live |
| U10 | quotes_snapshot/realtime_quotes映射与保留冲突：近5日、10交易日/21日历日、分钟不自动删/1095天；须有引用依据的统一裁定及预览对账 | I10与live清理配置，未关闭不新增自动删除 |

### 7.1 U1–U7 补证交接（闭合治理 B1）

按 #273 评论 7012015464 落地：负责人为建议属主，接收与到期由编排者登记；证据交齐并经复核签收前，对应 U 保持“未验证”，不因指派而关闭。U8–U10 及未编号实现沿原依赖，不因本表扩权。审核人＝复核；U3/U5/U6 的定义与用途边界先经架构核再交复核。

| 编号｜负责人 | 补证证据/产物 | 关闭判据（复核签收） |
| --- | --- | --- |
| U1｜后端M2＋运维 | 已授权脱敏快照的逐字段/单位对照表，含批次一致性与终值时点记录，15:05 与终值事实分开留证 | 字段逐项有出处、同批可重演、15:05 下限与终值可区分 |
| U2｜研究员＋后端M2 | 时点资格池与同日源批的逐成员对账表：可见资格、成交/停牌证据、漏项与覆盖计数 | 逐成员闭合、不以当前名单补历史；覆盖不明仍 null |
| U3｜研究员＋后端M5 | 具版号 G-02 正式参数、运行门禁与 F25 可重算历史产物 | 架构核参数来源；预热/防抖按正式参数重算一致；缺证 regime/区间仍 null |
| U4｜研究员＋后端M2/M3 | 涨跌停源字段、市场范围、时点与特殊交易制度对照表 | 逐市场逐规则段核涨跌停与真实零；缺项旧 breadth 整体 null 不变 |
| U5｜研究员＋后端V4 | 收益/费用/现金流/分红/未平仓/行业基准的指标定义与手算样例 | 架构审定义；样例可重算、模拟与实绩隔离 |
| U6｜后端D2/D3＋研究员 | 策略版本支持矩阵、缓存覆盖范围与研究读链映射 | 架构审用途边界；支持/拒绝/未知与零命中各有实测 |
| U7｜运维＋测试 | 重验输入＝锁定的 T-O111 观察版本、T-A210 原 87 条编号清单、当前 main 只读检出及运行日志；产物＝逐项旧/新归类、证据指针、未验证原因、与 T-A136 成本假设的差异清单 | 87 条逐项对账完成、原 18/69 基线可追溯、无证项仍标未验证 |
| U8｜后端I1/I5/I6＋运维 | 允许资料内既有授权脱敏证据的实时/1m 逐端点字段、单位、累计与单根量额、结束时点/修订/盘后补齐、竞价及 ETF 覆盖对照表；不自行实调 | 复核签收：逐端点逐字段有出处；缺证仍标未验证，不以离线假数据证能力 |
| U9｜后端I2/I8/I9 | 快照/分钟来源证书键与旧数据兼容的源码核读、离线迁移与双证书夹具验收记录 | 复核签收：两证书同分钟不覆盖、旧无归属行隔离；现场状态不据此宣称已修 |
| U10｜运维＋后端I10 | quotes_snapshot/realtime_quotes 表名映射与保留期冲突清单、有引用依据的统一裁定及清理预览对账 | 复核签收：裁定落地且预览对账一致；未关闭前不新增自动删除 |

## 8. 本次验收
> 注（2026-11-21，S12-DOC-ALIGN）：下述脚本为 2026-11-16 原稿验收记录；建议单号占位替换为已裁定编号后，正则中「待编排者编号」分支仅适用于替换前的历史版本。


本次静态文档验收已通过：不导入应用、不启动服务/pytest、不连数据库、不加载.env/密钥；只改本文件，代码只读，不联网、不真调、不提交、不push。执行下列命令核对全文≤300行、五项排序、16+31=47单/步骤、每单≤400行含测试、10组未验证、引用函数与允许修改范围；stdout仅3行计数。
```bash
python3 -B - <<'PY'
from pathlib import Path
import re, subprocess
p = Path('docs/contracts/T-A209-market-wiring.md'); s = p.read_text()
assert len(s.splitlines()) <= 300
rows = re.findall(r'^\| ([IMRVD]\d+)｜(?:T-[BF]待编排者编号|用户步骤)-\1 \|[^\n]*?(\d+)行 \|', s, re.M)
assert len(rows) == 47 and all(int(n) <= 400 for _, n in rows)
assert [sum(k.startswith(x) for k, _ in rows) for x in 'IMRVD'] == [16, 11, 6, 8, 6]
assert re.findall(r'^\| [1-5] \| ([⓪①②③④])', s, re.M) == list('⓪①②③④')
assert s.index('## 0. ⓪') < s.index('## 1. 总排序') < s.index('## 3. ①')
assert len(re.findall(r'^\| U(?:[1-9]|10) \|', s, re.M)) == 10
for file, func in set(re.findall(r'`(src/[^`:\s]+\.py):([A-Za-z_]\w*)`', s)):
    assert re.search(r'\bdef ' + re.escape(func) + r'\s*\(', Path(file).read_text()), (file, func)
for name in set(re.findall(r'(?:docs|src|config|deploy)/[A-Za-z0-9_./-]+\.(?:md|py|yaml|conf)', s)):
    assert Path(name).is_file(), name
for name in ('/workspace/team/reports/T-O111.md', '/workspace/team/tasks/BACKLOG-1116-gaps.md'):
    assert Path(name).is_file()
assert subprocess.check_output(['git', 'diff', '--name-only'], text=True).splitlines() == [str(p)]
assert not subprocess.check_output(['git', 'diff', '--cached', '--name-only'], text=True).strip()
assert not subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], text=True).strip()
subprocess.run(['git', 'diff', '--check'], check=True)
print('⓪拆单数：16（含用户切live 1步）')
print('新总单数：47（团队46＋用户1）')
print('未验证数：10组（U1–U10）')
PY
```
验收边界：以上验证方案结构与改动范围，不是未来实施单的功能验收；U1–U10仍待关闭，I16未执行。原①–④未因新增采集而宣称已接线。

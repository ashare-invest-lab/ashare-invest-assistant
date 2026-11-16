# Horizon 输入底座契约（T-A192）

## 1. 规格基线与适用范围

本契约裁定 T-B172 的六项阻塞，供 A0/A1 离线实施；不表示实现、真实数据或生产迁移已验收。仓库核对基点为 `ccd3eb2`。
实现以**本契约 + main 上的 T-R78 规格**为准；本契约细化底座，T-A188 的 Q01–Q12 继续约束特征语义及暂缓项，不重开评分、单位或供应商口径。
本次输入为 `.codex-input/T-B172.md`、`.codex-input/T-R78.md`「§T-A188」及 `.codex-input/horizon_inputs_spec.md`；后者是 #205 草稿，当前仓库没有已跟踪的 `docs/strategies/T-R78/` 规格。
#205 定稿须并入 T-A188 裁定引用，逐项指向 Q01–Q12 及共同裁定，修正 horizon API 节号为 §7.4；不得引用尚不存在的 `T-A188-rulings.md` 当作已发布依据。
本契约可先支持 A0/A1 的合成实现；真实特征接入须等待上述规格进入 main，未入 main 的草稿不能单独充当启用基线。

出处简称（均为仓库内文件；引用节号、函数名、表名，不用行号）：
- P＝[plan.md](../plan.md)；N＝[plan-next.md](../plan-next.md)；API＝[api-contract.md](../api-contract.md)。
- C＝[trading-calendar-exrights.md](trading-calendar-exrights.md)；R＝[daily-snapshot-from-bars.md](daily-snapshot-from-bars.md)。
- M＝[multi-source-ingest.md](multi-source-ingest.md)；W＝[daily-bars-source.md](daily-bars-source.md)。
- F＝[mairui-same-source-final-replace.md](mairui-same-source-final-replace.md)；L＝[post-close-synthetic-loop.md](post-close-synthetic-loop.md)。
- D＝`docs/strategies/phase2_daily_dimensions.md`；S＝T-R78 规格（本次仅输入副本）；A188＝输入报告「§T-A188」。下文 `app/` 指 `src/backend/app/`。

统一约束：`as_of` 必须带时区，按瞬时比较，T 为其北京日期；`available_at≤as_of` 且业务生效时间不晚于使用时点。缺即 null，未知不当 0，不猜单位，不用当前主数据补历史。
一轮评估只选一次 d；全部特征及三个分位池固定该 d、本人、证书、日历与来源版本，单键缺数不得自行回退旧日。派生可见时间为全部必要依赖的最大值；已落库派生还不得早于实际产出时间。
TEAM-RULES 第二节原文：「硬红线仍须用户本人批准：真调麦蕊（日K、分钟、单 D）、生产部署、删除用户数据、对外发送、解除 HALT、恢复外网出口、backfill --apply。（通达信真实全量导入已由用户 11-14 t1110u 授权，见本文件「t1110u」条；仍须走 upsert_daily_bars 并过写库门闩，绕开按误放处理。）」普通已派单登记不需本人重复批准，不将所有真实库 `--apply` 统列为硬红线；既有授权范围不重复批准，BJ 门闩保留。禁止借本单恢复出网、补取或 push。

## 2. 六项裁定

### A0-1 完成证据来源

结论｜`daily_snapshot.daily_bars_ready` 不是逐证券完成证据；当日例行 mairui 路径中只能作为必要批门禁之一。逐证券采用本节的版本化证据判据；无证据不得推断。｜出处｜A188 共同裁定/Q12、R §14、D §2 D 行；`app/marketdata/daily_snapshot.py` 的 `daily_bars_ready`、`_bar_item`；`app.pipeline_runs`。｜验收测试名（待新增）｜`test_a192_finality_requires_visible_symbol_proof`、`test_a192_ready_partial_not_symbol_final`、`test_a192_no_proof_falls_back_or_null`。

设 E(s,t,a) 为在截止 a 可引用的证券 s、交易日 t 的同源定稿证明。E 成立当且仅当以下条件全部满足：
1. 有不可变日线版本，明确 code、trade_date、adj_type=none、source、来源版本摘要与本人/证书范围；该版本已实际持久化，`first_seen_at`、`available_at` 均可证且 ≤a。
2. 有与该版本摘要精确绑定的定稿记录，`is_final=true`，其自身 `available_at≤a`；记录含同源明确的完成声明及可审计回执，能证明该证券该日的数据完成。批成功、接口成功、文件存在、非空 OHLC 均不能代替此声明。
3. 证据来自同一 source/证书/版本，没有未解决的修订冲突；拒绝用旧证据证明新行、用另一证券或另一证书补洞。`tdx_local` 不进入 owned/horizon 日线路径，沿 R §14、M §4；fake 只用于显式合成夹具。
4. mairui 当日例行路径还须有截止 a 前已可见的本人适用例行批就绪回执（ok 或 partial），且该证券无缺行/冲突；回执固定 run_id、运行范围、状态、finished_at、可见时刻与 issues，不能重放时读后来变更的 stats。

例行回执须满足 kind=daily_batch、step=daily_bars.fetch、run_date=T、window_trading_days 缺键或 null，finished_at≤a；无 owner 的全体批还须有该本人/证券属于当时范围的证明。partial 中其他证券失败不阻断已获 E 的证券，partial 本身不生成 E。

`d=T` 的充要条件：日历已覆盖且 T 开市、北京时刻不早于 17:10、E(s,T,as_of) 成立。17:10 是 D §2 的最早使用门禁，**不是**定稿证明；即使到 17:30 或更晚也不能免 E。停牌可有完成的状态证据，但不能据此当有效 K。
否则 d 为 ≤T 且已有 E 的最近开市日（T 未满足上述条件时只选 t<T）；已知休市日取最近完成日。无任何已证日则 d=null，依赖 d 的输入全为 null + gap；日历缺覆盖亦不得按工作日猜 d。
历史 t<T 不要求 t 或 T 的例行批，须有逐证券已证版本；A1 未落地时由注入提供者返回已证明记录，生产默认空提供者，保守退到最近已有证据日；没有则 null，不能直接取“上一根 bar”或机械 T−1。
现状差异：`daily_bars_ready` 接受 ok/partial，按 owner 或无 owner 的批记录选择，且本基点尚未实现 R §14.2 的 window_trading_days 过滤，也不接 as_of；A0 不直接把该布尔值当 PIT 回执。提供者须先滤例行批、再取截止前最新适用批并判状态，失败不得退到旧成功批。
`_bar_item` 的 `first_seen_at=fetched_at`、`is_final=(fetched_at≥FINAL_AFTER)` 及旧快照中的同形字段均标**待迁移、不得供 horizon 认证**。F §2/§6、R §14、L §3 的钟点定义只描述现行写入/快照路径，不足以满足本契约的 E；本单不改旧产物，不放宽或重写其写入规则。
真实供应商完成声明的字段及可核回执来源目前**未验证**；A1b 只能接收验证通过的显式证据，没有则返回缺口，不能发明厂商完成标志或借抓取钟点补证。

### A0-2 17:30 冻结与调用责任

结论｜`collect` 必须接显式 `as_of`，无缺省 now、不自取 now、不内部截到 17:30；冻结由调用方负责。｜出处｜N §1「信号」、A188 Q12；API §7.4；`app/strategy/horizon/inputs.py` 的 `collect`、`app/api/v1/horizon.py` 的 `get_horizon_assessment`。｜验收测试名（待新增）｜`test_a192_collect_explicit_asof_no_clock_or_clamp`、`test_a192_daily_cutoff_http_request_time_replay`。

每日决策调用方传 **T 日 Asia/Shanghai 17:30**，迟到不补跑原决策；HTTP `/horizon-assessments` 由服务端在请求入口捕获一次请求时刻并传入，只公开 security_code，不新增公开 as_of 参数；离线复算传原始 as_of。
明确区分“以原截止复算”与“该时刻已存结果”：后算结果保留真实 computed_at/created_at，不能伪称当时落库。等价时区瞬时必须同结果；缺时区或缺参数直接拒绝。
画像、持仓、成交、状态也受该截止约束；现有 latest_profile、当前 holdings/主数据及 `snapshot_id` 仅哈希 values 的做法不构成历史保证。A0 无版本证据时保留 null，账户版本/FIFO 按 A188 B13；已知缺口：`get_horizon_assessment` 仍返回 `snapshot_id` 函数生成的 values UUID，未履行 API §7.4 的真实快照要求，持久化/复用及本人/证书隔离归正式后继单 T-B177（我方后端），按 L-046 登记，#205 须同步引用 T-B177；实现与验收未验证，本 docs PR 不改后端。

### A0-3 盘中边界

结论｜horizon 的“盘中禁止当日日线”覆盖开市日 **[09:30,15:00)**，含午休；盘前、集合竞价及 15:00 至完成证据成立之间也只能 d<T，且遵守 17:10 最早使用门禁。｜出处｜P §0A.6、§2.13、§6.1 `market_rules.yaml`；`app/aggregates/calendar.py` 的 `market_clock`；A188 共同裁定、D §2；午休纳入 d<T 是本契约对上述约束的明确化。｜验收测试名（待新增）｜`test_a192_session_edges_lunch_close_and_finality`、`test_a188_asof_finality_intraday_close_weekend`。

| 北京时段（开市日） | 交易状态出处与 d 规则 |
| --- | --- |
| 09:15–09:25 | P §2.13 开盘集合竞价；d<T，09:25–09:30 等待阶段同样不得用当日日线 |
| [09:30,11:30)、[13:00,14:57)、[14:57,15:00) | 依次为上午、下午连续竞价及收盘集合竞价；P §2.13 的数值、market_clock 的左闭右开边界；全为 d<T |
| [11:30,13:00) | market_clock 为 lunch_break；不刷新行情不等于日线完成，horizon 仍按盘中 d<T |
| [15:00,17:10)；17:10 以后 E 未成立 | 收市待完成，仍 d<T；15:00、17:10、17:30 均不得单凭钟点放行 |
| 17:10 以后 E 成立 | 恰在证明 available_at 时可引用（含等于）；结合全部条件才 d=T，HTTP 不被内部截时 |

09:15 以前也是 d<T；已知休市与日历缺覆盖须区分，停牌不删交易日。历史特殊交易时段覆盖、真实完成时刻及供应商延迟均未验证，不扩展现有数值来猜测。

### A1-1 表结构与迁移草案

结论｜采用 §3 的两张追加式证据表，承载源/派生版本与逐证券完成证明；复用已有 horizon 快照/评估表，不改共享现值表主键或历史行。｜出处｜A188 Q12/A1；`app/db/tables/market.py` 的 daily_bars、ex_rights_events、factor_values、feature_bars_daily；`app/db/tables/reviews.py` 的 data_snapshots；`app/db/tables/strategy.py` 的 symbol_horizon_assessments；迁移 `0036_tb143_ex_rights_minute_catalog.py`。｜验收测试名（待新增）｜`test_a192_a1a_schema_keys_nullability_indexes`、`test_a192_a1a_append_only_no_history_backfill`。

本地 `src/backend/migrations/versions/` 的唯一 head 为 `0036`（父 `0035`），`paused/0021` 不属活动链；按 §A1-2 拆为两个迁移：`0037`（down_revision=`0036`，be/T-B172b1a，`horizon_input_versions`）与 `0038`（down_revision=`0037`，be/T-B172b1b，`horizon_completion_evidence`），文件名由实现方按既有命名规则定。实施前若 head 前移，重核父节点并改号，不能制造双 head。
**不改 daily_bars 现有写入口**：`upsert_daily_bars`、`daily_bar_write_allowed` 门闩语义保持不变，不另造 INSERT/UPDATE 旁路，不借证据表授权写行情。此基点未找到名为 `daily_bar_write_allowed` 的实现；实际为 `upsert_daily_bars` 调 `_bj_write_unconfirmed`，不得把目标名称当已落地证明（W §10.10–§10.12）。

### A1-2 拆单与规模

结论｜撤销 A1 必须一个 PR 的安排，改为 **A1a＝be/T-B172b1a、b1b（按迁移 0037/0038 拆）；A1b＝be/T-B172b2a、b2b、b2c**（编排者 11-15 裁定），每单独立 PR、净增 ≤800 行，包含迁移/模型/实现/测试及 tests/ci-groups.yaml 登记。｜出处｜A188「后端单草稿」A1 的已有两段估算及 T-B172 阻塞 2；本契约 §3–§5。｜验收测试名（待新增）｜`test_a192_a1a_single_head_empty_upgrade_guarded_downgrade`、`test_a192_a1b_provider_revision_isolation`。

| 单 | 范围与先后 | 验收（均待新增） |
| --- | --- | --- |
| A0（沿用 be/T-B172a） | 显式 as_of、d/窗口、§4 协议及默认空/假提供者；用假提供者测 PIT，不导入 A1 模型。原估算 450–650 行，未验证 | 本节 A0 三项测试；`test_a188_calendar_gap_and_suspension_window` |
| A1a-1（be/T-B172b1a） | 迁移 0037：`horizon_input_versions` 表、模型、约束/索引、不可变性、空库 upgrade/downgrade 与非空拒绝降级；无回填、无生产执行、无外呼。估 400–600 行，未验证；硬上限 ≤800 | A1-1 版本表相关测试及 single_head/upgrade/downgrade 测试 |
| A1a-2（be/T-B172b1b，依赖 b1a） | 迁移 0038：`horizon_completion_evidence` 表、模型、约束/索引及同等迁移验收。估 400–600 行，未验证；硬上限 ≤800 | A1-1 完成证据表相关测试及 single_head/upgrade/downgrade 测试 |
| A1b-1（be/T-B172b2a，依赖 b1a/b1b） | 版本与完成证据登记、校验、依赖链与幂等（register_version/register_completion）。估 422–522 行，未验证；硬上限 ≤800 | 登记幂等、修订链、来源隔离测试 |
| A1b-2（be/T-B172b2b，依赖 b2a） | 版本读取与完成证据提供者（实现 §4 协议），本人/证书/来源隔离。估 352–452 行，未验证；硬上限 ≤800 | provider_revision_isolation；`test_a188_source_revision_and_licence_isolation` |
| A1b-3（be/T-B172b2c，依赖 b2b） | `read_adjustment_factors` 权息可见性适配及向 prepare 的参数转换；仅接已有可证材料，无新采集器、无真实 gbbq 连乘启用，缺因子不补 1。估 292–372 行，未验证；硬上限 ≤800 | §A1-3 测试 |

若估算无法满足，实施前按边界另拆并重新派单，不压缩格式凑行数。两单合计可超过 800，不能合成一个超限 PR；A1b 不包含 B/C 特征算法、FIFO、分位池算法或 T-B177 承接的 C2 快照持久化/复用服务。拆分依据为 reports/T-A192.md 末节的估算（A1b 合计 852–1062 行，未验证）；顺序 A0 → b1a → b1b → b2a → b2b → b2c。

### A1-3 PN-03 权息可见性接口

结论｜已有要求在 C §4.1/§4.2、§11 Q3/Q5、§10 T-B162；已有消费函数为 `features.pipeline.prepare(..., as_of, factors, ...)`，尚无可直接复用的权息可见版本提供者。本契约 §4 定义接口，**归 A1b 实装**，与 PN-03 共用，不再等待一个未定义的 PN-03 前置接口。｜出处｜C 上述各节；M §2.5/§3.4；`market.ex_rights_events`、`app/features/pipeline.py` 的 `prepare`/`factor`；L §4/§11 Q3。｜验收测试名（待新增）｜`test_a192_pn03_unknown_visibility_and_single_snapshot`、`test_a188_qfq_future_event_and_anchor`。

明确采纳 C §11 Q3 的证据定义：事件版本首次进入指定快照且可供计算引用的实际时刻为 available_at，必须有持久化回执；registered_at 等价性仍未验证，不可自动复制。语义已定不代表旧数据已可补齐。
qfq@as_of 只用 `date≤T`、`available_at≤as_of` 且所依赖事件也可见、已生效的因子，价格 `raw(t)×A(t)/A(T)`；每次只用一个明确 snapshot_sha256，禁未来事件、最新展示锚及混锚拼接。
累计因子可按 prepare 取不晚于目标日的最近有效观测，不要求每天一条；覆盖/修订/因子未知时不得靠旧观测掩盖未知事件，缺因子不补 1，返回 `adjust_factor_missing:<date>`。真实 gbbq 连乘式仍“未验证，默认不生效”。

## 3. A1a 存储明细（拟新增，尚未实施）

仅新增下列两张普通 app 表，不建 hypertable。类型沿 `app/db/base.py`：UUID、text、date、timestamptz、jsonb；时间落 UTC，业务日期以北京换算。以下 NN＝NOT NULL，?＝可空；所有可空列无非空默认值，未知不当可见。
共享版本表承载有限的六类输入，payload 必须按下表验证，不允许任意 JSON 绕过证据要求；不会据此自动实现六类生产算法。

### 3.1 app.horizon_input_versions

| 列（完整清单） | 类型/可空性、语义 |
| --- | --- |
| id；user_id；licence_id | UUID NN 主键；UUID NN 本人外键 app.users.id；UUID ? 证书标识（不存证书内容、不以删除证书把历史改为公共数据） |
| kind；source；scope | text NN；kind 限 calendar/daily_bar/vendor_factor/ex_rights/adjust_factor/feature，scope 限 per_licence/public/synthetic；source 为已知源名 |
| code；data_date；source_key | text ?（仅 calendar 可空）；date NN 业务日；text NN 源内逻辑键，见 payload 表 |
| source_version；version_hash；payload | text NN 上游版本/材料摘要；text NN 64 位小写 sha256；jsonb NN 原值及证据包 |
| first_seen_at；available_at；computed_at | timestamptz ? 实际首次可见、可引用、实际产出；不可由事件日或 fetched_at 自动生成，派生种类 computed_at 必填 |
| dependency_ids；transform_version | UUID[] NN 默认空，仅指向本表已存版本；text NN 转换版本（原始可用 identity-v1），不能省略版本归属 |
| supersedes_id；recorded_at | UUID ? 自表外键，指同逻辑键被修订版本；timestamptz NN 默认 now()，仅记录登记时刻，不充当历史可见证据 |

主键 id；版本键/唯一索引 `(user_id,licence_id,kind,source,code,data_date,source_key,version_hash)`，采用 NULLS NOT DISTINCT，避免公共源空证书重复。version_hash 覆盖身份、源版本、payload、可见时点、转换、依赖与 supersedes_id，不只哈希数值。
读取索引 `(user_id,licence_id,kind,code,data_date,available_at)`；另建 supersedes_id 索引。CHECK：per_licence 时 licence_id 非空，其他 scope 时为空；sha 格式；available_at 非空须 first_seen_at 非空且不早于它；派生 available_at 不早于 computed_at。
kind 与 source 出处（T-A192 补，编排者 11-15 裁定单 T-B172b1a 第 4、6 条；出处给齐前 b1a 不加 kind/source CHECK，服务层白名单校验，代码注释标「未验证」）：

| kind（原始/派生） | source 允许值 | 出处 |
| --- | --- | --- |
| calendar（原始） | `merged_calendar`（DS `sessions.merged_calendar` 合并结果）；合成夹具 `fake` | trading-calendar-exrights.md §2 主源行、Q4（合成沿用 fake）；源名作为 source 值为本契约约定，未验证 |
| daily_bar（原始） | `mairui`；合成夹具 `fake`；`tdx_local` 不得登记 | `marketdata/daily_bars._ALLOWED_SOURCES`；multi-source-ingest.md §1 源清单；本契约 §2 A0-1 第 3 条（tdx_local 不进 horizon） |
| ex_rights（原始） | `tdx_gbbq`；合成夹具 `fake` | multi-source-ingest.md §1 源清单、§3.4 |
| vendor_factor（原始） | 未验证：`market.factor_values` 无 source 列，只有 calc_version；源名待 S §3.10/T-R78 horizon_vendor 定稿 | reports/T-R78.md horizon_vendor 节；在出处前 b2a 拒绝登记该 kind |
| adjust_factor（派生） | 派生不取外部源名，固定为算法标识 `derived`，来源由 dependency_ids 指向 ex_rights 与参考价版本 | 本契约 §3.1 payload 表 adjust_factor 行、§A1-3；`derived` 取值为本契约约定，未验证 |
| feature（派生） | 同上 `derived`；仅唯一 features pipeline 产出 | 本契约 §3.1 payload 表 feature 行；`derived` 取值同上未验证 |

派生 kind 清单＝adjust_factor、feature（computed_at 必填、available_at 按依赖取 max）；六类划分本身来自 A188 Q12/A1 的输入清单与本契约 §3.1，不另有外部出处。scope 与 source 搭配：`fake` 只配 synthetic，`mairui` 只配 per_licence，`merged_calendar`/`tdx_gbbq`/`derived` 配 public 或 per_licence（随依赖），未验证。

服务验证 dependency_ids 全部存在、无环、同本人/合法来源范围；supersedes 仅同逻辑键，不跨证书。派生 available_at=max(必要依赖可见时刻、实际 computed_at)，任一依赖未知则整体未知，不跳过 null 取 max。

| kind / source_key | payload 必需内容及条件可空性 |
| --- | --- |
| calendar / merged_calendar | data_date 的 is_open（bool 非空）、覆盖范围、主源版本/sha、重叠核对证据；缺自然日不能形成完整窗口 |
| daily_bar / none | open/high/low/close/pre_close/volume/amount（十进制字符串或 null）、is_suspended（bool 或 null）、原始字段/单位、标准单位、fetched_at（可空）、原表键/摘要、持久化回执；单位未知则原值留存但不可作为已归一输入 |
| vendor_factor / factor_id | factor_id、raw_value/value（十进制字符串或 null）、raw_unit/unit（可空）、窗口与披露/修订证据、原 calc_version；缺单位/PIT/窗口任一项即不输出主值 |
| ex_rights / snapshot_sha256 | code/ex_date、cash_per_share/rights_price/bonus_ratio/rights_ratio（十进制字符串）、snapshot_sha256、事件版本与首次可引用回执；旧 registered_at 只作旁证，未知时点保持 null |
| adjust_factor / 累计因子系列标识 | date/value（正十进制字符串）、snapshot_sha256、事件及参考价 dependency_ids、已验证算法版本、覆盖/完整性证据；纯合成明确 synthetic，不把空事件集合自动解释为因子 1 |
| feature / feature_set_version | values（缺值为 null）、units/raw_values/transforms、window、qfq_anchor=T、全部依赖与完成证据 ID、日历/因子/截面版本、评估 as_of/d；仅唯一 features pipeline 产出，不复制另一套算法 |

payload 的依赖/证据引用均须绑定版本摘要；没有的可选业务值显式 null，不能把必需字段省略当成功。三个分位的原值、ratio、完整成员及池版本由 C1/C2 固化到快照并引用，A1b 不计算分位。

### 3.2 app.horizon_completion_evidence

| 列（完整清单） | 类型/可空性、语义 |
| --- | --- |
| id；bar_version_id | UUID NN 主键；UUID NN 外键 horizon_input_versions.id，必须指 daily_bar；本人/证书/证券/日期从该版本继承 |
| pipeline_run_id | UUID ? 外键 app.pipeline_runs.id；当日 mairui 例行路径必填，历史证据可空；关联本身不证明 ready |
| is_final；available_at | bool ?（未知为 null）；timestamptz ? 该证明首次可引用时刻；is_final=true 必须 available_at 非空 |
| proof_kind；proof_hash；proof | text NN（source_final_receipt 或 synthetic）；text NN 64 位小写 sha256；jsonb NN 不可变证明正文 |
| recorded_at | timestamptz NN 默认 now()，仅登记时刻 |

版本键/唯一约束 `(bar_version_id,proof_hash)`；读取索引 `(bar_version_id,available_at)`、pipeline_run_id 索引；CHECK sha 格式及 true 必须有可见时点。proof_hash 覆盖证明全文、is_final、available_at 与关联版本。
proof 必含同源完成声明、证券/日期/来源/证书/版本摘要、原始回执摘要及持久化证据；例行批另固化 A0-1 第 4 项各字段。验证器校验与 bar 完全一致；synthetic 只能绑定 synthetic 版本。
证据与 bar 两边均通过 PIT 才 E 成立。多条证明矛盾且无法确定修订关系时返回 gap，不按数据库 ID 或任意排序挑一条；未知后来被证明时追加新证明，旧证明不改写。

### 3.3 不可变性、回填与既有表

两表拒绝 UPDATE，A1a 以触发器落实；重试按版本键 DO NOTHING 后比较全包，相同幂等，不同内容冲突即拒绝。保留删除用户数据的既有受控清理权限，不用不可变性绕过隐私删除；本单不执行删除。
迁移只建空表，**不批量回填历史**；旧 daily_bars/factor_values/feature_bars_daily 无版本或归属证明的不提升为 PIT 数据。首次登记仅可证明当前观察，不把旧 fetched_at、registered_at 或日期零点倒填为首次可见。
新写版本的实际持久化/可引用回执才能确立 available_at；事务未提交或回滚不发布完成证明。登记可晚于原始材料可见时刻，但只有原先已保存的不可变回执能证明历史可见，不能事后生成早时刻。
修订必须追加并留旧值；无法恢复的替换前版本留 gap，不能声称现值表能恢复历史。A1b 只登记已经保存的版本材料，不为“补证”修改 upsert 或打开同源替换。
`market.daily_bars`、`ex_rights_events`、`factor_values`、`feature_bars_daily`、`trading_calendar`、`app.pipeline_runs` **均零列变更**，其旧主键/索引/可空性及写行为保留；新表是 horizon 严格读取的版本层，不是新的行情写入口。
`app.data_snapshots`、`app.symbol_horizon_assessments` 同样零列变更。前者已有 purpose=horizon、user_id/licence_id、items/hash/created_at；后者已有 snapshot_id、classifier_version_id、evidence 等，不能重复迁移 purpose 枚举；API §7.4 要求的真实快照及评估落库缺口由 T-B177 承接，未验证。
C2 的新 items 包须含 schema_version、as_of、T、d（可空）、来源/证据/特征/日历/截面版本与缺口；hash/复用键含本人、证书、时点、分类器/转换版本，不能仅 values UUID。同一包复用，变更另存，旧 assessment/snapshot 不回写。T-B177 须验收返回的 snapshot_id 在 data_snapshots 真实存在、评估关联该快照、本人/证书隔离及同一输入重复请求复用；持久化与复用验收未验证。
仅隔离空库可验 upgrade/downgrade；两表有数据时 downgrade 必须拒绝，不以 DROP TABLE 抹历史。生产迁移按 §1 的生产部署批准关口执行；普通已派单的历史材料登记不需本人重复批准，既有授权及 upsert_daily_bars、BJ 门闩仍按 §1 执行。

## 4. A0 协议与 A1b 提供者（内部接口草案）

接口类型由 A0 在拟增 `app/features/horizon_sources.py` 定义，不导入数据库表；A1b 在同模块或适配模块实现，供 PN-03/T-B162 与 horizon 共用。以下是签名约定，不是当前已存在函数。
- `collect(conn, user_id, code, features, *, as_of: datetime, evidence_provider: HorizonEvidenceProvider) -> Inputs`。
- `HorizonEvidenceProvider.read_basis(*, user_id: UUID, licence_id: UUID | None, code: str, as_of: datetime) -> BasisEvidence`：返回可见日历版本/覆盖、按日期的日线版本及完成证明、批回执、gaps，A0 负责统一选 d。
- `HorizonEvidenceProvider.read_versions(*, user_id, licence_id, code, kind, dates, as_of) -> VersionBundle`：返回 immutable IDs、源/单位/转换、依赖、可见时点与 gaps；先按范围/PIT 筛选，再按显式修订链选版本，冲突不任意择一。
- `read_adjustment_factors(conn, *, user_id: UUID, licence_id: UUID | None, code: str, dates: Sequence[date], as_of: datetime, snapshot_sha256: str) -> FactorBundle`（A1b/PN-03）：dates 含窗口日期及锚 T，返回 `factors=[{date,value,available_at,version_id}]`、dependency_ids、snapshot_sha256、coverage、gaps。

所有返回包均带来源版本及可见性；licence_id=None 只能读明确 public/synthetic 范围，不能匹配 mairui 的空绑定行；public 引用须显式声明，不作为跨证书回退。来源资格沿现行门禁，授权与 PIT 分开检查。
A0 固定 d 后，日线/窗口和三个分位池只取业务日期≤d；传 prepare 的 sessions 截到 d，as_of 保留原截止、qfq 锚仍为 T，不把 as_of 改成 d 收盘。F14/F15 仍按前一交易日交付、次日生效，d=T 不提前使用 T 日状态。
FactorBundle 先校验事件可见/生效、同快照、完整性、因子来源/转换，再适配为 prepare 的 date/value/available_at；无合格版本返回空 factors + gap，不默认单位或因子 1。未知事件时点不得静默排除后输出“完整”累计因子。
证据登记只消费可审计材料，无采集副作用；读取不抓行情、不建任务、不注册新定时器。旧 ready/快照只作旁证，不能绕过 §2；存量不满足的新鲜结果仍应 null。

## 5. 顺序、验收与仍未验证事项

依赖顺序：**本契约 → A0 协议/纯计算（假提供者验收）→ A1a → A1b 实装提供者 → B/C 装配**。A1a 可在协议确定后独立建模；A0 不依赖 A1 表，A1b 不再等待外部未定义权息接口，循环依赖解除。
A0 假提供者验证算法，A1b 必须另测真实适配器读取隔离合成库；两者不能互相冒充集成验收。PN-03 日历补齐/真实 gbbq 算法仍按 C §10 分工；已有/后续 PN-03 提供者应实现同一协议，不重复造导入器。
六项裁定所列测试全部**待新增**；输入仅虚构证券、合成自然日覆盖及固定时钟，额外统一断言：available_at 等于/晚于截止、晚到修订不改旧值、跨用户/证书拒绝、缺单位/缺因子为 null、外呼次数为零。
边界测试必须覆盖 09:15/09:30/11:30/13:00/14:57/15:00/17:10/17:30、午休、周末、日历缺日、停牌保留日历、晚到证明以及无已证日；17:30 前后的值不能仅靠 fetched_at 改变完成状态。
未解决的数据/验证条件：真实定稿声明映射、历史首次可见证据、PN-03 真因子与日历覆盖、#205 合入、A188 暂缓的 Q01–Q06/Q08–Q10 真实口径；均未验证，不阻止协议和缺口路径离线实现，也不得以合成 PASS 宣称已解除。
本次仅文档验收：文件范围、行数、六项裁定/测试名/引用结构及本地迁移图；未运行上述业务测试、接口、数据库或迁移，不宣称生产接线完成。

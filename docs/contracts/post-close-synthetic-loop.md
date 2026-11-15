# PN-06 合成源盘后闭环契约（T-A160 第②部分）

## 1. 定位与流程映射

状态：主线契约草案，基线 main `f0914c3`；只约定后续离线接线与验收，本单不写实现/测试代码、不真调麦蕊、不碰真实库行。复用 [plan-phase2-next.md](../plan-phase2-next.md) §2 P2N-02/03/04 的风控、跟踪、建议证据，不重建模块、不改策略阈值。

进度报告第 6 步原文为「数据就绪 → 信号 → 风控 → 建议 → 跟踪」；任务的「取数 → 就绪判定(daily_bars_ready) → 指标 → 建议」作为**四环主轴**。指标环分信号与风控，建议环后接跟踪，以下用五段描述接线；不是五个新任务。接口层产物到 today 为止，前端实联归 PN-08，跨层复测归 PN-09。

| 段 / 环 | 既有入口（函数名） | 产物 |
| --- | --- | --- |
| 第 1 段：取数环 | `daily_bars_fetch_task`、`fetch_and_record`、既有 fake 夹具入口 | 合成 daily_bars、例行批 pipeline_runs 与 issues |
| 第 2 段：就绪环 | `daily_bars_ready`、`build_owned_snapshot`、`analyze` | owner 的就绪结果、不可变快照或缺口 |
| 第 3 段：指标环，信号 + 风控 | `prepare`、`evaluate_snapshot`、`conclusion`、`assess`、`apply_risk` | 求值证据、风控状态、可执行性或缺口 |
| 第 4 段：建议环 | `archive_conclusions`、`archive`、`report_task`、`build`、`today` | 不可变建议、日报与接口视图 |
| 第 5 段：建议后的跟踪 | `tracking_task`、`run_one`、`evaluate` | 模拟跟踪痕迹、样本状态及缺基准等排除原因 |

具体入口路径与阶段关系沿 [plan-next.md](../plan-next.md) §1；本契约的规范依赖是 [daily-snapshot-from-bars.md](daily-snapshot-from-bars.md) §10 J10、§14 和 [trading-calendar-exrights.md](trading-calendar-exrights.md) §2–§6。所有环节不得外呼，包括行情、真实模型与通知通道；只在隔离的合成测试存储中执行后续验收。

## 2. 第 1 段：取数（合成源）

| 项 | 契约 |
| --- | --- |
| 输入 | 合成账户/owner、虚构代码 A/B、合成业务日历与时钟；虚构 OHLC、量额、fetched_at、停牌标记、权息版本及 available_at。若需预热历史，只按已有规则所需窗口构造更早的虚构开市日，不改预热阈值 |
| 写入与来源 | 仅隔离测试存储的 daily_bars，adj_type 为 none，source 推荐 fake（§11 Q2）。不得标成 mairui 绕过证书绑定；不读生产库行、不复制真实账户、证书、行情或私有样本 |
| 可注入条件 | 例行批 pipeline_runs（window_trading_days 缺键或 null）；对照组窗口批、tdx_import、回填批；完成版/非完成版 fetched_at、缺行、停牌行、迟到 bar、迟到权息。迟到权息独立于 bar 的 fetched_at，按 PN-03 可见时点进入计算 |
| 输出 | 带来源、取数时点的虚构行及运行记录，合成缺失/冲突 issues；不伪造供应商响应或证书授权 |
| 就绪与失败 | 写入完成不等于业务就绪；批次失败保持 failed/缺口，交下一环判断。partial 可按既有就绪口径继续，但缺行不得填平；禁止为测试全绿伪造例行成功批 |
| 时序/不得外呼 | 固定北京时钟：17:15 例行取数，17:30 analyze；不启动真实调度，不连接麦蕊，不改变生产 Settings、HALT 或出口。外呼尝试即测试失败，不真实发送请求 |

fake 已用于 `test_analyze_fake_bars_produces_evaluations`，daily_bars 的来源 CHECK 也允许 fake。测试隔离须在整个取数与接线入口落实，不能假定 `analyze` 的 fake 路径会替调用方证明库是临时库；现有 owned 路径不调用旧 replay 的 `require_isolated`。

## 3. 第 2 段：就绪判定与快照

输入为同一 owner、快照日 T、业务日历、例行运行记录与合成行。必须真实调用 `daily_bars_ready(conn, owner, trade_date)`；不得 monkeypatch 为恒真。输出为就绪结果与 issues，只有过闸才经现有 `analyze` 路径惰性调用 `build_owned_snapshot`。

| 边界 | 必须行为 |
| --- | --- |
| 当日批次 | 严格沿快照契 §14.2：只认 window_trading_days 为空（缺键或 null）的例行批；先过滤，再按既有 started_at、finished_at 顺序取适用 owner 或全体的最新一条，再判状态。ok/partial 沿既有集合；不回退到更早成功批 |
| 排除 | 窗口批、tdx_import、回填批不能让 T 变就绪，也不能遮蔽合格例行批。T-B148 同时拒绝「回填批型 + 空窗口」，PN-06 不重复实现或放宽此防御 |
| 未就绪 | 沿现有 `phase` / `analyze`：记 `daily_bars_not_ready`，跳过该 owner 的快照；仍可经 REPORT 观察缺口日报与 issues，不伪造空的成功快照 |
| 当日行 | `FINAL_AFTER` 为 17:10，`ANALYZE_AS_OF` 为 17:30，Asia/Shanghai；当日 fetched_at 必须在两者之间（含边界），缺行、非完成或晚到按 §14 省略并保留对应 issues。fake 测试同样走这些时间检查 |
| 历史行 | §14.1 逐行时点就绪，不需要历史日 pipeline_runs。F 不早于该行所属日 17:10 才为完成版，且不晚于快照日 17:30；非完成版即使保留在原始 bars 也不是有效 K。构建 T 的快照仍须 T 的例行批就绪 |
| 来源/证书 | tdx_local 永不进入 owned 快照；空来源不入选。真实 mairui 必须绑定 owner 当前 active 证书，fake 只能在隔离测试使用，不据它宣称证书绑定已验收 |
| 源 off | 不建 owned 快照；现有测试环境 off 的旧 replay 路径不算本闭环成功，不拿预置快照绕过 ready |
| 日历与快照失败 | 缺覆盖保留 `calendar_not_covered`；构建失败或无有效输入保留缺口，不转成可交易。就绪为真不等于数据完整、求值可执行或日报 ready |
| 不得外呼 | 就绪/快照只读合成存储并写测试产物，不能为补齐条件临时抓行情、日历或因子 |

基线 `daily_bars_ready` 尚未做窗口过滤，T-B148 是实施依赖，未落地时相关负例应失败，不能降低断言。非完成版 mairui 的有效 K 缺口及受控同源替换见 [mairui-same-source-final-replace.md](mairui-same-source-final-replace.md) §2–§6，实施 T-B151；PN-06 不重复实现，补取需用户本人批准。

## 4. 第 3 段：指标（信号 + 风控）

| 子段 | 输入 | 输出 | 就绪/失败语义与不得外呼 |
| --- | --- | --- | --- |
| 信号 | ready 且已建成的 owner 快照、当时可见的因子/状态、合成实例绑定的已有规则版本及 feature_catalog | `prepare` / `evaluate_snapshot` 产生特征、求值、证据和 gaps；由既有规则链决定候选 | qfq 沿 PN-03，缺数/缺因子为 null + gap，停牌/未知状态不得推出可交易或可执行。不能为触发信号改策略阈值或补 1；不得外呼补特征 |
| 风控 | 信号证据、合成持仓/现金、可见交易状态和既有风控设置 | `conclusion`、`assess`、`apply_risk` 输出风险标记、可执行性、原因与解除条件，保留原策略动作 | 数据齐备且既有规则通过才是该夹具的完整路径；未知不判安全，停牌不判可成交。模拟标签与生命周期门禁照旧，不因此晋级或生成实盘交易；不得外呼或调用真实账户 |

全绿夹具须显式提供带 available_at 的有效合成累计因子，验证 qfq@as_of 的传递与尺度；它不证明 gbbq 连乘式已验证。缺因子夹具必须另跑。当前 `build_owned_snapshot` 的 `_instrument` 没有 factors，`analyze` 从 instrument 取 factors、缺省空列表：生产同形的因子输入接线由 PN-03 §11 Q5 裁定、T-B162 承接，T-B163 复用。不得事后改写快照 JSON、stub 求值结果或绕过 `prepare` 来制造端到端全绿。

## 5. 第 4 段：建议、日报与 today

| 项 | 契约 |
| --- | --- |
| 输入 | 本人求值/风控结果、可见数据证据与版本、缺口集合；未就绪分支可以没有快照或建议 |
| 输出 | 经既有建议归档、日报与 today 接口路径产生可追溯产物。复用 P2N-04；不在本单做前端实联（PN-08），不重建建议引擎 |
| 就绪/未就绪 | 有建议时保存证据、模拟标记和风险状态；没建议也要能观察缺口日报/issues。沿 today 既有状态协议，不把批次 ready、空建议集合或报告行存在直接解释为业务完整 |
| 失败 | 沿现有 `analysis_task` / `report_task` / `recover_task` 失败链保留问题；不能伪造建议补齐日报，也不能吞掉阻断原因或重置用户状态 |
| 幂等/晚到 | 同 owner、相同输入与时点重复运行幂等；旧修订、旧快照、旧建议及其证据指纹不变。晚到数据不回写已完成 D1 建议，只在后续满足可见条件的开市日参与新计算；不放宽 as_of、不自动补跑 D1 |
| 不得外呼 | 保持本地模板/合成输入，不调真实模型、不发送消息或通知；接口验收是本地服务调用，不是对外投递授权 |

## 6. 第 5 段：跟踪

输入为已存建议/版本、合成开市日历、可见入场与区间行情、合成基准；复用 P2N-03 的 `tracking_task` / `run_one` / `evaluate`。建议后的既有任务链留下可关联 owner、建议版本和交易日的跟踪痕迹；周期沿现有 `PERIODS`，不新定周期或收益阈值。

就绪样本按既有规则产生**模拟**跟踪；未到期可见其等待痕迹，缺基准/缺行情或无法成交时保留排除/未完成原因，不伪造收益、样本数或完整统计，不回改建议。全绿首切片至少确认入队/消费及可追踪状态，不要求 D2 已完成所有长期周期；缺基准负例使用合成到期窗口单独验证。PN-09 会再测，PN-06 后端产物须先支持这些断言。不得外呼抓基准或触达真实交易/账户。

## 7. 端到端验收（测试名，待实现）

统一合成账户与不同 owner，虚构代码 A/B、虚构开市日 D0<D1<D2；预热和跟踪到期需要的其他日期亦由夹具虚构。仅用隔离测试存储；不读真实数据、不使用真实证书。表内只列测试名与 Given/When/Then，不提供测试代码。完整路径调用现有业务函数，不能仅验证各环 stub 返回值。

| 测试名 | Given | When | Then |
| --- | --- | --- | --- |
| `test_pn06_synthetic_full_loop` | 合成日历、fake 行、例行批、有效可见因子、满足既有规则与风控的模拟实例 | D1 按四环及跟踪运行 | 取数记录→ready→快照→信号/风控证据→建议/日报/today→跟踪痕迹可串联；有模拟标识，全部仅合成数据 |
| `test_pn06_no_routine_run_no_snapshot` | D1 有行但没有例行批 | 经 phase/analyze/report | `daily_bars_not_ready`，该 owner 不建快照、不造建议；缺口日报/issues 可观察 |
| `test_pn06_windowed_and_import_runs_not_ready` | 仅窗口批或 tdx_import 成功 | daily_bars_ready 后接分析 | 不就绪，不建快照；回填批型加空窗口在 T-B148 入口被拒绝 |
| `test_pn06_filter_before_latest_routine` | 例行成功后有更晚窗口批；另组最新例行失败 | 判定并运行 | 第一组取例行成功且不被窗口批遮蔽；第二组不回退更早成功 |
| `test_pn06_missing_bar_or_factor_gap_report` | 例行 partial/ok，分别缺当日 bar、历史 bar、因子 | 构建与分析/报告 | 相应省略或有效 K/因子缺口保留，仍有缺口日报；不补 1、不编造可执行建议 |
| `test_pn06_suspension_and_unknown_state` | 开市日 A 明确停牌，B 状态未知，另组零成交 | 指标与风控 | 停牌/未知不判可执行；零成交不自动判停牌；开市日不被删 |
| `test_pn06_today_final_window_unchanged` | 当日 F 早于 17:10、等于两边界、晚于 17:30 四组 | 建快照并分析 | 仅窗口内（含边界）当日行通过时间门禁；其余缺口按 §14，不借窗口批放行 |
| `test_pn06_history_ready_without_historical_runs` | T 例行就绪，D0 合成历史行分别完成/非完成/晚到；D0 没有运行记录 | T 建快照并 prepare | 历史按逐行时点判，非完成版不作有效 K，晚于 T 截止不入选；不要求历史运行 |
| `test_pn06_idempotent_old_fingerprints_unchanged` | 完整合成输入与版本固定 | 同输入运行两次 | 业务产物不重复，旧快照/修订/建议证据指纹不变；运行审计可留多次，不算重复建议 |
| `test_pn06_late_bar_or_event_only_future_visible` | D1 建议完成，D0 缺 bar 或权息版本到 D1 截止后才可见 | 接收晚到输入，运行 D2 并读取 D1 | D1 建议、快照、旧修订不变；D2 符合时点才使用晚到输入，不补跑 D1；该用例不模拟同源覆盖 |
| `test_pn06_owner_isolation` | 两个合成 owner 各有账户/实例/例行批和不同 universe，含重叠公开代码 | 各自运行与读取 | 不串账户、运行 issues、快照、建议、日报或跟踪；共享公开 bar 不赋予另一 owner 私有产物权限 |
| `test_pn06_tracking_missing_benchmark_visible` | 合成建议在虚构到期窗口缺基准 | 跟踪并读接口产物 | 缺基准原因可见，不伪造收益或完整样本，旧建议不变 |
| `test_pn06_off_and_tdx_never_owned` | 源 off；另组 fake 模式仅有 tdx_local 行 | 分析 | off 不建 owned 快照；tdx_local 永不入 owned，缺行情可见；旧 replay 不算闭环通过 |
| `test_pn06_fake_source_preserved` | 合成取数输入 | 写入并串通 | source 保持 fake，不伪装 mairui、不修改证书绑定检查；无真实数据读取 |
| `test_pn06_zero_external_calls` | 本节全部场景，socket 禁网与 mairui_get 计数探针 | 全链运行并静态检查外呼接线 | socket 外呼尝试 0、麦蕊调用 0，无真实模型或通知调用 |
| `test_pn06_snapshot_functions_not_scheduled` | 现有任务表、schedule、slot_jobs | 沿快照契 §10 J10 检查 | `build_owned_snapshot` / `daily_bars_ready` 仍不进 TASKS、LOCKED_TASKS、schedule 或 slot_jobs；workers/jobs 全文静态纪律不变 |

## 8. 依赖边界与未验证

| 依赖 / 未验证项 | 处理 |
| --- | --- |
| T-B148 | 实施 §14.2 与拒绝回填批型加空窗口；本单只依赖口径，不实施其代码，也不声明已完成 |
| T-B151 | 非完成版 mairui 同源替换及审计归它；PN-06 不做替换或补取，不用 fake 证明 mairui 绑定/替换正确，旧缺口继续可见 |
| PN-03 / T-B162 / T-B153 | 日历、事件可见性、qfq 输入接线及缺口；真实 gbbq 连乘式仍未验证，默认不生效。合成因子证明接线，不证明真实算法 |
| PN-04/PN-05 | plan-next §3 的正式集成前置保留；本单只使用离线合成入口，不以纯合成通过宣称真实取数 adapter、codes 守卫或出网已就绪 |
| PN-08 / PN-09 | 前端实联与跨层复测不在本单；本单先产出可断言的后端日报、today、跟踪缺口及不可变性证据 |
| 实际端到端状态 | 全绿/幂等/晚到/跟踪链是否完整尚未验证；本单只核仓库代码，没有运行本文待写测试、没有连库 |
| 因子与快照接口 | owned 快照当前无 factors；具体接线、available_at 的来源和版本固化未验证，见 PN-03 §11 Q3/Q5；缺口不靠测试后改快照消除 |
| 测试输入/参数 | source=fake 有现有 CHECK 与测试依据；无出处的参数、阈值、时间宽限均「未验证，默认不生效」，不为合成成功放宽策略或数据门禁 |

本单不把源改为 mairui，不解除 HALT，不恢复出网；17:15/17:30 与 17:10 完成版边界均不改。

## 9. 硬红线

真调麦蕊（含补取）、生产部署、删除用户数据、对外发送、解除 HALT、恢复出网、backfill --apply、通达信真实全量导入：**每项均需用户本人批准**。真实写库、真实条件替换同样需用户本人批准。本契约不构成批准，合成验收通过不构成真实启用许可。实施与验收只用合成输入，不得把真实行情或私有样本写入仓库或发给外部模型，不得外呼。

## 10. 实施单（建议占号，不建任务文件）

占用核对及 PN-03 的 T-B162、T-B153（沿用）、T-T86 见 [trading-calendar-exrights.md](trading-calendar-exrights.md) §10。T-T83 已由团队测试状态明确派给 T-B149 路由失败测试；§7 的旧 PN-06 占位不再作为可用测试号。以下仅建议占号，不创建团队或仓库 tasks 文件。

| 建议号 | 范围 | 依赖 | 验收 | 硬红线 |
| --- | --- | --- | --- | --- |
| T-B163 | 合成取数夹具→daily_bars_ready→prepare/信号/风控→建议/日报/today→跟踪接线；复用 P2N-02/03/04，不改生产源，不重复改 ready | PN-03/PN-06 契约合入；T-B148；T-B162 的 qfq 缺口与输入接口；日历夹具遵守 T-B153 口径；T-B151 非本单范围 | §7 全部 `test_pn06_*`；零麦蕊、不碰真实行、旧证据不变 | 遵守 §9；真调/真写库等需用户本人批准 |
| T-T87 | 只改 tests，PN-06 端到端合成闭环验收 | T-B163；T-B148；契约合入，骨架可先红后绿 | §7 全部 `test_pn06_*`；socket/静态扫描、麦蕊 0 次；不以跳过未就绪依赖冒充通过 | 遵守 §9；纯合成、无真实库访问 |

## 11. 待裁定（每项附推荐）

| 项 | 推荐与未裁定边界 |
| --- | --- |
| Q1 T-A160 / T-T83 原占位冲突 | 推荐 T-A160 以本轮 PN-03/PN-06 派单为准；S03 契约改建议 T-A168、后端沿用 T-B152、测试改建议 T-T88；T-T87 专管本契约。沿 PN-03 §11 Q1，不改 plan-next §7 的旧建议号；其他旧 T-T83 范围由编排者另行整理 |
| Q2 合成库存 source 选 fake 还是专用值 | 推荐沿用 fake，不新增枚举。当前 CHECK 和既有测试支持 fake；仅在所需字段确有约束冲突时再提修订，不能改标 mairui 绕绑定。测试入口须显式隔离，生产默认源不变 |
| Q3 因子从取数到指标的缺口归属 | 推荐按 PN-03 §11 Q3/Q5，由 T-B162 定可见性与不可变输入接口，T-B163 复用；先用显式、版本化合成累计因子检验接线，不启用未验证 gbbq 算法。未解决前如实报完整路径阻塞，缺口路径仍可验收 |
| Q4 日历是否沿用 T-B153、T-A161 如何衔接 | 推荐沿用 T-B153，按 PN-03 §11 Q2 确认 T-A161 复核/同步范围；不重复开日历实现单、不擅改占位 |
| Q5 全绿闭环如何界定 | 推荐指满足既有规则的合成模拟实例贯通五段且留足证据；允许既有模拟门禁保持不可实盘执行，不把全绿解释为策略晋级。D1/D2 跟踪痕迹和单独到期缺基准用例分别验收，不强求 D2 完成所有周期 |

日历主源、qfq@as_of、§14 收紧、T-B151 边界及本人批准关口均沿已裁定口径，不在此重开。

## 12. 受影响可执行入口与逐项验收

按 L-043 补全入口；统一输入 S 见 [trading-calendar-exrights.md](trading-calendar-exrights.md) §12，沿本契约 §7 增加两合成 owner、例行/窗口/回填/tdx_import 批、完成/非完成/晚到行、可见/缺失因子和模拟跟踪到期组。每种格式均由同一 S 派生，各入口独立调用并留结果；不能以新入口测试代替旧入口。入口表列测试名后缀，对应下表的 `test_pn06_entry_*`；**全部待实现、未验证**，现有 §7 用例与旧 selfcheck PASS 均不构成逐入口已通过。

`app/` 均指 `src/backend/app/`。只定义离线合成验收，不运行真实调度；HTTP 仅本地请求，SQL 仅隔离临时库，PS1 仅临时包和隔离命令替身，取数 transport/模型/通知禁止外呼。真调麦蕊、对真实库 --apply、通达信真实全量导入须用户本人批准（§9）。旧 probe 未验证前不得接入本闭环；这是契约使用限制，本补丁未修改脚本或调度来实施停用。

| 类型 | 标识 | 与本契约的关系 | 验收后缀 / 状态 | 不得替代 |
| --- | --- | --- | --- | --- |
| 函数 | `app/marketdata/daily_snapshot.py` 的 `daily_bars_ready` | §3 例行批筛选及 owner | `ready`；未验证 | 预置 ready 或取数成功 |
| 函数 | `app/marketdata/daily_snapshot.py` 的 `build_owned_snapshot` | §3 来源、完成版、截止与不可变快照 | `snapshot`；未验证 | ready 单测 |
| 任务 | `app/marketdata/daily_bars.py` 的 `daily_bars_fetch_task` | §2 任务参数及运行记录 | `fetch_task`；未验证 | fetch_and_record 单测 |
| 函数 | `app/marketdata/daily_bars.py` 的 `fetch_and_record` | §2 合成写入与批型 | `fetch_record`；未验证 | 新 consumer 测试 |
| 函数 | `app/workers/daily.py` 的 `analyze` | §3→§4 ready 后惰性构建 | `analyze`；未验证 | 预置快照求值 |
| 函数 | `app/workers/daily.py` 的 `phase` | §3/§5 分 owner 阶段事务及失败 | `phase`；未验证 | analyze 单测 |
| 任务 | `app/workers/daily.py` 的 `analysis_task` | ANALYZE 原任务包装入口 | `analysis_task`；未验证 | 直调 phase |
| 任务 | `app/workers/daily.py` 的 `report_task` | §5 REPORT 原任务入口 | `report_task`；未验证 | reports.service.build 单测 |
| 任务 | `app/workers/daily.py` 的 `recover_task` | §5 失败/中断恢复入队 | `recover_task`；未验证 | 正常 phase 成功 |
| 函数 | `app/features/pipeline.py` 的 `prepare` | §4 可见因子与特征 gap | `prepare`；未验证 | stub 特征结果 |
| 函数 | `app/features/evaluation.py` 的 `evaluate_snapshot` | §4 真正消费快照求值 | `evaluate_snapshot`；未验证 | prepare 单测 |
| 函数 | `app/workers/assembly.py` 的 `conclusion` | §4 信号与风控证据 | `conclusion`；未验证 | 求值成功 |
| 函数 | `app/risk/rc1.py` 的 `assess` | §4 风控及状态未知 | `assess`；未验证 | apply_risk 单测 |
| 函数 | `app/suggestions/risk.py` 的 `apply_risk` | §4 风控作用于原策略动作 | `apply_risk`；未验证 | assess 单测 |
| 函数 | `app/workers/assembly.py` 的 `archive_conclusions` | §5 归档接线 | `archive_conclusions`；未验证 | archive 单测 |
| 函数 | `app/suggestions/service.py` 的 `archive` | §5 建议不可变及 owner | `archive`；未验证 | 仅检查日报存在 |
| 函数 | `app/reports/service.py` 的 `build` | §5 缺口日报与修订 | `report_build`；未验证 | report_task 入队成功 |
| 函数 | `app/aggregates/service.py` 的 `today` | §5 日报状态与缺口投影 | `today_service`；未验证 | /today 状态码成功 |
| 任务 | `app/tracking/worker.py` 的 `tracking_task` | §6 跟踪任务选择 owner | `tracking_task`；未验证 | run_one 单测 |
| 函数 | `app/tracking/service.py` 的 `run_one` | §6 消费建议版本并存跟踪 | `run_one`；未验证 | evaluate 单测 |
| 函数 | `app/tracking/engine.py` 的 `evaluate` | §6 到期、缺基准及模拟结果 | `tracking_evaluate`；未验证 | 新闭环全绿用例 |
| HTTP | `GET /today`（`app/api/v1/aggregates.py` 的 `today`） | §5 原协议、认证 owner 与时钟 | `today_http`；未验证 | service.today 单测 |
| HTTP | `GET /daily-reports`（`app/api/v1/daily_reports.py` 的 `listing`） | §5 日报分页读取 | `reports_list_http`；未验证 | /today 测试 |
| HTTP | `GET /daily-reports/{date}`（`app/api/v1/daily_reports.py` 的 `detail`） | §5 归档详情及旧投影 | `report_detail_http`；未验证 | 日报列表测试 |
| CLI | `python -m app.cli daily-bars-backfill`（`app/cli/daily_bars_backfill.py` 的 `main`） | 默认 dry-run，--apply 只入队，不自行取数 | `backfill_cli`；未验证 | daily_bars_fetch_task 单测 |
| CLI | `python -m app.cli daily-bars-import-tdx`（`app/cli/tdx_import.py` 的 `daily_main`） | 写 tdx_local/导入审计不等于例行 ready；永不进 owned | `tdx_cli`；未验证 | 新 source 过滤单测 |
| CLI | `python -m app.cli.tb143_export day` | 旧 SQL/PS1 上游 CSV 与 before 窗口 | `day_cli`；未验证 | 新导入 CLI 测试 |
| probe | `src/backend/probes/tb140_daily_bars.py` 的 `main` / `mkt`（latest20、ssjy_all、history） | 真调旧入口；mkt 将 920 误判 SH，历史默认旧窗口 | `tb140_daily_bars`；未验证，禁止接入闭环 | market_of、old_buggy_mkt 副本或新路由测试 |
| probe | `src/backend/probes/tb140_history_load.py` 的 `normalize_history` / `apply_daily_bars` | 规范化/写 mairui 来源，不自动证明例行 ready | `history_load`；未验证 | market_of 单测 |
| probe | `src/backend/probes/tb140_history_backfill.py` 的 `main` / `run_batch` | 旧回填、固定历史范围及 transport | `history_backfill`；未验证，禁真调 | 新 backfill CLI 测试 |
| probe | `src/backend/probes/tb140_history_selfcheck.py` 的 `main` | 存在；含旧 mkt 规则副本，未执行旧脚本原入口 | `history_selfcheck`；未验证 | selfcheck PASS 代替旧 mkt 验收 |
| probe | `src/backend/probes/tb140_history_supervisor.py` 的 `main` / `run_supervised` | 存在；跨批续接、写库与运行归属 | `history_supervisor`；未验证，禁真调 | run_batch 单测 |
| Windows | `src/backend/probes/tb143_day_load_runner.ps1` | 默认 Before 为 2023-11-13；只导日线不补日历，不制造例行批 | `day_runner_ps1`；未验证 | PN-03/C1 新入口无截止测试 |
| SQL | `src/backend/probes/tb143_load_day.sql` | before 强制边界；写 tdx_local，不应使 ready 误判 | `load_day_sql`；未验证 | PS1 成功、tdx CLI 测试 |
| SQL | `src/backend/probes/tb143_load_meta.sql` | 因子上游事件；stage 无 available_at | `load_meta_sql`；未验证 | prepare 的合成因子通过 |
| probe | `src/backend/probes/tb143_pg_selfcheck.sh` | 两份 SQL 原入口合成自检；不含闭环 ready | `pg_selfcheck`；未验证 | 旧 PASS 代替 ready/owned 验收 |
| 任务 | `app/workers/jobs.py` 的 `worker_tick` / `slot_jobs` / `beat_slots` | 原任务分派、17:15/17:30 与 REPORT/TRACKING 入队 | `worker_dispatch`；未验证 | 直调各任务函数 |
| 函数 | `app/marketdata/daily_bars_outbox.py` 的 `enqueue` | 当前取数任务的 outbox 交接 | `outbox`；未验证 | fetch_and_record 单测 |
| 任务 | `app/ingest/daily_bars_consumer.py` 的 `process` / `tick` / `wake_delayed` | 当前消费、例行/回填批归属与续接 | `consumer`；未验证 | 旧 probe 或 fetch_task 单测 |

下表测试名前缀完整写出；一行含多个包装/子入口时须逐个参数化调用原入口，独立记录结果，不以共享下游通过代替包装入口验收。

| 测试名 | Given | When | Then |
| --- | --- | --- | --- |
| `test_pn06_entry_ready` | S 仅窗口/回填/导入批，另组最新例行失败 | 直接调用 daily_bars_ready | 不就绪，不回退旧成功；合格例行单独验证，不 monkeypatch ready |
| `test_pn06_entry_snapshot` | S 的时点边界、tdx_local 及缺日/缺因子组 | 调用 build_owned_snapshot 并消费 | owned 排除 tdx_local/非完成/晚到行，缺口保留，因子未接通不伪造全绿 |
| `test_pn06_entry_fetch_task` | S 的例行/窗口参数，含回填批型加空窗口 | 调用原任务，接隔离 outbox/transport | 批型审计准确；非法组合拒绝，写入不冒充就绪 |
| `test_pn06_entry_fetch_record` | S 的 fake 输入及失败组 | 调用 fetch_and_record | 仅写合成行、运行与 issues，失败保留，不伪装 mairui |
| `test_pn06_entry_analyze` | S ready 真/假两组 | 调用 analyze | 仅过闸后构建；缺口日报可用，不预置或事后改快照 |
| `test_pn06_entry_phase` | S 两 owner、未知日及中途异常 | 分别执行 ANALYZE/REPORT phase | owner 隔离；缺日不当休市；失败记录保留，重复幂等 |
| `test_pn06_entry_analysis_task` | 同一 S 的 ready 真/假组 | 调原 analysis_task | ANALYZE 接线与 owner/date 传递可核，不绕 ready |
| `test_pn06_entry_report_task` | S 的缺口分析产物 | 调原 report_task | 产生缺口日报，不能造建议或吞 issues |
| `test_pn06_entry_recover_task` | S 的中断阶段与固定恢复时钟、隔离队列 | 调原 recover_task 两次并消费 | 恢复意图可追踪且防重复；消费仍过 ready，不回写已完成旧建议 |
| `test_pn06_entry_prepare` | S 的早到/晚到/缺因子及停牌组 | 原 prepare 计算各 T | qfq@as_of、null/gap 与尺度正确，不补 1 |
| `test_pn06_entry_evaluate_snapshot` | S 的真实构建快照及规则版本 | 调原 evaluate_snapshot | 消费真实 prepare 产物，保留缺口，不 stub 求值 |
| `test_pn06_entry_conclusion` | S 的求值证据、未知交易状态 | 调原 conclusion | 证据与风险可追溯，未知不判可执行，策略动作不改写 |
| `test_pn06_entry_assess` | S 的模拟持仓、现金及缺价格/状态组 | 调原 assess | 风险与解除条件可读，不以缺数判安全 |
| `test_pn06_entry_apply_risk` | 同一 S 的原动作、风险结果及 gaps | 调原 apply_risk | 风险限制保留，原策略动作与 gap 不被抹掉 |
| `test_pn06_entry_archive_conclusions` | S 的原 conclusion 产物 | 调原 archive_conclusions 两次 | owner、证据及版本串联，业务归档幂等 |
| `test_pn06_entry_archive` | S 的建议版本与晚到修订 | 调原 archive 后读取旧版本 | 旧指纹不变，模拟标志保留，不跨 owner |
| `test_pn06_entry_report_build` | S 的完整/缺口产物 | 调原 reports.service.build 并重复 | 冻结证据与修订不被覆盖；有日报不代表数据完整 |
| `test_pn06_entry_today_service` | S 的无报告/building/partial 组 | 调原 aggregates.service.today | 沿既有状态协议并保留缺口，不将 ready 展示解读为全链完整 |
| `test_pn06_entry_tracking_task` | S 两 owner 建议及固定到期时钟 | 调原 tracking_task | 任务选择与跟踪痕迹隔离，无行情/基准外呼 |
| `test_pn06_entry_run_one` | S 的建议版本、到期/未到期/缺基准组 | 调原 run_one | 等待/排除原因及建议版本可追踪，不改旧建议 |
| `test_pn06_entry_tracking_evaluate` | S 的模拟成交窗口与缺基准组 | 调原 tracking.engine.evaluate | 按原周期产模拟结果或缺口，不造收益/完整统计 |
| `test_pn06_entry_today_http` | S 两 owner 及缺日/缺口日报 | 本地请求 GET /today | 认证隔离、时钟错误与缺口保留，成功响应不冒充闭环完整 |
| `test_pn06_entry_reports_list_http` | S 两 owner、多修订与分页组 | 本地请求 GET /daily-reports | 列表不串 owner，分页与已有状态协议一致 |
| `test_pn06_entry_report_detail_http` | S 的冻结日报及旧组件时点 | 本地请求 GET /daily-reports/{date} | 详情只投影已冻结证据，不查询晚到输入回写旧报告 |
| `test_pn06_entry_backfill_cli` | S 的日历和隔离队列 | 经命令分派/模块 main dry-run；隔离替身验证 --apply 分支 | 默认零入队/取数；apply 仅回填入队，消费不使例行 ready 变真 |
| `test_pn06_entry_tdx_cli` | S 派生 .day 文件且无例行批 | 经命令分派/原 daily_main 离线导入后调 ready 和快照 | tdx_import 成功不使 daily_bars_ready 变真；tdx_local 永不进入 owned |
| `test_pn06_entry_day_cli` | S 派生跨旧截止 ZIP | 调原 day 子命令有/无 --before 两组 | 显式窗口与计数可读，不暗截、不写例行成功批 |
| `test_pn06_entry_tb140_daily_bars` | S 的虚构 920 代码及旧窗口两侧日期 | 仅隔离提取原文件 mkt 定义求值，并静态检查 main 各子命令；不导入/执行其密钥或真调逻辑 | 记录原 mkt 误判与旧截止风险，仍未验证、禁止接入；不得用 market_of 或规则副本宣称修复 |
| `test_pn06_entry_history_load` | S 的合成响应、冲突行与隔离连接 | 分别调用原 normalize_history、apply_daily_bars 后判 ready | 来源/时点与冲突可追溯；历史落库不自动成为例行就绪证据 |
| `test_pn06_entry_history_backfill` | S 的模拟响应、虚构窗口及 STOP/限流组 | 分别调用原 main/run_batch，全部依赖接离线替身 | 原窗口显式可审阅；遇熔断停，不真调、不读真实凭据，不报例行 ready |
| `test_pn06_entry_history_selfcheck` | S 替身及 socket 禁网 | 经原 main 核对各自检覆盖对象 | 自检结果只归所调原入口；old_buggy_mkt 副本不证明旧脚本 mkt 已通过 |
| `test_pn06_entry_history_supervisor` | S 的跨批、失败、续接及隔离存储 | 分别调用原 main/run_supervised，接离线连接与时钟 | 续接/批型/失败可追溯，回填不误作例行，不读真实凭据 |
| `test_pn06_entry_day_runner_ps1` | S 的跨旧截止年度包、隔离 docker/psql 替身 | 执行原 PS1 默认/显式 Before 两组并查 ready | 默认 2023-11-13 须声明，未声明截断即失败；不写日历或例行成功批，不宣称 PN-03/C1 取消截止通过 |
| `test_pn06_entry_load_day_sql` | S 派生 before 前/等于/之后 CSV 与无例行批临时库 | 执行原 SQL 后调用 ready/owned | 边界拒绝整批不静默丢行；tdx_local 不进 owned，ready 不因导入变真 |
| `test_pn06_entry_load_meta_sql` | S 的事件 CSV 无 available_at | 隔离执行原 SQL 后接因子消费 | 注册成功不等于历史可见；因子缺口继续阻断可执行结论 |
| `test_pn06_entry_pg_selfcheck` | S 派生临时 PG 输入 | 经原自检入口执行并接 ready/owned 检查 | 自检导入成功不使 ready 变真；原脚本无此断言时保留未验证 |
| `test_pn06_entry_worker_dispatch` | S 固定 17:15/17:30、原任务表和隔离队列 | 分别调用 slot_jobs、beat_slots、worker_tick | 取数→ANALYZE→REPORT/TRACKING 接线可追踪；ready/快照不被直接调度，失败链可见 |
| `test_pn06_entry_outbox` | S 的例行/回填入队参数与重复请求 | 调原 enqueue | 批型、owner、窗口保留，入队不冒充取数完成/ready |
| `test_pn06_entry_consumer` | S 的例行/回填消息、完成/失败/延迟组 | 分别调用原 process、tick、wake_delayed，transport 禁网 | 运行记录及续接归属准确；回填不升格例行，外呼尝试为零 |

补检的旁路入口亦逐个标为**未验证**：`app/risk/evaluation.py` 的 `assessed`、`app/suggestions/risk.py` 的 `evaluate_risk`（conclusion 下游风控）；`app/signals/service.py` 的 `write_candidate`（信号持久化）；`app/reports/service.py` 的 `latest`（日报读取）；`app/tracking/api.py` 的 `GET /suggestions/{identifier}/tracking`、`GET /strategies/{strategy_id}/versions/{version_id}/tracking`（跟踪读取）。后续各用 S 独立验收，不以本节盘后调用代替。`python -m app.workers.beat`、`python -m app.workers.worker`、`python -m app.workers.ingest` 的进程启动入口同为未验证，不能以 worker_tick/consumer 单测宣称真实调度已验收。

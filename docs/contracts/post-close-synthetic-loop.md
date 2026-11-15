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

# 下一阶段：每日收盘后决策流程

## §0 目标与范围

目标：复用现有流水线，让本人持仓与有效自选在每日收盘后形成可追溯的「数据就绪 → 信号 → 风控 → 建议 → 复盘」闭环（`docs/plan.md` §0A、§2、§8）。

本阶段不扩全市场选股、历史回测、新策略平台、自动交易或 LLM 决策；盘中实时、外部通知渠道和完整计划反馈不作为盘后首批前置，暂停任务不自行恢复（`docs/plan-phase2-next.md` §1–§3，P2N-06–09）。不修改策略规则；缺数据仍为 null + gap，不提升来源等级。

状态：T-A154 草案（架构师 2026-11-14，Codex L4 起草、架构师裁取），是路线建议，不是交付或启用证明。下列引用在本文提交时尚未合入 main：`docs/contracts/C2-successors.md`（PR #131）、`docs/contracts/multi-source-ingest.md`（PR #140）、`docs/contracts/strategy-detail.md`（PR #139）、`docs/mairui-fit-matrix.md`（PR #136）；以其定稿裁定为准，较早报告中的待裁定清单不重复派单。「团队 reports/」指团队目录 /workspace/team/reports，不在仓库内。T-B141 状态以团队 `reports/T-B141-review3.md` 第三轮复审（已通过，PR #134）为准。

## §1 端到端流程

以下均为北京时间、交易日；信号、风控、建议是现有 analyze 内部阶段，不新增三个定时任务。日报时序按 `docs/contracts/daily-bars-source.md` §9.1，取代 `docs/plan.md` §0A.5 的旧时刻。代码入口均已在本 worktree 核对；规划名 advice、evaluation、jobs 对应的顶层目录尚无业务实现，实际入口如下，不据规划名发明类或 CLI。

### 1. 数据就绪

- 触发：17:15 例行取数，17:30 分析过闸时惰性建快照；新加入标的的补历史入口按 `docs/contracts/daily-bars-source.md` §9.2，开市日 [17:00, 17:45) 延后。真调麦蕊、恢复出网、backfill --apply、通达信真实全量导入——关口：需用户本人批准。
- 输入：交易日历、本人合格持仓与有效自选、已有日 K、本人有效数据许可及来源绑定；输出：取数运行状态、owned 快照或明确缺口。
- 现有模块：`src/backend/app/workers/jobs.py` 的 `slot_jobs`、`beat_slots`；`src/backend/app/marketdata/daily_bars.py` 的 `daily_universe`、`daily_bars_fetch_task`；`src/backend/app/ingest/daily_bars_consumer.py` 的 `tick`、`process`；`src/backend/app/marketdata/daily_snapshot.py` 的 `daily_bars_ready`、`build_owned_snapshot`。
- 缺口：`daily_bars_fetch_task` 尚无 codes 入参；`src/backend/app/workers/ingest.py` 的 `write_heartbeat` 未向日 K tick 注入 transport/page_days；DB halted 恢复入口待实现，解除 HALT——关口：需用户本人批准。对应 `docs/contracts/C2-successors.md` (a)–(c)。
- 边界：通达信日线与 gbbq 入库、历史分钟 parquet + 目录表属于 T-B143；日报、today、owned 快照仍不读 tdx_local。日历与复权缺口按 PN-03 收口；来源绑定须核实，不能把 T-B141 通过当成用户库已经完成迁移（`docs/contracts/multi-source-ingest.md` §1、§4–§6；PR #141（T-B143）与团队 `reports/T-B143.md`；`docs/mairui-fit-matrix.md` §3、§6）。

### 2. 信号

- 触发：17:30 analyze，数据可见截止亦为 17:30；输入：本人快照、可运行实例、绑定卡版本、feature_catalog；输出：规则求值、证据、反证、失效条件或 gap，候选在下一段风控后落档。
- 现有模块：`src/backend/app/workers/daily.py` 的 `analyze`、`analysis_task`；`src/backend/app/features/evaluation.py` 的 `evaluate_snapshot`、`RuleEvaluator`；`src/backend/app/signals/service.py` 的 `write_candidate`；`src/backend/app/signals/execution.py` 的 `assess`。
- 缺口：目录播种、来源门禁与复权/日历不足会阻断求值；hold/wait 不生成候选，不能凑齐六维动作。17:30 后到达的行次日才作为历史可见，不自动补跑当日分析（`docs/contracts/daily-snapshot-from-bars.md` §11.3、§12.2、§13；`docs/plan.md` §8 T-B74；`docs/plan-phase2-next.md` §1）。

### 3. 风控

- 触发：17:30 起，同一次 analyze 内、候选持久化之前；输入：规则结果、现金/持仓、用户设置、可见行情与交易规则；输出：风控标记、可执行性、不可执行原因与解除条件，策略原动作保留。
- 现有模块：`src/backend/app/workers/assembly.py` 的 `conclusion`；`src/backend/app/risk/evaluation.py` 的 `inputs`、`assessed`；`src/backend/app/risk/rc1.py` 的 `load`、`assess`；`src/backend/app/suggestions/risk.py` 的 `effective_config`、`apply_risk`；`src/backend/app/risk/events.py` 的 `record`。
- 缺口：现金、ST 时点状态、行业归属、基准与复权证据不足须保留 unknown/gap；RC5/RC6 完整反馈按 P2N-08 与计划版本另切片，不把缺失输入判为安全（`docs/plan-phase2-next.md` §2 P2N-02、P2N-08；`docs/mairui-fit-matrix.md` §3、§5）。

### 4. 建议

- 触发：17:30 起，风控后归档建议；analyze 成功或失败转入重试/最终失败后链式推 REPORT；输入：各策略结论与不可变证据；输出：建议链、六维日报、分歧与缺口、today 入口。
- 现有模块：`src/backend/app/workers/assembly.py` 的 `archive_conclusions`；`src/backend/app/suggestions/service.py` 的 `archive`；`src/backend/app/reports/service.py` 的 `build`；`src/backend/app/reports/dimensions.py` 的 `build`；`src/backend/app/aggregates/service.py` 的 `today`；`src/backend/app/workers/daily.py` 的 `report_task`、`recover_task`。
- 缺口：沿 P2N-04/05 验证真实产物到页面的接线，不能把空集合当缺口解决；策略详情待 T-A151 补只读路由。解释优先模板，LLM 不改动作；对外发送——关口：需用户本人批准（`docs/plan-phase2-next.md` §2 P2N-04、P2N-05、P2N-09；`docs/contracts/strategy-detail.md` §0、§2–§6）。
- 后续交互复用 `src/backend/app/plans/drafts.py` 的 `generate`、`confirm`，仅用户显式请求，simulating 禁草案；站内能力复用 `src/backend/app/notify/service.py` 的 `append`、`src/backend/app/notify/transport.py` 的 `publish`，不据函数存在宣称盘后投递已接通（`docs/plan.md` §8；`docs/plan-phase2-next.md` §2 P2N-06、P2N-07）。

### 5. 复盘

- 触发：17:30 analyze 成功后入队 TRACKING；在后续交易日的同一路径检查 T+1/5/20 到期样本，无独立固定钟点；输入：已存建议/版本、交易日历、入场与区间行情、基准；输出：模拟跟踪、排除原因、样本数及收益统计。
- 现有模块：`src/backend/app/workers/jobs.py` 的 `worker_tick`；`src/backend/app/tracking/worker.py` 的 `tracking_task`；`src/backend/app/tracking/service.py` 的 `run_one`；`src/backend/app/tracking/engine.py` 的 `evaluate`；`src/backend/app/tracking/api.py` 的 `suggestion_tracking_view`、`strategy_tracking_view`。
- 缺口：日历、复权、基准不足时不能宣称模拟结果完整；模拟与实际收益分开。`conclusion` 当前写固定排序权重，不能声称已完成自动降权；完整反馈沿 P2N-08，内部 evaluation 平台不另起（`docs/plan-phase2-next.md` §2 P2N-03、P2N-08；`src/backend/app/workers/assembly.py` 的 `conclusion`）。

## §2 参数与口径表

无出处的参数一律「未验证，默认不生效」；有明确裁定但待实测者保留其裁定状态，不自行改值。

| 参数 | 取值 | 出处（契约章节/报告/代码常量名） |
|---|---|---|
| 日常取数 / 分析截止 / 完成版起点 | 17:15 / 17:30 / 17:10（北京） | `docs/contracts/daily-snapshot-from-bars.md` §11.3；`src/backend/app/workers/jobs.py` 的 `DAILY_BARS_FETCH_TIME`；`src/backend/app/marketdata/daily_snapshot.py` 的 `ANALYZE_AS_OF`、`FINAL_AFTER` |
| 日报 / today 逾时 | analyze 结束后链式 REPORT；17:45 起 not_yet 才逾时，宽限 15 分钟 | `docs/contracts/daily-bars-source.md` §9.1；`docs/contracts/today-view.md` §9 |
| 历史窗口 / 避让时段 | 近 3 年；开市日 [17:00, 17:45) 补历史/回填延后 | `docs/contracts/daily-bars-source.md` §9.2–§9.3 |
| 日常 / 回填批预算 | 当前均为 0；开放值分别 500 / 2,000 次 transport/批；开放——关口：需用户本人批准 | `docs/contracts/daily-bars-source.md` §9.3–§9.4；`src/backend/app/ingest/daily_bars.py` 的 `DAILY_BARS_BATCH_LIMIT`、`DAILY_BARS_BACKFILL_BATCH_LIMIT` |
| 批型硬边界 | 日常 500，回填 2,000；不互借，不等于每日总量上限 | `src/backend/app/ingest/daily_bars.py` 的 `DAILY_BARS_DAILY_BATCH_CEILING`、`DAILY_BARS_BATCH_CEILING`；`docs/contracts/daily-bars-source.md` §8.1、§9.3 |
| 回填最晚启动 | 北京时间 ≥22:45:00（含）拒绝新批；待实测但已裁定默认生效，不中断已开始批 | 团队 `reports/T-B142-review.md`；`src/backend/app/ingest/daily_bars_plan.py` 的 `BACKFILL_LATEST_START`、`backfill_start_blocked` |
| 跨日 / 熔断 | 北京自然日跨零点旧批失效；STOP/HALT/103/429/503 整批停、不续接；解除 HALT——关口：需用户本人批准 | 团队 `reports/T-A150.md`；`docs/contracts/C2-successors.md` (b)–(c) |
| live adapter 节奏 / 分页 | 单连接、请求间隔至少 2 秒；page_days 与无更早历史响应字段未验证，默认不生效；history_confirmation 默认 None | `docs/contracts/C2-successors.md` (c)；不得用 `docs/mairui-fit-matrix.md` §1 的单次历史样本代替分页验证 |
| 范围 | 本人合格持仓 ∪ 有效自选；全市场只存不推，market 开关约定默认 False、实现待补 | `docs/contracts/daily-bars-source.md` §8.2、§9.6；`docs/contracts/C2-successors.md` (a) |
| 日线单位 / 来源 | 库存 none；量为股（麦蕊日线 v×100），额为元；麦蕊后到替换 tdx_local 是唯一跨源替换，须先留对账记录 | `docs/contracts/multi-source-ingest.md` §2.4、§2.5、§4；现行实现对齐交 T-B143/PN-03 |
| 复权 / 日历 | gbbq 单快照；因子连乘式未验证，默认不生效，落地前缺因子不补 1；历史日历按 merged_calendar，指数日线核对 | `docs/contracts/multi-source-ingest.md` §2.2、§2.5、§5 C5/C8；与 `docs/mairui-fit-matrix.md` §4.1 的主源表述差异见 §6 |
| 离线分钟落点 | parquet + 目录表，不进 PG；只收沪深，按股票日单源；不扩盘后主线 | `docs/contracts/multi-source-ingest.md` §1、§3.2–§3.3、§4–§5 |
| 跟踪周期 / 风控阈值 | T+1/5/20；风控沿现有设置与策略版本，不在路线草案另定值 | `src/backend/app/tracking/service.py` 的 `PERIODS`；`src/backend/app/suggestions/risk.py` 的 `effective_config`；`docs/plan-phase2-next.md` §2 P2N-02、P2N-08 |
| 覆盖率 / 测试范围 | 领域 ≥90%、整体 ≥80% 为既有门槛；切片定点测试，集中全量由编排者派单，不逐单扩跑 | `docs/plan.md` §8.0；`docs/plan-phase2-next.md` §2 P2N-10 |

## §3 任务表（可派单）

PN 为暂定编号，由编排者正式编号；负责与 Codex 档位均为建议，依本任务分工规则分配。旧 P2N 是范围映射，不推断尚未交付；已有功能只核对/补缺。依赖列指集成验收前置，离线桩与测试骨架可先做。

| 暂定编号 | 标题 | 负责 | 建议 Codex 档位 | 依赖（等待编号） | 验收（一句） |
|---|---|---|---|---|---|
| PN-01 | 定稿契约与当前实现差异收口 | Grok | L3 | T-A150、T-A151、T-A152、T-A153 | 按四份定稿及 T-B142 评审列出已兑现/待实现项（§9.3 的 503、跨日与 22:45 含等于边界由 PR #131 落文，本单只核对），不重开已裁定问题。 |
| PN-02 | C2(b) DB halted 人工恢复入口 | Grok | L3 | PN-01 | `docs/contracts/C2-successors.md` (b) 的 dry-run、精确范围、审计、最小权限及不重排队用例通过；解除 HALT——关口：需用户本人批准。 |
| PN-03 | 日历、gbbq 与多源读写对齐 | Grok | L3 | PN-01、T-B143 | 按 `docs/contracts/multi-source-ingest.md` §2、§4–§6 验证历史日历、复权缺口、替换留证与日报排除 tdx_local；未验证算法保持关闭。 |
| PN-04 | C2(a) 新标的 codes 与研究范围守卫 | Grok | L2 | PN-01、PN-03 | `docs/contracts/C2-successors.md` (a) 的子集校验、codes 幂等续接、日常额度、延后及 market 默认拒绝全部离线通过。 |
| PN-05 | C2(c) 日 K live adapter 离线接线 | Grok | L3 | PN-01、PN-02、T-B141、T-B142 | `docs/contracts/C2-successors.md` (c) 的默认未接线、持有租约、停止及零出网用例通过，K3 绑定核实留证；真调麦蕊——关口：需用户本人批准。 |
| PN-06 | 盘后信号、风险、建议与跟踪缺口收敛 | Grok | L3 | PN-03、PN-04、PN-05 | 复用 P2N-02/03/04，在合成源串起五段，晚到/缺数仍出有缺口日报，同输入幂等且旧修订不变。 |
| PN-07 | 策略版本与知识卡只读关联 | Grok | L2 | PN-01、T-A151 | `docs/contracts/strategy-detail.md` §2–§6 的读取、版本绑定、分页与越权行为逐项覆盖，空态不猜关联。 |
| PN-08 | today、日报、风险与策略详情实联 | DS 团队 | L2 | PN-06、PN-07 | 按 P2N-05、`docs/contracts/today-view.md` §1、§7–§9 展示缺口、分歧和模拟结果，仅 ready 时取日报，跨时区显示一致。 |
| PN-09 | 盘后闭环定点测试与覆盖缺口 | DS 团队 | L2 | PN-06、PN-07、PN-08 | 按 P2N-10 首切片报告隔离、PIT、不可变性、恢复与零外呼证据，覆盖率缺口按既有门槛交编排者集中收口。 |
| PN-10 | 公开数据与口径交叉核对 | DS 团队 | L2 | PN-01、PN-03、T-A152、T-A153 | 按矩阵 §3–§5 与多源契约 §2、§6 整理日历、单位、来源差异，无法核实者保持未验证，不据核对自行升级特征。 |
| PN-11 | 本地栈与迁移版本同步准备 | DS 团队 | L2 | T-B143、PN-09、PN-10 | 按 PR #141（T-B143）与团队 `reports/T-B143.md` 核对镜像、迁移、只读挂载及文件校验并交可审阅清单；生产部署、通达信真实全量导入——关口：需用户本人批准。 |
| PN-12 | 阶段评审与合并收口 | Grok | L3 | PN-01–PN-11 | 沿 P2N-10 集中评审首切片及 T-A150 K1–K3，合并与生产启用分开记录，未验证项与用户批准关口均可追溯。 |

## §4 需用户本人批准的关口

本草案只安排实现、离线验证和可审阅准备，不代表下表任何授权；编排者派单、CI 通过及合并均不能替代用户本人批准。

| 流程位置 / 动作 | 关口 | 出处 |
|---|---|---|
| 数据就绪：真调麦蕊（含验证、首次小实调） | 关口：需用户本人批准 | `docs/plan-phase2-next.md` §1；`docs/contracts/C2-successors.md` (c) |
| 本地栈交付后：生产部署 | 关口：需用户本人批准 | `docs/plan.md` §8 T-B79；`docs/plan-phase2-next.md` §2 P2N-10 |
| 存储/维护：删用户数据（含保留策略清理） | 关口：需用户本人批准 | `docs/contracts/C2-successors.md` (b)；PR #141（T-B143）与团队 `reports/T-B143.md` |
| 建议/通知或授权询问：对外发送 | 关口：需用户本人批准 | `docs/plan-phase2-next.md` §1；团队 `reports/T-A152.md` |
| 熔断恢复：解除 HALT（文件与 DB 状态均包括） | 关口：需用户本人批准 | `docs/contracts/C2-successors.md` (b) |
| 采集启用：恢复出网 | 关口：需用户本人批准 | `docs/plan-phase2-next.md` §1 |
| 历史补齐：backfill --apply | 关口：需用户本人批准 | `docs/contracts/daily-bars-source.md` §9.4、§9.7；`docs/contracts/C2-successors.md` (b) |
| 多源同步：通达信真实全量导入 | 关口：需用户本人批准 | PR #141（T-B143）与团队 `reports/T-B143.md` |

## §5 T-B141 后续单草稿

以下四单逐一对应团队 `reports/T-B141-review3.md`「已知问题清单」第 1–4 条；原复审通过，不把后续改进重写成阻断。优先级与档位为建议：P2 随相邻切片，P3 清理；四单均不阻断已合入的 T-B141。

### FU-1｜验证前过期日期判定

| 字段 | 内容 |
|---|---|
| 问题 | `src/backend/app/ingest/verify_licence.py` 的 `process_verify_intent` 重置 pending 后，`src/backend/app/ingest/egress.py` 的 `mairui_get` 准入未再次按 expires_on 判过期，可能产生一次验证调用。 |
| 建议做法（最小改动） | 先裁定日期边界与重交语义，再在现有验证入口读 expires_on 并增加前置判定，复用既有日期口径，不另造有效期阈值或重试。 |
| 负责与档位 | Grok，L3；依赖 §6 第 4 项裁定。 |
| 验收 | 合成时钟覆盖已过期、未过期、日期缺失与边界；被拒时 transport 为零，管理员暂停与 STOP/HALT 不误放。 |
| 优先级 | P2（建议）：复审判定修复前同证书换新 id 时已有此行为，无新增风险，只多一次用户触发的验证调用；出处为上述清单第 1 条。 |

### FU-2｜重新 PUT 与 expired 连库覆盖

| 字段 | 内容 |
|---|---|
| 问题 | `tests/backend/unit/test_verify_licence_t_b141.py` 的 `test_tick_same_licence_reput_resets_invalid_memory` 直接改库模拟 PUT，未走 `src/backend/app/licences/service.py` 的 `set_licence`，expired 仅离线探针覆盖。 |
| 建议做法（最小改动） | 保留原例，补纯合成请求经 `src/backend/app/api/v1/data_licence.py` 的 `put_licence`、`set_licence` 到同一 core/tick 的集成用例，transport 打桩，增加 expired 分支。 |
| 负责与档位 | DS 团队，L2；FU-1 改动时同步其拒绝预期。 |
| 验收 | invalid/expired 均经过真实服务链，校验 id、库状态、ACK 与裁定后的调用次数；暂停/STOP/HALT 负例不放宽，零真实外呼。 |
| 优先级 | P2（建议）；出处为上述清单第 2 条。 |

### FU-3｜明确 user_reset 的退避语义

| 字段 | 内容 |
|---|---|
| 问题 | `src/backend/app/ingest/core.py` 的 `IngestCore.user_reset` 经 `src/backend/app/ingest/state.py` 的 `LicenceState.user_reset` 清除 backoff_until、paused_until；这是原有设计语义。 |
| 建议做法（最小改动） | 先由编排者裁定是否改；推荐暂不改行为，在契约/注释写明行级退避清除、用户级升级截止保留；若改，仅调整 reset 分支并补边界例。 |
| 负责与档位 | Grok，L3；依赖 §6 第 4 项裁定。 |
| 验收 | 合成测试与裁定一致，管理员暂停、用户级升级截止、令牌桶、HALT 及 503 停机均保留。 |
| 优先级 | P2（建议）；出处为上述清单第 3 条。 |

### FU-4｜验证测试文件格式清理

| 字段 | 内容 |
|---|---|
| 问题 | `test_tick_same_licence_reput_resets_invalid_memory` 所在的 `tests/backend/unit/test_verify_licence_t_b141.py` 被评审记录有两处多余空行，具体所属用例待核实；CI ruff 仅检查 src/backend，未拦截。 |
| 建议做法（最小改动） | 对该文件定点核实并修正两处格式；不改断言，不顺带扩大 CI 扫描范围。 |
| 负责与档位 | DS 团队，L1。 |
| 验收 | 该文件 ruff 通过，diff 仅格式变化；若基线已修，报告已满足，不制造空改动。 |
| 优先级 | P3（建议）；出处为上述清单第 4 条。 |

## §6 待裁定项

1. **日历来源表述冲突**：矩阵 §4.1/§6 用指数日线为主源，多源契约 §2.2/§5 C8 用 merged_calendar、指数只核对；推荐以较新的 T-A153 定稿为实施口径，PN-01 同步矩阵表述（`docs/mairui-fit-matrix.md`；`docs/contracts/multi-source-ingest.md`）。
2. **gbbq 因子落地前的验证责任**：方向已定，连乘式仍未验证；推荐 PN-03 提最小算法与时点证据、PN-10 独立核对、Grok 评审，关闭前沿现行缺口，不重开来源选择（`docs/contracts/multi-source-ingest.md` §2.5、§5 C5）。
3. **T-B143 后续范围**：迁移随镜像、minute_bars 保留策略 1095 天、退市股日线兜底未完；推荐首切片只依赖所需日线/权息及目录迁移，退市兜底另派，不以历史分钟量扩充 PG；删用户数据、生产部署、通达信真实全量导入——关口：需用户本人批准（PR #141（T-B143）与团队 `reports/T-B143.md`；`docs/contracts/multi-source-ingest.md` §5–§6）。
4. **T-B141 后续行为取舍**：推荐 FU-1 先明确 expires_on 的日期边界与重新 PUT 是否允许验证，不自行增加有效期阈值；FU-3 维持原 reset 语义并写明，行为变更另裁定（团队 `reports/T-B141-review3.md`「已知问题清单」第 1、3 条）。
5. **首切片终点与后续排期**：推荐 PN-06/08/09 以 P2N-02/03/04/05/10 的盘后闭环为终点；P2N-01 映射复用，P2N-06–09 的盘中、计划反馈与增强解释另批派单，不重建已有模块（`docs/plan-phase2-next.md` §1–§3）。
6. **T-A151 路由计数歧义**：§8 称四个只读路由，但 §2–§6 列出五类读取能力，另有生命周期等价路径；推荐 PN-07 按正文逐项验收，由编排者确认正式派单范围，不用摘要数量漏掉卡版本精确读取（`docs/contracts/strategy-detail.md` §2–§6、§8）。

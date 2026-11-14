# C2 后继三项：边界契约要点（T-A150 ②）

起草：Codex L3（gpt-6.1-sol/high）只读独立起草，与架构师初稿对照合并；架构师审改定稿。采纳与删减见 `reports/T-A150.md`。

上位契约：`daily-bars-source.md` §8.1、§9.2、§9.3、§9.6。本文件只定边界，不改上位契约的默认值。
三项共同遵守：
- 默认部署出网 0 次；
- 不新增读取环境变量、回执或 API 参数来放宽额度的途径；
- 参数要有出处，没有出处的标「未验证」，默认不生效；
- 测试只用打桩 transport，并经出网探针证明 0 次出网。

依赖顺序：(b) → (c)。(a) 可以与 (b) 并行开发；但 (a) 的真实补齐要等 (c) 和单 D 完成。

## (a) 新股／codes 自动入口（落实 §9.2，单 A2）

- **输入**：
  - 触发点：`confirm_import` 在事务提交后、`add_watchlist` 返回 201 后；
  - 内容：本次新进入 `daily_universe` 的代码（已规范化、排序去重）；
  - 附带：owner 和 trigger（import 或 watchlist）；
  - 导入撤销、删除自选不触发。
- **派生参数**（都在服务端算，不接受外部传入）：
  - trade_date 沿用 `cli/daily_bars_backfill._default_trade_date` 的规则；
  - window 取 `backfill_window_days(conn, trade_date, 3)`；
  - batch_kind 固定为 daily。
- **输出**：
  - 每次触发最多一个 `daily_bars_fetch` 任务，带 codes 参数；
  - codes（排序去重后的列表）写进原运行的 pipeline_runs.stats；`process` 本来就会读取该运行，从中取出 codes，续接批照抄；
  - outbox 幂等键加入 codes 摘要（排序后取哈希），不同代码集合不会被合并；
  - 不新增表，不加迁移，与 §9.2「无新迁移」一致。
- **状态和错误码**：
  - window 为 None：不入队，记 skipped，issue 为 `calendar_not_covered`；
  - 代码已就绪（`backfill_ready`，口径同 `ready_for_window`）：剔除，全部就绪则不入队；
  - Redis 去重：同一 owner、代码、trade_date，用 `SET NX`，TTL 等于 `SLOT_TTL_S`；
  - 开市日 [17:00, 17:45) 内触发：放进 `jobs:delayed`，17:45 放出；
  - 源为 off，或批上限为 0：记 skipped 待补运行，issue 为 `daily_bars_source_off` 或 `daily_bars_http_budget_unset`，stats 里带 codes 列表和 window；
  - codes 不是 owner `daily_universe` 的子集：任务记 ValueError 失败，transport 0 次。
- **禁区**：
  - API 进程不出网、不读回执、不建 outbox；
  - 201 和导入确认的结果不受入队成败影响；
  - 不新增任务名；不借用回填额度；
  - 不进 §9.6 的 market 范围。
- **验收**：
  - §9.2 的 7 条 G/W/T 全部按原名实现；
  - 另加 `test_codes_carried_by_continuation_and_idempotency_key`：续接批的 codes 等于首批，codes 不同的两次触发不合并。
- **范围补充**：§9.6 的 `--scope owned|market` 与 `RESEARCH_MARKET_SCOPE_ENABLED`（默认 False）随本单一起实现，按 §9.6 的 3 条 G/W/T 验收。
- **未验证**：
  - 新股补历史一个代码的调用次数是 ceil(W/k)，k 未验证（见 (c)）；
  - 用 `SLOT_TTL_S`（2 天）作去重 TTL，沿用 §9.2 原文，没有独立出处。

## (b) DB halted 人工恢复

- **背景**：`daily_bars_consumer._halted` 只要看到任一 halted outbox 行，`process`、`_resume`、`wake_delayed` 就永久拒绝；只删 HALT 文件不能恢复（`T-A150-C2-effective.md` 第 11 条）。
- **门控**：解除 HALT 属硬红线，每次都须用户本人批准。CLI 必须带 `--approval <卡片号>`，卡片号写入审计；默认 dry-run。
- **入口**：新 CLI `daily-bars-halt-clear [--approval ID] [--apply]`，由运维在 ingest 容器内执行。不提供 API、定时任务或 worker 入口。
- **前置**（任何一条不满足就拒绝，退出码非 0）：
  - STOP 文件不存在；
  - HALT 文件已由运维删除；
  - 存在 halted 行。
- **dry-run 输出**：逐行列出待处理 halted 行的 id、owner、error_code 和 finished_at，作为用户批准的精确范围。
- **动作**：
  - 在与消费相同的 `single_egress` 锁内逐行加锁复核；只处理批准范围内、且仍为 halted 的行；
  - 把这些行改为 failed，error_code 改为 `daily_bars_halt_cleared`，保留 finished_at 和 attempted_at；
  - 另记一条 pipeline_runs 审计，step 为 `daily_bars.halt_clear`，stats 带卡片号与行 id；
  - 重复执行为 no-op，不报错；范围外仍有 halted 行时继续阻断，并在输出中列出；
  - 不改回 pending，不重新入队，不重建续接；
  - 恢复后要再跑，由运维重新执行 `daily-bars-backfill --apply`，已就绪的标的自动跳过。
- **权限**：用迁移为 aia_maint 增加最小授权：只允许经一个 SECURITY DEFINER 函数改上述两列，不开放整表 UPDATE。
- **退出码**：
  - 0：完成或 dry-run；
  - 2：存在 STOP；
  - 3：存在 HALT 文件；
  - 4：缺批准卡片号；
  - 5：没有 halted 行；
  - 6：行状态在复核时已变化，整个事务回滚。
- **禁区**：
  - 不用 DELETE 消除拦截；不删除 outbox、pipeline_runs 或 bars（删用户数据属硬红线）；
  - 不恢复证书状态，不放宽预算；
  - 不碰名单链路的 HALT；
  - 代码里不自动清除 HALT（§8.1 不变）。
- **验收**：
  - `test_halt_clear_dry_run_default_and_requires_approval`；
  - `test_halt_clear_refuses_stop_or_halt_file`；
  - `test_halt_clear_exact_rows_atomic_and_idempotent`；
  - `test_halt_clear_marks_failed_never_pending_no_requeue`；
  - `test_after_clear_only_new_intents_run`；
  - `test_halt_clear_writes_audit_with_approval_id`；
  - `test_maint_role_cannot_update_outbox_directly`。

## (c) live adapter（日 K 真实 transport）

- **门控**：
  - 真调麦蕊属硬红线：接线提交可以离线合入，但生产启用就是单 D，须用户本人批准；
  - 批准内容按 §9.4：批型及每批上限、首次实调的次数和时段、`DAILY_BARS_SOURCE` 设为 mairui、回执安装；
  - T-B140 的既有批准不覆盖本项。
  - 前置：(b) 已合入；K2、K3（见生效确认）已裁定。
- **输入和输出**：
  - 签名沿用 `Transport`：(code, start, end) → (status, DailyBar | DailyBarsResult | None)；
  - 只经 `ingest/egress.mairui_get` 出网（单出口、STOP/HALT 前置、`limited`、`classify`、`_write_halt`），每个计划段只发一次；
  - 使用 `process` 已持有的 `single_egress` 租约，不另抢租约，不另开 HTTP 出口，不跟随重定向；
  - 证书只在全部门控通过后、在 ingest 进程内经 `daily_lists.credential` 解封；证书和完整请求地址都不进 Redis、日志或异常文本；
  - `adj_type` 固定为 none；
  - `history_confirmation` 默认 None。只有响应里有明确字段证明「没有更早历史」时，才设 `no_earlier`；该字段「未验证」，未验证前一律 None。
- **接线**：`write_heartbeat` 调 `tick_bars` 时传入 transport 和 page_days。两者都只由单 D 的那次提交打开，默认仍为 None，也就是现在的 0 出网状态。
- **停止**：
  - 遇 STOP、HALT、103、429，立即整批停，不重试，不续接；
  - 503 按用户卡片 t1088s3682 的口径同样即停（比 §9.3 严，**待编排者确认后写回 §9.3**）；
  - 网络异常按 `transport_or_response_failed_no_retry` 处理，不重试。
- **节流**：两次请求至少间隔 2 秒，依据用户卡片 t1080s3653 和 t1088s3682；单连接，`ingest.yaml` 并发为 1。
- **未验证**（单 D 小实调前都不得设默认值）：
  - 历史接口每页天数 k（page_days），未验证前多日窗口一律 `daily_bars_history_page_size_unverified`；
  - 停牌标志和成交额单位的映射，单 D 后与通达信行交叉核对；
  - 是否有上市日期或「无更早历史」的显式字段。
- **禁区**：
  - API、worker 进程不出网；
  - 不并发；不打印证书；
  - 不经本适配器写全市场（§9.6 另行批准）；
  - 测试不连真网。
- **验收（离线）**：
  - `test_live_adapter_unwired_by_default`；
  - `test_adapter_uses_held_lease_and_mairui_get_once_per_segment`；
  - `test_heartbeat_closed_gates_load_no_secret`；
  - `test_adapter_halts_on_stop_103_429_503_no_retry`；
  - `test_adapter_min_interval_2s`；
  - `test_adapter_never_logs_or_raises_secret`；
  - `test_adapter_history_confirmation_none_unless_explicit`；
  - `test_adapter_payload_maps_to_daily_bar_fields`。
- **验收（单 D）**：经用户批准做首次小实调（次数按批准），记录 HTTP 状态、行数和核对结果；遇 STOP、103、429 或 503 即停，等待用户。

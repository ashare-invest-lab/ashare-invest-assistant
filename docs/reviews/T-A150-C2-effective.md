# C2 生效确认（T-A150 ①）

- 契约：`docs/contracts/daily-bars-source.md` §8.1 开关、§9.3（PR #103 合入，merge 80bdd5f）。§9.7 把 C2 限定为 §9.3；§9.2（A2）与 §9.6 不在 C2 范围内，见文末「范围外」。
- 实物：#104 outbox 722c376、#109 plan abf42bd、#111 batch-budget bbd0e6d、#116 consumer 12aa2bb、#117 window f554c6b、#118 continuation 8d4303a、#119 time-gate 1d9d2c3、#120 late-history c99921e。八片都已在 origin/main=4aae38a 中。合计 54 个文件，+4,490／−240，21 个提交（git 复核）。
- 阻断口径：只算正常路径误拦或误放、契约承诺未兑现、放宽断言变绿、用户 Windows 部署必挂、前视或定义错误。其余记非阻断。

**结论：有条件生效。** 在默认双 0 下，§9.3 的结构、判定和离线测试都已兑现，部署后出网 0 次。打开任一批上限常量（单 D）之前，须先满足 K1–K3。

## 逐条核对

| # | 契约承诺 | 实现／用例 | 判定 |
|---|---|---|---|
| 1 | 两项常量默认 0，硬上界 2,000；删除 unlimited、`DAILY_BARS_HTTP_LIMIT` | `app/ingest/daily_bars.py` 模块常量；`test_c2_removes_unlimited_and_keeps_both_effective_defaults_closed`、`test_daily_http_limit_unchanged` | 一致。缺口（非阻断）：没有用例断言 `DAILY_BARS_BATCH_CEILING` 等于 2,000 |
| 2 | 纯函数判定：日常 ≤500、回填 ≤2,000，超界拒绝不截断；未知批型 unset | `daily_bars_batch_budget`；`test_batch_budget_rejects_unlimited_and_out_of_bounds`、`test_http_budget_resolution_table` | 一致。实现用 `type(value) is int`，布尔、浮点、字符串、None 都拒绝。缺口（非阻断）：参数表缺 None、字符串 500、500.0、回填 501、未知批型五个值 |
| 3 | 先选批型常量再判定，不借额度；窗口非空不升为回填 | `fetch_mairui_daily_bars`、`batch_budget`；`test_batch_kind_does_not_borrow_the_other_constant`、`test_window_does_not_select_backfill_budget`、`test_window_never_selects_larger_backfill_gate_implicitly` | 一致。批型来自内部队列参数，只有 CLI 回填写 backfill，不属外部参数（非阻断，见报告「Codex 删减」） |
| 4 | unset：不建 outbox、不读回执、transport 0 次，运行记 skipped 与 `daily_bars_http_budget_unset` | `enqueue`、`tick`、`wake_delayed`；`test_worker_default_zero_never_reads_receipt_or_egress`、`test_zero_budgets_short_circuit_tick_before_any_resource`、`test_both_budgets_unset_short_circuits_without_db_redis_or_grant` | 一致 |
| 5 | 三类批串行、单连接 | `process`、`_resume` 的 `single_egress`；`test_list_and_both_daily_bar_batch_types_use_the_same_egress_lease` | 一致 |
| 6 | 按 transport 次数计数；整标的，否则本标的及其后全部顺延 | `fetch_mairui_daily_bars` 的预算判断、`segments`；`test_history_quota_does_not_start_partial_next_code`、`test_window_pages_are_complete_nonoverlapping_and_whole_code_budget`、`test_less_than_one_whole_code_quota_sends_nothing` | 一致 |
| 7 | 达到上限：其余标的记 `daily_bars_quota_deferred`，运行 partial | 同上；`test_budget_cap_reached_defers_rest`、`test_batch_cap_defers_rest_and_continues` | 一致 |
| 8 | 不存游标，按就绪集合重算；例行批看当日完成版，补历史和回填看全窗；`tdx_local` 不计就绪 | `ready_for_window`、`code_ready`；`test_ready_only_complete_final_owned_mairui_rows`、`test_backfill_readiness_requires_every_day_not_just_a_latest_bar`、`test_ready_codes_do_not_consume_http_quota` | 一致，但比契约严：只认 mairui 来源、且与当前证书同 licence_id 的行。非阻断，K3 处理 |
| 9 | 续接条件：quota_deferred、有就绪进展、无 HALT 时推 batch_seq+1；无进展记 `daily_bars_resume_stalled` | `process` 的 `record`、`_resume`；`test_partial_progress_can_continue_until_later_batch_stalls`、`test_resume_stalled_no_infinite_loop`、`test_continuation_has_no_fixed_batch_count_ceiling`、`test_do_nothing_on_future_rows_is_not_new_readiness_progress` | 一致。17:00 截断时不看进展也续接，这是契约 §9.3 时间窗条款的要求，不算偏差 |
| 10 | 遇 STOP、HALT、103、429：整批停，写 HALT，不续接、不重试 | `send`、`UpstreamHaltError`、`persist_halt`；`test_each_send_rechecks_stop_and_rate_limit_halts_without_continuation`、`test_halt_never_creates_continuation`、`test_batch_budget_halts_on_103`／`_429`／`_stop` | 一致。非阻断：本批已收到的行随事务一起回滚（`test_stop_on_second_history_page_rolls_back_and_blocks_next_tick`），已花掉的调用作废 |
| 11 | HALT 由运维人工清除后才恢复 | `_halted`：只要存在任一 halted outbox 行，`process`、`_resume`、`wake_delayed` 就一律拒绝 | **偏差**：删掉 HALT 文件不能恢复，也没有解除入口（aia_maint 对 outbox 只有 SELECT(id,user_id) 和 DELETE）。默认 0 时无影响 → K1 |
| 12 | 「直到做完」：唯一的停止条件是做完、STOP/HALT/103/429 或无进展 | `process`、`send`、`_resume` 比较北京自然日：跨日后待续批记 `daily_bars_batch_expired`；运行中的批跨日时 `send` 抛 `DailyBarsPlanError`，整批回滚 | **偏差**：多了一个停止条件；跨北京零点的回填会丢掉本批已取到的行。默认 0 时无影响 → K2 |
| 13 | 开市日 17:00–17:45 不跑回填批和补历史批；运行中顺延，续接放入 `jobs:delayed`，17:45 放出；17:15 例行批不受限 | `delayed_until`、`HistoryWindowDeferredError`、`wake_delayed`、CLI 窗口拒绝；`test_running_batch_stops_at_1700_commits_completed_pages_and_delays_rest`、`test_exact_1745_releases_and_duplicate_wakeup_never_replays`、`test_1715_daily_can_pass_history_at_front_of_db_queue`、`test_cli_past_trade_date_respects_1700_start` | 一致 |
| 14 | 结构上界：一批调用次数 ≤ min(计划次数, 上限) | `test_batch_budget_no_cap_calls_equal_planned`、`test_window_pages_are_complete_nonoverlapping_and_whole_code_budget` | 一致 |
| 15 | 回执校验、`DAILY_HTTP_LIMIT` 为 1、`live_budget_issue()` 不变；环境变量和回执不能放宽上限 | `read_daily_bars_grant`、`_authorized`；`test_limit_not_widened_by_env_or_receipt`、`test_revalidate_exact_receipt_and_current_owner_status_before_attempt` | 一致 |
| 16 | 上市较晚的代码，须源方明确确认没有更早历史，才算就绪 | `_history_first`、`history_evidence`；`test_no_confirmation_does_not_infer_listing_from_earliest_row` 等 15 条 late-history 用例 | 一致，比契约严（只认源方显式确认）。目前没有适配器能产出确认 → 见后继 (c) |
| 17 | 测试没有靠放宽断言变绿 | #111 改写 T-T73 与 T-T73b：断言对象从旧哨兵换成两项常量，期望值仍是 0、unset、transport 0 次 | 一致 |
| 18 | 用户 Windows 部署 | 回执和 HALT 的 POSIX 权限检查跑在 WSL／容器里；生产 `tick_bars` 不注入 transport | 没有必挂依据 |
| 19 | 契约 G/W/T 的建议用例名 | 11 个里同名的只有 3 个，其余由上列改名用例覆盖 | 非阻断：契约写的是「建议名」 |

## 生效条件（单 D 打开任一常量之前）

- **K1**：实现 DB halted 的人工恢复入口（后继 (b)），并且该入口须经用户本人批准才能使用。
- **K2**：编排者二选一。①把「批次只在创建当日（北京时间）有效」写进 §9.3 停止条件，CLI 回填补一条最晚启动时刻的守卫；②改实现：跨日时像 17:00 截断那样提交已完成的标的再结束。架构师推荐①，改动最小。
- **K3**：单 D 前核实库里现有麦蕊行（含 T-B140 回填）的 source_licence_id 是否等于当前有效证书 id。如果不等，C2 会把这些行视为未就绪并重新请求，需先由编排者裁定。

## 范围外（不影响 C2 生效，转后继 (a)）

- §9.2 的入口（`confirm_import` 与 `add_watchlist` 两处触发、任务的 codes 参数、`backfill_ready`、按代码去重）尚未实现。
- §9.6 的 `--scope` 参数和 `RESEARCH_MARKET_SCOPE_ENABLED` 尚未实现。
- 目前 CLI 回填只能按 owned 范围入队。

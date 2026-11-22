# T-A230 实时类工程参数

本文件只登记实时链路的工程参数，与市场宽度、regime、仓位区间、冷静期、复盘阈值及板块扫描开关等判断类参数分开。参数清单与「工程取值」分类依据 PR `#383`@`4f7e2eeb`（T-R112b，尚未合入）；本文件不依赖该 PR 的路径，取值仍以 `origin/main` 的 `config/realtime.yaml`、`config/ingest.yaml`、代码与契约为准，不改变默认值。默认值的唯一出处仍是 `docs/plan.md` §6.1 与上述 YAML。

下列 31 项结论均为「工程取值」，不计入判断类未验证。理由中的公开文档用于说明机制（限频、SSE 保活/重连、反代空闲超时等），规范未强制本项目的具体秒数或只数时在理由中注明，但不把该行改判为缺证。可调范围只记录现有校验，不臆造上限。契约中的 `GET/PUT /admin/realtime-settings` 只描述接口形状，`origin/main` 尚无对应 API 实现，不能据此推断已有热加载。

## 总表

| 参数 | 工程取值 | 代码/契约出处 | 理由 | 可调范围 | 谁能改 |
|---|---:|---|---|---|---|
| `realtime.schema_version` | 1 | `config/realtime.yaml`；`config_files._File.schema_version` | 配置文件格式版本，工程取值 | 仅 `1`（`Literal[1]`） | 改加载器与 plan §6.1，不能只改 YAML |
| `intervals.quote_interval_s` | 15 秒 | `config/realtime.yaml`；`config_files.RealtimeIntervals.quote_interval_s`；`workers/jobs.py`；`intraday/consumer.Consumer.pump` 回退间隔为 2× 本值 | 多股批量 ≤20 只/次（[麦蕊博客](https://www.mairuiapi.com/blog/06-2/)）与钻石版 1 分钟 6 千次（[hsdata](https://www.mairuiapi.com/hsdata)）约束下，按 plan §0A.6 预算推出的默认间隔；规范未强制 15 秒 | 整数 ≥5 | 改默认值须先改 plan §6.1，再改 YAML；运行时已读取，非热调 |
| `intervals.all_market_interval_s` | 60 秒 | `config/realtime.yaml`；`config_files.RealtimeIntervals` | 与 plan §0A.6「全市场 1 次/分钟」记载对齐；本轮公开页未复核到该句，规范未强制 60 秒 | 正整数 | 改默认值按 plan→YAML；当前运行时尚未读取该键 |
| `intervals.pro_tier1_interval_s` | 60 秒 | `config/realtime.yaml`；`api/v1/aggregates.py` 传给 `aggregates/t_view.build` 的 `interval_s` | plan §0A.6 Tier-1 每分钟拉 1 分钟 K 的工程档；规范未强制 60 秒 | 正整数 | 改默认值按 plan→YAML；运行时已读取 |
| `intervals.pro_tier2_interval_s` | 300 秒 | `config/realtime.yaml`；`config_files.RealtimeIntervals` | plan §0A.6 Tier-2 每 5 分钟的工程档；规范未强制 300 秒 | 正整数 | 改默认值按 plan→YAML；当前运行时尚未读取该键 |
| `intervals.stale_threshold_s` | `null` | `config/realtime.yaml`；`RealtimeIntervals.effective_stale_threshold_s` | `null` 表示采用 2×`quote_interval_s`（plan §0A.3，T-A01 由 3× 统一为 2×）；规范未规定倍数 | `null` 或正整数 | 改默认值按 plan→YAML |
| `effective_stale_threshold_s` | 30 秒（`null` 时为 2×15） | `config_files.RealtimeIntervals.effective_stale_threshold_s`；`api/v1/suggestions.py`、`ingest/owned_quotes.py`、`intraday/engine.py`、`risk/rc1.py` | 允许错过一轮刷新再判 stale 的派生值；与 `t_view.build` 的 2×`interval_s` 不是同一阈值 | 由 `stale_threshold_s` 或 2×`quote_interval_s` 决定 | 改 YAML 默认值按上行；不能单独热改派生值 |
| `universe.tier1_cap` | 1500 只 | `config/realtime.yaml`；`intraday/engine.py`、`intraday/p0_plan.py` | plan §0A.7 由分钟线预算推出 | 正整数，且 ≤ `universe_hard_cap` | 改默认值按 plan→YAML；运行时已读取 |
| `universe.universe_hard_cap` | 4000 只 | 同上 | plan §0A.7 的系统去重池上限 | 正整数，且 ≥ `tier1_cap` | 同上 |
| `universe.tier1_alert_ratio` | 0.8 | `config/realtime.yaml`；`config_files.RealtimeUniverse` | plan §0A.7 接近 Tier-1 上限时告警的工程比例 | `0 < x ≤ 1` | 改默认值按 plan→YAML；当前运行时尚未读取该键 |
| `universe.tier1_priority` | `holding`→`focus`→`multi_user_watch`→`single_user_watch` | `config/realtime.yaml`；`config_files.RealtimeUniverse` | plan §0A.7 的名额分配顺序。YAML 键当前未被读取；`intraday/p0_plan.P0Planner.pool` 硬编码为 holding→focus→watchlist，且未区分 multi/single_user_watch | 非空 `Tier1Source[]`，不可重复 | 改 YAML 默认值按 plan→YAML；要让优先级生效须改分配器读取该键 |
| `watchlist.per_user_cap` | 100 只/人 | `config/realtime.yaml`；`api/v1/watchlist.py` | plan §0A.7 由 V1 用户规模与池容量推出 | 正整数；运行时可被权益覆盖 | 默认按 plan→YAML；权益覆盖由后端读取，非热加载 |
| `watchlist.focus_cap` | 20 只/人 | 同上 | plan §0A.7 的盘中重点关注上限 | 正整数；运行时可被权益覆盖 | 同上 |
| `watchlist.holdings_import_warn` | 200 只 | `config/realtime.yaml`；`config_files.RealtimeWatchlist` | plan §0A.7 导入持仓超限提示（持仓本身不设上限） | 正整数 | 改默认值按 plan→YAML；当前运行时尚未读取该键 |
| `flip_detection.debounce_rounds` | 2 轮 | `config/realtime.yaml`；`intraday/engine.py` | 翻转须连续成立才确认的工程去抖（plan 0A.3） | 正整数 | 改默认值按 plan→YAML；运行时已读取 |
| `adaptive.enabled` | `true` | `config/realtime.yaml`；`config_files.RealtimeAdaptive` | 源更新慢于拉取或遇 429/503 时放大间隔/退避的开关；[FAQ](https://www.mairui.club/faq) 说明过频会 503、超 IP 会 429，未规定本开关 | 布尔值 | 改默认值按 plan→YAML；当前运行时尚未读取该键 |
| `adaptive.unchanged_ratio` | 0.8 | 同上 | 「多数股票 `t` 未变」的工程比例（plan 0A.3） | `0 < x ≤ 1` | 同上 |
| `adaptive.unchanged_rounds` | 5 轮 | 同上 | 连续未变化轮数的工程阈值 | 正整数 | 同上 |
| `adaptive.breaker_cooldown_s` | 300 秒 | 同上 | 429/503 后熔断恢复的工程档；FAQ 未规定 300 秒。FAQ 同时写「无并发连接数限制」与「单 IP 多线程 503」，并发上限仍待核实，熔断取保守 | 非负整数 | 同上 |
| `notify.cadence_default` | `1min` | `config/realtime.yaml`；`config_files.RealtimeNotify` | 用户通知合并节奏默认值，不影响采集（plan 0A.3）。YAML 键当前未被读取；`user_realtime_prefs.notify_cadence` 库默认与 `notify/transport.enqueue` 回退字面量为 `1m`（语义同一分钟，拼写不同） | YAML：`realtime`/`1min`/`3min`/`5min`；库字段：`realtime`/`1m`/`3m`/`5m` | 改 YAML 默认值按 plan→YAML；用户可改本人通知偏好 |
| `notify.sse_heartbeat_s` | 15 秒 | `config/realtime.yaml`；契约 §8；`api/v1/notifications.py` 的 `stream`/`generate` 硬编码同值 | SSE 可用注释或事件保活（[WHATWG](https://html.spec.whatwg.org/multipage/server-sent-events.html)、[MDN](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events)），未规定 15 秒；15 秒低于 [nginx `proxy_read_timeout` 默认 60s](https://nginx.org/en/docs/http/ngx_http_proxy_module.html#proxy_read_timeout) 与 [ALB idle 默认 60s](https://docs.aws.amazon.com/elasticloadbalancing/latest/application/application-load-balancers.html#connection-idle-timeout)。本仓库 `deploy/nginx/nginx.conf` 写明不改 `proxy_read_timeout`（SSE 依赖默认值）。YAML 键尚未被通知代码读取 | 正整数 | 改 YAML 须同步改 `generate` 硬编码与契约 §8 |
| `notify.sse_replay_window_s` | 600 秒 | `config/realtime.yaml`；契约 §8；`notify/transport.py` 的 `publish`/`replay`/`reset_reason` 硬编码同值 | WHATWG 支持 `Last-Event-ID` 续传，未规定 10 分钟窗口。YAML 键尚未被 transport 读取 | 正整数 | 改 YAML 须同步改 transport 硬编码与契约 §8 |
| `notify.poll_fallback_s` | 15 秒 | `config/realtime.yaml`；契约 §8；前端 `api/queries.ts` 的 `UNREAD_POLL_MS`、`todayPollMs`（交易时段）与 `useStreamPolling` | 断线后与 quote 间隔对齐的轮询下限。YAML 键尚未被运行时读取。`todayPollMs` 在 `closed`/`non_trading_day` 为 60 秒，只降低收盘读取频率，不改变本默认值 | 正整数 | 改 YAML 须同步改前端常量与契约 §8 |
| `degraded_profile.quote_interval_s` | 60 秒 | `config/realtime.yaml`；`config_files.RealtimeDegradedProfile.quote_interval_s` | 证书到期降级档的放慢间隔（plan §6.1）；当前运行时尚未读取该键 | 整数 ≥5 | 改默认值按 plan→YAML |
| `ingest.heartbeat.interval_s` | 15 秒 | `config/ingest.yaml`；`config_files.IngestHeartbeat`；`workers/ingest.py` 的 `write_heartbeat` 经 `run(..., interval_s=)` 调度；契约 §7.10 | leader 周期写 Redis 心跳的工程间隔，须小于 `stale_after_s` | 正整数，且 `interval_s < stale_after_s ≤ ttl_s` | 改默认值须先改 plan §6.1，再改 `config/ingest.yaml` |
| `ingest.heartbeat.stale_after_s` | 120 秒 | `config/ingest.yaml`；契约 §7.10；`api/v1/health.ingest_state` 使用 `settings.ingest_stale_after_s` | 心跳超时判 `stale` 的工程阈值（约 8 个写间隔） | 正整数，且满足上一行不等式 | 环境变量 `INGEST_STALE_AFTER_S` 优先于 YAML；改默认值仍须同步 plan §6.1 |
| SSE `retry` | 3000 毫秒 | `api/v1/notifications.py` 的 `stream`/`generate`；前端 `lib/eventStream.ts` 的 `STREAM_DEFAULTS.retryMs` | WHATWG 规定 `retry` 为毫秒整数、初始重连时间为实现定义；[web.dev](https://web.dev/articles/eventsource-basics) 写大约 3 秒。规范未强制 3000 | 非 YAML 常量，前后端须保持同值 | 同时改后端硬编码与前端常量 |
| SSE 发送循环粒度 | 1 秒 | `api/v1/notifications.py` 的 `generate`（`asyncio.sleep(1)`） | 发送循环的调度粒度，须能满足 15 秒心跳 | 正数秒 | 改后端硬编码 |
| `Consumer.pump` Redis 等待 | 0.01 秒 | `intraday/consumer.Consumer.pump`（`pubsub.get_message(timeout=0.01)`） | 仅 `app_env=="test"` 分支使用，不是生产采集间隔 | 正数秒；仅测试分支 | 改后端测试专用硬编码 |
| `signal-rt` 调度粒度 | 1 秒 | `workers/signal_rt.py` 的 `run("signal-rt", tick, interval_s=1)` | worker 循环调度粒度 | 正数秒 | 改后端硬编码 |
| `aggregates.t_view` 过期倍数 | `2×interval_s`（当前传入 `pro_tier1_interval_s`，即 120 秒） | `aggregates/t_view.build`；`api/v1/aggregates.py` | 与有效行情过期共用「错过一轮再判」的 2× 关系，但乘数作用在分钟线间隔上，结果是 120 秒，不是 `effective_stale_threshold_s` 的 30 秒 | 随传入的 `interval_s` 变化 | 改调用方传入的间隔或 `t_view.build` 倍数，并与契约口径对齐 |

## 配置已建模但运行时尚未读取

本轮在 `src/backend`（除 `config_files.py` 与默认值测试 `test_config_yaml_defaults.py`）未找到读取方的键：`intervals.all_market_interval_s`、`intervals.pro_tier2_interval_s`、`universe.tier1_alert_ratio`、`universe.tier1_priority`、`watchlist.holdings_import_warn`、`adaptive.*`、`notify.cadence_default`、`notify.sse_heartbeat_s`、`notify.sse_replay_window_s`、`notify.poll_fallback_s`、`degraded_profile.quote_interval_s`。这只说明配置模型已存在，不表示热加载已生效。

## 硬编码与 YAML 同值

`generate` 中的 15 秒心跳与 `retry: 3000`、`transport` 中的 600 秒重放窗，与 YAML/契约同值但未读配置；改动必须三处对齐。`signal-rt` 的 1 秒与 `Consumer.pump` 的 0.01 秒不在 YAML。前端 `STREAM_DEFAULTS`、`UNREAD_POLL_MS`、`todayPollMs`、`useStreamPolling` 须单独改前端。

判断类参数（如 `flip_detection.invalidation_immediate`、`degraded_profile.holdings_only` / `tier2_enabled`、板块开关）见 `#383` 的判断类表，不在本文件登记。

**工程取值：31 条。判断类未验证：0 条（本文件不收录判断类参数）。**

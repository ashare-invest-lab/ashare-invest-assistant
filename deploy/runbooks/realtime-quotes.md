# 实时行情采集接入

## 开关

- `REALTIME_QUOTES_SOURCE` 取值为 `off`、`fake`、`mairui`，默认值为 `off`。
- `fake` 仅允许 `APP_ENV=test`。
- `mairui` 开启即真实调用麦蕊，须用户本人或编排者按红线批准。本文不构成批准。

## 任务与调度

- Celery 任务名为 `market.realtime_quotes_fetch`，由 beat 按 `config/realtime.yaml` 的 `quote_interval_s` 调度。
- beat 24/7 触发，交易时段门控在任务内部执行，非交易时段直接返回 0。
- 任务在 worker 执行，带锁不并发。

## 开启前置条件

- 本人 active 证书。
- `single_egress` 单出口租约。
- STOP/HALT 语义已生效。存在即停，不重试。
- 开启=真调麦蕊，须批准，本文不构成批准。

## 开启与关闭

1. 修改 `.env` 中的 `REALTIME_QUOTES_SOURCE`。
2. 重建 `api`、`worker`。
3. 关闭时将该变量改为 `off`，再重建 `api`、`worker`。

## 字段与监控

- `REALTIME_FIELD_MAP` 字段映射全部未验证（U8）。
- 新鲜度监控可按 `market.quotes_snapshot` 最新 `ts` 对 `effective_stale_threshold_s` 判断，默认值为 `2×quote_interval_s`，待实现。

## 已知缺口（开启前必须先解决）

- `market.realtime_quotes_fetch` 经 jobs 单一队列由 worker 消费，而 worker 只接 `aia_internal`（internal: true），没有 `aia_egress`；按 2026-11-09 编排者裁定 worker 不开出网，只有 ingest 可出网。
- 因此仅把开关改为 `mairui` 无法连到麦蕊。需先裁定：任务改由 ingest（已有出网与单出口）执行，或另行审批给 worker 出网。本 PR 不改网络，也不改任务路由。

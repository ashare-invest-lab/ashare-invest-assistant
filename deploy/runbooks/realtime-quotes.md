# 实时行情采集接入

## 开关

- `REALTIME_QUOTES_SOURCE` 取值为 `off`、`fake`、`mairui`，默认值为 `off`。
- `fake` 仅允许 `APP_ENV=test`。
- `mairui` 开启即真实调用麦蕊，须用户本人或编排者按红线批准。本文不构成批准。

## 任务与调度

- 采集由 ingest 进程在心跳循环里按 `config/realtime.yaml` 的 `quote_interval_s` 门控执行，不经 Celery、beat 或 worker。
- 交易时段门控仍在采集函数内部执行，`MAIRUI_MODE=replay` 时不采集。
- 采集异常只记日志，不影响心跳。ingest 为单实例出口（`replicas=1`），多实例场景未验证。

## 开启前置条件

- 本人 active 证书。
- `single_egress` 单出口租约。
- STOP/HALT 语义已生效。存在即停，不重试。
- 开启=真调麦蕊，须批准，本文不构成批准。

## 开启与关闭

1. 修改 `.env` 中的 `REALTIME_QUOTES_SOURCE`。
2. 重建 `ingest`。若 api 读取开关用于展示，一并重建 `api`。
3. 关闭时将该变量改为 `off`，再重建 `ingest`。若 api 读取开关用于展示，一并重建 `api`。

## 字段与监控

- `REALTIME_FIELD_MAP` 字段映射全部未验证（U8）。
- 新鲜度监控可按 `market.quotes_snapshot` 最新 `ts` 对 `effective_stale_threshold_s` 判断，默认值为 `2×quote_interval_s`，待实现。

## 已知缺口（开启前必须先解决）

- 本说明依赖 #388（T-B221）合入，合入前不得开启。本文不改网络与任务路由。
- worker 侧旧任务名已不登记。

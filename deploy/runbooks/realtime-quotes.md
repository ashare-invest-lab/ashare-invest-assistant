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

1. 开启前确认前置条件全部满足，并取得批准。仅在用户本机的 `.env`（不是 `.env.example`）设置 `MAIRUI_MODE=live` 与 `REALTIME_QUOTES_SOURCE=mairui`。`DAILY_BARS_SOURCE` 保持 `off`，与本开关无关。
2. 用 live profile 重建 ingest：`AIA_PROFILE=live deploy/scripts/up.sh --no-deps ingest`。`up.sh` 默认带 `--build`，服务名选择和 `--no-deps` 可只重建指定服务。需要 api 展示时使用 `AIA_PROFILE=live deploy/scripts/up.sh --no-deps ingest api`。live 不叠加 dev 覆盖层。基础 compose 注释要求 live/生产使用 `SESSION_COOKIE_SECURE=true`，脚本未校验该值，应用启动是否拒绝未验证。
3. 普通 `restart` 不会重新读取环境变量，改 `.env` 后必须走上述重建路径。核对时只查看两个开关值，例如 `AIA_PROFILE=live deploy/scripts/compose.sh config | grep -E 'MAIRUI_MODE|REALTIME_QUOTES_SOURCE'`。
4. 关闭或回退时，在用户本机 `.env` 设置 `REALTIME_QUOTES_SOURCE=off` 与 `MAIRUI_MODE=replay`，回到默认 dev 路径重建 ingest 和 api：`AIA_PROFILE=dev deploy/scripts/up.sh --no-deps ingest api`。该路径叠加 `docker-compose.dev.yml`，会固定 ingest 为 replay。核对可用 `AIA_PROFILE=dev deploy/scripts/compose.sh config | grep -E 'MAIRUI_MODE|REALTIME_QUOTES_SOURCE'`，或对 ingest 容器执行只输出这两个变量名和值的 `env` 查询。

仓库内 compose 默认、dev 覆盖层、`.env.example` 与 CI workflow 按 #361 守卫保持 `MAIRUI_MODE=replay`、`DAILY_BARS_SOURCE=off`。切 live 只能改本机 `.env`，不得改仓库默认值或提交 `.env`。

## 字段与监控

- `REALTIME_FIELD_MAP` 字段映射全部未验证（U8）。
- 新鲜度监控可按 `market.quotes_snapshot` 最新 `ts` 对 `effective_stale_threshold_s` 判断，默认值为 `2×quote_interval_s`，待实现。

## 已知缺口（开启前必须先解决）

- 本说明依赖 #388（T-B221）合入，合入前不得开启。本文不改网络与任务路由。
- worker 侧旧任务名已不登记。

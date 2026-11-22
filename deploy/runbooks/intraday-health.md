# 盘中健康检查
## 启用
1. 确认 `INTRADAY_ENABLED=true`，再执行 `deploy/scripts/compose.sh --profile monitor up -d intraday-health`。
2. 检查状态可执行 `deploy/scripts/compose.sh --profile monitor ps intraday-health`。
3. 启用队列检查前须由编排者确认，该检查未验收，待 I4 定稿。
## 日志
容器内日志为 `/tmp/intraday-health.log`，状态文件为 `/tmp/intraday-health.state`。
可用 `deploy/scripts/compose.sh --profile monitor logs --tail 50 intraday-health` 查看输出。
## 告警含义
- `心跳缺失` 或 `心跳过期` 表示 Redis 不可达、心跳不存在、心跳格式无效，或心跳超过配置的过期秒数。
- `队列长期为0` 表示队列长度持续为零达到配置阈值。
- `非交易时段` 表示当前不在周一至周五的连续交易时段，节假日未判定。
- `行情过期` 表示行情时间戳距当前超过 `stale_threshold_s`，日志同时给出行情龄和阈值，返回 rc=2；`行情时间异常` 表示行情时间戳晚于检查时点，日志给出负的时间差秒数，返回 rc=2；`行情未接入` 表示来源已启用但 `INTRADAY_QUOTES_TS_KEY` 为空，返回 rc=2；`配置错误` 表示实时配置缺失或非法，返回 rc=2。
Redis 心跳键默认 `ingest:heartbeat`，值为包含整数 `ts` 的 JSON，与 API `/health` 同源，可用 `INTRADAY_HEARTBEAT_KEY` 或 `INGEST_HEARTBEAT_KEY` 覆盖。
脚本只接受非负 JSON 整数 `ts` 作为 Unix 秒。API 也接受负整数，脚本在这里有意采用更严格的非负 epoch 口径。
队列检查默认关闭，未验证，待 I4 定稿。设置 `INTRADAY_QUEUE_KEY` 启用前须由编排者确认，属未验收项。
实时行情来源由 `REALTIME_QUOTES_SOURCE` 控制，默认 `off`，关闭时日志说明“行情采集未启用”且不报警。
启用来源时从 `INTRADAY_QUOTES_TS_KEY` 读取 epoch 秒，空键表示“行情未接入”并报警；写入方待后端实现，未验证。来源为 `off` 时仍输出“行情采集未启用”且不报警。可用 `INTRADAY_TRADING_DAY_KEY` 传入 1/0，0 表示非交易日，空值沿用周一至周五口径。
`config/realtime.yaml` 以只读方式挂载，阈值取 `intervals.quote_interval_s` 和 `intervals.stale_threshold_s`，后者为 null 时取前者两倍；`INTRADAY_QUOTES_STALE_S` 可覆盖。

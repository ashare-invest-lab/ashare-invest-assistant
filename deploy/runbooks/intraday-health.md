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
Redis 心跳键默认 `ingest:heartbeat`，值为包含整数 `ts` 的 JSON，与 API `/health` 同源，可用 `INTRADAY_HEARTBEAT_KEY` 或 `INGEST_HEARTBEAT_KEY` 覆盖。
脚本只接受非负 JSON 整数 `ts` 作为 Unix 秒。API 也接受负整数，脚本在这里有意采用更严格的非负 epoch 口径。
队列检查默认关闭，未验证，待 I4 定稿。设置 `INTRADAY_QUEUE_KEY` 启用前须由编排者确认，属未验收项。

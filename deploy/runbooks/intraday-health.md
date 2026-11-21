# 盘中健康检查

## 启用

1. 确认 `INTRADAY_ENABLED=true`，再执行 `deploy/scripts/compose.sh --profile monitor up -d intraday-health`。
2. 检查状态可执行 `deploy/scripts/compose.sh --profile monitor ps intraday-health`。

## 日志

容器内日志为 `/tmp/intraday-health.log`，状态文件为 `/tmp/intraday-health.state`。
可用 `deploy/scripts/compose.sh --profile monitor logs --tail 50 intraday-health` 查看输出。

## 告警含义

- `心跳缺失` 或 `心跳过期` 表示 Redis 不可达、心跳不存在，或心跳超过配置的过期秒数。
- `队列长期为0` 表示队列长度持续为零达到配置阈值。
- `非交易时段` 表示当前不在周一至周五的连续交易时段，节假日未判定。

Redis 心跳键默认 `intraday:heartbeat`，队列键默认 `intraday:queue`，均未验证，待 I4 定稿，可用环境变量覆盖。

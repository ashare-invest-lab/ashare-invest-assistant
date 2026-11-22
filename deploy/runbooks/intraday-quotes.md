# 盘中行情运维

## 新鲜度检查

`deploy/scripts/quotes-freshness.sh` 只读查询 `market.quotes_snapshot`。未启用时直接返回未启用状态，不访问数据库。

```bash
QUOTES_FRESHNESS_ENABLED=true deploy/scripts/quotes-freshness.sh
QUOTES_FRESHNESS_ENABLED=true deploy/scripts/quotes-freshness.sh --from-dir /tmp/quotes-check --now 1704160800
```

离线目录可放置 `max_ts` 和 `is_open` 两个文件。缺少 `max_ts` 表示无数据，缺少 `is_open` 时按周一至周五推断并标注未验证。`--now` 使用 Unix 秒数，适合隔离测试。

退出码如下。

| 退出码 | 含义 |
| --- | --- |
| 0 | 未启用、非交易时段、休市或正常 |
| 2 | 无数据或已过期 |
| 4 | 参数、阈值、容器或只读查询配置错误 |

阈值唯一来自 `config/realtime.yaml` 的 `intervals.stale_threshold_s`。该值为 `null` 时使用 `2 × intervals.quote_interval_s`，当前结果为 30 秒。设置 `QUOTES_STALE_S` 会覆盖配置文件，且必须是正整数。交易时段按 `TZ=CST-8` 计算为 09:30–11:30 与 13:00–15:00。在线检查使用只读事务，容器可由 `AIA_PG_CONTAINER` 指定，否则取带有 postgres Compose 服务标签的首个运行容器。

只有 `quotes_snapshot` 写入方上线并经过独立验收后，才可以把 `QUOTES_FRESHNESS_ENABLED` 设为 `true`。`QUOTES_FRESHNESS_LOG` 若设置，会追加同一行状态记录。日志中不包含环境变量值或密钥。

## 资源采样

`deploy/scripts/resource-sample.sh` 使用 `docker stats --no-stream` 只读采样指定 Compose 项目，输出 CSV 并在采样结束后按容器打印 CPU 与内存百分比峰值。

```bash
deploy/scripts/resource-sample.sh --project aia --samples 5 --interval 60 --out /tmp/aia-resource.csv
COMPOSE_PROJECT=aia SAMPLES=2 INTERVAL_S=0 deploy/scripts/resource-sample.sh
```

`SAMPLES` 默认 5，`INTERVAL_S` 默认 60，`COMPOSE_PROJECT` 未设时取 `deploy/scripts/compose.sh --get COMPOSE_PROJECT_NAME`（与部署同一项目名）。`--samples`、`--interval`、`--project` 和 `--out` 可覆盖这些值，间隔可以为 0。测试时可用 `AIA_DOCKER` 注入隔离的假 Docker 命令。

CSV 的内存用量和限制取自 Docker 的 `MemUsage`，峰值汇总只反映实际采样值。先在目标主机实测多个正常交易日和负载场景，再结合 CPU、内存、PIDs 峰值及保留余量另行确定限额。采样结果未经验证，不直接写入或修改 Compose。限额确定后另单修改 Compose 并验收。

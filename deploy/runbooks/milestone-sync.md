# 里程碑同步预案（T-O131）

**本脚本默认真跑：会建容器、执行 `uv sync`，不是 dry-run。**

本单只提供预案和隔离演练，不在用户电脑执行同步，不连接用户电脑，不调用麦蕊。当前核对的引用是工作树中的 Git 对象，旧环境为 `2dbfdee`（迁移头 0036），主线为 `origin/main=ee76304b`（迁移头 0039）。

## 1. 迁移清单

复核命令如下，输出以 Git 为准。

```
git log --format=%h 2dbfdee..origin/main -- src/backend/migrations/versions/
```

该命令得到 `9585dd62`、`ce6d4b6a`、`61f03829`、`47959ceb`、`7d8e18a5`、`fc07f108`、`a0517ffe`。其中 0037、0038、0039 的最终文件和链路由下表按文件内 `revision`、`down_revision` 核对，0036 是旧环境已有头。

| 迁移文件 | revision / down_revision | 作用 | downgrade | TimescaleDB / 大表锁 |
| --- | --- | --- | --- | --- |
| `0036_tb143_ex_rights_minute_catalog.py` | 0036 / 0035 | 在 `market` 建权息事件表 `ex_rights_events` 和离线分钟文件目录 `minute_file_catalog`，含来源、路径、哈希和行数约束。 | 有。仅当两表为空才删表。 | 不涉及 TimescaleDB，普通表，没有显式大表锁。 |
| `0037_tb172b1_horizon_input_evidence.py` | 0037 / 0036 | 建 `app.horizon_input_versions`，加入版本、可见时间、依赖数组、哈希校验、索引及不可变触发器。 | 有。先对表取 `ACCESS EXCLUSIVE` 锁，非空即拒绝。 | 不涉及 TimescaleDB。明确有表级排他锁，耗时未验证。 |
| `0038_tb172b1b_horizon_completion_evidence.py` | 0038 / 0037 | 建 `app.horizon_completion_evidence`，加入完成证据、版本外键、哈希约束、验证触发器和不可变触发器。 | 有。先对表取 `ACCESS EXCLUSIVE` 锁，非空即拒绝。 | 不涉及 TimescaleDB。明确有表级排他锁，耗时未验证。 |
| `0039_intraday_ownership_i2.py` | 0039 / 0038 | 为 `quotes_snapshot`、`realtime_quotes`、`minute_bars`、`minute5_bars` 增加来源归属、行 UUID、revision、指纹和分钟终态字段，回填行身份并重建主键、检查约束和唯一索引。 | 有。压缩 chunk 存在或出现新归属数据、非零 revision、分钟终态时拒绝降级。 | 涉及 TimescaleDB 检查和三个 hypertable，修改主键、列和索引会产生锁，具体锁等待未验证。 |

0039 的升级前会检查压缩 chunk，但不会替运维解压，也不会改变压缩或保留策略。CI migrations job 只执行 Alembic 的 up/down/up，不先执行 `deploy/scripts/db-apply-timescale.sh`。

## 2. Compose 变更

核对命令如下。

```
git diff 2dbfdee origin/main -- deploy/compose/
```

差异只新增 `intraday-health` 服务。它使用固定 digest 的 `redis:7.4.12-alpine3.21`，加入 `monitor` profile，默认不启动，依赖 Redis 健康状态，使用只读根文件系统和 `/tmp` tmpfs。新增一个只读 bind mount `deploy/scripts/intraday-health.sh`，没有新增命名卷，也没有删除或重命名现有卷。新增环境变量见下一节。

## 3. 环境变量

对比 `deploy/env/.env.example` 与 `deploy/compose/docker-compose.yml`、`docker-compose.dev.yml` 的 `${VAR:-默认}` 后，主线新增且示例文件没有的变量如下。

| 变量 | Compose 默认值 | 用途 |
| --- | --- | --- |
| `AIA_FRONTEND_IMAGE` | `aia-frontend:local` | nginx 前端镜像。 |
| `MASTER_SNAPSHOT_PATH` | `/var/lib/aia-dev/master` | worker 主数据快照目录。 |
| `INTRADAY_ENABLED` | `false` | 盘中健康检查开关，默认关闭。 |
| `INTRADAY_HEARTBEAT_KEY` | `${INGEST_HEARTBEAT_KEY:-ingest:heartbeat}` | Redis 心跳键，未覆盖时使用嵌套默认值。 |
| `INTRADAY_QUEUE_KEY` | 空值 | 盘中队列键，默认不启用。 |
| `INTRADAY_STALE_AFTER_S` | `120` | 心跳过期秒数。 |
| `INTRADAY_QUEUE_ZERO_ALERT_S` | `900` | 队列无进展告警秒数。 |
| `INTRADAY_HEALTH_LOG` | `/tmp/intraday-health.log` | 检查日志路径。 |
| `INTRADAY_HEALTH_STATE` | `/tmp/intraday-health.state` | 检查状态路径。 |

会触发真实外部调用的开关必须保持安全默认值。现有 Compose 默认 `MAIRUI_MODE=replay`，开发叠加层也强制 replay。后端 `DAILY_BARS_SOURCE` 默认 `off`，本次重建前应显式核对为 `off`。`INTRADAY_ENABLED` 保持 `false`。SMTP 主机、用户、口令和发件人默认空值。若发现 `MAIRUI_MODE=live`、`DAILY_BARS_SOURCE=mairui` 或盘中开关被打开，停止本次同步并由用户本人另行批准。

### 待合入

`REALTIME_QUOTES_SOURCE` 默认 `off` 由 PR #378/#389 引入，当前 `origin/main=ee76304b` 尚未包含。不得在本次同步中把它写成已实现或已验收，也不得凭此开关放行实时外呼。

## 4. 执行步骤

以下命令由编排者和 DS 在用户电脑、用户本人批准的维护窗口执行。本单不执行。

1. 进入 `main-live` 工作树，先核对当前维护窗口。`/workspace/team/runtime` 取自 `restart-guard.sh` 默认值，`stack-busy-*.txt` 的文件名约定未验证。检查 `/workspace/team/runtime/stack-busy-*.txt`、`/workspace/team/runtime/mairui-backfill.lock` 以及 `/run/aia/state/halt/`。任一 busy 或 backfill 锁存在就停止。HALT 目录和其中的文件只读检查，不移动、不删除、不解除。
2. 写入维护标记并保留内容，例如 `/workspace/team/runtime/stack-busy-T-O131.txt`。记录操作者、开始时间、目标提交和预计结束时间。
3. 记录旧状态。至少保存 `git -C main-live rev-parse HEAD`、postgres 容器的镜像名和 digest、`SELECT version_num FROM public.alembic_version` 的结果。不要把口令写入记录。
4. 用仓库现有备份脚本执行逻辑备份。先取得 postgres 容器标识，再按脚本实际参数运行，示例为：
   ```bash
   PG_CONTAINER="$(deploy/scripts/compose.sh ps -q postgres)"
   deploy/scripts/db-backup.sh --db aia --out-dir /srv/aia-backups \
     --container "$PG_CONTAINER" --protect
   ```
   `/srv/aia-backups` 是示例路径，实际备份目录未验证。`db-backup.sh` 生成 `pg_dump -Fc`、同名 meta 文件并校验 TimescaleDB 版本。不要加 `--rotate`，不要删除旧备份。
5. 升级前校验备份可恢复，通过后才执行升级。先用 `pg_restore --list` 校验 dump，再恢复到本步骤创建的临时库，核对 0036 和虚构数据夹具后删除临时库。校验失败立即停止，不得执行升级。
6. 在 `main-live` 工作树中执行 `git checkout --detach ee76304b`，或 checkout 已核验的等价目标提交。禁止执行 worktree prune。记录 checkout 后的提交。
7. 按现有 `deploy/scripts/up.sh` 和 `deploy/scripts/compose.sh` 的方式重建。默认开发模式只用于回放验收，示例为：
   ```bash
   AIA_PROFILE=dev deploy/scripts/up.sh --build
   ```
   该流程按依赖顺序启动 postgres/redis，运行 migrate 服务的 `alembic upgrade head`，再运行 `timescale-apply` 和常驻服务。不要执行 `docker compose down -v`，不要改卷名，不要改 HALT。
8. 完成下一节验收。确认数据库为 0039、ingest 为 replay，四项冒烟和两个健康端点均达到预期。任一项失败都保留日志和旧备份，停止后续操作。
9. 全部验收通过后，确认无并发任务，再删除本次写入的 `stack-busy-T-O131.txt`。只删除本脚本或本步骤创建的标记。

## 5. 回滚

### A：代码回滚并降级

仅当演练已证明每个待降级迁移可用、业务表没有触发非空保护、且 0039 没有新归属数据时选择。先停写并记录原因。**必须在仍是目标提交（含 0037–0039 迁移文件）的代码上先降级**，旧提交 `2dbfdee` 不认识 0037–0039，不能用它降级：

```bash
deploy/scripts/compose.sh run --rm migrate alembic downgrade 0036
```

确认 `alembic_version=0036` 后，再在 `main-live` checkout `2dbfdee` 并按旧版本重建。

实际编排中应复用 migrate 服务使用的 `DATABASE_URL` 和后端镜像。若任一 downgrade 保护触发，立即停止，改走 B。

### B：备份恢复

库内有 0037/0038/0039 数据、0039 降级保护触发、升级中断或无法证明代码回滚安全时选择 B。使用已生成的 dump 和同版本 TimescaleDB 容器，按脚本实际参数恢复到新库名：

```bash
deploy/scripts/db-restore.sh /srv/aia-backups/aia-<UTC时间>.dump \
  --db aia_o131_restore --container "$PG_CONTAINER"
```

`db-restore.sh` 会拒绝覆盖容器的主库名，并在新库创建 TimescaleDB、执行 `timescaledb_pre_restore()`、串行 `pg_restore`、`timescaledb_post_restore()` 和 `ANALYZE`。核对恢复库的 0036 版本与业务数据后，再 checkout `2dbfdee` 并按旧版本 `up.sh` 重建。主库切换或重命名必须遵循现场数据库切换流程，由用户本人批准，不能用删除主库或删卷代替恢复。

## 6. 冒烟清单

本地入口是 `http://127.0.0.1:8080`。API 前缀和前端路由按当前仓库核对如下，需使用已授权的本地登录会话。

| 功能 | 检查 |
| --- | --- |
| 实时行情 | `GET /terminal`，并观察其 `GET /api/v1/terminal` 返回。独立行情缓存接口为 `GET /api/v1/quotes`。后端路由已核到，真实数据可用性仍需现场验证。 |
| 市场概览 | `GET /market/overview`，并观察 `GET /api/v1/market/overview`。后端和前端路由已核到。 |
| 禁投冷静期 | `GET /restrictions`。仓库当前是占位路由，功能验收未验证。 |
| 复盘页 | `GET /reviews`。仓库当前是占位路由，功能验收未验证。 |

另外必须核对：

- `GET /healthz` 返回 nginx 自答健康结果。
- `GET /api/v1/health/live` 返回后端存活结果。
- 数据库 `SELECT version_num FROM public.alembic_version` 等于 `0039`。
- ingest 环境中的 `MAIRUI_MODE=replay`，并核对 `DAILY_BARS_SOURCE=off`、`INTRADAY_ENABLED=false`。
- 不因当前时间已收盘而把旧盘中行当收盘价。日快照继续遵守已有 `FINAL_AFTER=17:10` 门槛，迁移验收不替代数据口径验收。

## 7. 演练记录

由运维在 box 隔离环境运行 `deploy/scripts/milestone-sync-drill.sh` 后填写。脚本默认 `--from 2dbfdee --to origin/main`，日志写入 `${DRILL_OUT:-/workspace/team/runtime/T-O131}/drill-<时间>.log`。

| 项目 | 耗时（秒） | 结果 | 备注 |
| --- | ---: | --- | --- |
| from 代码 upgrade head | 3 | 通过 | 空库+虚构数据 |
| 虚构数据写入与保留 | 0 | 通过 | 空库+虚构数据 |
| pg_dump -Fc | 0 | 通过 | 空库+虚构数据 |
| 备份可恢复性校验 | 0 | 通过 | `pg_restore --list`、临时库恢复后核对 0036 与虚构数据 |
| to 代码 upgrade head | 2 | 通过 | 空库+虚构数据 |
| 回滚 A：downgrade/upgrade | 1 | 通过 | 空库+虚构数据 |
| 回滚 B：新库 pg_restore | 2 | 通过 | 空库+虚构数据 |

2026-11-21 21:07 MST（box）：from=2dbfdee(0036) → to=origin/main ee76304b(0039)，全程约 12 秒（含容器启动），日志 `runtime/T-O131/drill-20261122T040717Z.log`。耗时基于空库+少量虚构数据，用户真实库（含 hypertable 数据）的 0039 回填与锁等待耗时未验证。

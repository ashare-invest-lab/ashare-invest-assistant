# 威胁模型

供 Codex 自动代码审查使用；入口以本地 `origin/main` 的 `git grep` 源码核实结果为准，未联网核对远端。

## 资产

- 本人麦蕊证书：按用户隔离，不借用他人证书；证书绑定及对应行情可见性也须按用户核验。
- 交易数据和交割单、股东代码：私有资产，不进入公开仓库、日志产物或外部模型。
- 行情库 `market.daily_bars`：保护来源、单位、收盘口径、时间可见性及写入完整性。

## 信任边界与入口

下列 `app/`、`probes/` 均相对 `src/backend/`；入口存在不表示门闩已实现。

| 边界 | 已核实入口 | 审查重点 |
| --- | --- | --- |
| HTTP API → 身份与私有数据 | `app/main.py`、`app/api/v1/__init__.py`；`imports.py` 的 `upload`、`confirm_import`；`data_licence.py` 的证书路由 | 身份、归属、上传内容及返回值不能跨用户泄漏 |
| ingest／任务 → 上游与数据库 | `app/workers/ingest.py` 的 `main`；`app/ingest/core.py` 的 `IngestCore`；`app/ingest/daily_bars.py` 的 `fetch_mairui_daily_bars`；`app/workers/jobs.py` 注册的 `daily_bars_fetch_task` | 本人证书、停止状态、来源与唯一写入口 |
| CLI／对账 → 文件与写库 | `app/cli/__main__.py` 注册 `daily-bars-import-tdx`、`intraday-bars-import-tdx`、`mairui-licence-bind`、`daily-bars-backfill`、`delete-user-data` | `tdx_import.py` 是模块；`app/ingest/tdx_local.py` 的 `reconcile` 是函数，未注册独立 reconcile CLI |
| probes／SQL → 绕过业务层 | `tb140_daily_bars.py` 的 `main`；`tb140_history_load.py` 的 `render_insert_sql`、`apply_daily_bars`；`tb140_history_backfill.py` 的 `run_batch`；`tb140_history_supervisor.py` 的 `run_supervised`；`tb143_load_day.sql`、`tb143_day_load_runner.ps1` | SQL 产物、持久化回调及新会话均不能绕过公共入口 |
| CI／合并队列 → 公开产物与主线 | `.github/workflows/ci.yml`、`.github/workflows/secret-scan.yml` | 只用虚构夹具；核对检查所针对的提交；`merge_group` 触发由 PR #184 引入（待合入），队列设置未验证 |

## 写库门闩

- 唯一允许的目标表写入口是 `app/marketdata/daily_bars.py` 的 `upsert_daily_bars`；所有来源、INSERT、UPDATE、跨源替换均须收口，不能直接 COPY 到目标表。
- 这是审查要求：主线仍有 probe／SQL 旁路，以及同文件内 `update_mairui_source_licence_id` 的独立 UPDATE；不得据函数所在文件宣称已收口。
- 依据：PR #182 的 `docs/T-A172` 分支 `docs/contracts/daily-bars-source.md` §10，尤其 §10.2、§10.10、§10.11，**契约待合入**。主线虽已有旧版 §10，尚无这些门闩条款。
- BJ 默认拦截。须在共同单日取得至少 20 个不同合法 BJ 代码的可信原始对照；两源同码同日，任一源停牌或零量均排除，排除后仍须足数。
- 原始麦蕊 v（手）×100 与 tdx 股量用 `Decimal` 精确相等；不得容差、舍入凑齐、重复计数或跨日拼接；证据来源和转换链须可追溯。
- 所有来源含 `tdx_local` 均须过门闩；原始手量仅转换一次，已为股的规范化量及 tdx 量不得再乘 100。
- Python 确认仅当前进程有效；SQL 确认仅当前会话有效，且仅供隔离测试／临时表验证，不能授权直接写目标表。最终仍经公共入口并在实际写入进程确认。
- 新进程／会话默认未确认，不从父进程、其他会话、持久文件或环境标志继承；每次确认失败立即清除旧放行，SQL 回滚也不得恢复旧放行。
- 规范化、只读、演练及合成证据不产生生产确认；收口与逐入口验收完成前不承诺 BJ 写入支持。技术确认不替代用户授权。

## 主要威胁与控制

| 威胁 | 对应控制 |
| --- | --- |
| 证书泄漏或越权 | 认证后校验用户归属；不借证书、不在异常、路径日志或报告输出证书；证书绑定／回滚同样检查归属和写库门闩 |
| 私有数据进入仓库或外部模型 | 仓库已公开；夹具仅用虚构数据；提交差异和 CI 产物检查敏感内容，不发送私有数据给外部模型 |
| 盘中价冒充收盘价、前视 | 按 `fetched_at` 与该行交易日北京时间 15:00 比较，盘中取得的行不能随当前时钟过收盘而变成收盘价；还须满足查询时点可见性。依据 `app/marketdata/quotes_read.py` 的 `_daily_closes`；日快照保留 `daily_snapshot.py` 的 `FINAL_AFTER` 17:10 更严格门槛 |
| BJ 量单位错误 | 可信原始 v 与 tdx 精确对照、共同单日至少 20 码、排除停牌零量；单位只转换一次；小样本或公开页自洽不能放行 |
| 写库旁路 | 检查直接 SQL、ORM、SQL 生成器、回调及子进程；统一经 `upsert_daily_bars`；隔离测试假数据须明确标注用途，不形成生产例外 |

## 硬红线

以下均必须由用户本人明确批准：真实调用麦蕊、生产部署、删除用户数据、对外发送、解除 HALT、恢复出网、`backfill --apply`（实际注册命令为 `daily-bars-backfill --apply`）。
契约、测试通过、CI 通过或技术门闩确认均不是上述操作的批准。

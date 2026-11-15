# 非完成版麦蕊日线行 → 完成版同源替换契约（T-A156）

## 1. 定位与结论

依 T-A155 Q3 与 T-A158 裁定②，采用「受控例外 + 审计」：仅为 `docs/contracts/multi-source-ingest.md` §4 增加非完成版 mairui → 完成版 mairui 这一条同源例外。后端实施归 **T-B151**；定稿并实施前仍 DO NOTHING。本单只写方案，不执行只读盘点、补取或生产写入。
最小实现是在 `src/backend/app/marketdata/daily_bars.py` 的 `upsert_daily_bars` 冲突分支增加与 C1 并列的分支，复用 sink、`UpsertStats.reconcile_after_transaction` 与文件纪律；不新增列、主键、迁移、表或进程。生产接线未完成时，两条例外均因 sink 为空而不替换。

## 2. 判定与禁止边界

| 项 | 契约 |
| --- | --- |
| 键与时区 | 主键 (code, trade_date, adj_type) 不变；时区 Asia/Shanghai；逐行以自己的 trade_date 判定，不能用运行日代替 |
| 完成版 | source 为 mairui，带时区的 fetched_at 不早于该行 trade_date 当天 17:10；等于边界亦为完成版 |
| 非完成版 | source 为 mairui，fetched_at 早于该行 trade_date 当天 17:10 |
| 时点出处 | `src/backend/app/marketdata/daily_snapshot.py` 的 `FINAL_AFTER` 为 17:10、`ANALYZE_AS_OF` 为 17:30；`docs/contracts/daily-snapshot-from-bars.md` §0、§2、§14.1 |
| 入参 | 已符合既有入库映射，source 为 mairui，fetched_at 达完成版下限且不早于实际收到数据的时刻（`docs/contracts/daily-bars-source.md` §8.4）；source_licence_id 取调用方当时的 licence_id，与 `src/backend/app/ingest/daily_bars.py` 的 `fetch_mairui_daily_bars` 一致；不继承旧证书或旧 fetched_at。本例外路径 licence_id 必填（通用 `upsert_daily_bars` 现允许空值，T-B151 不得在本分支放行空证书） |
| 差异 | OHLC 到分相等、量相等、额容差沿用 `docs/contracts/daily-bars-tdx.md` §5 与 `docs/contracts/multi-source-ingest.md` §4；差异只进对账，不作拒绝条件，不新增阈值 |
| 禁止 | 完成版被非完成版或另一完成版覆盖；mairui 覆盖 fake 或其他来源；本例外替换 tdx_local；tdx_local 进入 owned 快照。tdx_local → mairui 仍仅走 C1 |

由定义推导而非实测：一批在某自然日 17:10 前入库且 fetched_at 取实际取数时刻时，只有 trade_date 等于该自然日的键可能非完成；更早日期的历史行已晚于各自的 FINAL_AFTER。实际数量与分布均未验证。

## 3. 对账、条件更新与事务

| 顺序 | 必须行为 |
| --- | --- |
| ① 先落盘 | 按 `docs/contracts/daily-bars-tdx.md` §5 比对；差异逐字段写 jsonl，kind 为 `replaced_mairui_non_final`；比对字段均相同也写一行，field 为星号、kind 为 `replaced_mairui_non_final_same`。任何落盘失败均不发 UPDATE，异常抛至事务边界 |
| 对账字段 | 记录格式对齐 `src/backend/app/marketdata/daily_bars.py` 的 `_replacement_audit`：replacement_id、code、trade_date、adj_type、ts、field、existing_value、incoming_value、tolerance、kind；existing_source 与 incoming_source 均为 mairui；另记 existing_fetched_at、incoming_fetched_at（带时区）。现行辅助函数的来源与 kind 固定为 C1 且不带新旧 F，「全部相同」只覆盖 OHLC/量/额，T-B151 须扩展，不能原样复用 |
| ② 条件 UPDATE | WHERE 同时限定主键、source 仍为 mairui、fetched_at 仍早于该 trade_date 当天的 FINAL_AFTER；必须保留此旧版本条件，防止并发覆盖完成版。Q2 另推荐要求 fetched_at 等于对账时读到的旧值，待裁定，不冒充现行 C1 条件 |
| 更新内容 | SET 整行取麦蕊入参，含 OHLC、量额、pre_close、is_suspended、source（仍为 mairui）、source_licence_id、fetched_at。影响 0 行时立即写 `replace_result`，value 为 skipped，不替换 |
| ③ 事务结果 | upsert 不提交事务；事务拥有者在 commit 成功或 rollback 后调用 `UpsertStats.reconcile_after_transaction`，按 replacement_id 追加 `replace_result`，value 为 committed 或 rolled_back；skipped 不得再改写为 committed。没有 committed 结果行视为未替换（审计口径，不代表数据库一定未变） |
| ④ 计数 | UPDATE 命中计 `UpsertStats.replaced`，不计 conflicts，不产生 daily_bar_conflict issue；命中 0 行不计 replaced。该计数在提交前仅为暂记，最终以事务结果行结算 |
| 失败回滚 | 同一调用全部批次属于调用方同一事务；任一批失败整体回滚，已 UPDATE 的键恢复旧非完成版行，结果写 rolled_back，不逐批提交，不发明重试次数 |

R5 验收目标：部分批次失败不得留下「对账已写 committed 但库未改」或「库已改但对账无结果行」。现有接口对后者尚有提交后写文件失败、进程中断，以及异常时 upsert 无返回值的缺口，见 §9 Q5，不能声称现有接口已保证原子性。

## 4. 审计路径（复用裁定③）

依据 T-B143 评审裁定③；与 C1 共用根与文件模板，以 kind 区分，不另造模板（Q4 待确认）。

| 项 | 纪律 |
| --- | --- |
| 常驻配置 | 名称未验证，暂定 `MARKETDATA_AUDIT_DIR`；运维写部署机本地 env，不写代码常量或 compose 默认值；默认位置无；建议 `F:\ashare-invest-assistant\data\audit`，未验证，本单不访问 |
| 前置检查 | 启动或首笔替换前检查可写；未配置或不可写视为 sink 为空，记 issue、不走例外、维持 DO NOTHING；启用后提交前写失败则抛异常并回滚，不能吞异常降级；提交后失败见 §10 |
| 文件 | `<审计根>/mairui-day-replace-<北京交易日 YYYYMMDD>-<run_id>.jsonl`；按运行及北京交易日分文件，run_id 不含冒号或路径分隔符 |
| 持久化 | UTF-8 无 BOM，一行一个 JSON，每行 flush + fsync，失败抛到事务边界；不经过日志脱敏；事务结束后追加结果，最后一行汇总各 kind 与结果计数 |
| 路径隔离 | CLI 仍用 `--audit-dir`；必填、可写、不得在数据根之下的纪律参照 `src/backend/app/ingest/tdx_local.py` 的 `check_audit_dir`；该函数仅作对照，不代表常驻接线已完成 |
| 运行记录 | pipeline_runs 只存相对文件名和计数，不存宿主绝对路径；不得借用 AIA_IMPORTS_DIR、MASTER_SNAPSHOT_PATH 或 Docker 日志 |

## 5. 触发与本人批准关口

| 路径 | 范围与关口 |
| --- | --- |
| 机制路径 | T-B151 可离线实现：已拿到完成版入参，同键已有非完成版行且显式提供持久化 sink 时走 §3。17:15 例行真调若已获用户授权，其入参来自该次调用，不构成额外补取；自动启用待 Q1 裁定 |
| 补取路径 | 专门再调麦蕊属于真调，须用户本人批准；范围仅只读盘点确认的非完成版键。遇 STOP、101、103、429、503 立即停且不重试，既有 HALT 闸不放宽；先取得合格入参、完成对账，再条件 UPDATE，成功提交前不得宣称已写库 |
| 本人批准事项 | 开启本地栈日常真调（daily_bars_source 从 off 改为 mairui）、专门补取及其范围/批次上限、backfill --apply、生产部署；本契约不替代任何批准，也不放宽 `docs/contracts/daily-bars-source.md` §8–§9 的回执、预算与停机规则 |

## 6. 快照、C1 与北交所边界

替换提交后按 `docs/contracts/daily-snapshot-from-bars.md` §14.1 的历史 mairui / C1 替换后规则，用新 fetched_at 计算 is_final 与入选，不继承旧 F；仍须当前 active 证书绑定与当日行就绪。历史 F 不晚于快照日 17:30，当日 F 仍在 17:10–17:30；不补建、重跑或放宽 as_of。代码依据为 `src/backend/app/marketdata/daily_snapshot.py` 的 `_bar_item`、`_include_historical`、`build_owned_snapshot`。
`docs/contracts/daily-bars-tdx.md` §4 的 tdx_local 隔离与 `docs/contracts/multi-source-ingest.md` §4、§5 的 C1 均不改。本例外落地前 `docs/contracts/daily-snapshot-from-bars.md` §14.1 所述「旧非完成版永不被覆盖、后续缺有效 K」仍有效；无 sink、入参非完成版或未批准专门补取时保持原行为（未批准补取不发请求）。
北交所路由与成交量单位归 T-A157 / T-B149；仅引用**分支 docs/T-A157 的 `docs/contracts/daily-bars-source.md` §10**（main 尚无 §10），不复制正文、不重开裁定。本替换仅接收已符合既有入库映射的入参，不改路由与单位口径。

## 7. 离线测试要求

全部用合成代码 A、B 与虚构开市日 D0 < D1 < D2，不使用真实行情；表内为前提（G）/ 操作（W）/ 断言（T）。

| 用例名 | G / W / T |
| --- | --- |
| `test_non_final_replaced_by_final_when_sink_present` | 旧非完成版、完成版入参、持久化 sink / upsert 后提交并对账 / 先落盘后 UPDATE，新 F 与 licence_id 生效，计 replaced、不计 conflicts；差异与全部相同两组均有明细与 committed |
| `test_non_final_replace_skipped_when_audit_root_unset` | 未设审计根、不可写、sink 空三组 / 同键 upsert / DO NOTHING，旧 F 不变，配置问题记 issue |
| `test_non_final_replace_where_requires_old_fetched_at` | 对账后并发把旧行改为完成版 / 条件 UPDATE / 影响 0 行、结果 skipped，不改完成版；Q2 通过后再测旧 F 改变但仍非完成版亦 skipped |
| `test_non_final_replace_rollback_restores_old_row` | 已落盘并 UPDATE / 调用方回滚 / 旧非完成版恢复，结果 rolled_back，无 committed |
| `test_final_not_overwritten_by_later_final_or_non_final` | 已有完成版 / 后到完成版或非完成版 upsert / 两组均不改旧行与 F |
| `test_same_source_replace_does_not_touch_tdx_local` | 已有 tdx_local / 经过本例外判定 / 不进入同源路径；另组显式启用 C1 时仍只走 C1，审计 kind 不混用 |
| `test_snapshot_uses_new_fetched_at_after_same_source_replace` | D0 非完成版在 D1 17:30 后替换提交，各快照日当日行合格且绑定证书 / 分别以 D1、D2 构建 / D1 不含 D0，D2 含 D0 且 is_final 为真；对照 `docs/contracts/daily-snapshot-from-bars.md` §14.3 的 `test_tdx_excluded_then_c1_visible_next_snapshot` |
| `test_non_final_history_not_effective` | 未启用例外的既有夹具 / 原 upsert、快照及求值 / 保留 `docs/contracts/daily-snapshot-from-bars.md` §14.3 原断言，旧 F 不变且缺有效 K；不替换成启用路径用例 |
| `test_non_final_replace_audit_failure_prevents_update` | sink 在明细 flush 或 fsync 失败 / upsert / 不发 UPDATE，异常上抛，事务回滚 |
| `test_non_final_replace_partial_batch_failure_audited` | 前批已 UPDATE、后批抛错 / 整体回滚 / 旧行全部保留，已尝试替换的结果可追踪为 rolled_back，无 committed；异常上下文如何保留须解决文末异议 |
| `test_non_final_replace_post_commit_audit_failure_not_success` | 数据库已提交、结果追加失败 / 事务后对账 / 异常不得吞掉，不报完整成功或伪造 rolled_back；恢复方案未裁定前不得据此启用生产 |
| 零外呼约束 | 全部用例 / 沿用 `docs/contracts/daily-bars-source.md` §7 补4 的 socket 与 mairui_get 探针及 `docs/contracts/daily-snapshot-from-bars.md` §10 J10 / 麦蕊调用 0 次，快照函数仍不进任务表 |

## 8. 只读统计方案与未验证

先只读盘点，再定稿启用范围。本单及 T-B151 **不执行 SQL**；另有只读盘点单且先核实例与端口归属后，才可用只读账号、只读事务执行。只输出聚合计数与分组标签、最早/最晚日期，禁止 SELECT 行情字段；C 可保留代码分布，不得把真实行情发给外部模型。
每条查询独立使用此前缀：`WITH s AS (SELECT code, trade_date, source, fetched_at < ((trade_date + TIME '17:10') AT TIME ZONE 'Asia/Shanghai') AS non_final FROM market.daily_bars)`；将其与下表对应语句拼接。只读事务以 `BEGIN READ ONLY;` 开始，以 `ROLLBACK;` 结束，不生成明细行情或写库。

| 查询 | 聚合语句 |
| --- | --- |
| A 非完成版总览 | `SELECT count(*), count(DISTINCT trade_date), count(DISTINCT code), min(trade_date), max(trade_date) FROM s WHERE source = 'mairui' AND non_final;` |
| B 按日期 | `SELECT trade_date, count(*), count(DISTINCT code) FROM s WHERE source = 'mairui' AND non_final GROUP BY trade_date ORDER BY trade_date;` |
| C 按标的 | `SELECT code, count(*), count(DISTINCT trade_date) FROM s WHERE source = 'mairui' AND non_final GROUP BY code ORDER BY code;` |
| D 全集对照 | `SELECT count(*) FILTER (WHERE source = 'mairui' AND NOT non_final) AS mairui_final, count(*) FILTER (WHERE source = 'mairui' AND non_final) AS mairui_non_final, count(*) FILTER (WHERE source = 'tdx_local') AS tdx_local, count(*) FILTER (WHERE source IS NULL OR source NOT IN ('mairui', 'tdx_local')) AS other_source FROM s;` |

未执行原因（转引本单任务背景，未在此复测）：架构师已检查 box 监听端口与容器，未发现 PostgreSQL 实例、数据库容器或 DATABASE/PG 环境；用户库存于用户电脑，团队规则禁止本角色触碰用户电脑及 F:\，不得自建库凑数。本次未读写 .env 或密钥。
**未验证清单**：非完成版总行数、日期/标的分布及全部来源计数；MARKETDATA_AUDIT_DIR 名称与建议路径；生产 jsonl sink 与事务后对账接线；补取批次上限与真实范围。无出处参数均未验证、无默认生效值；代码核对只证明现状，不等于生产验证。

## 9. 待编排者裁定

| 项 | 推荐与未裁定时边界 |
| --- | --- |
| Q1 已授权 17:15 真调且配置审计根时，自动替换当日非完成版键？ | 推荐是，入参来自已授权例行调用，并非额外补取；裁定及实施前不自动启用 |
| Q2 WHERE 除来源与非完成版下限，是否要求 F 等于对账读到的旧 F？ | 推荐要，提供更严的丢失更新保护；C1 未比旧 F，本建议不冒充既有实现 |
| Q3 补取范围与批次上限？ | 推荐仅只读统计确认的非完成版键；批次上限未验证，不编造、不借用其他批型额度，用户批准时再定，遇限流即停 |
| Q4 审计模板共用还是另起？ | 推荐共用裁定③模板，以 kind 区分；正文按该推荐起草，不新增默认路径 |
| Q5 提交后对账追加失败如何恢复？ | 推荐：异常不得吞掉、不得报完整成功或伪造 rolled_back；以库为准只读核对并补记结果行，不自动再 UPDATE。具体步骤由 T-B151 写出，生产启用前再裁；未裁定前不得据此启用生产 |

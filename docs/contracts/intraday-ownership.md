# 盘中行情归属键与迁移设计契约（I2-C，T-A211）

状态：拟定契约，未实现。本文只定义 I2 的存储适配、读侧边界和迁移设计，不生成迁移文件，不改变生产表。基线事实来自 `/workspace/team/reports/T-A211.md §2「I2 归属键迁移和存储适配」与 §4 I2-C/I2`、`/workspace/team/reports/T-A209.md §0.2`、`docs/contracts/T-B195-intraday-field-evidence.md §U8 逐项清单`、`src/backend/app/db/tables/market.py:quotes_snapshot/realtime_quotes/minute_bars/minute5_bars` 和 `src/backend/migrations/versions/0034_tb133_minute_bars_sources.py:upgrade`。供应商字段、单位、修订令牌和端点归属仍属 U8，标为“未验证”的内容不能作为生产事实。

## 1. 四表归属列

归属是行级事实。`source` 标识来源或来源通道，`source_licence_id` 标识实际取数所用的本人证书，二者不能从代码、请求人或库存反推。`ts` 是行情观察时点，`fetched_at` 是本次采集完成时点，均为带时区的时间戳。查询必须同时约束行情时点和知识时点。

| 表 | `source` | `source_licence_id` | `ts` | `fetched_at` |
| --- | --- | --- | --- | --- |
| `market.quotes_snapshot` | 现表没有此列。目标列可空以保留旧行，新写入的 `mairui` 行必须有来源；目标端点映射未验证。 | 目标列 UUID，可空。旧行和无可证明证书的行保持 NULL。本人可读的 `mairui` 行必须非空。 | 非空，快照对应的行情时点，不得以请求时间代替。 | 现为非空，继续非空，记录采集完成的实际时刻。 |
| `market.realtime_quotes` | 现列可空，保留 `ssjy_more`、`ssjy_all`、`real_all` 这些现有通道标签。标签与供应商字段的精确对应未验证。新写入按下表的来源关系校验。 | UUID，可空以保留旧行。本人可读的许可来源行必须绑定当前本人证书。 | 非空，实时报价的观察时点，不等同于 `fetched_at`。 | 现为非空，继续非空。 |
| `market.minute_bars` | 现列可空。新写入只允许 `mairui` 或 `tdx_local`，旧 `pro_latest`、`pro_history` 仅作兼容。`tdx_local` 不绑定本人证书。 | UUID，可空。`mairui` 本人行必须非空，`tdx_local` 和旧无归属行保持 NULL。 | 非空，1m bar 结束时刻，例 `09:31` 表示 `09:30–09:31`。 | 现为非空，继续非空，不能写行情时点。 |
| `market.minute5_bars` | 现列可空。新写入遵循分钟来源规则，既有 .lc5 历史和日后聚合的来源标签保持可追溯。 | UUID，可空。`mairui` 本人行必须非空，离线 `tdx_local` 行为 NULL。 | 非空，5m bar 结束时刻，例 `09:35` 表示 `09:30–09:35`。 | 现为非空，继续非空。 |

目标语义允许数据库列为可空，因为公开仓库必须保留旧数据。新写入的 `source`、来源与证书关系、`ts`、`fetched_at` 必须满足上述不变量。`volume`、`amount` 的未知值继续为 NULL，不以零替代。依据为 `src/backend/app/db/tables/market.py:quotes_snapshot`、`:realtime_quotes`、`:minute_bars`、`:minute5_bars`，以及 `docs/contracts/intraday-bars.md §1.1、§1.3、§2.2`。

### 1.1 来源与证书关系

以下关系是四表写适配器和 CHECK 的共同口径。表的 source CHECK 仍决定该表实际允许哪些来源，未列入该表 CHECK 的来源一律拒绝。

| 来源类别 | `source` | `source_licence_id` | owner 读 | 说明 |
| --- | --- | --- | --- | --- |
| 许可在线来源 | `mairui` | 必须为本次取数所用的本人证书 UUID | 走 active owner 证书精确匹配 | 证书不存在、已删除、非 active 或不属于 owner 均拒绝写入或读取。 |
| 本地离线来源 | `tdx_local` | **必须为 NULL** | **不走 owner 读** | 只允许隔离的文件层/研究复测读，不能进入本人行情、today 或日报。 |
| 旧兼容来源 | `pro_latest`、`pro_history`、既有 realtime 通道标签 `ssjy_more`、`ssjy_all`、`real_all` | 保留旧值，既有无证书行应为 NULL；不得新写 | 不走 owner 读 | 仅用于迁移和审计，不能借兼容标签取得 owner 归属。 |
| 旧无来源行 | `source IS NULL` | 必须为 NULL | 不走 owner 读 | 归类为 `legacy_unowned`，不与新的 `tdx_local` 来源行混为同一唯一键。 |

因此，“NULL-licence 旧行对 owner 读不可见”继续成立：`tdx_local` 的 NULL 是明确的离线来源语义，旧行的 NULL 是缺少可证明来源的遗留语义；两者都不代表 owner。隔离复测读按明确的 `source=tdx_local` 和隔离数据集授权读取，不能调用 owner 读谓词，也不能把该结果写入 owner 视图。适配器规则为 `mairui → licence_id IS NOT NULL`、`tdx_local/pro_*/ssjy_* → licence_id IS NULL`、`source IS NULL → licence_id IS NULL`；其余组合拒绝。

证书只作归属键，不进入公开响应。读请求先按 owner 找当前 active 证书，再用证书 UUID 精确筛行。此口径沿用 `src/backend/app/ingest/intents.py:readable_by`、`src/backend/app/marketdata/daily_snapshot.py:active_licence_id` 和 `docs/contracts/daily-snapshot-from-bars.md §14.1、§14.3`。

## 2. 唯一键、幂等和迟到修订

### 2.1 目标键形状

现有 `(code, ts)` 主键不能承载两个证书的同一分钟，`0034` 也没有改变这一点。目标迁移为每表增加内部 `row_id`，并增加 `revision`。`row_id` 只作物理行身份，不能作归属或可见性证据。`revision=0` 用于迁移保留的旧行，新的归属行由存储适配器分配非负递增版本。

- 普通表 `quotes_snapshot` 使用 `row_id` 主键。
- TimescaleDB 超表 `realtime_quotes`、`minute_bars`、`minute5_bars` 使用包含时间列的物理主键 `(ts, row_id)`。这满足 `src/backend/app/db/tables/market.py:module docstring` 和 `src/backend/migrations/versions/0001_baseline.py:upgrade` 对超表唯一键的约束。
- 许可行建立部分唯一键 `(code, ts, source, source_licence_id, revision)`，谓词为 `source_licence_id IS NOT NULL`。
- 离线及既有兼容来源行建立 `(code, ts, source, revision)`，谓词为 `source_licence_id IS NULL AND source IN ('tdx_local','pro_latest','pro_history','ssjy_more','ssjy_all','real_all')`。旧 `source IS NULL` 行另建 `(code, ts)`，谓词为 `source IS NULL AND source_licence_id IS NULL`，避免把旧行与 `tdx_local` 行混入同一 NULL 键。
- 超表上的上述部分唯一键都必须包含 `ts`。索引、chunk、压缩和保留配置沿 `deploy/db/timescale/sql/10-hypertable.sql:hypertable 参数`、`deploy/db/timescale/policies.conf:hypertable 策略`，本契约不调整现有保留策略。

`source_licence_id` 非空而 `source` 为空，或 `mairui` 缺少许可来源，均拒绝写入。`tdx_local`/兼容 `pro_*`、`ssjy_*` 缺少许可来源是必需语义，不得伪造证书。旧行不回填虚构的来源或证书。

### 2.2 内容指纹和回放

内容指纹只覆盖不可变行情内容，不覆盖 `fetched_at`、`revision`、`row_id` 或证书。按表取字段：`quotes_snapshot` 为 `price,pct_change,payload`；`realtime_quotes` 为 `price,open,high,low,pre_close,volume,amount,pct_change`；分钟表为 `open,high,low,close,volume,amount,is_final`。缺列按 `null`，字段名按 ASCII 升序；Decimal 以无指数的规范十进制字符串表示，去掉多余前导/尾随零，负零归零；时间统一为带时区 UTC 的 ISO-8601 字符串；JSON 对象键递归排序、数组保序、无空格；布尔值和 null 使用 JSON 标准字面量。将规范化对象以 UTF-8 编码后计算小写十六进制 `SHA-256`，得到 `content_fingerprint`。

同一归属作用域 `K=(table, code, ts, source, source_licence_id)` 下，对 `(K, content_fingerprint)` 建立部分唯一键。新写入的 `content_fingerprint` 必须非空；迁移保留的旧行可为 NULL，不能据此声称旧行已完成指纹化。许可行索引谓词为 `source_licence_id IS NOT NULL`，离线/兼容行索引谓词为 `source_licence_id IS NULL AND source IN ('tdx_local','pro_latest','pro_history','ssjy_more','ssjy_all','real_all')`。同一指纹重放返回既有行，不增加行数或 revision。不同指纹保留旧行并生成新 revision，冲突审计至少记录 `table,K,old_fingerprint,new_fingerprint,observed_at`，不覆盖旧内容。供应商是否提供可直接使用的修订令牌未验证，未验证前不得把供应商字段当作 `revision` 或指纹。

### 2.3 revision 分配与并发

写适配器在一个数据库事务内执行以下伪代码。锁粒度是单表单 `K` 的事务锁，不锁整表：

```text
payload = normalize(table, input)
fp = sha256(canonical_json(payload))
for attempt in 1..3:
    begin
    pg_advisory_xact_lock(first_64_bits(sha256(encode(K))))
    row = SELECT ... WHERE K AND content_fingerprint = fp FOR UPDATE
    if row exists: commit; return row                 # 幂等重放
    next = COALESCE(MAX(revision), -1) + 1            # 同一 K 内
    INSERT (..., revision=next, content_fingerprint=fp)
    try commit; return inserted_row
    except unique_violation on revision/fingerprint:
        rollback to savepoint; continue               # 重新读，不猜 revision
raise INTRADAY_REVISION_RETRY_EXHAUSTED              # 零部分提交
```

`K` 中 NULL 证书按来源类别分开使用上述部分索引，不能用普通含 NULL 的复合唯一键代替。唯一键冲突后必须重读指纹和 `MAX(revision)`，最多 3 次；第三次仍冲突返回内部错误码 `INTRADAY_REVISION_RETRY_EXHAUSTED`，调用方保持闸关闭并记录冲突审计。指纹命中即使 `fetched_at` 不同也不增 revision；只有内容字段变化才生成更高 revision。

迟到修订写入新版本并保留旧版本。分钟表的 `is_final` 是新增的可空兼容列，旧行 NULL 永不进入本人读侧，新行必须显式给出布尔值。1m 或 5m 行只有 `is_final=true` 才可见。已经完成的行收到更正时新增更高 `revision`，不原地改写旧版本。读侧在 `fetched_at <= as_of` 的可见版本中选最高 `revision`，再按 `is_final` 和字段完整性作公共投影。`is_final` 的供应商语义未验证，系统只把它当作本地完成判据。

## 3. 旧无归属行

- `source IS NULL AND source_licence_id IS NULL` 的行统一视为 `legacy_unowned`。`tdx_local` 的 NULL 证书是 `offline_unowned`，二者均不代表当前用户、当前证书或全局共享许可。
- 迁移只登记各表旧行数量、按 `(code, ts)` 的冲突统计和来源分布，不自动补证书、不改变 `fetched_at`、不删除。
- 本人读侧的谓词必须包含当前 owner 的 active `source_licence_id`，所以旧行、被删除证书行和他人证书行都不可冒领。
- 旧行可由隔离维护查询保留，不能进入 `/quotes`、`today_bars`、`/securities/{code}/bars` 或本人日报。`tdx_local` 行按 `offline_unowned` 规则隔离处理。

依据为 `docs/contracts/daily-snapshot-from-bars.md §2、§14.1` 的无绑定行处理，`src/backend/app/marketdata/quotes_read.py:_daily_closes` 的本人证书过滤，以及 `src/backend/app/aggregates/t_view.py:today_bars` 当前只按 `source` 读取的待修正现状。

## 4. 读侧知识截止

读函数接收显式 `as_of`，并按以下顺序筛选。

1. 证书必须是该 owner 当前可用的 active 证书，精确匹配 `source_licence_id`。不允许跨证书 fallback。
2. `fetched_at <= as_of`，并且 `ts <= as_of`。比较带时区的实际时刻，不用“现在已经收盘”放行未来采集行。
3. 同一归属键选最高可见 `revision`。分钟表还要求 `is_final=true`，未完成 1m 不可见。
4. `volume` 或 `amount` 缺失时返回 NULL 或公共层的缺数状态。不得转成零、拼接旧日线、插值或计算 VWAP。
5. `tdx_local`、`offline_unowned` 和 `legacy_unowned` 不进入本人盘中数据、today 或日报。研究复测可在明确隔离的文件层读取 `tdx_local`，并保留原始 `source`，不改变 owner 读规则。

`src/backend/app/marketdata/quotes_read.py:read_quotes` 目前只有日 K 回退，`src/backend/app/aggregates/t_view.py:today_bars` 目前把空量额转零，这两处均不构成契约已实现证据。日 K 回退仍须遵守 `src/backend/app/marketdata/quotes_read.py:_daily_closes` 的本人证书、北京时间收盘时点和 `fetched_at <= now` 规则。1m 的完成和缺字段边界沿 `docs/contracts/T-B195-intraday-field-evidence.md:U8 逐项清单`，未验证字段保持 NULL。

## 5. 迁移设计

迁移文件由后续 I2 实现单编写。本节规定执行顺序和失败语义。

1. **停写与盘点**。保持 `Settings.intraday_enabled=false`，停止盘中写入入口。记录四表 schema、是否 hypertable、chunk、索引、旧行数、NULL 证书行数和 `(code, ts)` 冲突统计。不得读取 `.env`、密钥或真实供应商数据。
2. **dry-run**。只读检查列、约束、超表维度和目标部分唯一键是否可建立，输出预计受影响行数和失败原因。dry-run 不加列、不改主键、不写标记、不建生产索引。
3. **扩展列**。按 §1、§2 增加 `source`、`source_licence_id`、`row_id`、`revision`、`content_fingerprint`，分钟表增加 `is_final`。先以可空兼容旧数据，回填 `row_id` 和 `revision=0`，旧行不伪造指纹、来源或证书。`quotes_snapshot` 的 `source` 也不从 payload 猜测。
4. **切换键**。在同一维护窗口内核验旧行计数，建立 `(ts,row_id)` 或 `row_id` 主键、revision 部分唯一键和内容指纹部分唯一键。超表必须先确认没有压缩 chunk 阻止索引或约束变更。既有 `0034` 的 source CHECK、`minute5_bars` 建表和 downgrade 保护继续有效。
5. **读写闸接线**。只有 schema、索引、旧行统计和离线回放全部通过后，后续实现单才允许在默认关闭的闸下接入新写入与读侧。打开 `intraday_enabled` 不等于获得真实麦蕊调用授权。
6. **提交后核验**。比较迁移前后行数、每表 NULL 证书数、唯一键冲突数和随机合成回放结果。任何计数异常都保持闸关闭，禁止用删除旧行或放宽断言收口。

TimescaleDB 约束来自 `src/backend/migrations/versions/0001_baseline.py:upgrade`、`src/backend/migrations/versions/0034_tb133_minute_bars_sources.py:upgrade` 和 `deploy/db/timescale/sql/10-hypertable.sql:hypertable 参数`。`market.realtime_quotes`、`market.minute_bars`、`market.minute5_bars` 的主键与唯一索引都必须含 `ts`，`quotes_snapshot` 是普通表。压缩和保留 job 沿 `deploy/db/timescale/policies.conf:hypertable 策略`，迁移不得顺便改变清理周期。

### 5.1 回滚和失败

- 每个可事务化阶段失败时回滚该事务，恢复原主键、索引和列状态。失败结果写入迁移审计，`intraday_enabled` 保持 false。
- 超表 DDL 或索引阶段若已提交部分变更，立即停写，不切读侧，不删除数据。先重新 dry-run，按实际 schema 做幂等修复。不得把未完成迁移宣称成功。
- 只有在“迁移后没有任何新归属行、没有 `revision>0` 行、没有新 `is_final` 值”的条件同时满足时，才允许执行反向 DDL。若已产生新行，回滚目标是保留数据并修复 schema，不能通过删除新行恢复旧状态。
- `0034` 的 `downgrade` 已在 `src/backend/migrations/versions/0034_tb133_minute_bars_sources.py:downgrade` 对有来源行或非空 `minute5_bars` 拒绝。I2 设计沿用这一原则，并扩大到四表的新归属行。

## 6. I2 离线验收清单

测试只使用虚构代码、虚构 UUID 和隔离测试库，不能作为生产旁路或 BJ 证据。实现单应至少覆盖以下项目。

- **双证书同分钟**。四表各插入同码同 `ts`、同来源、两个虚构证书的行，均保留两行，互不覆盖。本人读取只返回自己的证书行。
- **来源证书关系**。虚构 `mairui` 行缺证书必须拒绝；虚构 `tdx_local` 行证书必须为 NULL、隔离复测可读且 owner 读不可见；旧 `source IS NULL` 行仍不可见，且不与 tdx_local 冲突。
- **旧行隔离**。四表各有 `source IS NULL AND source_licence_id IS NULL` 的旧行。任一 owner 读取均不可见，迁移和回放后仍保留。
- **未来采集时点**。行的 `ts` 不晚于 `as_of`，但 `fetched_at` 晚于 `as_of`。读取排除该行。反向组合也必须排除未来 `ts`。
- **未完成 1m**。`is_final=false` 或 NULL 的分钟行不可见，完成版以更高 `revision` 到达后才可见。
- **未知量额**。`volume` 或 `amount` 为 NULL 时读侧保持 NULL，指标进入缺数状态，不变成零。
- **迁移失败回滚**。在加列、换键、建索引和核验阶段分别注入失败，断言闸关闭、原数据仍在、失败阶段不留下可读的半成品归属行。
- **重复回放与并发**。同一规范化负载、同一证书或 `tdx_local`、同一 `code/ts` 重放多次，行数不增加，版本不跳号。不同负载生成新 `revision`，旧版本保留；并发写入遇唯一冲突时重读，三次内成功或返回 `INTRADAY_REVISION_RETRY_EXHAUSTED`。
- **查询时点**。同一数据分别以两个 `as_of` 读取，后到修订只在其 `fetched_at` 已进入的查询中可见。
- **读侧旁路**。`today_bars`、报价读取和分钟读取均不跨证书、不读取 NULL 证书行，不触发外呼，不写 `market.daily_bars`。

建议用例名为 `test_intraday_ownership_two_licences_same_minute`、`test_intraday_legacy_rows_are_isolated`、`test_intraday_future_fetched_at_is_hidden`、`test_intraday_migration_failure_rolls_back` 和 `test_intraday_replay_is_idempotent`。用例名是 I2 实现建议，未表示仓库已有测试。

## 7. U9 与正式开关

本契约给出 U9 的拟定归属键和迁移方案。U9 仍标记为“未验证”，直到 I2 存储实现和本节离线验收全部通过。`0034` 已合入的可空 `source_licence_id` 不等于 U9 已关闭，因为它仍保留 `(code, ts)` 主键且没有快照归属列。

仓库没有可复用的盘中总开关。`daily_bars_source` 只描述日 K 来源，`MAIRUI_MODE` 只描述传输或回放模式。正式开关裁定为 `Settings.intraday_enabled`，环境变量名为 `INTRADAY_ENABLED`，位置为 `src/backend/app/config.py:Settings`。默认值为 `false`。它必须在任务注册、定时器、写入器和盘中读侧共同生效，false 时不得出网、不得写四表、不得把未排程标为 pending。`MAIRUI_MODE=replay` 仍是离线回放模式，不覆盖该开关。开关命名和默认值依据 `/workspace/team/reports/T-A211.md §1.2、§4 I2-C/I2`，正式解析接线属于后续实现，当前未验证。

本契约不授权真实麦蕊调用、生产部署、恢复出网或打开开关。I2 只交付迁移设计和离线验收依据。

## 8. 旧条款逐条失效清单

以下条款只描述 I2 之前的基线，均由本契约取代，不能作为 I2 实现或验收断言：

- `intraday-bars.md §1.3`：“主键 `(code, ts)` 一键一行；跨源一律 DO NOTHING，先写者留下；两源不重叠；同源 mairui 同键更新”。由本契约 §2.1–§2.3 取代，按 `K`、指纹和 revision 决定并存、重放与修订。
- `intraday-bars.md §2.2`：“minute_bars/minute5_bars 主键 `(code, ts)`；不改主键；tdx_local 行为空”。由本契约 §1.1、§2.1 取代。`tdx_local` NULL 证书仍有效，但物理键和唯一键改由 I2 迁移定义。
- `intraday-bars.md §5.1 M1`：“主键仍为 `(code, ts)`”及 `minute5_bars` 同键断言。由本契约 §2.1、§5 取代，M1 仅可作为迁移前基线记录。
- `intraday-bars.md §5.1 M2` 的 `test_lc_import_until_before_first_mairui_minute`：“按最早 mairui 日向前截断 tdx_local 导入”。由本契约 §2.1–§2.3 取代，不用日期截断模拟归属隔离。
- `intraday-bars.md §5.1 M3` 的 `test_postclose_same_source_update_cross_source_nothing`：“同源 mairui 更新、tdx_local 不变”。由本契约 §2.2–§2.3 取代，按指纹重放或新 revision 处理。
- `intraday-bars.md §5.3` 的 `test_minute_sources_never_mixed`：“先写 tdx_local、再写 mairui 只有一行且保留 tdx_local”。由本契约 §2.2–§2.3 和 §4 取代，I2 验收应断言归属隔离、指纹幂等及 owner 读不可见。

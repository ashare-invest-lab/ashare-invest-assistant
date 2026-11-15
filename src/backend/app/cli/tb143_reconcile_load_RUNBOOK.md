# T-B143w 用户电脑操作清单

1. 仅在运维明确安排的用户电脑执行以下步骤。同步到已包含迁移 0036 和本工具的 main；确认后端容器内有 `app.cli.tb143_reconcile_load`。本次准备任务不操作用户电脑、不迁移、不写库。以下路径全部由运维填写；不把 DSN、口令、证书或真实代码清单写入仓库/日志。

2. 先核实用户电脑分片完整：**p00–p12 只有约 13/57 片，不完整，禁止 `--apply`**。从 box 已有完整 PARTS/年 CSV 重传；完整旧格式应有 p00–p56、PARTS、BUNDLES（b1.tgz–b5.tgz 的哈希）、SUMS。检查 PARTS 原始清单来自完整导出，核对文件数量和 SHA256；不截短清单来绕过校验。年 CSV 可直接传输，保留并校验覆盖全部 CSV 的 SUMS。只有年度 CSV 而没有清单时，工具记录输入 SHA256，但不能证明上游是否漏传年份，须人工确认。不要调用旧 probes runner，不删除原件。

3. 在同步后的代码目录执行 `python -m alembic heads`，确认代码头是 **0036**；在目标栈执行 `python -m alembic current`，确认数据库当前头也是 **0036**。缺失或不符时停止并交运维处理；本清单不执行迁移，也不重启栈。

4. 准备独立的两路输入和北交所调用方资格集文件（一行一个规范代码，UTF-8，格式 `920xxx.BJ`）。生产由运维确认是 **355 只 920xxx**，仓库不保存该名单。A 路是 `trade_date < 2023-11-13` 的历史 CSV；B 路是资格集内 920 的**上市以来全窗口** CSV 或现有 day zip，禁止对 B 路设置历史截止日。CSV 表头必须与 `tb143_export.DAY_COLUMNS` 顺序一致：`code,trade_date,adj_type,open,high,low,close,volume,amount`。只有 `adj_type=none`，量已是股、额已是元；精度必须可无损写入 Numeric(20,4)。证券主数据 `type=stock` 才接收，沿用 tdx_local 判断。历史的日期过滤和 B 路资格过滤计入 `out_of_scope`。

5. 选一个后端容器名、该容器内后端目录、宿主机锁目录、已有的日志父目录、全新输出目录。**所有操作者必须使用同一锁路径**。锁目录以不覆盖的 mkdir 获取；存在就记 `LOCKED: skipped` 并立即退出 0；只有本次取得的锁会在结束时删除。异常断电留下的锁须人工确认没有正在运行的进程后再处理。宿主机入口只互斥/搬运，所有解析、校验、SQL、事务在容器内 Python 中执行；不要改用 sh 拼 SQL。容器连接使用已有 `DATABASE_URL`，本工具不读取 `.env`；确保它是 psycopg 支持的连接串。推荐通过现有容器环境提供，避免 `--dsn` 出现在命令历史。

6. 先运行 dry-run。PowerShell 设置以下变量为运维实际选择的路径和值（本清单不提供用户固定路径）；`$OutDry` 必须尚不存在。把输入搬运到专用容器临时目录会占用额外磁盘空间，预留分片恢复和候选 CSV 的容量。

   ```powershell
   & .\app\cli\tb143_reconcile_load.ps1 `
     -ShardsDir $DirA -BjCodes $Codes -BjData $DirBOrZip `
     -Out $OutDry -Lock $LockDir -Log $LogFile `
     -Container $BackendContainer -BackendDir $BackendPath
   ```

   直接在已挂载输入的容器中运行 Python 的等价参数如下；宿主机仍须先取得共同的 mkdir 锁并在 finally 释放。Python 的 `--lock-dir` 只对共享同一文件系统的调用互斥，不能代替跨容器的宿主机锁。

   ```text
   PYTHONPATH=src/backend python -m app.cli.tb143_reconcile_load
     --shards-dir DIR_A --bj-codes CODES --bj-data DIR_B_OR_ZIP
     --out NEW_AUDIT_DIR [--lock-dir SHARED_CONTAINER_LOCK]
     [--before 2023-11-13] [--dsn DSN]
   ```

   旧传输格式只剩 p?? 时还须提供 `--bundle-sizes N1,N2,N3,N4,N5`（PowerShell `-BundleSizes`），取完整包的五个原始 tgz 字节数，不能猜。Python 先校验全部 PARTS、恢复五包、校验 BUNDLES，再提取年度 CSV/SUMS（旧 tb143_load_day.sql 仅保留作哈希对象），最后校验 SUMS；不执行包内 SQL。已有年度 CSV 时不需要字节数，但目录内已有的 PARTS/BUNDLES 仍必须完整并通过哈希。准备产物保留于审计目录 `prepared_history`。

7. 阅读 `summary.json` 与 `reconcile.jsonl`：核对 `integrity.*.complete=true`、`incomplete=false`；所有预期年份/分片均有批次。查看新增 `new`、一致 `identical`、差异 `mismatch`、非 A 股 `non_a_share`、异常 `abnormal`、范围过滤 `out_of_scope`。OHLC/量复用 `tdx_local.reconcile` 精确比对，金额容差复用日契：`max(1 元, abs(已有金额) × 2.4e-7)`。差异逐字段列出现有来源和值、通达信值；差异不授权覆盖。缺列/解析文件失败会使该文件失败；无效记录仅拒该行并计数。查看每批 `coverage` 中各代码的日期起止与条数，确认 `bj_codes_requested=355`、`bj_codes_observed=355`、`bj_codes_missing=[]` 且日期覆盖上市以来窗口；有缺失须补齐再跑。工具不自带 355 名单，也不能证明调用方 CSV 上游没有裁剪历史。`zip_skipped` 是 zip 里未入调用方资格集/非日线成员的跳过数，不是行情行数。

8. 检查每批 `NNNN_new_keys.csv`（将新增主键，回滚核对依据）和 `NNNN_candidates.csv`（对应新增值）。dry-run 使用数据库只读事务，查询已有行，不 INSERT 行情。每批键只统计一次，重复输入键记异常；跨文件去重索引仅写入本次审计目录 `input_keys*`。对账记录、清单和写前计数会在首笔 INSERT 前刷盘。输出目录不可复用，失败原样保留；再次运行另选新目录，不覆盖旧清单。

9. 确认 dry-run 和完整性审核通过后，**显式 `--apply`**；PowerShell 使用同一参数并加 `-Apply`，输出换成全新 `$OutApply`。工具会重新校验/对账，不直接信任旧 dry-run。按每个 CSV 独立事务（zip 按年），任何已有来源的同键行都保留，只有新增键写 `source=tdx_local`、`ON CONFLICT DO NOTHING`；不 UPDATE/DELETE。每笔在对账开始前获取日线表写互斥锁并持有至事务结束，大文件可能持锁较久；等待锁超过 5 秒即该批失败，其他批继续，不需停止栈。

10. 复核 `batches[*].status`：`committed` 为独立成功，`failed` 已回滚，已成功批次保留；有失败不要当整次原子操作。每批 `before/after` 含全表、mairui、tdx_local、本批键数量；**mairui 必须前后不变**，否则回滚该批。新增数须等于全表、tdx_local、本批键数量的增量。`reconcile.jsonl` 也逐批记录 `batch_prepared` 和 `batch_result`；突然中断、只见 prepared 时以新主键清单配合只读查询判断事务结果，不自动删除任何行。失败/哈希不符时保留全部源文件、恢复文件和容器现场，宿主机日志会记录容器临时目录；搬运审计失败时从该目录取回。重跑对已提交键只对账/DO NOTHING。退出码：Python 0=完成或锁已存在，1=部分失败/输入不完整 dry-run，2=前置拒绝；PowerShell 对容器非零统一返回 1 并记日志。

11. 运维使用现有日K读取入口检查 `000001.SZ` 与调用方名单中一只 `920xxx.BJ` 的日K可读（这里只是验收代码标签，不提供任何真实行情），分别核实历史和全窗口。复核每笔 mairui 计数不变、总新增与汇总一致。人工回滚如有需要另行审批，本工具没有删除入口。保留审计文件和日志；**不要重启栈，重启由运维另做**。

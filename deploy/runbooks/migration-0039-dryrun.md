# 0039 日内归属迁移只读演练

脚本只查询目标库，不改变表、数据或版本记录。它检查 0038 前置版本、压缩分块、来源与证书关系、重复键和半成品列，并在收口后核对行数、证书空值数、身份列和新唯一键。

## 用户机 PowerShell

先用 compose 查 PostgreSQL 容器名，以下命令中的 `<pg容器>` 替换为结果。

```powershell
$pg = (docker compose ps -q postgres)
docker cp deploy/scripts/db-dryrun-0039.sh "$pg`:/tmp/db-dryrun-0039.sh"
docker exec $pg sh /tmp/db-dryrun-0039.sh --pre | Tee-Object pre.txt
```

迁移完成后把前置输出送入收口检查。管道会去掉 Windows 的回车字符。

```powershell
Get-Content pre.txt | docker exec -i $pg sh /tmp/db-dryrun-0039.sh --post - | Tee-Object post.txt
```

连接串可通过容器内环境变量 `POSTGRES_USER`、`POSTGRES_DB` 确定，也可在容器内显式传入 `--dbname`。脚本不会打印连接串或口令。状态为 `ok` 才能继续迁移，`blocked` 需按每条 `reason=` 处理。压缩分块必须先停写并按运维流程解压，脚本不会替代该操作。

## 结果键

四张表按 `quotes_snapshot`、`realtime_quotes`、`minute_bars`、`minute5_bars` 固定顺序输出。盘点键以 `table.<表>.` 开头，预测键以 `predict.<表>.` 开头。行数、来源计数、证书空值数和重复组数都只输出计数，对象字段只输出名称。

## 限制

每次查询都使用只读事务和容器 Unix socket。压缩分块、证书空值、来源越界、预测冲突或已存在新列会阻断前置检查。收口检查读取前置文件，遇到行数变化、身份空值、revision 非零或唯一键冲突会阻断。该流程未在用户机验证。

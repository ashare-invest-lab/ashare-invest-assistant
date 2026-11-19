<#
.SYNOPSIS
旧日线装载 runner 已停用；启动即报错并非零退出，保留所有产物。
.DESCRIPTION
保留原 param 声明，供旧调度收到明确拒绝信息。
不加锁、不解包、不调用 Docker、psql 或 Python，也不清理任何产物。
请在 src/backend 下改用 python -m app.cli daily-bars-import-tdx；
年度 CSV 可用 python -m app.cli.tb143_day_load --csv <CSV> --before <DATE>。
替代入口仍受公共 writer 的 BJ 确认门闩约束。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Dir,
    [Parameter(Mandatory=$true)][string]$AllSha,
    [Parameter(Mandatory=$true)][string]$BundleSizes,
    [ValidateSet('aia-local-postgres-1')][string]$Container = 'aia-local-postgres-1',
    [string]$Before = '2023-11-13',
    [Parameter(Mandatory=$true)][string]$Lock,
    [Parameter(Mandatory=$true)][string]$Log,
    [ValidateRange(0,2147483647)][int]$PauseSeconds = 5
)
Write-Error 'REFUSED: legacy tb143 load path is disabled; all artifacts are retained. Use python -m app.cli daily-bars-import-tdx（通达信日线导入）或 python -m app.cli.tb143_day_load --csv <CSV> --before <DATE>（年度 CSV 经公共 writer，仍受 BJ 确认门闩约束）。' -ErrorAction Continue
exit 1

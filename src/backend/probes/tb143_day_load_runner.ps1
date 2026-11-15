<#
.SYNOPSIS
旧日线 psql 装载入口已停用：SQL 现在仅 staging，不能提交目标表。
.DESCRIPTION
旧包可能仍含可执行目标表 SQL，故在解包、docker、psql 与清理前拒绝。
保留调用参数便于旧调度获得明确非零退出；待 Python 公共 writer 包装器迁移后启用。
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
$ErrorActionPreference = 'Stop'
Write-Error 'tb143 day load runner disabled: use app.marketdata.daily_bars; keep all input artifacts.'
exit 1

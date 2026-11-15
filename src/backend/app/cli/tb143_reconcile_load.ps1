<#
T-B143w 宿主机入口：只做互斥、文件搬运和调用容器内 Python。
容器必须已同步包含本工具的代码，并通过其已有环境提供 DATABASE_URL。
不传递/读取任何本地 .env，不重启栈，不删除输入或失败现场。
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$ShardsDir,
    [Parameter(Mandatory=$true)][string]$BjCodes,
    [Parameter(Mandatory=$true)][string]$BjData,
    [Parameter(Mandatory=$true)][string]$Out,
    [Parameter(Mandatory=$true)][string]$Lock,
    [Parameter(Mandatory=$true)][string]$Log,
    [Parameter(Mandatory=$true)][string]$Container,
    [Parameter(Mandatory=$true)][string]$BackendDir,
    [string]$Before = '2023-11-13',
    [string]$BundleSizes,
    [switch]$Apply
)
$ErrorActionPreference = 'Stop'
function Write-Log([string]$Message) {
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value ('[{0}] {1}' -f (Get-Date -Format o), $Message)
}
# New-Item 不带 -Force：mkdir 已存在须原子失败，且绝不删除他人的锁。
try { New-Item -ItemType Directory -Path $Lock -ErrorAction Stop | Out-Null }
catch {
    if (Test-Path -LiteralPath $Lock -PathType Container) { Write-Log 'LOCKED: skipped'; exit 0 }
    throw
}
$exitCode = 0
$started = $false
$stage = '/tmp/reconcile-' + [guid]::NewGuid().ToString('N')
function Invoke-Docker([string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        & docker @Arguments 2>&1 | ForEach-Object { Write-Log ([string]$_) }
        $nativeExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    if ($nativeExit -ne 0) { throw "docker exit=$nativeExit" }
}
try {
    if (Test-Path -LiteralPath $Out) { throw 'Out 必须是全新目录；请保留已有审计目录。' }
    Write-Log "START stage=$stage mode=$(if ($Apply) {'apply'} else {'dry-run'})"
    Invoke-Docker @('exec', $Container, 'python', '-c',
        'import pathlib,sys; p=pathlib.Path(sys.argv[1]); (p/''history'').mkdir(parents=True)', $stage)
    Invoke-Docker @('cp', (Join-Path $ShardsDir '.'), "${Container}:$stage/history/")
    Invoke-Docker @('cp', $BjCodes, "${Container}:$stage/bj-codes.txt")
    $bjTarget = if (Test-Path -LiteralPath $BjData -PathType Container) { 'bj' } else { 'bj.zip' }
    Invoke-Docker @('cp', $BjData, "${Container}:$stage/$bjTarget")
    $arguments = @('exec', '-w', $BackendDir, $Container, 'python', '-m', 'app.cli.tb143_reconcile_load',
        '--shards-dir', "$stage/history", '--bj-codes', "$stage/bj-codes.txt",
        '--bj-data', "$stage/$bjTarget", '--out', "$stage/out", '--before', $Before)
    if ($BundleSizes) { $arguments += @('--bundle-sizes', $BundleSizes) }
    if ($Apply) { $arguments += '--apply' }
    $started = $true
    Invoke-Docker $arguments
} catch {
    $exitCode = 1
    Write-Log "ERROR $($_.Exception.Message)"
} finally {
    if ($started) {
        try { Invoke-Docker @('cp', "${Container}:$stage/out", $Out) }
        catch { $exitCode = 1; Write-Log "COPY OUT ERROR；容器现场保留于 $stage" }
    }
    try { Write-Log "KEEP 输入和容器现场 $stage；不重启栈。exit=$exitCode" }
    finally { Remove-Item -LiteralPath $Lock -ErrorAction Stop }
}
exit $exitCode

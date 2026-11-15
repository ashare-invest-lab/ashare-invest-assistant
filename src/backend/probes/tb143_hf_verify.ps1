[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Root,
    [Parameter(Mandatory=$true)][string]$Out,
    [Parameter(Mandatory=$true)][string]$Lock
)
$ErrorActionPreference = 'Stop'
try {
    New-Item -ItemType Directory -Path $Lock -ErrorAction Stop | Out-Null
} catch {
    Write-Output 'LOCKED'
    exit 0
}
$result = New-Object 'System.Collections.Generic.List[string]'
$total = 0
$ok = 0
$bad = 0
$missing = 0
try {
    $parent = Split-Path -Parent $Out
    if ($parent) { New-Item -ItemType Directory -Path $parent -Force | Out-Null }
    # Windows PowerShell 5.1 的 UTF8 可读取有 BOM 或无 BOM 的 UTF-8 CSV。
    $rows = @(Import-Csv -LiteralPath (Join-Path $Root 'manifest_files.csv') -Encoding UTF8)
    $total = $rows.Count
    if ($total -eq 0) { throw 'manifest_files.csv 没有数据行' }
    foreach ($row in $rows) {
        if ($row.exchange -notmatch '^(SH|SZ|BJ)$' -or $row.symbol -notmatch '^\d{6}$') {
            throw '清单 exchange 或 symbol 缺失或非法，拒绝拼接空路径'
        }
    }
    $firstPath = Join-Path (Join-Path $Root $rows[0].exchange) ($rows[0].symbol + '.parquet')
    $firstExists = Test-Path -LiteralPath $firstPath -PathType Leaf
    $result.Add("first_path=$firstPath exists=$firstExists")
    foreach ($row in $rows) {
        $path = Join-Path (Join-Path $Root $row.exchange) ($row.symbol + '.parquet')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $missing++
            $result.Add("MISSING $path")
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($actual -eq $row.sha256.Trim().ToLowerInvariant()) {
            $ok++
        } else {
            $bad++
            $result.Add("BAD $path expected=$($row.sha256) actual=$actual")
        }
    }
    # 输出前再自检第一行，缺失时明确报错，仍保留完整校验统计。
    if (-not (Test-Path -LiteralPath $firstPath -PathType Leaf)) {
        throw "第一行路径不存在：$firstPath"
    }
    if ($bad -gt 0 -or $missing -gt 0) { throw 'HF 文件校验失败，详见结果文件' }
} catch {
    $result.Add("ERROR $($_.Exception.Message)")
    throw
} finally {
    try {
        @("total=$total ok=$ok bad=$bad missing=$missing") + $result.ToArray() |
            Set-Content -LiteralPath $Out -Encoding UTF8
    } finally {
        Remove-Item -LiteralPath $Lock -Force
    }
}

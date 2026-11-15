<#
.SYNOPSIS
校验已离线导出的日线包，按年加载到本地 PostgreSQL。
.DESCRIPTION
先在 src/backend 下运行 python -m app.cli.tb143_export day --zip <ZIP> `
    --eligible-codes <资格集> --before <日期> --split-by-year --out <输出目录> `
    --generator <app/cli/tb143_export.py 的 git blob SHA>。
将生成的年度 CSV 与 tb143_load_day.sql 打包并生成清单后，才运行本 runner。
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
function Write-Log([string]$Message) {
    Add-Content -LiteralPath $Log -Encoding UTF8 -Value (('[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'), $Message))
}
try { New-Item -ItemType Directory -Path $Lock -ErrorAction Stop | Out-Null }
catch { Write-Log 'LOCKED'; exit 0 }
$exitCode = 0
$allYearsSucceeded = $false
$year = '尚未开始'
function Invoke-Docker([string[]]$Arguments) {
    $oldPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue' # PS 5.1 的原生命令 stderr 也必须完整记入日志。
        $script:dockerOutput = @(& docker @Arguments 2>&1)
        $nativeExit = $LASTEXITCODE
    } finally { $ErrorActionPreference = $oldPreference }
    foreach ($line in $script:dockerOutput) { Write-Log ([string]$line) }
    if ($nativeExit -ne 0) { throw "docker exit=$nativeExit arguments=$($Arguments -join ' ')" }
}
function Check-Hash([string]$Path, [string]$Expected) {
    if ((Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash -ine $Expected) { throw "SHA256 不符: $Path" }
    Write-Log "SHA256 OK $Path"
}
function Read-Manifest([string]$Name, [string]$Pattern, [string[]]$ExpectedNames) {
    $entries = @{}
    foreach ($line in Get-Content -LiteralPath (Join-Path $Dir $Name) -Encoding UTF8) {
        if ($line -notmatch "^([0-9a-fA-F]{64})  ($Pattern)$") { throw "$Name 行格式错误: $line" }
        $file = $Matches[2]; $hash = $Matches[1]
        if ($entries.ContainsKey($file)) { throw "$Name 重复文件: $file" }
        $entries[$file] = $hash
    }
    if ($entries.Count -ne $ExpectedNames.Count) { throw "$Name 文件数错误" }
    foreach ($file in $ExpectedNames) { if (-not $entries.ContainsKey($file)) { throw "$Name 缺少 $file" } }
    return $entries
}
try {
    Write-Log 'START；仅全部年份成功后清理本地 all.bin、b1..b5.tgz、p??；失败保留文件供重跑。'
    $Dir = (Get-Item -LiteralPath $Dir -Force).FullName
    if (-not (Test-Path -LiteralPath $Dir -PathType Container)) { throw 'Dir 必须是目录' }
    if ($AllSha -notmatch '^[0-9a-fA-F]{64}$') { throw 'AllSha 格式错误' }
    $parsedDate = [datetime]::MinValue
    if (-not [datetime]::TryParseExact($Before, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None, [ref]$parsedDate)) { throw 'Before 必须是 yyyy-MM-dd' }
    $sizes = @($BundleSizes.Split(',') | ForEach-Object {
        $n = 0L
        if (-not [long]::TryParse($_.Trim(), [ref]$n) -or $n -le 0) { throw 'BundleSizes 必须是正整数字节数' }
        $n
    })
    if ($sizes.Count -ne 5) { throw 'BundleSizes 必须恰好有五项' }
    $partNames = @(0..56 | ForEach-Object { 'p{0:00}' -f $_ })
    $bundleNames = @(1..5 | ForEach-Object { "b$_.tgz" })
    $parts = Read-Manifest 'PARTS' 'p[0-9]{2}' $partNames
    $bundles = Read-Manifest 'BUNDLES' 'b[1-5]\.tgz' $bundleNames
    $allPath = Join-Path $Dir 'all.bin'
    if (Test-Path -LiteralPath $allPath) {
        Check-Hash $allPath $AllSha
        Write-Log 'REUSE all.bin'
    } else {
        foreach ($name in $partNames) { Check-Hash (Join-Path $Dir $name) $parts[$name] }
        $output = [IO.File]::Create($allPath)
        try {
            foreach ($name in ($partNames | Sort-Object)) {
                $inputStream = [IO.File]::OpenRead((Join-Path $Dir $name))
                try { $inputStream.CopyTo($output) } finally { $inputStream.Dispose() }
            }
        } finally { $output.Dispose() }
        Check-Hash $allPath $AllSha
    }
    $inputStream = [IO.File]::OpenRead($allPath)
    try {
        $buffer = New-Object byte[] 1048576
        for ($i = 0; $i -lt 5; $i++) {
            $remaining = $sizes[$i]
            if ($remaining -gt ($inputStream.Length - $inputStream.Position)) { throw 'BundleSizes 超出 all.bin' }
            $bundlePath = Join-Path $Dir $bundleNames[$i]
            if (Test-Path -LiteralPath $bundlePath) {
                Check-Hash $bundlePath $bundles[$bundleNames[$i]]
                if ((Get-Item -LiteralPath $bundlePath).Length -ne $remaining) { throw "BundleSizes 与 $bundlePath 不符" }
                $inputStream.Seek($remaining, [IO.SeekOrigin]::Current) | Out-Null
                Write-Log "REUSE $($bundleNames[$i])"
                continue
            }
            $output = [IO.File]::Create($bundlePath)
            try {
                while ($remaining -gt 0) {
                    $read = $inputStream.Read($buffer, 0, [int][Math]::Min([long]$buffer.Length, $remaining))
                    if ($read -eq 0) { throw 'all.bin 提前结束' }
                    $output.Write($buffer, 0, $read); $remaining -= $read
                }
            } finally { $output.Dispose() }
            Check-Hash $bundlePath $bundles[$bundleNames[$i]]
        }
        if ($inputStream.Position -ne $inputStream.Length) { throw 'BundleSizes 未覆盖整个 all.bin' }
    } finally { $inputStream.Dispose() }
    Invoke-Docker @('exec', $Container, 'mkdir', '-p', '/tmp/tb143d')
    foreach ($name in $bundleNames) {
        Invoke-Docker @('cp', (Join-Path $Dir $name), "${Container}:/tmp/tb143d/")
        Invoke-Docker @('exec', '-w', '/tmp/tb143d', $Container, 'tar', 'xzf', $name)
        Invoke-Docker @('exec', $Container, 'rm', '-f', "/tmp/tb143d/$name")
    }
    Invoke-Docker @('exec', '-w', '/tmp/tb143d', $Container, 'sha256sum', '-c', 'SUMS')
    Invoke-Docker @('exec', '-w', '/tmp/tb143d', $Container, 'find', '.', '-maxdepth', '1', '-type', 'f', '-name', 'day_*.csv')
    $csvs = @($script:dockerOutput | ForEach-Object {
        if ([string]$_ -notmatch '^\./day_[0-9]{4}\.csv$') { throw "非法日线文件名: $_" }
        ([string]$_).Substring(2)
    } | Sort-Object)
    Write-Log "CSV count=$($csvs.Count)"
    if ($csvs.Count -eq 0) { throw '没有 day_YYYY.csv' }
    $candidates = 0L; $inserted = 0L; $skipped = 0L
    for ($i = 0; $i -lt $csvs.Count; $i++) {
        $csv = $csvs[$i]; $year = $csv.Substring(4, 4)
        Write-Log "YEAR $year START；此前成功年份已独立提交。"
        Invoke-Docker @('exec', $Container, 'psql', '-U', 'aia', '-d', 'aia', '-v', 'ON_ERROR_STOP=1',
            '-v', "csv=/tmp/tb143d/$csv", '-v', "before=$Before", '-f', '/tmp/tb143d/tb143_load_day.sql')
        $counts = @($script:dockerOutput | ForEach-Object {
            if ([string]$_ -match '^\s*(\d+)\s*\|\s*(\d+)\s*\|\s*(\d+)\s*$') {
                [pscustomobject]@{ Candidates = [long]$Matches[1]; Inserted = [long]$Matches[2]; Skipped = [long]$Matches[3] }
            }
        })
        if ($counts.Count -ne 1) { throw "YEAR $year 已提交，但 candidates/inserted/skipped 解析失败" }
        $candidates += $counts[0].Candidates; $inserted += $counts[0].Inserted; $skipped += $counts[0].Skipped
        Write-Log "YEAR $year COMMITTED candidates=$($counts[0].Candidates) inserted=$($counts[0].Inserted) skipped=$($counts[0].Skipped)"
        if ($i -lt $csvs.Count - 1) { Start-Sleep -Seconds $PauseSeconds }
    }
    Write-Log "TOTAL candidates=$candidates inserted=$inserted skipped=$skipped"
    $allYearsSucceeded = $true
} catch {
    $exitCode = 1
    Write-Log "ERROR stopped_year=$year；此前已提交年份保留。$($_.Exception.Message)"
} finally {
    try { Invoke-Docker @('exec', $Container, 'rm', '-rf', '/tmp/tb143d') }
    catch { $exitCode = 1; Write-Log "CLEANUP container ERROR $($_.Exception.Message)" }
    try {
        if ($allYearsSucceeded -and $exitCode -eq 0) {
            foreach ($file in Get-ChildItem -LiteralPath $Dir -File -Force) {
                if ($file.Name -cmatch '^(all\.bin|b.*\.tgz|p[0-9]{2})$') { Remove-Item -LiteralPath $file.FullName -Force }
            }
        } else {
            Write-Log 'KEEP local all.bin、b*.tgz、p??、PARTS、BUNDLES；可校验 SHA256 后重跑。'
        }
    } catch { $exitCode = 1; Write-Log "CLEANUP local ERROR $($_.Exception.Message)" }
    finally {
        try { Remove-Item -LiteralPath $Lock -Force }
        catch { $exitCode = 1; Write-Log "CLEANUP lock ERROR $($_.Exception.Message)" }
    }
}
exit $exitCode

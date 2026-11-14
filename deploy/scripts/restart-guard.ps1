#Requires -Version 5.1
# Check backfill locks before restarting, rebuilding or taking down a local stack.
[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string]$LockDir = $(if ($env:AIA_RUNTIME_LOCK_DIR) { $env:AIA_RUNTIME_LOCK_DIR } else { 'F:\workspace\team\runtime' }),
    [ValidateNotNullOrEmpty()]
    [string]$Then
)

$ErrorActionPreference = 'Stop'

function Get-LockFirstLine {
    param([string]$Path)
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        # Reparse points (including junctions) must not expose unrelated files.
        if (-not $item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $line = Get-Content -LiteralPath $Path -TotalCount 1 -Encoding UTF8 -ErrorAction Stop
            if (-not [string]::IsNullOrEmpty($line)) { return $line }
        }
    } catch {
        # Missing, empty or unreadable metadata never makes a lock disappear.
    }
    return '未知'
}

try {
    if (-not (Test-Path -LiteralPath $LockDir)) {
        Write-Warning "锁目录不存在：$LockDir"
    } else {
        if (-not (Test-Path -LiteralPath $LockDir -PathType Container)) {
            throw 'LockDir must be a directory'
        }
        $locks = @(Get-ChildItem -LiteralPath $LockDir -Force -Filter '*.lock' -ErrorAction Stop)
        foreach ($lock in $locks) {
            $owner = '未知'
            if (-not ($lock.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                if ($lock.PSIsContainer) {
                    foreach ($metadata in @('owner', 'info')) {
                        $owner = Get-LockFirstLine -Path (Join-Path $lock.FullName $metadata)
                        if ($owner -ne '未知') { break }
                    }
                } else {
                    $owner = Get-LockFirstLine -Path $lock.FullName
                }
            }
            $modified = $lock.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
            Write-Output ("锁：{0} | 持锁任务：{1} | 修改时间：{2}" -f $lock.Name, $owner, $modified)
        }
        if ($locks.Count -gt 0) {
            [Console]::Error.WriteLine('存在回填锁，拒绝重启、重建或 down')
            exit 3
        }
    }
} catch {
    [Console]::Error.WriteLine("无法检查锁目录：$LockDir，拒绝执行")
    exit 2
}

Write-Output '无回填锁，可以重启'
if ($PSBoundParameters.ContainsKey('Then')) {
    try {
        $global:LASTEXITCODE = 0
        & ([scriptblock]::Create($Then))
        $thenSucceeded = $?
        if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
        if (-not $thenSucceeded) { exit 1 }
    } catch {
        [Console]::Error.WriteLine('后续命令执行失败')
        exit 1
    }
}
exit 0

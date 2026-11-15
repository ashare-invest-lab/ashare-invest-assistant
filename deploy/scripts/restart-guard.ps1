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

function Get-MetadataValue {
    param($Value)
    if ($Value -is [string]) { return ([regex]::Replace($Value, '\s+', ' ')).Trim() }
    return ''
}

function Get-LockMetadata {
    param([string]$Path)
    $result = [PSCustomObject]@{ Owner = '未知'; Status = '未知' }
    try {
        $item = Get-Item -LiteralPath $Path -Force -ErrorAction Stop
        # Reparse points (including junctions) must not expose unrelated files.
        if (-not $item.PSIsContainer -and -not ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
            $text = Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop
            if ([string]::IsNullOrEmpty($text)) { return $result }
            $fields = @{}
            try {
                $json = ConvertFrom-Json -InputObject $text -ErrorAction Stop
                foreach ($name in @('task', 'owner', 'status', 'state')) {
                    if ($null -ne $json -and $null -ne $json.PSObject.Properties[$name]) {
                        $fields[$name] = $json.$name
                    }
                }
            } catch {
                # Invalid JSON still holds the lock; report unknown metadata.
            }
            if ($text.TrimStart() -notmatch '^[\{\[]') {
                $pattern = '(?:^|\s)(task|owner|status|state)\s*=\s*(?:"([^"\r\n]*)"|''([^''\r\n]*)''|([^\s]+))'
                foreach ($match in [regex]::Matches($text, $pattern)) {
                    $name = $match.Groups[1].Value
                    if (-not $fields.ContainsKey($name)) {
                        foreach ($index in @(2, 3, 4)) {
                            if ($match.Groups[$index].Success) {
                                $fields[$name] = $match.Groups[$index].Value
                                break
                            }
                        }
                    }
                }
            }
            foreach ($name in @('task', 'owner')) {
                $value = Get-MetadataValue $fields[$name]
                if ($value) { $result.Owner = $value; break }
            }
            $first = ($text -split '\r?\n', 2)[0]
            if ($result.Owner -eq '未知' -and $text.TrimStart() -notmatch '^[\{\[]' -and $first -notmatch '=') {
                $value = Get-MetadataValue $first
                if ($value) { $result.Owner = $value }
            }
            foreach ($name in @('status', 'state')) {
                $value = Get-MetadataValue $fields[$name]
                if ($value) { $result.Status = $value; break }
            }
        }
    } catch {
        # Missing, empty or unreadable metadata never makes a lock disappear.
    }
    return $result
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
            $status = '未知'
            if (-not ($lock.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
                if ($lock.PSIsContainer) {
                    foreach ($metadata in @('owner', 'info')) {
                        $details = Get-LockMetadata -Path (Join-Path $lock.FullName $metadata)
                        if ($owner -eq '未知') { $owner = $details.Owner }
                        if ($status -eq '未知') { $status = $details.Status }
                    }
                } else {
                    $details = Get-LockMetadata -Path $lock.FullName
                    $owner = $details.Owner
                    $status = $details.Status
                }
            }
            $modified = $lock.LastWriteTimeUtc.ToString('yyyy-MM-ddTHH:mm:ssZ')
            Write-Output ("锁：{0} | 持锁任务：{1} | 修改时间：{2} | 状态：{3}" -f $lock.Name, $owner, $modified, $status)
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

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$Src,
    [Parameter(Mandatory=$true)][string]$Dst,
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
$summary = New-Object 'System.Collections.Generic.List[string]'
$rows = New-Object 'System.Collections.Generic.List[object]'
$mismatch = 0
try {
    New-Item -ItemType Directory -Path $Out -Force | Out-Null
    New-Item -ItemType Directory -Path $Dst -Force | Out-Null
    $vipdoc = Get-Item -LiteralPath $Dst
    if ($vipdoc.Name -ne 'vipdoc' -or $vipdoc.Parent.Name -ne 'tdx-min') {
        throw 'Dst 必须是快照根目录下的 tdx-min/vipdoc'
    }
    $snapshotRoot = $vipdoc.Parent.Parent.FullName
    $prefixes = @{
        sh = '600|601|603|605|688|689'
        sz = '000|001|002|003|300|301|302'
    }
    foreach ($market in @('sh', 'sz')) {
        foreach ($pair in @(@('minline', 'lc1'), @('fzline', 'lc5'))) {
            $directory = $pair[0]
            $kind = $pair[1]
            $sourceDir = Join-Path (Join-Path $Src $market) $directory
            $destDir = Join-Path (Join-Path $Dst $market) $directory
            $pattern = '^' + $market + '(' + $prefixes[$market] + ')\d{3}\.' + $kind + '$'
            $selected = @(Get-ChildItem -LiteralPath $sourceDir -File | Where-Object { $_.Name -match $pattern })
            New-Item -ItemType Directory -Path $destDir -Force | Out-Null
            $copyCodes = New-Object 'System.Collections.Generic.List[int]'
            # 每批文件名控制长度，避免 Windows 原生命令行长度限制。
            for ($start = 0; $start -lt $selected.Count; $start += 100) {
                $end = [Math]::Min($start + 99, $selected.Count - 1)
                $names = @($selected[$start..$end] | ForEach-Object { $_.Name })
                $copyArgs = @($sourceDir, $destDir) + $names + @('/COPY:DAT', '/R:1', '/W:1', '/NP', '/NJH', '/NJS')
                & robocopy @copyArgs | Out-Null
                $copyCode = $LASTEXITCODE
                $copyCodes.Add($copyCode)
                $summary.Add("robocopy $market/$directory batch=$start code=$copyCode")
                if ($copyCode -ge 8) { throw "robocopy 失败：$market/$directory code=$copyCode" }
            }
            # 对快照中所有选定股票文件逐个核对源文件，包含此前留存的文件。
            $targets = @(Get-ChildItem -LiteralPath $destDir -File | Where-Object { $_.Name -match $pattern })
            [long]$bytes = 0
            foreach ($file in $targets) {
                $bytes += $file.Length
                $sourcePath = Join-Path $sourceDir $file.Name
                $destHash = (Get-FileHash -LiteralPath $file.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
                if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
                    $mismatch++
                    $summary.Add("SOURCE_MISSING $sourcePath")
                } else {
                    $sourceHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
                    if ($sourceHash -ne $destHash) {
                        $mismatch++
                        $summary.Add("SHA_MISMATCH $sourcePath")
                    }
                }
                $relative = $file.FullName.Substring($snapshotRoot.TrimEnd('\').Length + 1).Replace('\', '/')
                $rows.Add([pscustomobject]@{ rel_path=$relative; sha256=$destHash; bytes=$file.Length })
            }
            # 检查源文件是否全部出现在快照，防止复制遗漏。
            foreach ($file in $selected) {
                if (-not (Test-Path -LiteralPath (Join-Path $destDir $file.Name) -PathType Leaf)) {
                    $mismatch++
                    $summary.Add("DEST_MISSING $market/$directory/$($file.Name)")
                }
            }
            $summary.Add("$market/$directory files=$($targets.Count) bytes=$bytes robocopy_codes=$($copyCodes -join ',')")
        }
    }
    $manifest = Join-Path $Out 'tdx_min_sha256.csv'
    if ($rows.Count -eq 0) {
        '"rel_path","sha256","bytes"' | Set-Content -LiteralPath $manifest -Encoding UTF8
    } else {
        $rows | Export-Csv -LiteralPath $manifest -NoTypeInformation -Encoding UTF8
    }
    Copy-Item -LiteralPath $manifest -Destination (Join-Path $vipdoc.Parent.FullName 'SHA256SUMS.csv') -Force
    if ($mismatch -gt 0) { throw "源目标校验失败：$mismatch" }
} catch {
    $summary.Add("ERROR $($_.Exception.Message)")
    throw
} finally {
    try {
        $summary.Add("sha_mismatch=$mismatch")
        if (Test-Path -LiteralPath $Out -PathType Container) {
            $summary | Set-Content -LiteralPath (Join-Path $Out 'summary.txt') -Encoding UTF8
        }
    } finally {
        Remove-Item -LiteralPath $Lock -Force
    }
}

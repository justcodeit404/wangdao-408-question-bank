# 408 bank hot-update: scp changed data + shell files to the cloud shared dir.
# No platform release, no service restart. Since 2026-10-08 this is the ONLY channel
# for bank-408 changes (data and shell alike): the cloud serves shared/banks/bank-408
# directly (release math-bank is a symlink apply never touches), so a full pack+apply
# never updated live bank files anyway. Reserve pack+apply for platform/bank-mount changes.
# Usage (from apps/bank-408):  powershell -File scripts/push_data.ps1
# Optional: -Server ubuntu@122.51.26.195 -RemoteDir /home/ubuntu/kaoyan/shared/banks/bank-408
[CmdletBinding()]
param(
    [string]$Server = "ubuntu@122.51.26.195",
    [string]$RemoteDir = "/home/ubuntu/kaoyan/shared/banks/bank-408"
)
$ErrorActionPreference = "Stop"
$Root = Split-Path $PSScriptRoot -Parent
$Bank = Join-Path $Root "math-bank"
$StateFile = Join-Path $Root "data\quality\cloud_push_hash.txt"
$Python = "python"
$Courses = @("ds", "coa", "os", "net")
# Git's ssh.exe times out under Win32 (System32 OpenSSH works); pin explicit paths.
$Ssh = "C:\Windows\System32\OpenSSH\ssh.exe"
$Scp = "C:\Windows\System32\OpenSSH\scp.exe"
if (-not (Test-Path -LiteralPath $Ssh)) { $Ssh = "ssh" }
if (-not (Test-Path -LiteralPath $Scp)) { $Scp = "scp" }

function Die([string]$Msg) { Write-Error $Msg; exit 1 }
function Sha256([string]$Path) { (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() }
# network to the cloud box is flaky under rapid reconnection; retry with longer backoff
function Invoke-WithRetry([string]$Label, [scriptblock]$Cmd) {
    for ($i = 1; $i -le 5; $i++) {
        & $Cmd
        if ($LASTEXITCODE -eq 0) { return }
        Write-Host "$Label failed (attempt $i/5), retrying..."
        Start-Sleep -Seconds 15
    }
    Die "$Label failed after 5 attempts"
}

# ---- preflight ----
if (-not (Test-Path -LiteralPath $Bank -PathType Container)) { Die "math-bank not found: $Bank" }
try { & $Ssh -o BatchMode=yes -o ConnectTimeout=10 $Server "test -d $RemoteDir" 2>$null | Out-Null } catch {}
if ($LASTEXITCODE -ne 0) { Die "remote $RemoteDir missing; create shared/banks/bank-408 symlink layout first (docs/server.md)" }

# ---- align cache stamps (idempotent; no-op when hashes unchanged) ----
Push-Location $Root
try {
    & $Python scripts/bump_bank_version.py | Write-Host
    if ($LASTEXITCODE -ne 0) { Die "bump_bank_version.py failed" }
} finally { Pop-Location }

# ---- refresh quality manifests so their hashes match the data being pushed ----
# 热更只改 data-*.json 时若不刷新清单，平台 408 导入 API 会因哈希过期直接 400。
Push-Location $Root
try {
    & $Python scripts/quality_ledger.py --refresh-hashes | Write-Host
    if ($LASTEXITCODE -ne 0) { Die "quality_ledger.py --refresh-hashes failed" }
} finally { Pop-Location }

# ---- stamp consistency: index.html __BANK_DATA_VER__ == sw.js cache name ----
$index = (Get-Content -LiteralPath (Join-Path $Bank "index.html") -Raw -Encoding UTF8)
$sw = (Get-Content -LiteralPath (Join-Path $Bank "sw.js") -Raw -Encoding UTF8)
$idxVer = [regex]::Match($index, "__BANK_DATA_VER__\s*=\s*'?(\d+)'?").Groups[1].Value
$swVer = [regex]::Match($sw, "wd408-ui-v(\d+)").Groups[1].Value
$stampCount = [regex]::Matches($index, "\?v=$idxVer").Count
if (-not $idxVer -or $idxVer -ne $swVer) { Die "stamp mismatch: index=$idxVer sw=$swVer; run python scripts/bump_bank_version.py --force" }
if ($stampCount -lt 3) { Die "index.html has suspiciously few ?v=$idxVer stamps ($stampCount)" }

# ---- diff against last-pushed record ----
$old = @{}
if (Test-Path -LiteralPath $StateFile) {
    foreach ($line in (Get-Content -LiteralPath $StateFile -Encoding UTF8)) {
        if ($line -match '^\s*([^=]+)=(.+)$') { $old[$matches[1].Trim()] = $matches[2].Trim() }
    }
}
$new = @{}
$toPush = New-Object System.Collections.Generic.List[string]
foreach ($key in $Courses) {
    # ponytail: 云 nginx 未开 gzip_static 且 viewer 不引用 .gz，只推 json（.gz 留本地无用，2026-09-27 起停推）
    foreach ($ext in @("json")) {
        $name = "data-$key.$ext"
        $p = Join-Path $Bank $name
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $h = Sha256 $p
        $new[$name] = $h
        if ($old[$name] -ne $h) { $toPush.Add($name) }
    }
}
# small entry/manifest files: push every time so stamps and data always land together
# styles.css 一并热更：云端 408 = shared/banks/bank-408（release 是指向它的符号链接），
# 壳样式改动也走这条通道，否则 design 变更到不了云。
foreach ($name in @("index.html", "sw.js", "app.js", "styles.css", "data.js", "choice-only.js",
                    "quality-ledger.json", "quality-hold.json", "manifest.json")) {
    $p = Join-Path $Bank $name
    if (Test-Path -LiteralPath $p) { $toPush.Add($name) }
}

# ---- figure crops: hash-tracked like data; tar-stream push when any drifted ----
# 题图/解析图是静态资产。旧通道只推数据+壳，裁图修复到不了云（2026-10-17 X07 题图踩过）；
# 全部文件做哈希记录，任一漂移则整包 tar 流推送（8.8MB/183 个，单次连接）。
$cropDir = Join-Path $Bank "crops"
$cropsDrifted = $false
if (Test-Path -LiteralPath $cropDir -PathType Container) {
    Get-ChildItem -LiteralPath $cropDir -Recurse -File | ForEach-Object {
        $rel = "crops/" + $_.FullName.Substring($cropDir.Length + 1).Replace("\", "/")
        $h = Sha256 $_.FullName
        $new[$rel] = $h
        if ($old[$rel] -ne $h) { $cropsDrifted = $true }
    }
}

if ($toPush.Count -eq 0 -and -not $cropsDrifted) { Write-Host "no changes, nothing to push"; exit 0 }
Write-Host ("pushing {0} file(s) to {1}:{2}" -f $toPush.Count, $Server, $RemoteDir)
$toPush | ForEach-Object { Write-Host "  $_" }
if ($cropsDrifted) { Write-Host "  crops/ (drifted, full dir)" }

# ---- transfer: data first, then stamped entries (avoid new data under old shell) ----
# single scp call = single connection; argument order preserves transfer order
$ordered = @($toPush | Where-Object { $_ -like "data-*" }) + @($toPush | Where-Object { $_ -notlike "data-*" })
$src = $ordered | ForEach-Object { Join-Path $Bank $_ }
Invoke-WithRetry "scp" { try { & $Scp -C $src "${Server}:${RemoteDir}/" 2>$null } catch {} }

# crops drifted → pack to temp tar, scp, remote extract (PS 5.1 pipe would mangle the binary stream)
if ($cropsDrifted) {
    $Tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $Tar)) { Die "tar.exe not found for crops push" }
    $tmpTar = Join-Path $env:TEMP ("bank408-crops-" + [guid]::NewGuid().ToString("N") + ".tar")
    try {
        & $Tar -C $Bank -cf $tmpTar crops
        if ($LASTEXITCODE -ne 0) { Die "local tar pack failed" }
        Invoke-WithRetry "scp crops" { try { & $Scp -C $tmpTar "${Server}:${RemoteDir}/.crops-sync.tar" 2>$null } catch {} }
        Invoke-WithRetry "ssh extract" { try { & $Ssh $Server "tar -C $RemoteDir -xf $RemoteDir/.crops-sync.tar && rm -f $RemoteDir/.crops-sync.tar" 2>$null } catch {} }
    } finally {
        if (Test-Path -LiteralPath $tmpTar) { Remove-Item -LiteralPath $tmpTar -Force }
    }
}

# ---- remote verify in ONE ssh over HTTP (what users actually get), not the file on disk:
# a full platform release can re-point /banks/408 at a release-internal dir and silently
# shadow the shared folder; only the HTTP view catches that ----
$checkNames = @($ordered | Where-Object { $_ -like "data-*.json" }) -join " "
$remoteScript = "set -e; curl -sS http://127.0.0.1:8000/banks/408/index.html | grep -o '__BANK_DATA_VER__[^;]*' | head -1 | grep -o '[0-9]\+' | head -1; for f in $checkNames; do printf '%s ' `$f; curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/banks/408/`$f; done"
$remoteOut = $null
for ($i = 1; $i -le 5 -and -not $remoteOut; $i++) {
    # EAP=Stop 下 ssh 超时的 stderr 会经 NativeCommandError 变终止错误，2>$null 拦不住，须 try/catch
    $remoteOut = $(try { & $Ssh $Server $remoteScript 2>$null } catch { $null })
    if (-not $remoteOut) { Write-Host "verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
}
if (-not $remoteOut) { Die "verify ssh failed after 5 attempts" }
Write-Host "remote: $($remoteOut -join '; ')"
$remoteVer = ($remoteOut | Select-Object -First 1)
if ("$remoteVer" -notmatch [regex]::Escape($idxVer)) { Die "remote stamp check failed: remote='$remoteVer' local=$idxVer" }
foreach ($line in ($remoteOut | Select-Object -Skip 1)) {
    if ($line -notmatch " 200$") { Die "remote data file check failed: '$line'" }
}

# ---- crops landed? full hash compare (local record vs remote disk), one ssh ----
if ($cropsDrifted) {
    $localCropLines = @($new.GetEnumerator() | Where-Object { $_.Key -like "crops/*" } | ForEach-Object { "$($_.Value)  $($_.Key.Substring(6))" })
    $remoteCropOut = $null
    for ($i = 1; $i -le 5 -and -not $remoteCropOut; $i++) {
        $remoteCropOut = $(try { & $Ssh $Server "cd $RemoteDir/crops && find . -type f -exec sha256sum {} + | sed 's|  \./|  |'" 2>$null } catch { $null })
        if (-not $remoteCropOut) { Write-Host "crops verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
    }
    if (-not $remoteCropOut) { Die "crops verify ssh failed after 5 attempts" }
    $diff = Compare-Object $localCropLines @($remoteCropOut)
    if ($diff) { Die "crops hash mismatch vs remote: $(($diff | Select-Object -First 5) -join '; ')" }
    Write-Host "crops: $($localCropLines.Count) file(s) hash-verified on remote"
}

# ---- record pushed hashes ----
($new.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -LiteralPath $StateFile -Encoding UTF8
Write-Host "OK: remote __BANK_DATA_VER__=$idxVer, $($toPush.Count) file(s) hot-updated (no service restart)"

# ---- sync platform question pool: 408 hot-update only touches the static bank ----
# 云端 questions 表不会自己更新；重导让 /practice、错题本、题目详情与静态库一致。
# 旧 release 缺该脚本时只告警，不阻断热更。
Write-Host "syncing platform 408 question pool..."
$syncCmd = "cd /home/ubuntu/kaoyan/apps/platform-v2/backend && .venv/bin/python scripts/import_408_banks.py"
$syncOut = $null
for ($i = 1; $i -le 3 -and -not $syncOut; $i++) {
    $syncOut = $(try { & $Ssh -o BatchMode=yes -o ConnectTimeout=15 $Server $syncCmd 2>&1 } catch { $null })
    if (-not $syncOut) { Write-Host "platform sync ssh failed (attempt $i/3), retrying..."; Start-Sleep -Seconds 10 }
}
if ($syncOut) { $syncOut | ForEach-Object { Write-Host "  $_" } } else { Write-Host "WARN: platform 408 sync skipped (release may predate scripts/import_408_banks.py)" }

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
    [string]$RemoteDir = "/home/ubuntu/kaoyan/shared/banks/bank-408",
    # 平时壳文件按哈希增量推；只有怀疑云端被手工改动/需要整份重刷时才加这个开关
    [switch]$ForceShell
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
# 壳文件同样按哈希增量推：quality-ledger.json 有 12MB，每次无条件重推并重写云端
# 就为了「戳一定落地」并不划算——戳本身是 index.html/sw.js/app.js 的内容，改了哈希就变，
# 一样会推。要强制整份重刷用 -ForceShell。
# styles.css 一并热更：云端 408 = shared/banks/bank-408（release 是指向它的符号链接），
# 壳样式改动也走这条通道，否则 design 变更到不了云。
foreach ($name in @("index.html", "sw.js", "app.js", "styles.css", "data.js", "choice-only.js",
                    "quality-ledger.json", "quality-hold.json", "manifest.json")) {
    $p = Join-Path $Bank $name
    if (-not (Test-Path -LiteralPath $p)) { continue }
    $h = Sha256 $p
    $new[$name] = $h
    if ($ForceShell -or $old[$name] -ne $h) { $toPush.Add($name) }
}

# ---- static figure assets: 题图 crops/ + 答案图 answer_crops/ 都按哈希记录 ----
# 旧通道只推数据+壳，裁图修复到不了云（2026-10-17 X07 题图踩过）；
# answer_crops 同样漏在通道外（2026-10-19 I/O接口 X14 答案图 404）。
# 按文件增量推（2026-10-20 起）：裁图目录一多一张图就整目录 tar + 189 张全量复核，
# 一次单题文字修复也被拖成分钟级；现在只打变了的文件、只核这些、删掉本地已删除的。
# 3447 张、118MB，每次全量算 SHA256 要 5 秒，所以用 (mtime|size) 缓存跳过没动过的文件。
# ponytail: 只认 mtime+size；若有人保留旧时间戳覆盖同名裁图，会漏判——重裁走 gen_answer_crops 的写入时间，正常不会。
$CacheFile = Join-Path $Root "data\quality\local_hash_cache.txt"
$cache = @{}
if (Test-Path -LiteralPath $CacheFile) {
    foreach ($line in (Get-Content -LiteralPath $CacheFile -Encoding UTF8)) {
        if ($line -match '^([^|]+)\|([^|]+)\|([^|]+)\|(.+)$') {
            $cache[$matches[1]] = "$($matches[2])|$($matches[3])|$($matches[4])"
        }
    }
}
$newCache = @{}
$assetDirs = @("crops", "answer_crops")
$assetChanged = New-Object System.Collections.Generic.List[string]
$assetRemoved = New-Object System.Collections.Generic.List[string]
foreach ($d in $assetDirs) {
    $dir = Join-Path $Bank $d
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { continue }
    Get-ChildItem -LiteralPath $dir -Recurse -File | ForEach-Object {
        $rel = "$d/" + $_.FullName.Substring($dir.Length + 1).Replace("\", "/")
        $stamp = "$($_.LastWriteTimeUtc.Ticks)|$($_.Length)"
        $entry = $cache[$rel]
        if ($entry -and $entry.StartsWith("$stamp|")) {
            $h = $entry.Substring($stamp.Length + 1)
        } else {
            $h = Sha256 $_.FullName
        }
        $newCache[$rel] = "$stamp|$h"
        $new[$rel] = $h
        if ($old[$rel] -ne $h) { $assetChanged.Add($rel) }
    }
    foreach ($k in @($old.Keys)) {
        if ($k -like "$d/*" -and -not $new.ContainsKey($k)) { $assetRemoved.Add($k) }
    }
}
($newCache.GetEnumerator() | ForEach-Object { "$($_.Key)|$($_.Value)" } | Sort-Object) |
    Set-Content -LiteralPath $CacheFile -Encoding UTF8

if ($toPush.Count -eq 0 -and $assetChanged.Count -eq 0 -and $assetRemoved.Count -eq 0) { Write-Host "no changes, nothing to push"; exit 0 }
if ($toPush.Count -gt 0) {
    Write-Host ("pushing {0} file(s) to {1}:{2}" -f $toPush.Count, $Server, $RemoteDir)
    $toPush | ForEach-Object { Write-Host "  $_" }
}
if ($assetChanged.Count -gt 0) {
    $byDir = ($assetChanged | Group-Object { ($_ -split '/')[0] } | ForEach-Object { "$($_.Name)=$($_.Count)" }) -join ", "
    Write-Host ("  asset changed: {0} ({1})" -f $assetChanged.Count, $byDir)
}
if ($assetRemoved.Count -gt 0) { Write-Host ("  asset removed: {0}" -f $assetRemoved.Count) }

# ---- transfer: data first, then stamped entries (avoid new data under old shell) ----
# single scp call = single connection; argument order preserves transfer order
# 空的 scp 会报错并触发 5×15s 重试（2026-10-20 裁图-only 推送卡了 78 秒才被发现），必须先判空
$ordered = @($toPush | Where-Object { $_ -like "data-*" }) + @($toPush | Where-Object { $_ -notlike "data-*" })
if ($ordered.Count -gt 0) {
    $src = $ordered | ForEach-Object { Join-Path $Bank $_ }
    Invoke-WithRetry "scp" { try { & $Scp -C $src "${Server}:${RemoteDir}/" 2>$null } catch {} }
}

# changed assets → pack to temp tar + scp only; extraction happens in the verify ssh below
# (PS 5.1 pipe would mangle the binary stream, hence a file transfer)
if ($assetChanged.Count -gt 0) {
    $Tar = Join-Path $env:SystemRoot "System32\tar.exe"
    if (-not (Test-Path -LiteralPath $Tar)) { Die "tar.exe not found for asset push" }
    $tmpTar = Join-Path $env:TEMP ("bank408-assets-" + [guid]::NewGuid().ToString("N") + ".tar")
    try {
        & $Tar -C $Bank -cf $tmpTar @assetChanged
        if ($LASTEXITCODE -ne 0) { Die "local tar pack failed" }
        Invoke-WithRetry "scp assets" { try { & $Scp -C $tmpTar "${Server}:${RemoteDir}/.assets-sync.tar" 2>$null } catch {} }
    } finally {
        if (Test-Path -LiteralPath $tmpTar) { Remove-Item -LiteralPath $tmpTar -Force }
    }
}

# ---- ONE ssh does: extract changed assets → HTTP verify → re-import platform 408 pool ----
# 云端 SSH 建连有限流（约 4–5 次/分钟），每多一次建连就多一次被拒的机会：早先
# extract / verify / platform-sync 各占一次，第 6 次必被拒，于是平台池静默跳过、
# 还得人工补跑（2026-10-20 ds X09 踩过）。合成一次连接后最多 4 次（preflight/scp/verify/资产哈希）。
# 平台池结果用标记行切出来，失败只告警并给出可直接粘贴的命令，不再空转 3×10s 重试。
# HTTP 视图（不是磁盘文件）才能抓到 release 遮蔽 shared 目录的情况。
$checkNames = @($ordered | Where-Object { $_ -like "data-*.json" }) -join " "
$extract = if ($assetChanged.Count -gt 0) { "tar -C $RemoteDir -xf $RemoteDir/.assets-sync.tar && rm -f $RemoteDir/.assets-sync.tar; " } else { "" }
if ($assetRemoved.Count -gt 0) {
    # 本地删掉的裁图云端也要删，否则已经作废的题图还能被直接 URL 命中
    $extract += "cd $RemoteDir && rm -f " + (($assetRemoved | ForEach-Object { "'$_'" }) -join " ") + "; cd - > /dev/null; "
}
$importCmd = "cd /home/ubuntu/kaoyan/apps/platform-v2/backend && .venv/bin/python scripts/import_408_banks.py"
# 只有 data-*.json 变了平台题池才会不同步；裁图/壳文件热更跑一次全量导入纯属浪费 3–6 秒
$syncStep = if ($checkNames) { "echo '@@PLATFORM_SYNC'; { $importCmd 2>&1 || true; }; echo '@@PLATFORM_SYNC_END'" }
            else { "echo '@@PLATFORM_SYNC'; echo 'platform 408 sync skipped (data-*.json unchanged)'; echo '@@PLATFORM_SYNC_END'" }
$remoteScript = "set -e; ${extract}curl -sS http://127.0.0.1:8000/banks/408/index.html | grep -o '__BANK_DATA_VER__[^;]*' | head -1 | grep -o '[0-9]\+' | head -1; for f in $checkNames; do printf '%s ' `$f; curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/banks/408/`$f; done; $syncStep"
$remoteOut = $null
for ($i = 1; $i -le 5 -and -not $remoteOut; $i++) {
    # EAP=Stop 下 ssh 超时的 stderr 会经 NativeCommandError 变终止错误，2>$null 拦不住，须 try/catch
    $remoteOut = $(try { & $Ssh $Server $remoteScript 2>$null } catch { $null })
    if (-not $remoteOut) { Write-Host "verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
}
if (-not $remoteOut) { Die "verify ssh failed after 5 attempts" }
$verLines = New-Object System.Collections.Generic.List[string]
$syncLines = New-Object System.Collections.Generic.List[string]
$inSync = $false
foreach ($line in $remoteOut) {
    if ("$line" -eq "@@PLATFORM_SYNC") { $inSync = $true; continue }
    if ("$line" -eq "@@PLATFORM_SYNC_END") { $inSync = $false; continue }
    if ($inSync) { $syncLines.Add("$line") } else { $verLines.Add($line) }
}
Write-Host "remote: $($verLines -join '; ')"
$remoteVer = $verLines[0]
if ("$remoteVer" -notmatch [regex]::Escape($idxVer)) { Die "remote stamp check failed: remote='$remoteVer' local=$idxVer" }
foreach ($line in ($verLines | Select-Object -Skip 1)) {
    if ($line -notmatch " 200$") { Die "remote data file check failed: '$line'" }
}

# ---- assets landed? hash-compare just the files that changed (one ssh) ----
if ($assetChanged.Count -gt 0) {
    # ponytail: 待核清单按一条 ssh 命令传过去；几千张以上才会撞命令行长度上限，那时再退回整目录 find
    $assetList = ($assetChanged | ForEach-Object { "'$_'" }) -join " "
    $localLines = @($assetChanged | ForEach-Object { "$($new[$_])  $_" })
    $remoteLines = $null
    for ($i = 1; $i -le 5 -and -not $remoteLines; $i++) {
        $remoteLines = $(try { & $Ssh $Server "cd $RemoteDir && sha256sum -- $assetList" 2>$null } catch { $null })
        if (-not $remoteLines) { Write-Host "asset verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
    }
    if (-not $remoteLines) { Die "asset verify ssh failed after 5 attempts" }
    $diff = Compare-Object $localLines @($remoteLines)
    if ($diff) { Die "asset hash mismatch vs remote: $(($diff | Select-Object -First 5) -join '; ')" }
    Write-Host "$($assetChanged.Count) asset file(s) hash-verified on remote"
}

# ---- record pushed hashes ----
($new.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -LiteralPath $StateFile -Encoding UTF8

# ---- platform pool result (already imported in the verify ssh above) ----
# 云端 questions 表不会自己更新；重导让 /practice、错题本、题目详情与静态库一致。
# 旧 release 缺该脚本、或云端报错时只告警，不阻断已生效的热更。
if (($syncLines -join "`n") -match "platform 408 sync (done|skipped)") {
    $syncLines | ForEach-Object { Write-Host "  $_" }
} else {
    if ($syncLines) { $syncLines | ForEach-Object { Write-Host "  $_" } }
    Write-Host "WARN: platform 408 question pool NOT synced; re-run when ssh settles:"
    Write-Host "  ssh $Server `"$importCmd`""
}

Write-Host "OK: remote __BANK_DATA_VER__=$idxVer, $($toPush.Count) file(s) hot-updated (no service restart)"

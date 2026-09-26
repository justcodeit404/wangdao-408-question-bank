# 408 bank content hot-update: scp only changed data files to the cloud shared dir.
# No platform release, no service restart. For content/data fixes only;
# shell code changes (js/html/viewer) still go through the full pack + apply release.
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
& $Ssh -o BatchMode=yes -o ConnectTimeout=10 $Server "test -d $RemoteDir" 2>$null
if ($LASTEXITCODE -ne 0) { Die "remote $RemoteDir missing; create shared/banks/bank-408 symlink layout first (docs/server.md)" }

# ---- align cache stamps (idempotent; no-op when hashes unchanged) ----
Push-Location $Root
try {
    & $Python scripts/bump_bank_version.py | Write-Host
    if ($LASTEXITCODE -ne 0) { Die "bump_bank_version.py failed" }
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
    foreach ($ext in @("json", "json.gz")) {
        $name = "data-$key.$ext"
        $p = Join-Path $Bank $name
        if (-not (Test-Path -LiteralPath $p)) { continue }
        $h = Sha256 $p
        $new[$name] = $h
        if ($old[$name] -ne $h) { $toPush.Add($name) }
    }
}
# small entry/manifest files: push every time so stamps and data always land together
foreach ($name in @("index.html", "sw.js", "app.js", "data.js", "choice-only.js",
                    "quality-ledger.json", "quality-hold.json", "manifest.json")) {
    $p = Join-Path $Bank $name
    if (Test-Path -LiteralPath $p) { $toPush.Add($name) }
}

if ($toPush.Count -eq 0) { Write-Host "no changes, nothing to push"; exit 0 }
Write-Host ("pushing {0} file(s) to {1}:{2}" -f $toPush.Count, $Server, $RemoteDir)
$toPush | ForEach-Object { Write-Host "  $_" }

# ---- transfer: data first, then stamped entries (avoid new data under old shell) ----
# single scp call = single connection; argument order preserves transfer order
$ordered = @($toPush | Where-Object { $_ -like "data-*" }) + @($toPush | Where-Object { $_ -notlike "data-*" })
$src = $ordered | ForEach-Object { Join-Path $Bank $_ }
Invoke-WithRetry "scp" { & $Scp -C $src "${Server}:${RemoteDir}/" }

# ---- remote verify in ONE ssh over HTTP (what users actually get), not the file on disk:
# a full platform release can re-point /banks/408 at a release-internal dir and silently
# shadow the shared folder; only the HTTP view catches that ----
$checkNames = @($ordered | Where-Object { $_ -like "data-*.json" }) -join " "
$remoteScript = "set -e; curl -sS http://127.0.0.1:8000/banks/408/index.html | grep -o '__BANK_DATA_VER__[^;]*' | head -1 | grep -o '[0-9]\+' | head -1; for f in $checkNames; do printf '%s ' `$f; curl -sS -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/banks/408/`$f; done"
$remoteOut = $null
for ($i = 1; $i -le 5 -and -not $remoteOut; $i++) {
    $remoteOut = & $Ssh $Server $remoteScript 2>$null
    if (-not $remoteOut) { Write-Host "verify ssh failed (attempt $i/5), retrying..."; Start-Sleep -Seconds 15 }
}
if (-not $remoteOut) { Die "verify ssh failed after 5 attempts" }
Write-Host "remote: $($remoteOut -join '; ')"
$remoteVer = ($remoteOut | Select-Object -First 1)
if ("$remoteVer" -notmatch [regex]::Escape($idxVer)) { Die "remote stamp check failed: remote='$remoteVer' local=$idxVer" }
foreach ($line in ($remoteOut | Select-Object -Skip 1)) {
    if ($line -notmatch " 200$") { Die "remote data file check failed: '$line'" }
}

# ---- record pushed hashes ----
($new.GetEnumerator() | ForEach-Object { "$($_.Key)=$($_.Value)" }) | Set-Content -LiteralPath $StateFile -Encoding UTF8
Write-Host "OK: remote __BANK_DATA_VER__=$idxVer, $($toPush.Count) file(s) hot-updated (no service restart)"

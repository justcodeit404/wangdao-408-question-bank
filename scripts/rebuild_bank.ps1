#!/usr/bin/env pwsh
# bank-408 one-shot rebuild + auto cache bump
# Usage:
#   powershell -File scripts/rebuild_bank.ps1
#   powershell -File scripts/rebuild_bank.ps1 -SkipTests
#   powershell -File scripts/rebuild_bank.ps1 -SkipScan
#   powershell -File scripts/rebuild_bank.ps1 -SampleSeed 20270117

param(
    [switch]$SkipTests,
    [switch]$SkipScan,
    [int]$SampleSeed = 0
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

# Build python needs PIL (fix_questions recrops). Prefer MIMO_PYTHON.
$buildPy = $env:MIMO_PYTHON
if (-not $buildPy) {
    $buildPy = "python"
}
# Test python needs pytest. Derive from repo root (avoid non-ASCII in this file
# so Windows PowerShell 5.1 does not mojibake the path).
$testPy = Join-Path $root "..\platform-v2\backend\.venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $testPy)) {
    $testPy = $buildPy
}

Write-Host "==> merge duplicate patches" -ForegroundColor Cyan
& $buildPy scripts/merge_patches.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> apply patches (fix_questions.py)" -ForegroundColor Cyan
& $buildPy scripts/fix_questions.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> normalize OCR spaces (normalize_spaces.py --apply)" -ForegroundColor Cyan
& $buildPy scripts/normalize_spaces.py --apply
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host "==> merge_courses.py" -ForegroundColor Cyan
& $buildPy scripts/merge_courses.py output/questions_all.json
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# wire_explanation rebuilds 答案图片 lines from real crops; without this step,
# curated patches that replace answer wholesale silently drop the lines (2026-09-29 incident)
Write-Host "==> wire answer crops + explanations (gen_answer_crops.py --write-expl x4)" -ForegroundColor Cyan
foreach ($k in @("ds", "coa", "net", "os")) {
    & $buildPy scripts/gen_answer_crops.py --course $k --write-expl
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

Write-Host "==> bump cache version (data content hash)" -ForegroundColor Cyan
& $buildPy scripts/bump_bank_version.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

if (-not $SkipTests) {
    Write-Host "==> pytest" -ForegroundColor Cyan
    & $testPy -m pytest tests/test_page_review_patches.py tests/test_notes_katex.py -q
    if ($LASTEXITCODE -ne 0) {
        Write-Host "tests failed" -ForegroundColor Red
        exit 1
    }
}

if (-not $SkipScan) {
    Write-Host "==> pattern scan" -ForegroundColor Cyan
    & $buildPy scripts/scan_patterns.py --summary
    Write-Host "==> option mismatch scan" -ForegroundColor Cyan
    & $buildPy scripts/scan_option_mismatch.py
}

if ($SampleSeed -gt 0) {
    Write-Host "==> sample audit seed=$SampleSeed n=20" -ForegroundColor Cyan
    & $buildPy scripts/sample_choice_audit.py $SampleSeed 20
}

Write-Host "==> done" -ForegroundColor Green
Write-Host "Next: review scan/sample hits, write patches, re-run this script, pack + deploy"

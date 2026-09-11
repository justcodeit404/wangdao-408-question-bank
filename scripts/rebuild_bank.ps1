#!/usr/bin/env pwsh
# bank-408 一键重建 + 自动 bump 缓存
# 用法：
#   powershell -File scripts/rebuild_bank.ps1
#   powershell -File scripts/rebuild_bank.ps1 -SkipTests

param(
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

Write-Host "==> 合并重复补丁" -ForegroundColor Cyan
python scripts/merge_patches.py

Write-Host "==> 应用补丁 fix_questions.py" -ForegroundColor Cyan
python scripts/fix_questions.py

Write-Host "==> merge_courses.py" -ForegroundColor Cyan
python scripts/merge_courses.py output/questions_all.json

if (-not $SkipTests) {
    Write-Host "==> pytest" -ForegroundColor Cyan
    $pytest = "C:\Users\16416\Desktop\考研\apps\platform-v2\backend\.venv\Scripts\python.exe"
    if (Test-Path $pytest) {
        & $pytest -m pytest tests/test_page_review_patches.py tests/test_notes_katex.py -q
    } else {
        python -m pytest tests/test_page_review_patches.py tests/test_notes_katex.py -q
    }
    if ($LASTEXITCODE -ne 0) {
        Write-Host "测试失败" -ForegroundColor Red
        exit 1
    }
}

Write-Host "==> 扫描高频 OCR 病征" -ForegroundColor Cyan
python scripts/scan_patterns.py

Write-Host "==> 完成" -ForegroundColor Green
Write-Host "提示：scripts/bump_bank_version.py 可根据 data.js hash 自动 bump 缓存"
Write-Host "  python scripts/bump_bank_version.py"

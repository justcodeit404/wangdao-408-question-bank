@echo off
chcp 65001 >nul 2>&1
cd /d "%~dp0"

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERR] python not found. Please install Python and add it to PATH.
    pause
    exit /b 1
)

echo Starting 408 Wangdao bank server on port 8080...
start "" "http://localhost:8080/"
python scripts/serve_bank.py 8080

if errorlevel 1 (
    echo.
    echo [ERR] Server failed to start.
    pause
    exit /b 1
)
exit /b 0

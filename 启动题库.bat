@echo off
chinese 27 王道《数据结构》题库 一键启动
chinese ---------------------------------------

cd /d "C:\Users\16416\Desktop\日常询问\408题库\math-bank"

chinese 检查端口 8000 是否被占用
netstat -ano | findstr ":8000 " >nul
if %ERRORLEVEL% ==0 (
    echo Port 8000 is in use. Trying to use a different port...
    set PORT=8001
) else (
    set PORT=8000
)

echo ============================================
echo    启动 HTTP 服务器 (端口 %PORT%)
echo    题库地址: http://localhost:%PORT%
echo ============================================
echo    按 Ctrl+C 停止服务器
echo.

start "" "http://localhost:%PORT%/"

python -m http.server %PORT%

pause

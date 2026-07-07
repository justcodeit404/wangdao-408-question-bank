#!/bin/bash
# 一键启动脚本（Git Bash / WSL）

DIR="$(cd "$(dirname "$0")/math-bank" && pwd)"
cd "$DIR" || exit 1

# 找一个空闲端口
PORT=8000
while netstat -ano 2>/dev/null | grep -q ":$PORT "; do
    PORT=$((PORT+1))
done

echo "============================================"
echo " 启动 HTTP 服务器 (端口 $PORT)"
echo " 题库地址: http://localhost:$PORT"
echo "============================================"

# 启动浏览器（后台）
(explorer.exe "http://localhost:$PORT/" 2>/dev/null || xdg-open "http://localhost:$PORT/" 2>/dev/null) &

python -m http.server $PORT

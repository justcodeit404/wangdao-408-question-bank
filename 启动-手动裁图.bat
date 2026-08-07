@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 有图选择题 · 手动框选裁图
echo 打开后会自动对准当前题区域（不再缩在角落）
echo 左键框选 ^| 右键平移 ^| 滚轮缩放 ^| F对准本题 ^| S保存 ^| N/P翻题
echo.
python apps\bank-408\scripts\manual_crop_fig.py --course ds --start 213
if errorlevel 1 pause

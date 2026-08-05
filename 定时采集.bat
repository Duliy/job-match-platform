@echo off
chcp 65001 >nul
title 定时采集 - 每日08:00自动更新

cd /d "%~dp0"

echo.
echo ╔══════════════════════════════════════════╗
echo ║   招聘信息定时采集（每天 08:00 运行）    ║
echo ║   按 Ctrl+C 停止                         ║
echo ╚══════════════════════════════════════════╝
echo.

echo 启动定时采集服务...
echo 当前时间: %time%
echo 下次采集: 明天 08:00
echo.

python crawler.py --schedule --time 08:00

pause

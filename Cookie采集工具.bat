@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cookie 采集工具 - 就业服务平台

echo ============================================================
echo   Cookie 采集工具
echo   用途：智联招聘、猎聘网需要登录才能采集完整数据，
echo   本工具帮你完成登录并生成 Cookie 文件。
echo   生成后请打开管理后台 → 爬虫系统 → Cookie 管理 上传。
echo ============================================================
echo.

if not exist "runtime\python\python.exe" (
  echo [错误] 未找到内嵌运行环境，请确认完整解压了整个文件夹。
  pause
  exit /b 1
)

runtime\python\python.exe cookie_collector.py
pause

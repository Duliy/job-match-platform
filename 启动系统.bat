@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 就业服务平台（服务运行中，请勿关闭本窗口）

if not exist "runtime\python\python.exe" (
  echo [错误] 未找到内嵌运行环境 runtime\python\python.exe
  echo 请确认完整解压了整个文件夹，而不是只复制了本文件。
  echo.
  pause
  exit /b 1
)

runtime\python\python.exe serve.py
echo.
echo 服务已停止。
pause

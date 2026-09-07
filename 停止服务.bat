@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 停止服务 - 就业服务平台

:: 结束占用 8000 端口的 python 进程
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000 " ^| findstr "LISTENING"') do (
  echo 正在停止服务进程 PID=%%a
  taskkill /PID %%a /F >nul 2>&1
)
echo [OK] 服务已停止
timeout /t 2 >nul

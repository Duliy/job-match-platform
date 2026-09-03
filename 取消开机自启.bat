@echo off
chcp 65001 >nul
title 取消开机自启 - 就业服务平台

net session >nul 2>&1
if errorlevel 1 (
  echo 正在请求管理员权限...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)

schtasks /delete /tn "JobBoard就业服务平台" /f
if %errorlevel%==0 (echo [OK] 开机自启已取消) else (echo [提示] 未找到开机自启任务，可能本来就未安装)
echo.
pause

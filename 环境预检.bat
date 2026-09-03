@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 环境预检 - 就业服务平台
if exist "runtime\python\python.exe" (
  runtime\python\python.exe 环境预检.py
) else (
  echo 未找到内嵌 Python，尝试使用系统 Python...
  python 环境预检.py
)
pause

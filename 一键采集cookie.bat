@echo off
chcp 65001 >nul
cd /d "%~dp0"
python cookie_collector.py
pause

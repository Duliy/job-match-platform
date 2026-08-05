@echo off
chcp 65001 >nul
title JobBoard Launcher
cd /d "%~dp0"

echo ============================================
echo   JobBoard Career Service Platform
echo ============================================
echo.

:: Check Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo.
    echo Please install Python 3.10+ from:
    echo   https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

:: Check Node.js
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found!
    echo.
    echo Please install Node.js LTS from:
    echo   https://nodejs.org/en/download
    echo.
    pause
    exit /b 1
)

:: Check launcher.py exists
if not exist "%~dp0launcher.py" (
    echo [ERROR] launcher.py not found!
    echo.
    echo Current directory: %~dp0
    echo.
    echo Possible reasons:
    echo   1. This .bat file is NOT placed inside the job-board folder
    echo   2. The job-board project files are incomplete
    echo.
    echo Please make sure the job-board folder contains these files:
    echo   - launcher.py
    echo   - index.html
    echo   - crawler.py
    echo   - requirements.txt
    echo   - data\ folder
    echo   - cookies\ folder
    echo.
    pause
    exit /b 1
)

echo Python and Node.js detected. Starting JobBoard...
echo.
python launcher.py

if errorlevel 1 (
    echo.
    echo [ERROR] launcher.py exited with error code %errorlevel%
    pause
)

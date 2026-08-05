@echo off
chcp 65001 >nul
echo ============================================
echo   JobBoard 启动器 EXE 打包工具
echo ============================================
echo.

set PYTHON=C:\Users\QinNa.NiceBuddy\.workbuddy\binaries\python\envs\jobboard\Scripts\python.exe
set PROJDIR=C:\Users\QinNa.NiceBuddy\WorkBuddy\20260513100852\job-board
set DISTDIR=%PROJDIR%\dist

echo [1/3] 检查 PyInstaller ...
"%PYTHON%" -c "import PyInstaller; print('PyInstaller', PyInstaller.__version__)"
if errorlevel 1 (
    echo 安装 PyInstaller ...
    "%PYTHON%" -m pip install pyinstaller -q
)

echo.
echo [2/3] 开始打包 launcher.py ...
cd /d "%PROJDIR%"
"%PYTHON%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --name "JobBoard启动器" ^
    --distpath "%DISTDIR%" ^
    --workpath "%PROJDIR%\build" ^
    --specpath "%PROJDIR%" ^
    --add-data "index.html;." ^
    --add-data "resume_match.html;." ^
    --add-data "admin.html;." ^
    --add-data "manifest.json;." ^
    --add-data "requirements.txt;." ^
    --add-data "requirements_match.txt;." ^
    --add-data "serve.js;." ^
    "%PROJDIR%\launcher.py"

echo.
if exist "%DISTDIR%\JobBoard启动器.exe" (
    for %%F in ("%DISTDIR%\JobBoard启动器.exe") do echo [3/3] ✅ 打包成功：%%~zF 字节
    echo 输出位置：%DISTDIR%\JobBoard启动器.exe
) else (
    echo [3/3] ❌ 打包失败，请查看上方错误信息
)
echo.
pause

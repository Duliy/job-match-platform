@echo off
chcp 65001 >nul
cd /d "%~dp0"
title 安装开机自启 - 就业服务平台

:: 需要管理员权限，自动提权
net session >nul 2>&1
if errorlevel 1 (
  echo 正在请求管理员权限...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)

echo 正在配置开机自动启动...
echo.

:: 防火墙放行（顺手做掉，一劳永逸）
netsh advfirewall firewall delete rule name="JobBoard-8000" >nul 2>&1
netsh advfirewall firewall add rule name="JobBoard-8000" dir=in action=allow protocol=TCP localport=8000 >nul 2>&1
if %errorlevel%==0 (echo [OK] 防火墙已放行端口 8000) else (echo [提示] 防火墙规则添加失败，可忽略)

:: 创建开机计划任务（SYSTEM 账户，无需登录即运行）
schtasks /delete /tn "JobBoard就业服务平台" /f >nul 2>&1
schtasks /create /tn "JobBoard就业服务平台" /tr "\"%~dp0runtime\python\pythonw.exe\" \"%~dp0serve.py\" --background" /sc onstart /ru SYSTEM /rl HIGHEST /f
if %errorlevel%==0 (
  echo [OK] 开机自启已安装。服务器重启后服务会自动运行。
) else (
  echo [错误] 计划任务创建失败，请截图本窗口联系技术支持。
)
echo.
pause

@echo off
chcp 65001 > nul
cd /d "%~dp0"
echo.
echo ╔══════════════════════════════════════════════════╗
echo ║       招聘平台 手动登录 + 真实数据采集          ║
echo ╚══════════════════════════════════════════════════╝
echo.
echo 运行流程：
echo   1. 打开浏览器，请依次在各平台完成登录
echo   2. 登录后按 Enter 继续下一个平台
echo   3. 所有平台登录完成后，输入搜索关键词
echo   4. 开始采集数据并保存到 data/jobs_latest.json
echo.
python login_helper.py
echo.
echo 采集完成！按任意键退出...
pause > nul

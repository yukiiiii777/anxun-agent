@echo off
chcp 65001 >nul
setlocal
title 安巡 Agent · 研判台（真模型）

rem 找 Python：优先用本机自带的，其次系统里的
set "PY="
if exist "%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe" (
  set "PY=%USERPROFILE%\.dsh\dsh-runtimes\dsh-primary-runtime\dependencies\python\python.exe"
)
if not defined PY (
  python -c "import sys" >nul 2>nul && set "PY=python"
)
if not defined PY (
  py -3 -c "import sys" >nul 2>nul && set "PY=py -3"
)

if not defined PY (
  echo.
  echo   没找到 Python。装一个 3.10 以上的版本再来：
  echo   https://www.python.org/downloads/  安装时勾选 "Add python.exe to PATH"
  echo.
  pause
  exit /b 1
)

cd /d "%~dp0"
echo.
echo   安巡 Agent 研判台正在启动，浏览器会自动打开 http://127.0.0.1:8611
echo   右侧面板会用 best.pt 实跑：现场照片 - 检测 - 四态 - 定级 - 工单
echo   关掉这个黑窗口就停止。
echo.
%PY% serve.py --open
pause

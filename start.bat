@echo off
chcp 65001 >nul
title AI 量化交易系统

echo.
echo ╔══════════════════════════════════════╗
echo ║  🤖 AI 量化交易系统 启动中...       ║
echo ╚══════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ❌ 未找到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM 检查 Flask（确认服务器需要）
python -c "import flask" >nul 2>&1
if %errorlevel% neq 0 (
    echo 📦 安装 Flask...
    pip install flask -q
)

echo.
echo 🚀 启动确认服务器（端口 5000）...
start "AI-Confirm" cmd /c "cd /d %~dp0 && python confirm_server.py"

timeout /t 2 /nobreak >nul

echo 🧠 启动 AI 决策引擎...
echo.
echo ──────────────────────────────────────
echo  交易时间：周一至周五 9:30-11:30, 13:00-15:00
echo  AI 每 3 分钟扫描一次市场
echo  按 Ctrl+C 停止
echo ──────────────────────────────────────
echo.

python ai_trader.py

echo.
echo 🛑 AI 交易系统已停止
pause

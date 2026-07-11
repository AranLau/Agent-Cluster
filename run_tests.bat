@echo off
chcp 65001 >nul
echo ╔══════════════════════════════════════════╗
echo ║   Agent Cluster 自动化测试 — Round 1/2  ║
echo ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

python -m pytest tests/ -v --tb=short --durations=10 2>&1
set ROUND1=%ERRORLEVEL%

echo.
echo ╔══════════════════════════════════════════╗
echo ║   Agent Cluster 自动化测试 — Round 2/2  ║
echo ╚══════════════════════════════════════════╝
echo.

python -m pytest tests/ -v --tb=short --durations=10 2>&1
set ROUND2=%ERRORLEVEL%

echo.
echo ════════════════════════════════════════════

if %ROUND1% EQU 0 if %ROUND2% EQU 0 (
    echo ✅ 两轮测试全部通过！可以推 git 了。
    echo    git add . ^&^& git commit -m "feat: agent cluster v1.0" ^&^& git push
    exit /b 0
) else (
    echo ❌ 测试失败！Round1: %ROUND1%  Round2: %ROUND2%
    echo    请先修复问题再推送。
    exit /b 1
)

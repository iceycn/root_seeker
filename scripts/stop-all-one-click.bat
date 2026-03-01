@echo off
chcp 65001 >nul
:: 停止一键启动的所有服务
:: 用法: scripts\stop-all-one-click.bat

echo === 停止服务 ===

for %%p in (8000 8080 6333 6070) do (
    for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":%%p" ^| findstr "LISTENING" 2^>nul') do (
        if not "%%a"=="" if not "%%a"=="0" (
            echo   终止端口 %%p 的进程 PID %%a
            taskkill /F /PID %%a >nul 2>&1
        )
    )
)

echo   完成

@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
:: 一键启动：Qdrant、Zoekt、RootSeeker、RootSeeker Admin（后台运行）
:: 用法: scripts\start-all-one-click.bat
:: 停止: scripts\stop-all-one-click.bat

cd /d "%~dp0\.."
set "PROJECT_ROOT=%CD%"
set "LOG_DIR=%PROJECT_ROOT%\logs"
set "TOOLS_DIR=%PROJECT_ROOT%\tools"
set "INDEX_DIR=%PROJECT_ROOT%\data\zoekt\index"

if not exist "%LOG_DIR%" mkdir "%LOG_DIR%"

echo === 一键启动 ===

:: 检查端口是否占用
call :check_port 6333
if %errorlevel% equ 1 (
    echo [Qdrant] 端口 6333 已占用，跳过
) else (
    if exist "%TOOLS_DIR%\qdrant.exe" (
        echo [Qdrant] 启动中...
        start /b "" cmd /c ""%TOOLS_DIR%\qdrant.exe" --config-path "%PROJECT_ROOT%\config\qdrant_config.yaml" >> "%LOG_DIR%\qdrant.log" 2>&1"
        timeout /t 1 /nobreak >nul
        echo [Qdrant] 已启动
    ) else if exist "%TOOLS_DIR%\qdrant" (
        echo [Qdrant] 启动中...
        start /b "" cmd /c ""%TOOLS_DIR%\qdrant" --config-path "%PROJECT_ROOT%\config\qdrant_config.yaml" >> "%LOG_DIR%\qdrant.log" 2>&1"
        timeout /t 1 /nobreak >nul
        echo [Qdrant] 已启动
    ) else (
        echo [Qdrant] 未找到 tools\qdrant，跳过（请手动下载或执行 install-without-docker.ps1）
    )
)

:: Zoekt
call :check_port 6070
if %errorlevel% equ 1 (
    echo [Zoekt] 端口 6070 已占用，跳过
) else (
    set "ZOOKT_BIN="
    where zoekt-webserver >nul 2>&1 && set "ZOOKT_BIN=zoekt-webserver"
    if "!ZOOKT_BIN!"=="" (
        for /f "tokens=*" %%i in ('go env GOPATH 2^>nul') do set "GOPATH=%%i"
        if exist "!GOPATH!\bin\zoekt-webserver.exe" set "ZOOKT_BIN=!GOPATH!\bin\zoekt-webserver.exe"
        if exist "!GOPATH!\bin\zoekt-webserver" set "ZOOKT_BIN=!GOPATH!\bin\zoekt-webserver"
    )
    if not "!ZOOKT_BIN!"=="" if exist "%INDEX_DIR%" (
        echo [Zoekt] 启动中...
        start /b "" cmd /c ""!ZOOKT_BIN!" -index "%INDEX_DIR%" -listen :6070 -rpc >> "%LOG_DIR%\zoekt.log" 2>&1"
        timeout /t 1 /nobreak >nul
        echo [Zoekt] 已启动
    ) else (
        echo [Zoekt] 未安装或索引不存在，跳过（需先执行 index-zoekt-all.ps1 或 go install）
    )
)

:: RootSeeker (Python)
call :check_port 8000
if %errorlevel% equ 1 (
    echo [RootSeeker] 端口 8000 已占用，跳过
) else (
    echo [RootSeeker] 启动中...
    start /b "" cmd /c "python -m uvicorn main:app --host 0.0.0.0 --port 8000 >> "%LOG_DIR%\root-seeker.log" 2>&1"
    timeout /t 2 /nobreak >nul
    echo [RootSeeker] 已启动
)

:: RootSeeker Admin (Java)
call :check_port 8080
if %errorlevel% equ 1 (
    echo [RootSeeker Admin] 端口 8080 已占用，跳过
) else (
    if exist "%PROJECT_ROOT%\ruoyi-rootseeker-admin" (
        echo [RootSeeker Admin] 启动中（首次需下载依赖，较慢）...
        pushd "%PROJECT_ROOT%\ruoyi-rootseeker-admin"
        start /b "" cmd /c "mvn spring-boot:run -pl ruoyi-admin -q >> "%LOG_DIR%\root-seeker-admin.log" 2>&1"
        popd
        timeout /t 2 /nobreak >nul
        echo [RootSeeker Admin] 已启动
    ) else (
        echo [RootSeeker Admin] 未找到 ruoyi-rootseeker-admin 目录，跳过
    )
)

echo.
echo 已启动的服务:
echo   - RootSeeker:      http://localhost:8000
echo   - RootSeeker Admin: http://localhost:8080
echo   - Qdrant:          http://localhost:6333
echo   - Zoekt:           http://localhost:6070
echo.
echo  日志: %LOG_DIR%\
echo  停止: scripts\stop-all-one-click.bat
echo.
goto :eof

:check_port
netstat -ano | findstr ":%1 " | findstr "LISTENING" >nul 2>&1
if %errorlevel% equ 0 (exit /b 1) else (exit /b 0)

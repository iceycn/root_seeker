# RootSeeker Docker 一键启动（开箱即用）
# 用法: 在项目根目录执行  .\root_seeker_docker\start.ps1
#       .\root_seeker_docker\start.ps1 -Pull   # 使用预构建镜像

param([switch]$Pull)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# 1. 确保 data 目录存在（repos、repos_from_git、audit）
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\repos") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\repos_from_git") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\audit") | Out-Null

# 2. 启动
Set-Location $ScriptDir
if ($Pull) {
    Write-Host ""
    Write-Host "=== 启动 Docker 服务（使用预构建镜像 ghcr.io/iceycn/root-seeker:latest）==="
    docker compose build zoekt root-seeker-admin
    docker compose -f docker-compose.yml -f docker-compose.pull.yml up -d --no-build
} else {
    Write-Host ""
    Write-Host "=== 启动 Docker 服务（本地构建，MySQL 首次启动将自动初始化表）==="
    docker compose up -d --build
}

Write-Host ""
Write-Host "=== 服务已启动 ==="
Write-Host "  RootSeeker:       http://localhost:8000"
Write-Host "  RootSeeker Admin: http://localhost:8088  （默认 admin/admin123，AI应用配置在 Git源码管理 下）"
Write-Host "  Qdrant:           http://localhost:6333"
Write-Host "  Zoekt:            http://localhost:6070"
Write-Host ""
Write-Host "健康检查: curl http://localhost:8000/healthz"
Write-Host "查看日志: cd root_seeker_docker; docker compose logs -f"
Write-Host "停止服务: cd root_seeker_docker; docker compose down"

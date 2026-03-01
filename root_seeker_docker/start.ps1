# RootSeeker Docker 一键启动（开箱即用）
# 用法: 在项目根目录执行  .\root_seeker_docker\start.ps1

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

$Config = Join-Path $ProjectRoot "config.yaml"
$ConfigExample = Join-Path $ProjectRoot "config.example.yaml"
$ConfigDocker = Join-Path $ScriptDir "config.docker.yaml"

# 1. 若 config.yaml 不存在，从 config.example.yaml 复制
if (-not (Test-Path $Config)) {
    Write-Host "config.yaml 不存在，从 config.example.yaml 复制..."
    Copy-Item $ConfigExample $Config
    Write-Host "  已创建默认配置，服务可启动。完整功能需编辑 config.yaml 填写 aliyun_sls、llm 等"
}

# 2. 合并 Docker 专用配置（qdrant、zoekt、config_db、repos 路径）
$MergeScript = Join-Path $ScriptDir "merge_config.py"
try {
    python $MergeScript $Config $ConfigDocker 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "已合并 config.docker.yaml（容器内服务地址）" }
} catch { }

# 3. 确保 data 目录存在（repos、repos_from_git、audit）
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\repos") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\repos_from_git") | Out-Null
New-Item -ItemType Directory -Force -Path (Join-Path $ProjectRoot "data\audit") | Out-Null

# 4. 启动
Write-Host ""
Write-Host "=== 启动 Docker 服务（MySQL 首次启动将自动初始化表）==="
Set-Location $ScriptDir
docker compose up -d

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

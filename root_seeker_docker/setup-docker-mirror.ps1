# Docker 国内镜像加速配置脚本（Windows）
# 需以管理员身份运行，或手动按提示操作
# 注意：错误配置可能导致 Docker 无法启动，脚本会自动备份原配置

$ConfigPath = "$env:ProgramData\Docker\config\daemon.json"
$Mirrors = @(
    "https://docker.xuanyuan.me",
    "https://docker.1panel.live",
    "https://hub.rat.dev",
    "https://docker.m.daocloud.io"
)

Write-Host "=== Docker 镜像加速配置 ===" -ForegroundColor Cyan
Write-Host ""

# 检查 Docker 是否安装
if (-not (Test-Path "$env:ProgramData\Docker")) {
    Write-Host "未检测到 Docker 安装目录，请确认已安装 Docker Desktop。" -ForegroundColor Yellow
    exit 1
}

# 备份原配置
if (Test-Path $ConfigPath) {
    $BackupPath = "$ConfigPath.bak.$(Get-Date -Format 'yyyyMMdd-HHmmss')"
    Copy-Item $ConfigPath $BackupPath -Force
    Write-Host "已备份原配置到: $BackupPath" -ForegroundColor Gray
}

# 读取现有配置
$config = $null
if (Test-Path $ConfigPath) {
    try {
        $config = Get-Content $ConfigPath -Raw | ConvertFrom-Json
    } catch {
        Write-Host "现有配置解析失败，将创建新配置。" -ForegroundColor Yellow
    }
}

# 添加或更新 registry-mirrors
if ($null -eq $config) {
    $config = [PSCustomObject]@{}
}
$config | Add-Member -NotePropertyName "registry-mirrors" -NotePropertyValue $Mirrors -Force

# 确保目录存在
$dir = Split-Path $ConfigPath
if (-not (Test-Path $dir)) {
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
}

# 写入配置
try {
    $config | ConvertTo-Json -Depth 10 | Set-Content $ConfigPath -Encoding UTF8 -NoNewline
    Write-Host "配置已写入: $ConfigPath" -ForegroundColor Green
    Write-Host ""
    Write-Host "请重启 Docker Desktop 使配置生效。" -ForegroundColor Yellow
    Write-Host "  - 右键任务栏 Docker 图标 -> Restart" -ForegroundColor Gray
    Write-Host "  - 或关闭后重新打开 Docker Desktop" -ForegroundColor Gray
} catch {
    Write-Host "写入失败（可能需管理员权限）。请手动操作：" -ForegroundColor Red
    Write-Host "  1. 打开 Docker Desktop -> Settings -> Docker Engine" -ForegroundColor Gray
    Write-Host "  2. 在 JSON 中添加: `"registry-mirrors`": [`"https://docker.xuanyuan.me`", `"https://docker.m.daocloud.io`"]" -ForegroundColor Gray
    Write-Host "  3. 点击 Apply & Restart" -ForegroundColor Gray
    Write-Host ""
    Write-Host "或复制 daemon.json.example 到 $ConfigPath" -ForegroundColor Gray
}

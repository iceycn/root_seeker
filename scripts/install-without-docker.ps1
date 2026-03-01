# RootSeeker 依赖安装（Windows，不依赖 Docker）
# 用法: 在项目根目录执行  .\scripts\install-without-docker.ps1

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$ToolsDir = Join-Path $ProjectRoot "tools"
$QdrantVersion = if ($env:QDRANT_VERSION) { $env:QDRANT_VERSION } else { "v1.16.3" }

Write-Host "=== 1. Python 依赖（RootSeeker）===" -ForegroundColor Cyan
pip install -e .

Write-Host "`n=== 2. Go（用于 Zoekt）===" -ForegroundColor Cyan
if (-not (Get-Command go -ErrorAction SilentlyContinue)) {
    Write-Host "未检测到 Go，请先安装: https://go.dev/dl/" -ForegroundColor Red
    exit 1
}
go version

Write-Host "`n=== 3. Zoekt（词法检索）===" -ForegroundColor Cyan
go install github.com/google/zoekt/cmd/zoekt-index@latest
go install github.com/google/zoekt/cmd/zoekt-webserver@latest
$GOPATH = go env GOPATH
Write-Host "Zoekt 已安装到: $GOPATH\bin"

Write-Host "`n=== 4. Qdrant（向量库，Windows 二进制）===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
$QdrantZip = "qdrant-x86_64-pc-windows-msvc.zip"
$QdrantUrl = "https://github.com/qdrant/qdrant/releases/download/$QdrantVersion/$QdrantZip"
$QdrantExe = Join-Path $ToolsDir "qdrant.exe"

if (-not (Test-Path $QdrantExe)) {
    Write-Host "下载 Qdrant: $QdrantUrl"
    $ZipPath = Join-Path $ToolsDir $QdrantZip
    Invoke-WebRequest -Uri $QdrantUrl -OutFile $ZipPath -UseBasicParsing
    Expand-Archive -Path $ZipPath -DestinationPath $ToolsDir -Force
    Remove-Item $ZipPath -Force
    $Extracted = Get-ChildItem -Path $ToolsDir -Filter "qdrant.exe" -Recurse | Select-Object -First 1
    if ($Extracted -and $Extracted.DirectoryName -ne $ToolsDir) {
        Move-Item $Extracted.FullName $QdrantExe -Force
        Get-ChildItem $ToolsDir -Directory | Remove-Item -Recurse -Force
    }
    Write-Host "Qdrant 已解压到: $QdrantExe"
} else {
    Write-Host "已存在 $QdrantExe，跳过下载"
}

Write-Host "`n=== 安装完成 ===" -ForegroundColor Green
Write-Host "`n后续步骤:"
Write-Host "  1. 复制配置: Copy-Item config.example.yaml config.yaml  并修改 config.yaml"
Write-Host "  2. 一键启动: .\scripts\start-all-one-click.bat"
Write-Host "  3. 一键停止: .\scripts\stop-all-one-click.bat"

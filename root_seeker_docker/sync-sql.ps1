# 同步 ruoyi-rootseeker-admin/sql 到 mysql-init/sql（当上游 SQL 更新时执行）
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Source = Join-Path (Split-Path -Parent $ScriptDir) "ruoyi-rootseeker-admin\sql"
$Dest = Join-Path $ScriptDir "mysql-init\sql"
if (Test-Path $Source) {
    Copy-Item "$Source\*.sql" $Dest -Force
    Write-Host "已同步 SQL 到 mysql-init/sql"
} else {
    Write-Host "源目录不存在: $Source"
}

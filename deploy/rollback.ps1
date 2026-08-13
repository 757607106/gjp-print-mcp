<#
.SYNOPSIS
    yunprint-print MCP 服务一键回滚脚本
.DESCRIPTION
    回退到上一个 Git 提交版本，同步依赖并重启服务
.PARAMETER Commit
    指定回退到的 commit hash（可选），默认回退到上一个提交
.EXAMPLE
    .\rollback.ps1                  # 回退到上一个提交
    .\rollback.ps1 -Commit abc1234  # 回退到指定提交
#>
param(
    [string]$Commit = ""
)

$ErrorActionPreference = "Stop"
$ProjectDir = "D:\gjp-print-mcp"
$ServiceName = "yunprint-print"

Set-Location $ProjectDir

if ($Commit) {
    Write-Host "[1/4] 回退到指定提交 $Commit..." -ForegroundColor Yellow
    git checkout $Commit
} else {
    Write-Host "[1/4] 回退到上一个提交..." -ForegroundColor Yellow
    git checkout HEAD~1
}

if ($LASTEXITCODE -ne 0) {
    Write-Host "      git checkout 失败" -ForegroundColor Red
    exit 1
}

Write-Host "      当前版本: $(git rev-parse --short HEAD)"
Write-Host "      提交信息: $(git log -1 --format='%s')"

Write-Host "[2/4] 同步依赖..." -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "      uv sync 失败" -ForegroundColor Red
    exit 1
}

Write-Host "[3/4] 重启服务..." -ForegroundColor Cyan
nssm restart $ServiceName

Write-Host "[4/4] 等待服务启动..." -ForegroundColor Cyan
Start-Sleep -Seconds 3

# 健康检查
try {
    $response = Invoke-WebRequest -Uri "http://127.0.0.1:8931/mcp" -Method POST `
        -Headers @{
            "Authorization" = "Bearer health-check"
            "Content-Type"  = "application/json"
            "Accept"        = "application/json, text/event-stream"
        } `
        -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"rollback-check","version":"1.0"}}}' `
        -TimeoutSec 5 -ErrorAction Stop
    Write-Host ""
    Write-Host "=== 回滚完成 ===" -ForegroundColor Green
    Write-Host "版本: $(git rev-parse --short HEAD)"
    Write-Host "提交: $(git log -1 --format='%s')"
}
catch {
    Write-Host ""
    Write-Host "=== 警告：健康检查未通过 ===" -ForegroundColor Red
    Write-Host "请检查日志：type $ProjectDir\logs\stderr.log"
    exit 1
}

Write-Host ""
Write-Host "提示：回到最新版本请执行：" -ForegroundColor DarkGray
Write-Host "  git checkout main && git pull" -ForegroundColor DarkGray

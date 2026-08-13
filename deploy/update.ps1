<#
.SYNOPSIS
    yunprint-print MCP 服务一键更新脚本
.DESCRIPTION
    执行 git pull → uv sync → 重启 NSSM 服务 → 健康检查
    预计停机时间 3-5 秒（仅服务重启期间）
.PARAMETER Branch
    Git 分支名，默认 main
.EXAMPLE
    .\update.ps1
    .\update.ps1 -Branch dev
#>
param(
    [string]$Branch = "main"
)

$ErrorActionPreference = "Stop"
$ProjectDir = "D:\gjp-print-mcp"
$ServiceName = "yunprint-print"
$HealthUrl = "http://127.0.0.1:8931/mcp"
$HealthTimeout = 10

Set-Location $ProjectDir

Write-Host "[1/5] 拉取最新代码 ($Branch)..." -ForegroundColor Cyan
git fetch origin $Branch
$localHash = git rev-parse HEAD
$remoteHash = git rev-parse "origin/$Branch"

if ($localHash -eq $remoteHash) {
    Write-Host "      已是最新版本，无需更新" -ForegroundColor Green
    return
}

git pull origin $Branch
if ($LASTEXITCODE -ne 0) {
    Write-Host "      git pull 失败" -ForegroundColor Red
    exit 1
}

Write-Host "[2/5] 同步依赖..." -ForegroundColor Cyan
uv sync
if ($LASTEXITCODE -ne 0) {
    Write-Host "      uv sync 失败" -ForegroundColor Red
    exit 1
}

Write-Host "[3/5] 重启服务（停机开始）..." -ForegroundColor Yellow
nssm restart $ServiceName
if ($LASTEXITCODE -ne 0) {
    Write-Host "      服务重启失败" -ForegroundColor Red
    exit 1
}

Write-Host "[4/5] 等待服务启动..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

Write-Host "[5/5] 健康检查..." -ForegroundColor Cyan
$checkPassed = $false
for ($i = 1; $i -le $HealthTimeout; $i++) {
    try {
        $response = Invoke-WebRequest -Uri $HealthUrl -Method POST `
            -Headers @{
                "Authorization"     = "Bearer health-check"
                "Content-Type"      = "application/json"
                "Accept"            = "application/json, text/event-stream"
            } `
            -Body '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"deploy-check","version":"1.0"}}}' `
            -TimeoutSec 3 -ErrorAction Stop
        if ($response.StatusCode -eq 200) {
            $checkPassed = $true
            break
        }
    }
    catch {
        # 服务还在启动中，继续等待
    }
    Start-Sleep -Seconds 1
    Write-Host "      等待中... ($i/$HealthTimeout)"
}

if ($checkPassed) {
    Write-Host ""
    Write-Host "=== 更新完成 ===" -ForegroundColor Green
    Write-Host "版本: $(git rev-parse --short HEAD)"
    Write-Host "提交: $(git log -1 --format='%s')"
    Write-Host "服务: $ServiceName 已启动"
    Write-Host "停机时间: 约 3-5 秒" -ForegroundColor DarkGray
}
else {
    Write-Host ""
    Write-Host "=== 警告：健康检查未通过 ===" -ForegroundColor Red
    Write-Host "服务可能未正常启动，请检查日志："
    Write-Host "  type $ProjectDir\logs\stderr.log"
    Write-Host "  nssm status $ServiceName"
    exit 1
}

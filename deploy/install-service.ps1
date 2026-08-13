<#
.SYNOPSIS
    yunprint-print MCP 服务 Windows 服务注册脚本（一次性执行）
.DESCRIPTION
    使用 NSSM 将 uvicorn 注册为 Windows 服务，实现：
    - 开机自启
    - 崩溃自动重启（5 秒后）
    - 日志自动轮转（10MB/文件，保留 5 个）
.PARAMETER ProjectDir
    项目目录，默认 D:\gjp-print-mcp
.EXAMPLE
    .\install-service.ps1
    .\install-service.ps1 -ProjectDir "E:\apps\gjp-print-mcp"
#>
param(
    [string]$ProjectDir = "D:\gjp-print-mcp"
)

$ErrorActionPreference = "Stop"
$ServiceName = "yunprint-print"
$PythonExe = Join-Path $ProjectDir ".venv\Scripts\python.exe"
$LogDir = Join-Path $ProjectDir "logs"

# 检查 NSSM 是否可用
if (-not (Get-Command nssm -ErrorAction SilentlyContinue)) {
    Write-Host "错误：未找到 nssm，请从 https://nssm.cc 下载并放入 PATH" -ForegroundColor Red
    exit 1
}

# 检查 Python 解释器
if (-not (Test-Path $PythonExe)) {
    Write-Host "错误：未找到 Python 解释器 $PythonExe" -ForegroundColor Red
    Write-Host "请先在 $ProjectDir 执行 uv sync" -ForegroundColor Yellow
    exit 1
}

# 检查 .env
$EnvFile = Join-Path $ProjectDir ".env"
if (-not (Test-Path $EnvFile)) {
    Write-Host "错误：未找到 .env 文件，请配置后再安装服务" -ForegroundColor Red
    exit 1
}

# 创建日志目录
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir | Out-Null
    Write-Host "已创建日志目录: $LogDir" -ForegroundColor Green
}

# 如果服务已存在，先移除
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "服务 $ServiceName 已存在，正在移除旧服务..." -ForegroundColor Yellow
    nssm stop $ServiceName 2>$null
    Start-Sleep -Seconds 2
    nssm remove $ServiceName confirm
}

# 注册服务
Write-Host "注册 Windows 服务 $ServiceName ..." -ForegroundColor Cyan
nssm install $ServiceName $PythonExe "-m yunprint --host 0.0.0.0 --port 8931"
nssm set $ServiceName AppDirectory $ProjectDir

# 日志配置
nssm set $ServiceName AppStdout (Join-Path $LogDir "stdout.log")
nssm set $ServiceName AppStderr (Join-Path $LogDir "stderr.log")
nssm set $ServiceName AppRotateFiles 1
nssm set $ServiceName AppRotateBytes 10485760
nssm set $ServiceName AppRotateBackups 5

# 崩溃自动重启
nssm set $ServiceName AppRestartDelay 5000

# 开机自启
nssm set $ServiceName Start SERVICE_AUTO_START

# 启动服务
Write-Host "启动服务..." -ForegroundColor Cyan
nssm start $ServiceName
Start-Sleep -Seconds 3

# 验证
$status = nssm status $ServiceName
if ($status -eq "SERVICE_RUNNING") {
    Write-Host ""
    Write-Host "=== 服务安装完成 ===" -ForegroundColor Green
    Write-Host "服务名:   $ServiceName"
    Write-Host "项目目录: $ProjectDir"
    Write-Host "监听地址: 0.0.0.0:8931"
    Write-Host "日志目录: $LogDir"
    Write-Host ""
    Write-Host "常用命令：" -ForegroundColor DarkGray
    Write-Host "  nssm start $ServiceName       # 启动" -ForegroundColor DarkGray
    Write-Host "  nssm stop $ServiceName        # 停止" -ForegroundColor DarkGray
    Write-Host "  nssm restart $ServiceName     # 重启" -ForegroundColor DarkGray
    Write-Host "  nssm status $ServiceName      # 状态" -ForegroundColor DarkGray
    Write-Host "  .\update.ps1                  # 一键更新" -ForegroundColor DarkGray
    Write-Host "  .\rollback.ps1                # 一键回滚" -ForegroundColor DarkGray
} else {
    Write-Host "服务启动失败，状态: $status" -ForegroundColor Red
    Write-Host "请检查日志: type $LogDir\stderr.log" -ForegroundColor Yellow
    exit 1
}

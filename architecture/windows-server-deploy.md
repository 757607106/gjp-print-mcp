# Windows Server 2019 Datacenter 部署与更新指南

yunprint-print MCP 服务在 Windows Server 2019 Datacenter 上的完整部署、
日常更新和运维指南。使用 NSSM 将服务注册为 Windows 系统服务，配合
PowerShell 脚本实现一键更新和回滚，停机时间约 3-5 秒。

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [首次部署](#首次部署)
- [服务管理](#服务管理)
- [日常更新](#日常更新)
- [版本回滚](#版本回滚)
- [运维速查](#运维速查)
- [故障排查](#故障排查)

---

## 架构概览

```
GitHub 仓库 (757607106/gjp-print-mcp)
    ↓ git pull
Windows Server 2019 Datacenter
    ├── NSSM 系统服务（守护 uvicorn 进程）
    │   ├── 服务名: yunprint-print
    │   ├── 监听: 0.0.0.0:8931
    │   ├── 开机自启: 是
    │   ├── 崩溃重启: 5 秒后自动恢复
    │   └── 日志轮转: 10MB/文件, 保留 5 个
    ├── deploy/update.ps1      ← 一键更新（频繁使用）
    ├── deploy/rollback.ps1    ← 一键回滚
    └── deploy/install-service.ps1  ← 首次安装（一次性）
```

---

## 前置条件

### 软件清单

| 组件 | 版本要求 | 下载地址 | 用途 |
|---|---|---|---|
| Python | >= 3.11 | https://www.python.org/downloads/ | 运行时 |
| uv | 最新版 | https://docs.astral.sh/uv/ | Python 包管理 |
| Git | 最新版 | https://git-scm.com/download/win | 代码拉取 |
| NSSM | 2.24 | https://nssm.cc/release/nssm-2.24.zip | Windows 服务管理 |

### 网络要求

- 服务器需开放 **TCP 8931** 入站端口
- 服务器需能访问 `https://github.com`（拉取代码）
- 服务器需能访问 `https://yunprint.gmgrasp.com.cn`（业务 API）
- 服务器需能访问 `https://pypi.org` 和 `https://astral.sh`（安装依赖）

---

## 首次部署

> 以下所有命令在 **PowerShell（管理员）** 中执行。
> 打开方式：右键开始菜单 → "Windows PowerShell (管理员)"

### 第 1 步：安装 Python 3.11+

1. 从 https://www.python.org/downloads/ 下载 Python 3.11+ 安装包
2. 运行安装程序，**勾选 "Add Python to PATH"**
3. 安装完成后验证：

```powershell
python --version
# 预期输出: Python 3.11.x 或更高
```

### 第 2 步：安装 Git

1. 从 https://git-scm.com/download/win 下载安装
2. 安装时保持默认选项即可
3. 验证：

```powershell
git --version
# 预期输出: git version 2.x.x
```

### 第 3 步：安装 uv

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

安装后**关闭并重新打开** PowerShell 窗口，验证：

```powershell
uv --version
# 预期输出: uv 0.x.x
```

### 第 4 步：安装 NSSM

1. 从 https://nssm.cc/release/nssm-2.24.zip 下载压缩包
2. 解压后将 `nssm.exe`（64 位版本在 `win64` 子目录）复制到 `C:\Windows\System32\`
3. 验证：

```powershell
nssm version
# 预期输出: NSSM 2.24
```

### 第 5 步：克隆项目

```powershell
cd D:\
git clone https://github.com/757607106/gjp-print-mcp.git
cd D:\gjp-print-mcp
```

### 第 6 步：安装依赖

```powershell
uv sync
```

安装完成后验证虚拟环境：

```powershell
.\.venv\Scripts\python.exe --version
# 预期输出: Python 3.11.x 或更高
```

### 第 7 步：配置环境变量

创建 `.env` 文件：

```powershell
notepad .env
```

写入以下内容（根据实际环境调整）：

```dotenv
# === 通用日志配置 ===
GJP_LOG_ENABLED=true
GJP_LOG_LEVEL=INFO
GJP_LOG_CONTEXT=false

# === 打印服务配置 ===
YUNPRINT_CHAT_MAX_TURNS=20

# 必填：云打印平台地址
YUNPRINT_BASE_URL=https://yunprint.gmgrasp.com.cn

# 云打印 API 调用超时（秒）
YUNPRINT_TIMEOUT_SECONDS=30
```

> **安全提示**：`.env` 文件被 `.gitignore` 排除，不会提交到 Git。
> 不要在 `.env` 中保存云打印用户 Token——Token 由 Agent 平台通过
> `Authorization` 请求头动态传入。

### 第 8 步：开放防火墙端口

```powershell
netsh advfirewall firewall add rule name="yunprint-print" dir=in action=allow protocol=TCP localport=8931
```

验证规则已添加：

```powershell
netsh advfirewall firewall show rule name="yunprint-print"
```

### 第 9 步：注册 Windows 服务

```powershell
cd D:\gjp-print-mcp\deploy
.\install-service.ps1
```

脚本会自动完成以下操作：
- 检查 Python 解释器、.env 文件是否存在
- 创建 `logs` 目录
- 用 NSSM 注册 `yunprint-print` 服务
- 配置日志轮转（10MB/文件，保留 5 个）
- 配置崩溃自动重启（5 秒后）
- 配置开机自启
- 启动服务并验证

预期输出：

```
注册 Windows 服务 yunprint-print ...
启动服务...

=== 服务安装完成 ===
服务名:   yunprint-print
项目目录: D:\gjp-print-mcp
监听地址: 0.0.0.0:8931
日志目录: D:\gjp-print-mcp\logs
```

### 第 10 步：验证服务

```powershell
# 检查服务状态
nssm status yunprint-print
# 预期输出: SERVICE_RUNNING

# 检查端口监听
netstat -ano | findstr :8931
# 预期输出: TCP    0.0.0.0:8931    0.0.0.0:0    LISTENING    <PID>
```

发送 MCP 握手请求验证服务可用性：

```powershell
curl.exe -s -i -X POST http://127.0.0.1:8931/mcp `
  -H "Authorization: Bearer <你的云打印Token>" `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
```

预期响应：
- HTTP `200`
- 响应头包含 `mcp-session-id`
- 响应体 JSON 中 `serverInfo.name` 为 `yunprint-print`

---

## 服务管理

服务注册后，使用以下命令管理：

| 操作 | 命令 |
|---|---|
| 启动 | `nssm start yunprint-print` |
| 停止 | `nssm stop yunprint-print` |
| 重启 | `nssm restart yunprint-print` |
| 查看状态 | `nssm status yunprint-print` |
| 查看日志 | `type D:\gjp-print-mcp\logs\stderr.log` |
| 实时查看日志 | `Get-Content D:\gjp-print-mcp\logs\stderr.log -Wait` |
| 也可以用系统命令 | `net start yunprint-print` / `net stop yunprint-print` |

---

## 日常更新

> 这是频繁更新时最常用的操作，只需一条命令。

### 更新命令

```powershell
cd D:\gjp-print-mcp\deploy
.\update.ps1
```

### 脚本执行流程

```
[1/5] 拉取最新代码 (main)...        ← 1-3 秒（服务继续运行旧版本）
[2/5] 同步依赖...                   ← 3-10 秒（服务继续运行旧版本）
[3/5] 重启服务（停机开始）...        ← 此刻开始停机
[4/5] 等待服务启动...               ← 2 秒
[5/5] 健康检查...                   ← 1-3 秒
=== 更新完成 ===
停机时间: 约 3-5 秒
```

**设计要点**：`git pull` 和 `uv sync` 在服务重启之前执行，服务仍在运行旧版本。
只有 `nssm restart` 的瞬间才停机，将停机窗口压缩到 3-5 秒。

### 更新到指定分支

```powershell
.\update.ps1 -Branch dev
```

### 无更新时自动跳过

如果远程没有新提交，脚本会直接退出，不重启服务：

```
[1/5] 拉取最新代码 (main)...
      已是最新版本，无需更新
```

---

## 版本回滚

当更新后发现问题，需要快速回退到上一个版本：

### 回退到上一个提交

```powershell
cd D:\gjp-print-mcp\deploy
.\rollback.ps1
```

### 回退到指定提交

```powershell
.\rollback.ps1 -Commit abc1234
```

### 回滚后回到最新版本

```powershell
cd D:\gjp-print-mcp
git checkout main
git pull
.\deploy\update.ps1
```

---

## 运维速查

### 常用操作一览

```powershell
# === 更新 ===
cd D:\gjp-print-mcp\deploy
.\update.ps1                         # 一键更新
.\rollback.ps1                       # 一键回滚

# === 服务管理 ===
nssm start yunprint-print            # 启动
nssm stop yunprint-print             # 停止
nssm restart yunprint-print          # 重启
nssm status yunprint-print           # 状态

# === 日志 ===
Get-Content D:\gjp-print-mcp\logs\stderr.log -Wait    # 实时日志
Get-Content D:\gjp-print-mcp\logs\stderr.log -Tail 50 # 最后 50 行

# === 网络 ===
netstat -ano | findstr :8931         # 检查端口
curl.exe -s http://127.0.0.1:8931/mcp -X POST ...    # 手动测试

# === Git ===
cd D:\gjp-print-mcp
git log --oneline -5                 # 最近 5 个提交
git rev-parse --short HEAD           # 当前版本号
```

### 服务器重启后

服务设置为开机自启，服务器重启后服务会自动启动。无需手动操作。

验证服务已自动启动：

```powershell
nssm status yunprint-print
# 预期: SERVICE_RUNNING
```

---

## 故障排查

### 服务无法启动

```powershell
# 1. 查看错误日志
type D:\gjp-print-mcp\logs\stderr.log

# 2. 常见原因
#    - .env 文件缺失或 YUNPRINT_BASE_URL 未配置
#    - .venv 损坏 → 执行 uv sync 重建
#    - 端口 8931 被占用 → netstat -ano | findstr :8931 查看占用进程
```

### 更新后服务异常

```powershell
# 1. 查看当前版本
cd D:\gjp-print-mcp
git log --oneline -3

# 2. 查看错误日志
type D:\gjp-print-mcp\logs\stderr.log

# 3. 快速回滚
cd D:\gjp-print-mcp\deploy
.\rollback.ps1
```

### 端口被占用

```powershell
# 查找占用进程
netstat -ano | findstr :8931
# 输出最后一列是 PID

# 终止占用进程
taskkill /PID <PID> /F

# 重启服务
nssm restart yunprint-print
```

### Git pull 失败（本地有修改）

```powershell
cd D:\gjp-print-mcp

# 查看哪些文件被修改
git status

# 丢弃本地修改（谨慎！会丢失未提交的改动）
git checkout .

# 重新拉取
git pull origin main

# 继续更新
cd deploy
.\update.ps1
```

### 依赖安装失败

```powershell
cd D:\gjp-print-mcp

# 删除虚拟环境重建
rmdir /s /q .venv
uv sync

# 重启服务
nssm restart yunprint-print
```

### NSSM 服务被删除（误操作）

```powershell
cd D:\gjp-print-mcp\deploy
.\install-service.ps1
```

脚本会检测到服务不存在并重新注册。

---

## 注意事项

1. **单进程部署**：当前 `BearerConnectionStore` 和 `TemplateConversationStore`
   是进程内存状态，服务以单进程运行。不要在启动命令中加 `--workers` 参数。
   多副本部署需先改为 Redis 共享状态。

2. **.env 不在 Git 中**：`.env` 文件被 `.gitignore` 排除，`update.ps1`
   不会覆盖 `.env`。首次部署后无需在更新时重新配置。

3. **日志轮转**：NSSM 配置了 10MB 自动轮转，保留 5 个备份。日志位于
   `D:\gjp-print-mcp\logs\` 目录，文件名为 `stdout.log` 和 `stderr.log`。

4. **生产日志级别**：生产环境保持 `GJP_LOG_LEVEL=INFO`。DEBUG 级别会
   输出含 Token 的完整请求头，仅用于调试。

5. **健康检查原理**：`update.ps1` 发送 MCP `initialize` 握手请求验证
   服务可用性，不涉及业务 API 调用，不会产生副作用。

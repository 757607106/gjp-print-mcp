# Linux 服务器部署与更新指南

yunprint-print MCP 服务在 Linux 服务器（CentOS / Ubuntu / Debian 等）上的完整部署、
日常更新和运维指南。通过 `scripts/deploy.sh` 一键完成停服务、拉代码、同步依赖、
重启和验证，自动检测 systemd 或 nohup 方式。

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [首次部署](#首次部署)
- [服务管理](#服务管理)
- [日常更新](#日常更新)
- [版本回滚](#版本回滚)
- [临时 DEBUG 调试](#临时-debug-调试)
- [运维速查](#运维速查)
- [故障排查](#故障排查)

---

## 架构概览

```
GitHub 仓库 (757607106/gjp-print-mcp)
    ↓ git fetch + reset --hard
Linux 服务器
    ├── 服务进程（python -m yunprint，监听 0.0.0.0:8931）
    │   ├── systemd 方式（生产推荐）：开机自启、崩溃 5 秒自动重启、journald 日志
    │   └── nohup 方式（快速验证）：日志写入 /var/log/yunprint-print-mcp.log
    ├── scripts/deploy.sh          ← 一键部署脚本（停服务→拉代码→依赖→重启→验证）
    └── Nginx 反向代理 + HTTPS（可选，生产推荐）
```

---

## 前置条件

### 软件清单

| 组件 | 版本要求 | 说明 |
|---|---|---|
| Linux | CentOS 7+ / Ubuntu 18.04+ 等主流发行版 | 需支持 systemd |
| uv | 最新版 | Python 包管理，同时托管独立 Python 3.11+ |
| Git | 最新版 | 代码拉取 |
| curl | 系统自带 | 健康检查 |

> 无需手动安装 Python。系统自带 Python 通常版本较低，通过
> `uv python install 3.11` 安装独立管理的 Python，与系统 Python 隔离。

### 网络要求

- 服务器需开放 **TCP 8931** 入站端口（云服务器还需检查安全组）
- 服务器需能访问 `https://github.com`（拉取代码）
- 服务器需能访问 `https://yunprint.gmgrasp.com.cn`（业务 API）
- 服务器需能访问 `https://pypi.org` 和 `https://astral.sh`（安装依赖）

---

## 首次部署

> 以下所有命令以 **root** 身份执行，部署目录 `/root/gjp-print-mcp`。

### 第 1 步：安装 Git

```bash
# CentOS / RHEL / Alibaba Cloud Linux
yum install -y git

# Ubuntu / Debian
apt update && apt install -y git

# 验证
git --version
```

### 第 2 步：安装 uv

官方脚本安装：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv --version
```

国内服务器访问 `astral.sh` 超时时，改用 GitHub 加速镜像下载二进制：

```bash
curl -L https://ghfast.top/https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-unknown-linux-gnu.tar.gz -o /tmp/uv.tar.gz
mkdir -p /tmp/uv-extract
tar -xzf /tmp/uv.tar.gz -C /tmp/uv-extract
install -m 755 /tmp/uv-extract/uv-x86_64-unknown-linux-gnu/uv /usr/local/bin/uv
install -m 755 /tmp/uv-extract/uv-x86_64-unknown-linux-gnu/uvx /usr/local/bin/uvx
uv --version
```

如需 Python 3.11+（系统自带版本过低时）：

```bash
uv python install 3.11
```

### 第 3 步：克隆项目

```bash
cd /root
git clone https://github.com/757607106/gjp-print-mcp.git
cd gjp-print-mcp
```

### 第 4 步：同步依赖

```bash
uv sync
```

uv 自动使用托管的 Python 3.11+ 创建虚拟环境。验证：

```bash
.venv/bin/python --version
# 预期输出: Python 3.11.x 或更高
```

### 第 5 步：配置环境变量

创建 `.env` 文件：

```bash
vim .env
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

### 第 6 步：一键启动并验证

```bash
chmod +x scripts/deploy.sh
./scripts/deploy.sh
```

首次运行时 systemd 服务尚未注册，脚本自动以 nohup 方式拉起服务，
并依次验证进程、端口和 MCP 握手。预期输出：

```
[INFO] ===== yunprint-print MCP 服务快速部署 =====
[INFO] 1/5 停止当前服务...
[INFO] 2/5 拉取最新 main 分支代码...
[INFO] 当前版本：xxxxxxx 部署迁移：...
[INFO] 3/5 同步项目依赖...
[INFO] 4/5 启动服务...
[INFO] nohup 服务已启动 PID=12345
[INFO] 5/5 验证服务状态...
[INFO] 进程运行中 ✓
[INFO] 端口 8931 监听中 ✓
[INFO] MCP 握手检查通过 ✓
[INFO] ===== 部署完成 =====
```

### 第 7 步：开放防火墙端口

```bash
# firewalld（CentOS / Alibaba Cloud Linux）
firewall-cmd --permanent --add-port=8931/tcp
firewall-cmd --reload

# ufw（Ubuntu）
ufw allow 8931/tcp
```

> 云服务器（阿里云 / 腾讯云等）还需在控制台**安全组**中放行 TCP 8931。

### 第 8 步：systemd 服务化（生产推荐）

nohup 方式在服务器重启后不会自动恢复。生产环境创建
`/etc/systemd/system/yunprint-print.service`：

```bash
vim /etc/systemd/system/yunprint-print.service
```

写入（若部署目录不同请相应调整）：

```ini
[Unit]
Description=yunprint-print MCP Service
After=network.target

[Service]
Type=simple
WorkingDirectory=/root/gjp-print-mcp
ExecStart=/root/gjp-print-mcp/.venv/bin/python -m yunprint --host 0.0.0.0 --port 8931
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

再执行一次部署脚本，它会自动停止 nohup 进程并切换到 systemd 方式：

```bash
./scripts/deploy.sh
```

预期输出 `4/5 启动服务...` 后显示 `systemd 服务已启动`。此后服务具备
开机自启、崩溃 5 秒自动重启能力。

### 第 9 步（可选）：Nginx 反向代理 + HTTPS

生产环境建议在反向代理层配置 HTTPS。创建
`/etc/nginx/conf.d/yunprint-print.conf`：

```nginx
server {
    listen 80;
    server_name mcp.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl;
    server_name mcp.example.com;

    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/cert.key;
    ssl_session_cache shared:SSL:1m;
    ssl_session_timeout 5m;
    ssl_ciphers HIGH:!aNULL:!MD5;
    ssl_prefer_server_ciphers on;

    client_max_body_size 10m;

    access_log /var/log/nginx/yunprint-print-access.log;
    error_log /var/log/nginx/yunprint-print-error.log;

    location / {
        proxy_pass http://127.0.0.1:8931;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # MCP Streamable HTTP / SSE 流式响应支持
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
}
```

测试并加载配置：

```bash
nginx -t
nginx -s reload
```

> 关键点：MCP 走 Streamable HTTP / SSE，需 `proxy_buffering off` 关闭缓冲
> 以支持流式推送，`proxy_read_timeout` 设长以支持长连接。配置 HTTPS 后
> 云服务器安全组只需放行 80/443，可关闭 8931 外网访问。

---

## 服务管理

systemd 方式注册后，使用以下命令管理：

| 操作 | 命令 |
|---|---|
| 启动 | `systemctl start yunprint-print` |
| 停止 | `systemctl stop yunprint-print` |
| 重启 | `systemctl restart yunprint-print` |
| 查看状态 | `systemctl status yunprint-print` |
| 查看日志 | `journalctl -u yunprint-print -n 100 --no-pager` |
| 实时查看日志 | `journalctl -u yunprint-print -f` |

nohup 方式的日志位于 `/var/log/yunprint-print-mcp.log`：

```bash
tail -f /var/log/yunprint-print-mcp.log
```

---

## 日常更新

> 这是频繁更新时最常用的操作，只需一条命令。

```bash
cd /root/gjp-print-mcp
./scripts/deploy.sh
```

常用场景：

```bash
# 部署 main 分支（默认，生产环境）
./scripts/deploy.sh

# 部署 test 分支（测试环境）
BRANCH=test ./scripts/deploy.sh

# DEBUG 模式（临时调试，仅 nohup 方式生效）
./scripts/deploy.sh --debug
```

脚本执行流程：

```
[INFO] 1/5 停止当前服务...            ← systemd 或 nohup 自动检测
[INFO] 2/5 拉取最新 main 分支代码...   ← git fetch + reset --hard
[INFO] 3/5 同步项目依赖...            ← uv sync
[INFO] 4/5 启动服务...                ← 停机窗口开始
[INFO] 5/5 验证服务状态...            ← 进程 + 端口 + MCP 握手
[INFO] ===== 部署完成 =====
```

> **注意**：`git reset --hard origin/<分支>` 会丢弃部署机上的本地改动。
> 生产部署机不应直接修改代码；`.env` 不在 Git 管理中，不受影响。

---

## 版本回滚

更新后发现问题，手动回退到上一版本（或指定提交）：

```bash
cd /root/gjp-print-mcp

# 回退到上一个提交
git checkout HEAD~1

# 或回退到指定提交
git checkout abc1234

# 同步依赖并重启（systemd 方式）
uv sync
systemctl restart yunprint-print
```

验证：

```bash
git log --oneline -1
systemctl status yunprint-print
```

回滚后回到最新版本：

```bash
cd /root/gjp-print-mcp
git checkout main
./scripts/deploy.sh
```

---

## 临时 DEBUG 调试

排查业务 API 调用、鉴权问题需要 DEBUG 日志时：

**nohup 方式**（推荐用于临时调试）：直接用部署脚本一键切换：

```bash
cd /root/gjp-print-mcp

# 先切换到 nohup 方式运行（若当前是 systemd 方式）
systemctl stop yunprint-print 2>/dev/null; systemctl disable yunprint-print 2>/dev/null

# DEBUG 模式重启
./scripts/deploy.sh --debug

# 实时跟踪日志
tail -f /var/log/yunprint-print-mcp.log
```

调试完毕切回 INFO 并恢复 systemd：

```bash
./scripts/deploy.sh --debug   # 再次运行时去掉 --debug 即为 INFO
systemctl enable --now yunprint-print
./scripts/deploy.sh
```

**systemd 方式**（不中断 systemd 托管）：用 override 临时调整：

```bash
systemctl edit yunprint-print
```

在编辑器中写入：

```ini
[Service]
Environment=GJP_LOG_LEVEL=DEBUG
```

保存后 `systemctl restart yunprint-print` 生效，用
`journalctl -u yunprint-print -f` 查看日志。调试完毕移除 override 并重启。

> **安全提示**：DEBUG 级别会输出含 Token 的完整请求头，仅用于临时调试，
> 排查完毕必须恢复 `INFO`。

---

## 运维速查

```bash
# === 部署 ===
cd /root/gjp-print-mcp
./scripts/deploy.sh                      # 一键部署 main 分支
BRANCH=test ./scripts/deploy.sh          # 部署 test 分支
./scripts/deploy.sh --debug              # DEBUG 模式部署

# === 服务管理（systemd 方式） ===
systemctl start yunprint-print           # 启动
systemctl stop yunprint-print            # 停止
systemctl restart yunprint-print         # 重启
systemctl status yunprint-print          # 状态

# === 日志 ===
journalctl -u yunprint-print -f          # systemd 实时日志
tail -f /var/log/yunprint-print-mcp.log  # nohup 实时日志

# === 网络 ===
ss -ltnp | grep 8931                     # 检查端口
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8931/mcp \
  -H "Authorization: Bearer health-check" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
# 预期: 200

# === Git ===
cd /root/gjp-print-mcp
git log --oneline -5                     # 最近 5 个提交
git rev-parse --short HEAD               # 当前版本号
```

### 服务器重启后

- systemd 方式：服务开机自启，无需手动操作，`systemctl is-active yunprint-print` 验证
- nohup 方式：不会自动恢复，需重新执行 `./scripts/deploy.sh`

---

## 故障排查

### 服务无法启动

```bash
# 1. 查看错误日志
tail -n 50 /var/log/yunprint-print-mcp.log          # nohup 方式
journalctl -u yunprint-print -n 50 --no-pager       # systemd 方式

# 2. 常见原因
#    - .env 文件缺失或 YUNPRINT_BASE_URL 未配置
#    - .venv 损坏 → 执行 uv sync 重建
#    - 端口 8931 被占用 → ss -ltnp | grep 8931 查看占用进程
```

### 更新后服务异常

```bash
# 1. 查看当前版本
cd /root/gjp-print-mcp
git log --oneline -3

# 2. 查看错误日志（同上）

# 3. 快速回滚（见「版本回滚」章节）
git checkout HEAD~1 && uv sync && systemctl restart yunprint-print
```

### 端口被占用

```bash
# 查找占用进程（输出最后一列是 PID）
ss -ltnp | grep 8931

# 终止占用进程
kill <PID>

# 重新部署
./scripts/deploy.sh
```

### Git reset 失败（本地有改动）

```bash
cd /root/gjp-print-mcp

# 查看哪些文件被修改
git status

# 丢弃本地改动（谨慎！会丢失未提交的改动；.env 不受影响）
git checkout .

# 重新部署
./scripts/deploy.sh
```

### 依赖安装失败

```bash
cd /root/gjp-print-mcp

# 删除虚拟环境重建
rm -rf .venv
uv sync

# 重新部署
./scripts/deploy.sh
```

---

## 注意事项

1. **单进程部署**：当前 `BearerConnectionStore` 和 `TemplateConversationStore`
   是进程内存状态，服务以单进程运行，启动命令中未加 `--workers` 参数。
   多副本部署需先改为 Redis 共享状态。

2. **.env 不在 Git 中**：`.env` 文件被 `.gitignore` 排除，部署脚本
   `git reset --hard` 不会覆盖 `.env`。首次部署后无需在更新时重新配置。

3. **日志轮转**：nohup 方式日志追加写入 `/var/log/yunprint-print-mcp.log`，
   长期运行可用 logrotate 托管；systemd 方式由 journald 自动轮转。

4. **生产日志级别**：生产环境保持 `GJP_LOG_LEVEL=INFO`。DEBUG 级别会
   输出含 Token 的完整请求头，仅用于调试。

5. **健康检查原理**：部署脚本发送 MCP `initialize` 握手请求验证服务
   可用性，不涉及业务 API 调用，不会产生副作用。

6. **部署目录**：部署脚本自动定位自身所在仓库根目录（`scripts/` 的上一级），
   克隆到哪里就从哪里运行，无需配置；也可通过 `DEPLOY_DIR` 环境变量显式指定。

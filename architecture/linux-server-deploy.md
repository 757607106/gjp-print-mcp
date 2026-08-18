# Linux 服务器部署与更新指南

yunprint-print MCP 服务在 Linux 服务器（CentOS / Ubuntu / Debian 等）上的完整部署、
日常更新和运维指南。使用 systemd 将服务注册为系统服务，配合 Bash 脚本实现
一键更新和回滚，停机时间约 3-5 秒。

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
    ↓ git pull
Linux 服务器
    ├── systemd 系统服务（守护 uvicorn 进程）
    │   ├── 服务名: yunprint-print
    │   ├── 监听: 0.0.0.0:8931
    │   ├── 开机自启: 是
    │   ├── 崩溃重启: 5 秒后自动恢复（Restart=on-failure）
    │   └── 日志托管: journald（自动轮转）
    ├── deploy/update.sh             ← 一键更新（频繁使用）
    ├── deploy/rollback.sh           ← 一键回滚
    ├── deploy/install-service.sh    ← 首次安装（一次性）
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

> 以下所有命令以 **root** 身份执行，部署目录默认 `/root/gjp-print-mcp`。

### 第 1 步：安装 Git

```bash
# CentOS / RHEL
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
source ~/.bashrc
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

uv 自动下载独立 Python 3.11+ 并创建虚拟环境。验证：

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

### 第 6 步：开放防火墙端口

```bash
# firewalld（CentOS）
firewall-cmd --permanent --add-port=8931/tcp
firewall-cmd --reload

# ufw（Ubuntu）
ufw allow 8931/tcp
```

> 云服务器（阿里云 / 腾讯云等）还需在控制台**安全组**中放行 TCP 8931。

### 第 7 步：注册 systemd 服务

```bash
cd /root/gjp-print-mcp/deploy
chmod +x install-service.sh update.sh rollback.sh
sudo ./install-service.sh
```

脚本会自动完成以下操作：

- 检查 `.venv` 虚拟环境和 `.env` 文件是否存在
- 生成 `/etc/systemd/system/yunprint-print.service` 单元文件
- 配置崩溃自动重启（5 秒后）与开机自启
- 启动服务并验证运行状态

生成的单元文件等价于：

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

预期输出：

```
[INFO] === 服务安装完成 ===
服务名:   yunprint-print
项目目录: /root/gjp-print-mcp
监听地址: 0.0.0.0:8931
```

### 第 8 步：验证服务

```bash
# 检查服务状态
systemctl status yunprint-print
# 预期: Active: active (running)

# 检查端口监听
ss -ltnp | grep 8931
# 预期: LISTEN 0 ... 0.0.0.0:8931 ...
```

发送 MCP 握手请求验证服务可用性：

```bash
curl -s -i -X POST http://127.0.0.1:8931/mcp \
  -H "Authorization: Bearer <你的云打印Token>" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
```

预期响应：

- HTTP `200`
- 响应头包含 `mcp-session-id`
- 响应体 JSON 中 `serverInfo.name` 为 `yunprint-print`

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

服务注册后，使用以下命令管理：

| 操作 | 命令 |
|---|---|
| 启动 | `systemctl start yunprint-print` |
| 停止 | `systemctl stop yunprint-print` |
| 重启 | `systemctl restart yunprint-print` |
| 查看状态 | `systemctl status yunprint-print` |
| 查看日志 | `journalctl -u yunprint-print -n 100 --no-pager` |
| 实时查看日志 | `journalctl -u yunprint-print -f` |

---

## 日常更新

> 这是频繁更新时最常用的操作，只需一条命令。

### 更新命令

```bash
cd /root/gjp-print-mcp/deploy
sudo ./update.sh
```

### 更新到指定分支

```bash
sudo ./update.sh -b dev
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

**设计要点**：`git reset --hard` 和 `uv sync` 在服务重启之前执行，服务仍在
运行旧版本。只有 `systemctl restart` 的瞬间才停机，将停机窗口压缩到 3-5 秒。

> **注意**：`git reset --hard origin/main` 会丢弃部署机上的本地改动。
> 生产部署机不应直接修改代码；`.env` 不在 Git 管理中，不受影响。

### 无更新时自动跳过

如果远程没有新提交，脚本会直接退出，不重启服务：

```
[1/5] 拉取最新代码 (main)...
[INFO] 已是最新版本，无需更新
```

---

## 版本回滚

当更新后发现问题，需要快速回退到上一个版本：

### 回退到上一个提交

```bash
cd /root/gjp-print-mcp/deploy
sudo ./rollback.sh
```

### 回退到指定提交

```bash
sudo ./rollback.sh abc1234
```

### 回滚后回到最新版本

```bash
cd /root/gjp-print-mcp
git checkout main
git pull
cd deploy && sudo ./update.sh
```

---

## 临时 DEBUG 调试

排查业务 API 调用、鉴权问题需要 DEBUG 日志时，用 systemd override
临时调整，不修改主单元文件：

```bash
# 创建 override 并添加 DEBUG 环境变量
systemctl edit yunprint-print
```

在编辑器中写入：

```ini
[Service]
Environment=GJP_LOG_LEVEL=DEBUG
```

保存后重启生效：

```bash
systemctl restart yunprint-print
journalctl -u yunprint-print -f
```

调试完毕恢复 INFO：

```bash
# 移除 override 并重启
rm -f /etc/systemd/system/yunprint-print.service.d/override.conf
rmdir /etc/systemd/system/yunprint-print.service.d 2>/dev/null || true
systemctl daemon-reload
systemctl restart yunprint-print
```

> **安全提示**：DEBUG 级别会输出含 Token 的完整请求头，仅用于临时调试，
> 排查完毕必须恢复 `INFO`。

---

## 运维速查

### 常用操作一览

```bash
# === 更新 ===
cd /root/gjp-print-mcp/deploy
sudo ./update.sh                      # 一键更新
sudo ./rollback.sh                    # 一键回滚

# === 服务管理 ===
systemctl start yunprint-print        # 启动
systemctl stop yunprint-print         # 停止
systemctl restart yunprint-print      # 重启
systemctl status yunprint-print       # 状态

# === 日志 ===
journalctl -u yunprint-print -f       # 实时日志
journalctl -u yunprint-print -n 50 --no-pager   # 最后 50 行
journalctl -u yunprint-print --since "1 hour ago"  # 最近 1 小时

# === 网络 ===
ss -ltnp | grep 8931                  # 检查端口
curl -s -o /dev/null -w "%{http_code}\n" -X POST http://127.0.0.1:8931/mcp \
  -H "Authorization: Bearer health-check" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
# 预期: 200

# === Git ===
cd /root/gjp-print-mcp
git log --oneline -5                  # 最近 5 个提交
git rev-parse --short HEAD            # 当前版本号
```

### 服务器重启后

服务已设置开机自启（`systemctl enable`），服务器重启后自动启动，无需手动操作。

验证服务已自动启动：

```bash
systemctl is-active yunprint-print
# 预期: active
```

---

## 故障排查

### 服务无法启动

```bash
# 1. 查看错误日志
journalctl -u yunprint-print -n 50 --no-pager

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

# 2. 查看错误日志
journalctl -u yunprint-print -n 50 --no-pager

# 3. 快速回滚
cd deploy && sudo ./rollback.sh
```

### 端口被占用

```bash
# 查找占用进程（输出最后一列是 PID）
ss -ltnp | grep 8931

# 终止占用进程
kill <PID>

# 重启服务
systemctl restart yunprint-print
```

### Git reset 失败（本地有改动）

```bash
cd /root/gjp-print-mcp

# 查看哪些文件被修改
git status

# 丢弃本地改动（谨慎！会丢失未提交的改动；.env 不受影响）
git checkout .

# 重新更新
cd deploy && sudo ./update.sh
```

### 依赖安装失败

```bash
cd /root/gjp-print-mcp

# 删除虚拟环境重建
rm -rf .venv
uv sync

# 重启服务
systemctl restart yunprint-print
```

### systemd 服务被删除（误操作）

```bash
cd /root/gjp-print-mcp/deploy
sudo ./install-service.sh
```

脚本会检测到服务不存在并重新注册。

---

## 注意事项

1. **单进程部署**：当前 `BearerConnectionStore` 和 `TemplateConversationStore`
   是进程内存状态，服务以单进程运行，单元文件中未加 `--workers` 参数。
   多副本部署需先改为 Redis 共享状态。

2. **.env 不在 Git 中**：`.env` 文件被 `.gitignore` 排除，`update.sh`
   不会覆盖 `.env`。首次部署后无需在更新时重新配置。

3. **日志轮转**：日志由 journald 托管，按系统策略自动轮转，无需单独
   配置 logrotate。查看命令见 [服务管理](#服务管理)。

4. **生产日志级别**：生产环境保持 `GJP_LOG_LEVEL=INFO`。DEBUG 级别会
   输出含 Token 的完整请求头，仅用于调试。

5. **健康检查原理**：`update.sh` 发送 MCP `initialize` 握手请求验证
   服务可用性，不涉及业务 API 调用，不会产生副作用。

6. **部署目录**：部署脚本自动定位自身所在仓库根目录（`deploy/` 的上一级），
   克隆到哪里就从哪里运行，无需配置；也可通过 `PROJECT_DIR` 环境变量或
   脚本参数显式指定，例如 `sudo ./install-service.sh /root/gjp-print-mcp`。

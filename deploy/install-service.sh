#!/usr/bin/env bash
# yunprint-print MCP 服务 systemd 服务注册脚本（一次性执行）
#
# 将 uvicorn 进程注册为 systemd 服务，实现：
# - 开机自启
# - 崩溃自动重启（5 秒后）
# - 日志托管 journald（journalctl 查看，系统自动轮转）
#
# 用法：
#   sudo ./install-service.sh                        # 默认部署目录 /opt/gjp-print-mcp
#   sudo ./install-service.sh /root/gjp-print-mcp    # 指定项目目录
#
# 环境变量（可选覆盖默认值）：
#   PROJECT_DIR   部署目录（默认 /opt/gjp-print-mcp）
#   HOST          监听地址（默认 0.0.0.0）
#   PORT          监听端口（默认 8931）

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-${1:-/opt/gjp-print-mcp}}"
HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8931}"
SERVICE_NAME="yunprint-print"
UNIT_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
PYTHON_EXE="${PROJECT_DIR}/.venv/bin/python"

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ===== 前置检查 =====
if [[ $EUID -ne 0 ]]; then
    error "请以 root 身份运行：sudo $0 [项目目录]"
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    error "当前系统不支持 systemd，请确认使用主流 Linux 发行版（CentOS/Ubuntu/Debian 等）"
    exit 1
fi

if [[ ! -x "$PYTHON_EXE" ]]; then
    error "未找到 Python 解释器 $PYTHON_EXE"
    echo "请先在 $PROJECT_DIR 执行 uv sync"
    exit 1
fi

if [[ ! -f "${PROJECT_DIR}/.env" ]]; then
    error "未找到 .env 文件，请配置后再安装服务"
    exit 1
fi

# ===== 已有服务先移除（重装场景） =====
if systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    warn "服务 $SERVICE_NAME 已存在，正在移除旧服务..."
    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    systemctl disable "$SERVICE_NAME" 2>/dev/null || true
    rm -f "$UNIT_FILE"
    systemctl daemon-reload
    sleep 2
fi

# ===== 生成 systemd 单元文件 =====
info "生成 systemd 服务 $SERVICE_NAME ..."
cat > "$UNIT_FILE" <<EOF
[Unit]
Description=yunprint-print MCP Service
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_DIR}
ExecStart=${PYTHON_EXE} -m yunprint --host ${HOST} --port ${PORT}
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# ===== 启动服务 =====
info "启动服务..."
systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
sleep 3

# ===== 验证 =====
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo ""
    info "=== 服务安装完成 ==="
    echo "服务名:   $SERVICE_NAME"
    echo "项目目录: $PROJECT_DIR"
    echo "监听地址: ${HOST}:${PORT}"
    echo ""
    echo "常用命令："
    echo "  systemctl status $SERVICE_NAME     # 状态"
    echo "  systemctl restart $SERVICE_NAME    # 重启"
    echo "  systemctl stop $SERVICE_NAME       # 停止"
    echo "  journalctl -u $SERVICE_NAME -f     # 实时日志"
    echo "  ./update.sh                        # 一键更新"
    echo "  ./rollback.sh                      # 一键回滚"
else
    error "服务启动失败，状态: $(systemctl is-active "$SERVICE_NAME")"
    echo "请检查日志: journalctl -u $SERVICE_NAME -n 50 --no-pager"
    exit 1
fi

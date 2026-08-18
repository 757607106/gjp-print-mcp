#!/bin/bash
# yunprint-print MCP 服务快速部署脚本
#
# 一键完成：停服务 → 拉代码 → 同步依赖 → 重启 → 验证
# 自动检测 systemd 或 nohup 方式。
#
# 用法：
#   ./scripts/deploy.sh                # 部署 main 分支（默认）
#   BRANCH=test ./scripts/deploy.sh    # 部署 test 分支
#   ./scripts/deploy.sh --debug        # DEBUG 模式（仅 nohup 方式生效）
#
# 环境变量（可选覆盖默认值）：
#   DEPLOY_DIR   部署目录（默认自动定位脚本所在仓库根目录）
#   PORT         服务端口（默认 8931）

set -euo pipefail

# ===== 可配置项 =====
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOY_DIR="${DEPLOY_DIR:-$(dirname "$SCRIPT_DIR")}"
LOG_FILE="${LOG_FILE:-/var/log/yunprint-print-mcp.log}"
PORT="${PORT:-8931}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="yunprint-print"

# ===== 解析命令行参数 =====
LOG_LEVEL="INFO"
while [[ $# -gt 0 ]]; do
    case "$1" in
        --debug)
            LOG_LEVEL="DEBUG"
            shift
            ;;
        *)
            echo "未知参数：$1"
            echo "用法：$0 [--debug]"
            exit 1
            ;;
    esac
done

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ===== 步骤 1：停止当前服务 =====
stop_service() {
    info "1/5 停止当前服务..."
    if systemctl is-active --quiet "$SERVICE_NAME" 2>/dev/null; then
        systemctl stop "$SERVICE_NAME"
        info "systemd 服务已停止"
    else
        pkill -f "python -m yunprint" 2>/dev/null || true
        sleep 1
        if pgrep -f "python -m yunprint" >/dev/null 2>&1; then
            warn "进程仍在运行，强制终止..."
            pkill -9 -f "python -m yunprint" || true
            sleep 1
        fi
        info "nohup 进程已停止"
    fi
}

# ===== 步骤 2：拉取最新代码 =====
pull_code() {
    info "2/5 拉取最新 $BRANCH 分支代码..."
    cd "$DEPLOY_DIR"
    git fetch origin "$BRANCH"
    git reset --hard "origin/$BRANCH"
    info "当前版本：$(git log --oneline -1)"
}

# ===== 步骤 3：同步项目依赖 =====
sync_deps() {
    info "3/5 同步项目依赖..."
    cd "$DEPLOY_DIR"
    uv sync
    info "依赖同步完成"
}

# ===== 步骤 4：启动服务 =====
start_service() {
    info "4/5 启动服务..."
    # 确保日志目录存在
    mkdir -p "$(dirname "$LOG_FILE")"

    if [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
        # systemd 方式：环境变量在 service 文件中配置
        if [ "$LOG_LEVEL" = "DEBUG" ]; then
            warn "检测到 systemd 方式，--debug 参数需通过 override 生效"
            warn "临时调试建议改用 nohup：先停用 systemd 再运行此脚本"
        fi
        systemctl daemon-reload
        systemctl start "$SERVICE_NAME"
        sleep 2
        info "systemd 服务已启动"
    else
        # nohup 方式：.env 由服务启动时从部署目录自动加载
        cd "$DEPLOY_DIR"
        export GJP_LOG_LEVEL="$LOG_LEVEL"
        # 确保 uv 在 PATH 中
        export PATH="/usr/local/bin:/root/.local/bin:$PATH"

        nohup uv run python -m yunprint \
            --host 0.0.0.0 --port "$PORT" \
            >> "$LOG_FILE" 2>&1 &
        sleep 2
        local pid
        pid=$(pgrep -f "python -m yunprint" | head -1)
        if [ -n "$pid" ]; then
            info "nohup 服务已启动 PID=$pid"
        else
            error "服务启动失败！最近日志："
            tail -n 20 "$LOG_FILE" 2>/dev/null
            exit 1
        fi
    fi
}

# ===== 步骤 5：验证服务状态 =====
verify_service() {
    info "5/5 验证服务状态..."
    sleep 1

    # 检查进程
    if pgrep -f "python -m yunprint" >/dev/null 2>&1; then
        info "进程运行中 ✓"
    else
        error "进程未运行！"
        tail -n 20 "$LOG_FILE" 2>/dev/null
        exit 1
    fi

    # 检查端口
    if ss -ltnp 2>/dev/null | grep -q ":$PORT"; then
        info "端口 $PORT 监听中 ✓"
    else
        error "端口 $PORT 未监听！"
        tail -n 20 "$LOG_FILE" 2>/dev/null
        exit 1
    fi

    # MCP initialize 握手健康检查
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 \
        -X POST "http://127.0.0.1:$PORT/mcp" \
        -H "Authorization: Bearer health-check" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"deploy-check","version":"1.0"}}}' \
        || echo "000")
    if [ "$code" = "200" ]; then
        info "MCP 握手检查通过 ✓"
    else
        error "MCP 握手检查未通过（HTTP $code）！"
        tail -n 20 "$LOG_FILE" 2>/dev/null
        exit 1
    fi

    # 显示最近日志
    info "最近日志："
    tail -n 5 "$LOG_FILE" 2>/dev/null || journalctl -u "$SERVICE_NAME" -n 5 --no-pager

    echo ""
    info "===== 部署完成 ====="
    info "分支=$BRANCH  日志级别=$LOG_LEVEL  端口=$PORT"
    if [ "$LOG_LEVEL" = "DEBUG" ]; then
        info "实时查看日志：tail -f $LOG_FILE"
    fi
}

# ===== 主流程 =====
echo ""
info "===== yunprint-print MCP 服务快速部署 ====="
info "部署目录：$DEPLOY_DIR"
info "目标分支：$BRANCH"
info "日志级别：$LOG_LEVEL"
echo ""

stop_service
pull_code
sync_deps
start_service
verify_service

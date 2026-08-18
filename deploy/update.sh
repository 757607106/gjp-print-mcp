#!/usr/bin/env bash
# yunprint-print MCP 服务一键更新脚本
#
# 执行拉取代码 → 同步依赖 → 重启 systemd 服务 → 健康检查
# 预计停机时间 3-5 秒（仅服务重启期间）
#
# 用法：
#   sudo ./update.sh                    # 更新 main 分支（默认）
#   sudo ./update.sh -b dev             # 更新指定分支
#
# 环境变量（可选覆盖默认值）：
#   PROJECT_DIR   部署目录（默认 /opt/gjp-print-mcp）
#   PORT          服务端口（默认 8931）

set -euo pipefail

PROJECT_DIR="${PROJECT_DIR:-/opt/gjp-print-mcp}"
PORT="${PORT:-8931}"
BRANCH="main"
SERVICE_NAME="yunprint-print"
HEALTH_URL="http://127.0.0.1:${PORT}/mcp"
HEALTH_TIMEOUT=30

# ===== 解析命令行参数 =====
while [[ $# -gt 0 ]]; do
    case "$1" in
        -b|--branch)
            BRANCH="$2"
            shift 2
            ;;
        *)
            echo "未知参数：$1" >&2
            echo "用法：$0 [-b 分支名]" >&2
            exit 1
            ;;
    esac
done

# ===== 颜色输出 =====
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
NC='\033[0m'
info()  { echo -e "${GREEN}[INFO]${NC} $1"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# ===== 健康检查：发送 MCP initialize 握手验证服务可用性 =====
health_check() {
    local body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"deploy-check","version":"1.0"}}}'
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" -m 3 \
        -X POST "$HEALTH_URL" \
        -H "Authorization: Bearer health-check" \
        -H "Content-Type: application/json" \
        -H "Accept: application/json, text/event-stream" \
        -d "$body" || echo "000")
    [[ "$code" == "200" ]]
}

# ===== 前置检查 =====
if [[ $EUID -ne 0 ]]; then
    error "请以 root 身份运行：sudo $0"
    exit 1
fi

if ! systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    error "服务 $SERVICE_NAME 未注册，请先执行 deploy/install-service.sh"
    exit 1
fi

cd "$PROJECT_DIR"

# ===== 1/5 拉取最新代码 =====
echo -e "${CYAN}[1/5] 拉取最新代码 ($BRANCH)...${NC}"
git fetch origin "$BRANCH"
local_hash=$(git rev-parse HEAD)
remote_hash=$(git rev-parse "origin/$BRANCH")

if [[ "$local_hash" == "$remote_hash" ]]; then
    info "已是最新版本，无需更新"
    exit 0
fi

git reset --hard "origin/$BRANCH"
info "当前版本: $(git log --oneline -1)"

# ===== 2/5 同步依赖 =====
echo -e "${CYAN}[2/5] 同步依赖...${NC}"
if ! uv sync; then
    error "uv sync 失败"
    exit 1
fi

# ===== 3/5 重启服务（停机开始） =====
echo -e "${YELLOW}[3/5] 重启服务（停机开始）...${NC}"
systemctl restart "$SERVICE_NAME"

# ===== 4/5 等待服务启动 =====
echo -e "${CYAN}[4/5] 等待服务启动...${NC}"
sleep 2

# ===== 5/5 健康检查 =====
echo -e "${CYAN}[5/5] 健康检查...${NC}"
check_passed=false
for ((i = 1; i <= HEALTH_TIMEOUT; i++)); do
    if health_check; then
        check_passed=true
        break
    fi
    sleep 1
    echo "      等待中... ($i/$HEALTH_TIMEOUT)"
done

if $check_passed; then
    echo ""
    info "=== 更新完成 ==="
    echo "版本: $(git rev-parse --short HEAD)"
    echo "提交: $(git log -1 --format='%s')"
    echo "服务: $SERVICE_NAME 已启动"
    echo "停机时间: 约 3-5 秒"
else
    echo ""
    error "=== 警告：健康检查未通过 ==="
    echo "服务可能未正常启动，请检查日志："
    echo "  journalctl -u $SERVICE_NAME -n 50 --no-pager"
    echo "  systemctl status $SERVICE_NAME"
    exit 1
fi

#!/usr/bin/env bash
# yunprint-print MCP 服务一键回滚脚本
#
# 回退到上一个 Git 提交版本（或指定提交），同步依赖并重启服务
#
# 用法：
#   sudo ./rollback.sh                  # 回退到上一个提交
#   sudo ./rollback.sh abc1234          # 回退到指定提交
#
# 环境变量（可选覆盖默认值）：
#   PROJECT_DIR   部署目录（默认自动定位脚本所在仓库根目录）
#   PORT          服务端口（默认 8931）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="${PROJECT_DIR:-$(dirname "$SCRIPT_DIR")}"
PORT="${PORT:-8931}"
COMMIT="${1:-}"
SERVICE_NAME="yunprint-print"
HEALTH_URL="http://127.0.0.1:${PORT}/mcp"
HEALTH_TIMEOUT=30

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
    local body='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"rollback-check","version":"1.0"}}}'
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
    error "请以 root 身份运行：sudo $0 [commit]"
    exit 1
fi

if ! systemctl list-unit-files | grep -q "^${SERVICE_NAME}.service"; then
    error "服务 $SERVICE_NAME 未注册，请先执行 deploy/install-service.sh"
    exit 1
fi

cd "$PROJECT_DIR"

# ===== 1/4 回退版本 =====
if [[ -n "$COMMIT" ]]; then
    echo -e "${YELLOW}[1/4] 回退到指定提交 $COMMIT...${NC}"
else
    echo -e "${YELLOW}[1/4] 回退到上一个提交...${NC}"
    COMMIT="HEAD~1"
fi

if ! git checkout "$COMMIT"; then
    error "git checkout 失败"
    exit 1
fi

info "当前版本: $(git rev-parse --short HEAD)"
info "提交信息: $(git log -1 --format='%s')"

# ===== 2/4 同步依赖 =====
echo -e "${CYAN}[2/4] 同步依赖...${NC}"
if ! uv sync; then
    error "uv sync 失败"
    exit 1
fi

# ===== 3/4 重启服务 =====
echo -e "${CYAN}[3/4] 重启服务...${NC}"
systemctl restart "$SERVICE_NAME"

# ===== 4/4 健康检查 =====
echo -e "${CYAN}[4/4] 等待服务启动并健康检查...${NC}"
sleep 2

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
    info "=== 回滚完成 ==="
    echo "版本: $(git rev-parse --short HEAD)"
    echo "提交: $(git log -1 --format='%s')"
else
    echo ""
    error "=== 警告：健康检查未通过 ==="
    echo "请检查日志：journalctl -u $SERVICE_NAME -n 50 --no-pager"
    exit 1
fi

echo ""
echo "提示：回到最新版本请执行："
echo "  git checkout main && deploy/update.sh"

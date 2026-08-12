# 本地 MCP 服务与 ngrok 内网穿透启动指南

通过 ngrok 把本地 `yunprint-print` MCP 服务暴露为公网 HTTPS 地址，供云端
Agent 平台或局域网外的客户端对接。适用于本地开发、演示和联调。

## 适用场景

- 云端 Agent 平台需要连接本地运行的 MCP 服务。
- 本地服务无法部署到公网服务器，临时需要公网入口。
- 联调阶段快速验证 MCP 工具调用链路。

## 前置条件

| 条目 | 要求 |
|---|---|
| Python | >= 3.11 |
| 包管理 | uv（已执行 `uv sync`） |
| ngrok | >= 3.x，已配置 authtoken |
| `.env` | 已配置 `YUNPRINT_BASE_URL` |

### 安装与配置 ngrok

```bash
# macOS 安装
brew install ngrok

# 配置 authtoken（在 ngrok 官网注册后获取）
ngrok config add-authtoken <你的authtoken>
```

配置完成后，authtoken 会写入
`~/Library/Application Support/ngrok/ngrok.yml`（macOS）。

### 确认 .env 配置

项目根目录 `.env` 必须包含云打印平台地址，否则工具调用会报
`BUSINESS_CONNECTION_INVALID`：

```dotenv
YUNPRINT_BASE_URL=https://yunprint.gmgrasp.com.cn
YUNPRINT_TIMEOUT_SECONDS=30
GJP_LOG_ENABLED=true
GJP_LOG_LEVEL=DEBUG
```

不要在 `.env` 中保存云打印用户 Token。Token 属于连接凭据，由 Agent 平台
通过 `Authorization` 请求头动态传入。

## 第一步：启动本地 MCP 服务

```bash
cd /path/to/gjp-print-mcp
uv run python -m yunprint --host 127.0.0.1 --port 8931
```

使用 `127.0.0.1` 即可，ngrok 默认连接本地回环地址，无需改为 `0.0.0.0`，
也无需开放 macOS 防火墙入站。

启动成功后终端输出：

```
INFO:     Started server process [xxxx]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8931 (Press CTRL+C to quit)
```

此终端窗口保持打开，服务运行期间不要关闭。

## 第二步：启动 ngrok 隧道

新开一个终端窗口，执行：

```bash
ngrok http 8931 --log=stdout
```

启动成功后终端会显示 ngrok 的会话界面，其中包含公网转发地址，形如：

```
Forwarding   https://xxxx-xxxx-xxxx.ngrok-free.dev -> http://localhost:8931
```

此终端窗口同样保持打开。

## 第三步：获取公网地址

ngrok 提供本地 API，可直接查询当前隧道公网地址：

```bash
curl -s http://localhost:4040/api/tunnels | python3 -c "import sys,json; print(json.load(sys.stdin)['tunnels'][0]['public_url'])"
```

输出示例：

```
https://jawline-certainly-jolliness.ngrok-free.dev
```

记下这个地址，后续配置需要用到。MCP 端点完整路径为该地址加上 `/mcp`。

## 第四步：平台端配置

在 Agent 平台的"新增 MCP"配置中按以下填写：

| 表单项 | 填写内容 |
|---|---|
| MCP 名称 | `yunprint-print` |
| 功能描述 | 云打印模板样式服务：getPrintInfo 查询参考样式、newStyle 创建模板、saveStyle 保存模板 |
| Server 地址 | `https://<ngrok公网域名>/mcp` |
| 传输协议 | Streamable HTTP / HTTP |
| 认证方式 | Bearer Token |
| Token 值 | 当前用户的云打印 Token |
| 额外 Header | `X-Report-Name: <URL编码的报表分类>` |

`X-Report-Name` 常见值：

| 报表分类 | URL 编码值 |
|---|---|
| 销售单 | `%E9%94%80%E5%94%AE%E5%8D%95` |
| 采购单 | `%E9%87%87%E8%B4%AD%E5%8D%95` |
| 库存盘点 | `%E5%BA%93%E5%AD%98%E7%9B%98%E7%82%B9` |
| 付款单 | `%E4%BB%98%E6%AC%BE%E5%8D%95` |

> 如果平台不支持在 Bearer Token 之外再添加自定义 Header，需在平台与
> MCP 之间加一层鉴权网关，由网关注入 `Authorization` 和 `X-Report-Name`
> 两个头。详见 `saas-mcp-integration.md` 的网关方案。

## 第五步：验证连通性

### 手工验证 MCP 握手

```bash
curl -s -i -X POST 'https://<ngrok公网域名>/mcp' \
  -H 'Authorization: Bearer <云打印Token>' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
```

预期响应：

- HTTP `200`
- 响应头包含 `mcp-session-id: <会话ID>`
- 响应体 JSON 中 `serverInfo.name` 为 `yunprint-print`

### 验证认证与工具调用

握手成功只代表传输通道正常，认证在 `tools/call` 时才触发。让平台模型
调用一次 `getPrintInfo`，观察本地 MCP 服务终端日志：

| 日志内容 | 含义 |
|---|---|
| `MCP 调用开始 tool=getPrintInfo auth=Bearer xxxxxxxx…` | 认证解析成功 |
| `MCP 调用成功 tool=getPrintInfo ...` | 全链路打通 |
| `MCP 鉴权失败 ... MCP_UNAUTHORIZED` | 平台未带 Bearer Token，检查认证方式配置 |
| `BUSINESS_CREDENTIAL_REQUIRED` | 会话头丢失，检查平台是否支持有状态 Streamable HTTP |
| `BUSINESS_CONNECTION_INVALID` | 服务端 `.env` 未配置 `YUNPRINT_BASE_URL` |

## 注意事项

### ngrok 免费版限制

- **地址不固定**：每次重启 ngrok，公网域名会变化，平台配置需同步更新。
  需要固定地址请升级 ngrok 付费版。
- **拦截页**：ngrok 免费版可能对浏览器请求（`Accept: text/html`）返回
  拦截页。MCP 客户端发送 `Accept: application/json, text/event-stream`，
  正常情况下不受影响。如遇到拦截，在平台自定义 Header 中追加
  `ngrok-skip-browser-warning: any` 即可绕过。
- **连接数与带宽**：免费版有并发和流量限制，仅适用于开发联调，不可用于
  生产。

### 进程管理

本地 MCP 服务和 ngrok 隧道是两个独立前台进程，分别占用一个终端窗口：

| 进程 | 作用 | 停止方式 |
|---|---|---|
| MCP 服务 | 监听 `127.0.0.1:8931` | 在对应终端按 `Ctrl+C` |
| ngrok | 公网隧道转发 | 在对应终端按 `Ctrl+C` |

关闭终端窗口或按 `Ctrl+C` 都会停止对应进程。两者任一停止，公网链路即
断开。

### 多 worker 限制

当前 `TemplateConversationStore` 是进程内存实现，本地启动命令保持单进程。
不要加 `--workers` 参数。多 worker 部署需先改为 Redis 或数据库共享状态。

## 停止服务

在两个终端窗口分别按 `Ctrl+C`：

1. ngrok 终端：`Ctrl+C` 断开公网隧道。
2. MCP 服务终端：`Ctrl+C` 停止本地服务。

确认 ngrok 已停止：

```bash
curl -s http://localhost:4040/api/tunnels
# 连接被拒绝则表示 ngrok 已停止
```

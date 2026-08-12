# SaaS 与三接口 MCP 接入

## 服务信息

| 项目 | 值 |
|---|---|
| MCP 服务名 | `yunprint-print` |
| 首选传输 | Streamable HTTP |
| MCP 路径 | `/mcp` |
| 本地默认地址 | `http://127.0.0.1:8931/mcp` |
| 鉴权 | `Authorization: Bearer <Token>` + `X-Report-Name: <URL编码分类>` |
| 会话 | 服务端签发并校验 `Mcp-Session-Id` |
| 兼容传输 | SSE `/sse` + `/messages/`，仅用于旧客户端 |

## 启动 MCP 服务

### 安装

```bash
cd /path/to/gjp-print-mcp
uv sync
```

需要执行测试时安装开发依赖：

```bash
uv sync --extra dev
```

### 配置

项目根目录 `.env` 示例：

```dotenv
YUNPRINT_BASE_URL=https://yunprint.gmgrasp.com.cn
YUNPRINT_TIMEOUT_SECONDS=30
GJP_LOG_ENABLED=true
GJP_LOG_LEVEL=INFO
```

`YUNPRINT_BASE_URL` 只填写 HTTPS 根地址。Repository 会自动追加
`ElectronPrintApi/GetPrintInfo`、`ElectronPrintApi/NewStyle` 或
`ElectronPrintApi/SaveStyle`。

不要在服务端 `.env` 中保存某个用户的云打印 Token。Token 属于
MCP 连接凭据，应由每个客户端通过 `Authorization` 头传入。

### 本地或开发启动

```bash
uv run python -m yunprint --host 127.0.0.1 --port 8931
```

### 服务器启动

```bash
uv run uvicorn yunprint.app:app --host 0.0.0.0 --port 8931 --workers 1
```

当前 `TemplateConversationStore` 是进程内存实现，启动命令必须保持
`--workers 1`。多 worker、多容器或滚动重启部署前，需先改为 Redis/数据库
共享状态。

## MCP 客户端配置

### 通用 JSON 配置

```json
{
  "mcpServers": {
    "yunprint-print": {
      "type": "streamable-http",
      "url": "https://<mcp-host>/mcp",
      "headers": {
        "Authorization": "Bearer <云打印Token>",
        "X-Report-Name": "%E9%94%80%E5%94%AE%E5%8D%95"
      }
    }
  }
}
```

`X-Report-Name` 值需 URL 编码（如 `销售单` → `%E9%94%80%E5%94%AE%E5%8D%95`）。

#### 编码规范（对接方必读）

`X-Report-Name` 必须使用**标准 URL 百分号编码（RFC 3986，UTF-8），且只编码一次**。服务端用标准 `unquote` 解码一次还原原文；多次编码会导致解码失败、业务 API 收到编码值而非原文。

- 编码方式：标准 percent-encoding，字符集 UTF-8
- **只编码一次**：对原文编码一次后放入头，不要对已编码值再编码
- ASCII 字母数字不编码；中文按 UTF-8 字节转 `%XX`；`%` 本身编码成 `%25`

| 原文 | 正确（编码一次） | 错误（双重编码） |
|---|---|---|
| `MCP测试` | `MCP%E6%B5%8B%E8%AF%95` | `MCP%25E6%25B5%258B%25E8%25AF%2595` |
| `销售单` | `%E9%94%80%E5%94%AE%E5%8D%95` | `%25E9%2594%2580%25E5%2594%25AE%25E5%258D%2595` |

各语言编码函数（调用一次）：

| 语言 | 函数 |
|---|---|
| Python | `urllib.parse.quote("销售单")` |
| Java | `URLEncoder.encode("销售单", "UTF-8")` |
| JavaScript | `encodeURIComponent("销售单")` |

> 禁止双重编码：若已持有编码后的值，原样放入头，不要再编码；若持有原文，编码一次后放入。二选一，不要叠。

如果平台用表单配置 MCP，则填写：

| 表单项 | 填写内容 |
|---|---|
| 名称 | `yunprint-print` |
| 类型/传输 | Streamable HTTP 或 HTTP |
| URL | `https://<mcp-host>/mcp` |
| Header 名 | `Authorization` + `X-Report-Name` |
| Header 值 | `Bearer <云打印Token>` + URL编码分类名 |

客户端必须支持自定义 HTTP Header，否则无法把云打印 Token 传入该 MCP。

### Token 和 reportName 动态配置

Token 和 reportName 都不是 MCP 工具的 `arguments` 参数，而是当次 MCP HTTP
请求的头。SaaS 平台应在发起 MCP 请求时，按当前用户和入口动态填入：

```text
入口A（销售单）→ Authorization: Bearer <Token-A>, X-Report-Name: %E9%94%80%E5%94%AE%E5%8D%95
入口B（采购单）→ Authorization: Bearer <Token-B>, X-Report-Name: %E9%87%87%E8%B4%AD%E5%8D%95
```

不同对接方入口对应不同的 token 和 reportName。两者在 MCP 连接时由对接方
设置，不进入工具参数和模型上下文。

如果 Agent 平台支持密钥变量或用户级凭据，可将 Header 配置成类似：

```json
{
  "headers": {
    "Authorization": "Bearer ${YUNPRINT_USER_TOKEN}"
  }
}
```

`${YUNPRINT_USER_TOKEN}` 只是变量名示例，是否支持以及具体语法由 Agent 平台
决定。不支持变量时，应通过平台的 Secret/凭据管理功能为每个用户或租户
创建独立 MCP 连接，不要让模型在对话中生成 Token。

GetPrintInfo 调用中，SaaS 对接方在 HTTP 头中传入：

```text
HTTP Header: Authorization = Bearer <当前用户Token>
HTTP Header: X-Report-Name = <URL编码的报表分类>
Tool arguments: {} (无参数)
```

MCP 服务端再把它们转换为业务 API 中的 `token`、`reportName`，并自动
补全固定的 `reportType=1` 和其他空字段。

### 多账号动态 Token 方案

不同云打印账号的 Token 和可访问的 `reportName` 都可能不同。对接方必须
按当前登录账号选择凭据，不能在 MCP 服务的 `.env` 中配置一个全局用户
Token。

```text
账号A
  → 凭据库取得 Token-A
  → 建立 MCP 会话A，Authorization: Bearer Token-A
  → get_print_info(report_name=账号A当前分类)

账号B
  → 凭据库取得 Token-B
  → 建立 MCP 会话B，Authorization: Bearer Token-B
  → get_print_info(report_name=账号B当前分类)
```

调用规则：

1. 用户进入对话时，SaaS 后端根据当前 `account_id` 从 Secret/凭据库读取该
   账号的云打印 Token。
2. 使用该 Token 建立账号专属 MCP 连接，或在该账号的每个 MCP HTTP 请求中
   动态设置 `Authorization: Bearer <Token>`。
3. 图片识别出的分类名称作为 `get_print_info.arguments.report_name` 传入。
4. 账号切换时必须新建 MCP 会话，不得沿用上一个账号的
   `Mcp-Session-Id`。
5. 一个账号的多轮模板修改应继续使用该账号的原 MCP 会话。

如果对接的 Agent 平台只支持"应用级固定 Header"，不支持用户级动态 Header，
则需要在 Agent 平台与本 MCP 之间增加对接方的鉴权网关：

```text
Agent 平台
  → 对接方网关验证当前账号
  → 凭据库查询该账号的云打印 Token
  → 网关注入 Authorization Header
  → yunprint-print MCP
```

网关不得把 Token 追加到 `tools/call.arguments`，也不得记录完整 Token。

### 本地与远程 URL

| 场景 | URL |
|---|---|
| MCP 客户端与服务在同一台机器 | `http://127.0.0.1:8931/mcp` |
| 局域网其他机器访问 | `http://<服务器IP>:8931/mcp` |
| 生产公网访问 | `https://<MCP域名>/mcp` |
| 容器间访问 | `http://<service-name>:8931/mcp` |

`127.0.0.1` 始终指向 MCP 客户端所在的机器或容器。客户端与服务不在同一
网络命名空间时，不能使用 `127.0.0.1`。

## 会话与多轮编辑

Streamable HTTP 初始化成功后，服务端在响应头中返回
`Mcp-Session-Id`。标准 MCP SDK 应在后续的通知、工具列表和工具调用请求中
自动回传该值。

- 不要把 `Mcp-Session-Id` 写死在 MCP 配置中。
- 不同对话建立不同 MCP 会话，即使它们使用同一个 Token 也不会互相覆盖。
- 一次连续编辑必须复用同一 MCP 会话。
- 客户端不支持会话头时，服务端退化为按 Token 哈希隔离，同 Token 的多个对话
  可能共享当前模板。

`get_print_info` 除远端 GetPrintInfo 数据外，还返回当前会话的
`currentStyle`。Agent 每轮修改前读取其中的完整 `styleContent`，修改后使用
相同 `styleId` 保存。

## 手工验证 MCP 握手

正常的 MCP 客户端会自动完成以下流程。排查连接问题时可使用 `curl`
手工验证。

### 1. Initialize

```bash
curl -i -X POST 'http://127.0.0.1:8931/mcp' \
  -H 'Authorization: Bearer <云打印Token>' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-11-25","capabilities":{},"clientInfo":{"name":"manual-check","version":"1.0"}}}'
```

预期 HTTP 200，响应头包含：

```text
Mcp-Session-Id: <服务端生成的会话ID>
```

### 2. 发送 initialized 通知

把下面 `<会话ID>` 替换为上一步响应头的值：

```bash
curl -i -X POST 'http://127.0.0.1:8931/mcp' \
  -H 'Authorization: Bearer <云打印Token>' \
  -H 'Mcp-Session-Id: <会话ID>' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
```

预期 HTTP 202。

### 3. 查看工具列表

```bash
curl -sS -X POST 'http://127.0.0.1:8931/mcp' \
  -H 'Authorization: Bearer <云打印Token>' \
  -H 'Mcp-Session-Id: <会话ID>' \
  -H 'MCP-Protocol-Version: 2025-11-25' \
  -H 'Content-Type: application/json' \
  -H 'Accept: application/json, text/event-stream' \
  --data '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

返回工具名必须且只能是：

1. `get_print_info`
2. `new_style`
3. `save_style`

## 反向代理要求

生产环境建议由 Nginx、网关或负载均衡器终止 TLS，并保证：

- 转发 `Authorization`、`X-Report-Name`、`Mcp-Session-Id`、`MCP-Protocol-Version`、
  `Accept` 和 `Content-Type` 请求头。
- 不缓存 `/mcp` 的 POST 响应。
- 不在访问日志中记录完整 `Authorization` 值。
- 未使用共享会话存储前，只转发到一个 MCP 进程。

## 鉴权与工具边界

云打印 Token 是 opaque token。服务不解析其结构，而是将它与服务端签发的
`Mcp-Session-Id` 共同派生内部 `session_id`。原始 Token 仅保存在服务端连接
存储中，实际有效性由云打印 API 校验。

SaaS Agent 只会发现 `get_print_info`、`new_style` 和 `save_style`。工具参数
中不存在 Token、账号、密码、Cookie、业务地址或任意 URL。

## 失败恢复

`new_style` 不自动重试，避免网络结果不明确时产生重复模板。`save_style`
失败后应复用已经返回的 `styleId` 重试保存，不得再次调用 `new_style`。

## 常见错误

| 现象或错误 | 含义 | 处理 |
|---|---|---|
| 404 | MCP URL 错误 | 确认 URL 以 `/mcp` 结尾 |
| 400 / 会话不存在 | 未完成 initialize 或没有回传会话头 | 使用支持有状态 Streamable HTTP 的 MCP 客户端 |
| `MCP_UNAUTHORIZED` | Bearer 头缺失或格式错误 | 检查 `Authorization: Bearer <Token>` |
| `BUSINESS_CONNECTION_INVALID` | 业务 API 地址未配置 | 检查 `YUNPRINT_BASE_URL` |
| `YUNPRINT_REQUEST_FAILED` | 云打印 API 访问或业务失败 | 检查 Token、网络、超时和云打印 API |
| `currentStyle=null` | 当前 MCP 会话没有可继续编辑的模板 | 确认会话未被重建，或新建模板 |

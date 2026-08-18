# GJP 云打印模板样式 MCP

基于 AgentScope 2.0.4 的云打印 MCP 服务。对外只发布三个模板样式工具，供视觉
模型根据用户图片还原模板并保存到云打印业务系统。

## MCP 工具

| 工具 | 业务 API | 参数 |
|---|---|---|
| `getPrintInfo` | `/ElectronPrintApi/GetPrintInfo` | 无参数；`reportType` 固定为 1 |
| `newStyle` | `/ElectronPrintApi/NewStyle` | `report_type`、`style_name` |
| `saveStyle` | `/ElectronPrintApi/SaveStyle` | `report_type`、`style_name`、`style_id`、`style_content` |

工具名使用 camelCase 发布（通过 `FunctionTool(name=)` 显式覆盖），确保协议层、
系统提示词和模型可见名三者统一。

Token 和 reportName 都不属于工具参数。MCP 客户端通过 `Authorization: Bearer <云打印Token>`
和 `X-Report-Name: <URL编码的报表分类>` 两个请求头动态传入，服务端 Adapter 再把
Token 注入三个业务 API 的请求体。

## 动态参数

对接方每次调用 MCP 时，同时提供当前用户的 Token 和本次的 reportName：Token 放在
`Authorization` 头中，reportName 放在 `X-Report-Name` 头中（URL 编码）。两者都是每次
请求动态传入，不进入工具参数、Tool Schema 或模型上下文。

| 业务字段 | MCP 传入方式 | 来源 | 规则 |
|---|---|---|---|
| `token` | HTTP `Authorization: Bearer <Token>` | 对接方 | 每次请求动态注入，不出现在工具 Schema 中 |
| `reportName` | HTTP `X-Report-Name` 头（URL 编码） | 对接方按入口传入 | 服务端 `unquote` 解码一次还原原文 |
| `reportType` | `report_type` 工具参数 | 业务上下文 | GetPrintInfo 固定为 `1`；NewStyle/SaveStyle 动态传入 |
| `styleName` | `style_name` 工具参数 | 用户命名 | NewStyle 动态传入；SaveStyle 必须沿用 NewStyle 返回值 |
| `styleId` | `style_id` 工具参数 | NewStyle 响应 | SaveStyle 动态传入，必须作为字符串保留 |
| `styleContent` | `style_content` 工具参数 | 模板 JSON 生成/编辑逻辑 | 传入完整 JSON 对象，由服务端序列化 |

GetPrintInfo 的完整 MCP 调用形式：

```http
POST /mcp
Authorization: Bearer <对接方本次动态传入的Token>
X-Report-Name: %E9%94%80%E5%94%AE%E5%8D%95
Mcp-Session-Id: <initialize返回的会话ID>
Content-Type: application/json
```

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "tools/call",
  "params": {
    "name": "getPrintInfo",
    "arguments": {}
  }
}
```

MCP 服务从请求头取出 Token 和 reportName，再生成业务 API 请求：

```json
{
  "token": "<本次请求的Token>",
  "reportName": "销售单",
  "reportType": 1,
  "styleName": "",
  "styleId": "",
  "styleContent": "",
  "isDynamicBaseStyle": "",
  "baseStyleContent": "",
  "isPublic": false
}
```

三个 MCP 工具的动态调用关系：

```text
getPrintInfo()
  → 读取当前分类下已有样式和打印信息

newStyle(report_type, style_name)
  → 创建空白模板，返回 styleId/reportType/styleName

saveStyle(report_type, style_name, style_id, style_content)
  → 把生成的模板 JSON 保存到已创建的样式
```

## 图片还原流程

```text
用户图片
  → 视觉模型识别报表名称、字段和布局
  → getPrintInfo()
  → 生成完整的云打印原生模板 JSON
  → newStyle(report_type, style_name)
  → saveStyle(
        使用 newStyle 返回的 reportType/styleName/styleId,
        style_content=生成的模板 JSON 对象
    )
```

`style_id` 始终作为字符串传递，避免超大整数精度丢失。`newStyle` 和
`saveStyle` 不自动重试；创建成功后保存失败，应使用同一 `style_id` 重试保存，
不能重复创建空模板。

## 多轮编辑

服务端按 `tenant_id / account_id / session_id / report_name` 保存当前模板。
Streamable HTTP 初始化时服务端签发 `Mcp-Session-Id`，客户端后续自动
回传，因此同一 Token 下的不同对话也会隔离。未提供会话头时才回退为
Token 哈希会话。首次 `newStyle` 后记录模板身份，首次 `saveStyle` 后记录
完整 JSON；后续调用 `getPrintInfo()` 会同时返回：

```json
{
  "currentStyle": {
    "reportName": "销售单",
    "reportType": 1,
    "styleName": "图片还原模板",
    "styleId": "2086707921336647680",
    "revision": 2,
    "hasContent": true,
    "styleContent": {"ReportName": "销售单", "Pages": []}
  }
}
```

模型以 `currentStyle.styleContent` 为基线，只修改用户本轮指定内容，再使用同一个
`styleId` 调用 `saveStyle`。只有用户明确要求另存为新模板时才调用 `newStyle`。

参考实现使用进程内状态（`BearerConnectionStore` 和 `TemplateConversationStore`），
支持同一服务进程内多轮对话；通过 TTL 自动清理过期会话（默认 2 小时），避免内存
无限增长。服务重启会丢失状态，多副本部署应把会话存储替换为 Redis 或数据库共享状态。

## 快速启动

运行要求：Python 3.11 或更高版本，并已安装 `uv`。

### 1. 安装依赖

```bash
cd /path/to/gjp-print-mcp
uv sync
```

本地开发和执行测试时使用：

```bash
uv sync --extra dev
```

### 2. 配置服务

可在项目根目录创建 `.env`：

```dotenv
YUNPRINT_BASE_URL=https://yunprint.gmgrasp.com.cn
YUNPRINT_TIMEOUT_SECONDS=30
GJP_LOG_ENABLED=true
GJP_LOG_LEVEL=INFO
```

也可以使用同名进程环境变量；进程环境变量优先于 `.env`。

| 变量 | 必填 | 默认值 | 说明 |
|---|---|---|---|
| `YUNPRINT_BASE_URL` | 是 | - | 云打印平台 HTTPS 根地址，不包含三个 API 路径 |
| `YUNPRINT_TIMEOUT_SECONDS` | 否 | 30 | 三个业务 API 的超时时间（秒） |
| `GJP_LOG_ENABLED` | 否 | false | 是否开启终端日志 |
| `GJP_LOG_LEVEL` | 否 | INFO | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

云打印 Token 不写入 `.env`，而是由每个 MCP 客户端连接通过
`Authorization` 请求头动态传入。

### 3. 启动 MCP

本地启动：

```bash
uv run python -m yunprint --host 127.0.0.1 --port 8931
```

容器、服务器或局域网启动：

```bash
uv run uvicorn yunprint.app:app --host 0.0.0.0 --port 8931 --workers 1
```

启动后的首选 MCP 地址为 `http://127.0.0.1:8931/mcp`，传输类型为
Streamable HTTP。生产环境应在反向代理层配置 HTTPS。

> 当前多轮模板状态保存在进程内存中，因此必须使用单 worker。
> 启用 Redis/数据库共享状态后才能安全扩展为多 worker 或多副本。

Linux 服务器部署见 [Linux 服务器部署与更新指南](architecture/linux-server-deploy.md)。

## 连接 MCP

支持 Streamable HTTP 的 Agent 平台使用以下配置：

```json
{
  "mcpServers": {
    "yunprint-print": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8931/mcp",
      "headers": {
        "Authorization": "Bearer <云打印Token>",
        "X-Report-Name": "%E9%94%80%E5%94%AE%E5%8D%95"
      }
    }
  }
}
```

`X-Report-Name` 值需 URL 编码（如 `销售单` → `%E9%94%80%E5%94%AE%E5%8D%95`），
且**只编码一次**，禁止双重编码。

不同 Agent 平台的配置字段名可能不同，但必须保持以下三项：

| 配置项 | 值 |
|---|---|
| 传输 | Streamable HTTP |
| URL | `http(s)://<MCP服务地址>/mcp` |
| Header | `Authorization: Bearer <云打印Token>` + `X-Report-Name: <URL编码分类>` |

MCP 服务在 `initialize` 响应中签发 `Mcp-Session-Id`。标准 MCP 客户端会在
后续请求中自动携带它，不要在配置文件里写死该请求头。同一轮对话
必须复用同一 MCP 会话，才能继续编辑 `currentStyle`。

连接成功后应只能发现：

1. `getPrintInfo`
2. `newStyle`
3. `saveStyle`

### 连接排查

| 现象 | 检查项 |
|---|---|
| 404 | URL 必须以 `/mcp` 结尾 |
| `MCP_UNAUTHORIZED` | 检查 `Authorization` 是否为 `Bearer <Token>` |
| 缺少或无效 `Mcp-Session-Id` | 确认客户端支持有状态 Streamable HTTP，并复用初始化会话 |
| `BUSINESS_CONNECTION_INVALID` | 检查服务端 `YUNPRINT_BASE_URL` |
| `YUNPRINT_REQUEST_FAILED` | 检查云打印 Token、网络和云打印 API 状态 |

更完整的部署、反向代理和手工握手验证方式见
[SaaS 与三接口 MCP 接入](architecture/saas-mcp-integration.md)。

## 测试

```bash
uv run pytest -q
```

三个工具的请求契约、动态 Token 注入、权限和 Schema 测试位于
`tests/printing/test_style_*.py`。

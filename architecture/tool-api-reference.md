# 三个 MCP 工具与业务 API

MCP 客户端连接 `http(s)://<MCP服务地址>/mcp`，在请求头中携带
`Authorization: Bearer <云打印Token>` 和 `X-Report-Name: <URL编码的报表分类>`。
两者均由对接方按入口动态传入，不进入工具参数。客户端不直接调用下面的
`ElectronPrintApi` 路径；这三个业务 API 由 MCP 服务端 Adapter 调用。

工具名使用 camelCase（`getPrintInfo`、`newStyle`、`saveStyle`），通过
`FunctionTool(name=)` 显式发布，确保协议层、系统提示词和模型可见名三者统一。

启动和连接配置见 [SaaS 与三接口 MCP 接入](saas-mcp-integration.md)。

## 动态参数总表

| 参数 | getPrintInfo | newStyle | saveStyle | 值的来源 |
|---|---|---|---|---|
| Token | 动态 | 动态 | 动态 | `Authorization: Bearer` 请求头 |
| `reportName` | 动态 | 动态 | 动态 | `X-Report-Name` 请求头（URL 编码） |
| `reportType` | 固定 `1` | 动态 | 动态 | 业务上下文；保存时沿用 NewStyle 返回值 |
| `styleName` | 固定空字符串 | 动态 | 动态 | 新模板名称；保存时沿用 NewStyle 返回值 |
| `styleId` | 固定空字符串 | 固定空字符串 | 动态 | NewStyle 返回的 `id`，始终作为字符串 |
| `styleContent` | 固定空字符串 | 固定空字符串 | 动态 | 模板 JSON 生成或多轮编辑结果 |
| `isDynamicBaseStyle` | 固定空字符串 | 固定空字符串 | 固定空字符串 | 服务端填充 |
| `baseStyleContent` | 固定空字符串 | 固定空字符串 | 固定空字符串 | 服务端填充 |
| `isPublic` | 固定 `false` | 固定 `false` | 固定 `false` | 服务端填充 |

Token 和 reportName 均由 HTTP 请求头注入，不进入工具 `arguments`，
模型不会看到它们，也不能把它们当作工具参数。

## 对接方的动态传参方式

对接方调用 `getPrintInfo` 时，Token 和 reportName 都在 HTTP 请求头中传入：

```http
POST http://<mcp-host>/mcp
Authorization: Bearer <本次动态Token>
X-Report-Name: <URL编码的报表分类，如 %E9%94%80%E5%94%AE%E5%8D%95>
Mcp-Session-Id: <initialize返回的会话ID>
MCP-Protocol-Version: 2025-11-25
Content-Type: application/json
Accept: application/json, text/event-stream
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

| 对接方输入 | 位置 | MCP 服务端映射 |
|---|---|---|
| 当前 `token` | HTTP `Authorization` 头 | 业务请求体 `token` |
| 当前 `reportName` | HTTP `X-Report-Name` 头 | 业务请求体 `reportName` |
| 无需传入 | - | 业务请求体 `reportType=1` |

Token 和 reportName 都不放入 `arguments`，避免它们进入模型上下文、
工具 Schema 和工具调用记录。

## 1. getPrintInfo

获取 `reportType=1` 的指定分类下已有模板样式。

路径：`POST /ElectronPrintApi/GetPrintInfo`

MCP 参数：

| 参数 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| （无参数） | | | | reportName 由 `X-Report-Name` 头注入 |

MCP 调用参数：

```json
{}
```

业务请求：

```json
{
  "token": "<动态注入>",
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

返回 `styles` 摘要、完整 `printInfo`，以及当前会话的 `currentStyle`：

| 字段 | 说明 |
|---|---|
| `currentStyle` | 没有当前模板时为 `null` |
| `currentStyle.styleId` | 后续修改必须复用的模板 ID |
| `currentStyle.styleContent` | 最近一次 SaveStyle 成功后的完整模板 JSON |
| `currentStyle.revision` | 同一 styleId 在当前会话内的成功保存次数 |
| `currentStyle.hasContent` | NewStyle 后尚未保存时为 false |

## 2. newStyle

路径：`POST /ElectronPrintApi/NewStyle`

| 参数 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `report_type` | integer | 是 | `minimum: 1` | 当前业务的报表类型，例如 `1` |
| `style_name` | string | 是 | `minLength: 1` | 用户指定的新模板名称 |

MCP 调用参数：

```json
{
  "report_type": 1,
  "style_name": "图片还原模板"
}
```

服务端转换后的业务 API 请求：

```json
{
  "token": "<从当前 Authorization 头动态注入>",
  "reportName": "销售单",
  "reportType": 1,
  "styleName": "图片还原模板",
  "styleId": "",
  "styleContent": "",
  "isDynamicBaseStyle": "",
  "baseStyleContent": "",
  "isPublic": false
}
```

Repository 发送的其他字段固定为空字符串或 `false`。成功结果必须包含字符串
`result.data.id`。MCP 返回：

```json
{
  "ok": true,
  "message": "打印模板样式已创建，请继续调用 saveStyle 保存模板内容",
  "styleId": "2086707921336647680",
  "reportName": "销售单",
  "reportType": 1,
  "styleName": "图片还原模板",
  "revision": 0
}
```

## 3. saveStyle

路径：`POST /ElectronPrintApi/SaveStyle`

| 参数 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `report_type` | integer | 是 | `minimum: 1` | 使用 NewStyle 返回的 `reportType` |
| `style_name` | string | 是 | `minLength: 1` | 使用 NewStyle 返回的 `styleName` |
| `style_id` | string | 是 | `minLength: 1` | 使用 NewStyle 返回的 `styleId` |
| `style_content` | object | 是 | `minProperties: 1` | 本轮生成或编辑后的完整原生模板 JSON |

MCP 调用参数：

```json
{
  "report_type": 1,
  "style_name": "图片还原模板",
  "style_id": "2086707921336647680",
  "style_content": {
    "ReportName": "销售单",
    "PageSetting": {
      "PrinterName": "默认打印机",
      "PaperName": "A4"
    },
    "Pages": []
  }
}
```

服务端转换后的业务 API 请求：

```json
{
  "token": "<从当前 Authorization 头动态注入>",
  "reportName": "销售单",
  "reportType": 1,
  "styleName": "图片还原模板",
  "styleId": "2086707921336647680",
  "styleContent": "<服务端序列化后的完整模板 JSON 字符串>",
  "isDynamicBaseStyle": "",
  "baseStyleContent": "",
  "isPublic": false
}
```

Repository 使用紧凑 JSON 把 `style_content` 序列化为业务 API 所需的字符串，中文
保持原文，不进行 ASCII 转义。

保存成功后 MCP 把完整 `style_content` 写入当前会话状态并返回递增后的
`revision`。远端保存失败时不会更新会话状态。

## 统一响应与错误

业务 API 响应信封：

```json
{
  "result": {
    "success": true,
    "message": null,
    "data": null
  }
}
```

MCP 工具响应统一使用 `{"ok": true, ...}` 或 `{"ok": false, "error": {"code": ..., "message": ...}}`
格式。未被工具方法捕获的 `DomainError` 由 MCP 层统一拦截并返回结构化错误响应。

| 错误码 | 说明 |
|---|---|
| `MCP_UNAUTHORIZED` | 缺少或错误的 Bearer 头 |
| `CAPABILITY_FORBIDDEN` | 缺少 read/write scope（由 `check_permissions` 校验） |
| `STYLE_INVALID` | reportName、名称、模板 ID 或 reportType 无效 |
| `STYLE_CONTENT_INVALID` | 模板 JSON 为空、非原生格式、多表格或无字段绑定 |
| `YUNPRINT_REQUEST_FAILED` | HTTP、网络或业务失败 |
| `YUNPRINT_RESPONSE_INVALID` | 响应信封、类型或新增模板 ID 无效 |
| `BUSINESS_CREDENTIAL_REQUIRED` | 当前会话缺少云打印 Bearer |
| `BUSINESS_CONNECTION_INVALID` | 未配置 `YUNPRINT_BASE_URL` 或地址无效 |
| `PRINT_API_NOT_CONFIGURED` | 打印服务未注入已鉴权 PrintApiPort |

GetPrintInfo 可对网络错误和 5xx 重试（异步 `asyncio.sleep` 指数退避）。NewStyle
与 SaveStyle 不自动重试。

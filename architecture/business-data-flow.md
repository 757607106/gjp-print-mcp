# 三接口业务数据流

## 输入与输出

| 数据 | 来源 | 去向 | 说明 |
|---|---|---|---|
| reportName | `X-Report-Name` HTTP 头 | BearerConnectionStore → 工具 | URL 编码的报表分类，由对接方按入口传入 |
| `report_type` | 业务上下文 | NewStyle / SaveStyle | 动态报表类型；GetPrintInfo 固定为 1 |
| `style_name` | 用户或视觉 Agent | NewStyle / SaveStyle | 新模板名称 |
| `style_id` | NewStyle 响应 | SaveStyle | 字符串 ID，不转为数值 |
| `style_content` | 模板 JSON 生成内核或视觉 Agent | SaveStyle | 完整原生模板 JSON 对象 |
| 云打印 Token | MCP Authorization 头 | Adapter / Repository | 不进入工具 Schema、结果或模型参数 |
| `currentStyle` | `TemplateConversationStore` | GetPrintInfo 工具结果 | 当前会话最近模板、完整 JSON 和 revision |

## 动态参数传递

```text
对接方 MCP 连接
  → Authorization Bearer Token + X-Report-Name 头
  → 服务端动态注入三个业务 API

工具调用（reportName 由头注入）
  → report_type / style_name
  → NewStyle
  → reportType / styleName / styleId
  → SaveStyle

模板生成或本轮编辑
  → 完整 style_content JSON 对象
  → SaveStyle
```

多账号时，对接方使用 `account_id` 从服务端凭据库选择当前 Token，并按入口
设置对应的 X-Report-Name 头。账号切换必须新建 MCP 会话，不共享
`Mcp-Session-Id`。

## 数据流

```text
Authorization: Bearer <token>
  → OpaqueTokenIdentityResolver
  → BearerConnectionStore
  → InvocationContext（不含 Token）
  → PrintToolSet（三个工具）
  → YunPrintAccessTokenAdapter（重新注入 Token）
  → YunPrintRepository
  → GetPrintInfo / NewStyle / SaveStyle
```

## 模板 JSON 生成边界

`catalog`、`domain`、`planner`、`plan_builder`、`paper`、`native`、`reports`、
`service` 和模板计划模型继续负责生成、修改和校验原生模板 JSON。它们是内部
领域代码，不改变对外 MCP 只发布三个工具的边界。

MCP 不写本地文件。`TemplateConversationStore` 在进程内保存每个认证会话、每个
报表分类最新的完整模板 JSON；最终 JSON 仍通过 `save_style.style_content` 写入
云打印业务系统。

## 多轮修改

```text
第 1 轮：NewStyle → SaveStyle(JSON v1) → revision=1
第 2 轮：GetPrintInfo.currentStyle(JSON v1)
        → 只修改用户指定内容
        → SaveStyle(同一 styleId, JSON v2) → revision=2
第 N 轮：重复恢复、修改、保存
```

不同 `tenant_id / account_id / session_id / report_name` 的状态相互隔离。参考存储
不保留历史版本，仅保留最新 JSON。`session_id` 优先由 Token 与标准
`Mcp-Session-Id` 共同派生，避免同一 Token 的并行对话互相覆盖。

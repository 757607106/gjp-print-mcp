# GJP Agent

基于 AgentScope 2.0.4 的云打印模板样式 MCP 服务。对外只发布 GetPrintInfo、NewStyle、SaveStyle 三项能力，同时保留内部模板 JSON 生成内核。

## 产品与服务边界

| 产品 | ToolSet | 业务端口 | MCP 服务名 |
|---|---|---|---|
| 打印服务 | `PrintToolSet` | `PrintApiPort` | `yunprint-print` |

### 对接模式

```
打印产品 → 各 AI 平台智能体 → 绑定 yunprint-print MCP → 调用打印业务 API
```

MCP 只发布 `get_print_info`、`new_style`、`save_style`。视觉模型识别用户图片并生成模板 JSON，随后通过三个工具查询参考样式、创建模板和保存模板。

## 鉴权与安全设计

- **生产禁止账号密码登录**：打印 MCP 使用 Token 鉴权（opaque token，由云打印 API 自身验证有效性）。
- **token 和 reportName 均由请求头注入**：token 在 `Authorization: Bearer` 头，reportName 在 `X-Report-Name` 头（URL 编码）。两者不进入工具参数、Tool Schema 或模型上下文。
- **对接方按入口动态传入**：不同对接方入口对应不同的 token 和 reportName，在 MCP HTTP 请求头中动态设置。
- **base_url 部署级固定**：云打印业务 API 地址通过 `YUNPRINT_BASE_URL` 环境变量配置。
- **身份隔离**：`OpaqueTokenIdentityResolver` 从 Authorization 头派生 `InvocationContext`，`BearerConnectionStore` 按会话保存 token 和 reportName，通过 `ContextVar` 绑定到当前异步任务。
- **媒体边界**：业务方在调用 Agent 前把语音和图片转换并确认为文本；MCP 不处理音频、图片、附件、ASR 或 OCR。

## 技术栈

| 类别 | 选型 |
|---|---|
| Agent 框架 | AgentScope 2.0.4（[稳定版文档](https://docs.agentscope.io/versions/2.0.4/zh)） |
| 工具开发 | [Tool 参考](https://docs.agentscope.io/versions/2.0.4/zh/building-blocks/tool) |
| 语言 | Python >= 3.11 |
| 包管理 | uv + pyproject.toml |
| MCP 协议 | mcp >= 1.28（Streamable HTTP） |
| 模型支持 | OpenAI / Anthropic / DashScope / DeepSeek / Gemini / Moonshot / xAI / Ollama |

## 代码结构

```
src/
├── yunprint/                  # 打印服务包：App、ToolSet、Port、Adapter、Prompt、MCP、领域代码
└── gjp_common/                # 业务无关公共层：上下文、连接、MCP、配置、路径、日志
```

`ToolSet` 是 Agent 与 MCP 的唯一工具来源。`create_print_mcp_service` 有 `isinstance` 类型守卫，确保只发布 `PrintToolSet`。`catalog / planner / native / service` 等模块是内部模板 JSON 生成能力，不额外注册 MCP 工具。`TemplateConversationStore` 仅保存三个工具间的当前模板 JSON 和修订号，不定义工具。

## 开发规范

### 架构原则
- 站在 Agent 应用开发架构师角度设计项目架构。
- 遵循 AgentScope 2.0.4 官方语法构建代码，遇到问题先查官方文档。
- 禁止过度设计，逻辑清晰易于维护。
- 禁止兼容或补丁方式实现——遇到设计问题应重构而非打补丁。
- 业务逻辑和测试逻辑严格分开，不遗留无关代码或文件。
- 新增产品时建立独立产品包的 `app.py`、`toolset.py`、`ports.py`、`adapters.py`、`prompt.py` 和 `mcp_service.py`。

### 文档与文件组织
- 文档按类别放在 `architecture/` 子目录，不乱放。
- 工程文件命名需规范，与功能对应。
- 代码功能概要使用中文注释。
- Git 提交信息使用中文。

### 架构设计文档
- `architecture/architecture-diagrams.md` — 系统架构图
- `architecture/business-data-flow.md` — 业务数据与数据流梳理
- `architecture/saas-mcp-integration.md` — SaaS 对话页与 MCP 租户连接方案
- `architecture/tool-api-reference.md` — 三个工具与业务 API 契约

### 本地开发

```bash
uv sync --extra dev                          # 安装开发依赖
uv run pytest -q                             # 运行测试
```

生产服务通过 `yunprint.mcp_service.create_print_mcp_service()` 创建独立 MCP HTTP 应用。

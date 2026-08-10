"""打印能力独立 MCP 服务，只发布 PrintToolSet。"""

from collections.abc import Sequence

from starlette.applications import Starlette
from starlette.routing import BaseRoute

from gjp_common.mcp import (
    McpIdentityResolver,
    McpToolSetResolver,
    create_mcp_http_app,
    create_mcp_server,
)
from .prompt import TEMPLATE_AGENT_SYSTEM_PROMPT
from .toolset import PrintToolSet


def create_print_mcp_service(
    schema_toolset: PrintToolSet,
    identity_resolver: McpIdentityResolver,
    toolset_resolver: McpToolSetResolver,
    extra_routes: Sequence[BaseRoute] = (),
) -> Starlette:
    """创建打印 MCP 服务；部署时使用独立域名、进程和认证配置。"""
    if not isinstance(schema_toolset, PrintToolSet):
        raise TypeError("打印服务只能发布 PrintToolSet")
    server = create_mcp_server(
        "yunprint-print",
        schema_toolset,
        identity_resolver,
        toolset_resolver,
        instructions=TEMPLATE_AGENT_SYSTEM_PROMPT,
    )
    return create_mcp_http_app(server, extra_routes=extra_routes)

"""通用工具基类：AgentScope 工具包装器。

本文件只包含所有业务 Agent 共用的工具基础设施，不包含任何业务特定逻辑。
业务特定的工具入参 schema 放在各自业务模块的 tools.py 中。
"""

from typing import Any

from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool


class BusinessFunctionTool(FunctionTool):
    """已认证业务工具基类：调用时免二次确认。

    工具的读写属性仍会发布到 MCP annotations；权限由 InvocationContext
    和远端业务 API 共同校验。
    """

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Allowed for the authenticated business invocation.",
        )

"""通用工具基类：AgentScope 工具包装器。

本文件只包含所有业务 Agent 共用的工具基础设施，不包含任何业务特定逻辑。
业务特定的工具入参 schema 放在各自业务模块的 tools.py 中。
"""

from typing import Any

from agentscope.permission import PermissionBehavior, PermissionDecision
from agentscope.tool import FunctionTool

from .context import InvocationContextStore


class BusinessFunctionTool(FunctionTool):
    """已认证业务工具基类：调用时免二次确认，但接入 scope 权限检查。

    工具的读写属性仍会发布到 MCP annotations；权限由 InvocationContext
    和远端业务 API 共同校验。check_permissions 从 ContextVar 读取当前
    InvocationContext，校验 required_scope 后放行，将框架权限系统与
    项目的 scope 体系对齐。
    """

    def __init__(
        self,
        func: Any,
        *,
        name: str | None = None,
        description: str | None = None,
        is_concurrency_safe: bool = True,
        is_read_only: bool = False,
        input_schema: dict[str, Any] | None = None,
        contexts: InvocationContextStore | None = None,
        required_scope: str = "",
    ) -> None:
        super().__init__(
            func,
            name=name,
            description=description,
            is_concurrency_safe=is_concurrency_safe,
            is_read_only=is_read_only,
        )
        if input_schema is not None:
            self.input_schema = input_schema
        self._contexts = contexts
        self._required_scope = required_scope

    async def check_permissions(self, *_args: Any, **_kwargs: Any) -> PermissionDecision:
        """从 ContextVar 读取当前 InvocationContext 并校验 scope。"""
        if self._contexts is not None and self._required_scope:
            context = self._contexts.get()
            context.require_scope(self._required_scope)
        return PermissionDecision(
            behavior=PermissionBehavior.ALLOW,
            message="Allowed for the authenticated business invocation.",
        )

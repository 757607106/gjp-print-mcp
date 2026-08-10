"""三个云打印模板样式 API 的动态 Token Adapter。"""

from __future__ import annotations

from typing import Any, Callable

from gjp_common.connections import TenantApiConnectionProvider
from gjp_common.context import InvocationContext
from gjp_common.errors import DomainError

from .repository import YunPrintRepository


class YunPrintAccessTokenAdapter:
    """按当前 MCP 调用上下文注入云打印访问令牌。"""

    def __init__(
        self,
        connection_provider: TenantApiConnectionProvider,
        *,
        timeout_seconds: float = 30,
        max_retries: int = 3,
        repository_factory: Callable[[str], YunPrintRepository] | None = None,
    ) -> None:
        self._connection_provider = connection_provider
        self._repository_factory = repository_factory or (
            lambda base_url: YunPrintRepository(
                base_url,
                timeout_seconds=timeout_seconds,
                max_retries=max_retries,
            )
        )

    def _client(self, context: InvocationContext) -> tuple[YunPrintRepository, str]:
        connection = self._connection_provider.resolve(context)
        connection.require_product("print")
        if connection.credential.kind != "business_token":
            raise DomainError("PRINT_API_UNAUTHORIZED", "当前打印会话的鉴权类型无效")
        return self._repository_factory(connection.base_url), connection.credential.value

    def get_print_info(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
    ) -> dict[str, Any]:
        repository, token = self._client(context)
        return repository.get_print_info(token, report_name, report_type)

    def new_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
    ) -> dict[str, Any]:
        repository, token = self._client(context)
        return repository.new_style(token, report_name, report_type, style_name)

    def save_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> Any:
        repository, token = self._client(context)
        return repository.save_style(
            token,
            report_name,
            report_type,
            style_name,
            style_id,
            style_content,
        )


class UnavailablePrintApi:
    """Schema ToolSet 未注入真实 Adapter 时返回明确错误。"""

    @staticmethod
    def _raise() -> None:
        raise DomainError("PRINT_API_NOT_CONFIGURED", "打印服务尚未注入已鉴权 PrintApiPort")

    def get_print_info(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
    ) -> dict[str, Any]:
        self._raise()

    def new_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
    ) -> dict[str, Any]:
        self._raise()

    def save_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> Any:
        self._raise()

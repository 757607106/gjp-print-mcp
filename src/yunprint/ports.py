"""三个云打印模板样式 API 的业务端口。"""

from __future__ import annotations

from typing import Any, Protocol

from gjp_common.context import InvocationContext


class PrintApiPort(Protocol):
    """获取、新建和保存模板样式的已鉴权 API 端口。"""

    def get_print_info(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
    ) -> dict[str, Any]:
        ...

    def new_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
    ) -> dict[str, Any]:
        ...

    def save_style(
        self,
        context: InvocationContext,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> Any:
        ...

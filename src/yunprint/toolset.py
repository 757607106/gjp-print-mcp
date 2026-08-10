"""云打印模板样式的三个标准 MCP 工具。"""

from __future__ import annotations

from typing import Any, Callable

from gjp_common.context import InvocationContext, InvocationContextStore
from gjp_common.errors import DomainError
from gjp_common.tools import BusinessFunctionTool
from gjp_common.toolset import AgentScopeToolSet

from .conversation import TemplateConversationStore
from .ports import PrintApiPort
from .repository import YunPrintRepository


PRINT_MCP_TOOL_NAMES = frozenset(
    {
        "get_print_info",
        "new_style",
        "save_style",
    },
)


def _coerce_int(value: int | str, name: str) -> int:
    """把模型可能传入的字符串整数统一转为 int。"""
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            raise DomainError("STYLE_INVALID", "%s 必须是整数" % name)
    return value


def _required_text(value: str, name: str) -> str:
    """校验业务 API 必填文本。"""
    normalized = value.strip()
    if not normalized:
        raise DomainError("STYLE_INVALID", "%s 不能为空" % name)
    return normalized


def _style_report_type(value: int | str) -> int:
    """校验模板样式接口使用的 reportType。"""
    report_type = _coerce_int(value, "report_type")
    if report_type <= 0:
        raise DomainError("STYLE_INVALID", "report_type 必须是正整数")
    return report_type


def _validate_native_template(content: dict[str, Any]) -> None:
    """校验 style_content 是否为云打印原生模板 JSON 格式。

    云打印平台要求 styleContent 是包含 ReportName、Pages、BandAreas 等
    字段的原生模板结构。拒绝自定义格式（如 version/components/page），
    避免保存后平台无法渲染。
    """
    if "ReportName" not in content:
        raise DomainError(
            "STYLE_CONTENT_INVALID",
            "style_content 缺少 ReportName 字段；必须使用云打印原生模板格式"
            "（ReportName、PageSetting、Pages、BandAreas），"
            "不要使用 version/components 等自定义格式",
        )
    pages = content.get("Pages")
    if not isinstance(pages, list) or not pages:
        raise DomainError(
            "STYLE_CONTENT_INVALID",
            "style_content 缺少 Pages 数组；必须包含至少一个页面，"
            "每个页面需有 ClassName、Width、Height、BandAreas",
        )
    for index, page in enumerate(pages):
        if not isinstance(page, dict):
            raise DomainError(
                "STYLE_CONTENT_INVALID",
                "Pages[%d] 不是 JSON 对象" % index,
            )
        if "ClassName" not in page:
            raise DomainError(
                "STYLE_CONTENT_INVALID",
                "Pages[%d] 缺少 ClassName 字段（应为 TTemplatePage）" % index,
            )
        if not isinstance(page.get("BandAreas"), list):
            raise DomainError(
                "STYLE_CONTENT_INVALID",
                "Pages[%d] 缺少 BandAreas 数组" % index,
            )


class PrintToolSet(AgentScopeToolSet):
    """只发布获取、新建和保存模板样式三个工具。

    token 和 reportName 由 MCP 请求头动态注入，不进入工具参数。
    """

    def __init__(
        self,
        api: PrintApiPort,
        contexts: InvocationContextStore,
        conversations: TemplateConversationStore | None = None,
        report_name_resolver: Callable[[InvocationContext], str] | None = None,
    ) -> None:
        self._api = api
        self._conversations = conversations or TemplateConversationStore()
        self._report_name_resolver = report_name_resolver or (lambda _ctx: "")
        super().__init__(
            [
                BusinessFunctionTool(self.get_print_info, is_read_only=True),
                BusinessFunctionTool(self.new_style, is_concurrency_safe=False),
                BusinessFunctionTool(self.save_style, is_concurrency_safe=False),
            ],
            contexts=contexts,
            agent_tool_names=PRINT_MCP_TOOL_NAMES,
            mcp_tool_names=PRINT_MCP_TOOL_NAMES,
        )

    def _resolve_report_name(self) -> str:
        """从当前会话的 MCP 请求头解析 reportName。"""
        context = self._contexts.get()
        return _required_text(self._report_name_resolver(context), "report_name")

    def get_print_info(self) -> dict[str, Any]:
        """获取当前分类（reportType 固定为 1）下已有的打印模板样式。

        reportName 由 MCP 请求头 X-Report-Name 动态注入，Token 由
        Authorization 头注入，均不进入工具参数。

        返回 styles 是样式摘要，printInfo 保留 GetPrintInfo 的完整业务数据，
        供视觉模型还原设计时参考。
        """
        try:
            report_name = self._resolve_report_name()
            context = self._contexts.get()
            context.require_scope("print:read")
            print_info = self._api.get_print_info(context, report_name, 1)
            return self.ok_response(
                reportName=report_name,
                reportType=1,
                styles=YunPrintRepository.style_records(print_info),
                printInfo=print_info,
                currentStyle=self._conversations.current(context, report_name),
            )
        except DomainError as exc:
            return self.error_response(exc)

    def new_style(
        self,
        report_type: int | str,
        style_name: str,
    ) -> dict[str, Any]:
        """在当前报表分类下新增一个空白打印模板样式。

        reportName 由 MCP 请求头 X-Report-Name 动态注入。

        Args:
            report_type: 报表类型，例如 1。
            style_name: 新增模板名称。
        """
        try:
            report_name = self._resolve_report_name()
            report_type = _style_report_type(report_type)
            style_name = _required_text(style_name, "style_name")
            context = self._contexts.get()
            context.require_scope("print:write")
            created = self._api.new_style(
                context,
                report_name,
                report_type,
                style_name,
            )
            style_id = _required_text(str(created.get("id") or ""), "style_id")
            created_report_name = str(created.get("reportName") or report_name)
            created_report_type = int(created.get("reportType") or report_type)
            created_style_name = str(created.get("styleName") or style_name)
            current_style = self._conversations.record_created(
                context,
                report_name=created_report_name,
                report_type=created_report_type,
                style_name=created_style_name,
                style_id=style_id,
            )
            return self.ok_response(
                message="打印模板样式已创建，请继续调用 save_style 保存模板内容",
                styleId=style_id,
                reportName=created_report_name,
                reportType=created_report_type,
                styleName=created_style_name,
                revision=current_style["revision"],
            )
        except (DomainError, TypeError, ValueError) as exc:
            if isinstance(exc, DomainError):
                return self.error_response(exc)
            return self.error_response(
                DomainError("YUNPRINT_RESPONSE_INVALID", "新增样式返回的 reportType 无效"),
            )

    def save_style(
        self,
        report_type: int | str,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> dict[str, Any]:
        """把生成的原生模板 JSON 保存到已创建的打印模板样式。

        reportName 由 MCP 请求头 X-Report-Name 动态注入。

        Args:
            report_type: new_style 返回的报表类型。
            style_name: new_style 返回的模板名称。
            style_id: new_style 返回的模板 ID。
            style_content: 模板生成逻辑输出的原生打印模板 JSON 对象。
        """
        try:
            report_name = self._resolve_report_name()
            report_type = _style_report_type(report_type)
            style_name = _required_text(style_name, "style_name")
            style_id = _required_text(style_id, "style_id")
            if not isinstance(style_content, dict) or not style_content:
                raise DomainError(
                    "STYLE_CONTENT_INVALID",
                    "style_content 必须是非空 JSON 对象",
                )
            _validate_native_template(style_content)
            context = self._contexts.get()
            context.require_scope("print:write")
            api_result = self._api.save_style(
                context,
                report_name,
                report_type,
                style_name,
                style_id,
                style_content,
            )
            current_style = self._conversations.record_saved(
                context,
                report_name=report_name,
                report_type=report_type,
                style_name=style_name,
                style_id=style_id,
                style_content=style_content,
            )
            return self.ok_response(
                message="打印模板样式已保存",
                styleId=style_id,
                reportName=report_name,
                reportType=report_type,
                styleName=style_name,
                revision=current_style["revision"],
                apiResult=api_result,
            )
        except DomainError as exc:
            return self.error_response(exc)

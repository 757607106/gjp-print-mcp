"""三个 MCP 工具共享的多轮模板编辑状态。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import threading
from typing import Any

from gjp_common.context import InvocationContext


@dataclass(frozen=True)
class TemplateStyleState:
    """当前会话在一个报表分类下最近操作的模板。"""

    report_name: str
    report_type: int
    style_name: str
    style_id: str
    style_content: dict[str, Any] | None = None
    revision: int = 0

    def to_tool_dict(self) -> dict[str, Any]:
        """返回与内部状态隔离的工具响应对象。"""
        return {
            "reportName": self.report_name,
            "reportType": self.report_type,
            "styleName": self.style_name,
            "styleId": self.style_id,
            "revision": self.revision,
            "hasContent": self.style_content is not None,
            "styleContent": deepcopy(self.style_content),
        }


class TemplateConversationStore:
    """按认证会话和报表分类保存最近一次完整模板 JSON。

    每个分类只保存最新版本，不保存历史快照。状态位于当前服务进程内；多副本
    部署时可用同一接口替换为共享存储。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._states: dict[tuple[str, str, str, str], TemplateStyleState] = {}

    @staticmethod
    def _key(
        context: InvocationContext,
        report_name: str,
    ) -> tuple[str, str, str, str]:
        return (
            context.tenant_id,
            context.account_id,
            context.session_id,
            report_name.strip().casefold(),
        )

    def current(
        self,
        context: InvocationContext,
        report_name: str,
    ) -> dict[str, Any] | None:
        """读取当前报表最近一次模板状态。"""
        with self._lock:
            state = self._states.get(self._key(context, report_name))
            return state.to_tool_dict() if state is not None else None

    def record_created(
        self,
        context: InvocationContext,
        *,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
    ) -> dict[str, Any]:
        """记录 NewStyle 结果，等待首次 SaveStyle 写入内容。"""
        state = TemplateStyleState(
            report_name=report_name,
            report_type=report_type,
            style_name=style_name,
            style_id=style_id,
        )
        with self._lock:
            self._states[self._key(context, report_name)] = state
        return state.to_tool_dict()

    def record_saved(
        self,
        context: InvocationContext,
        *,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> dict[str, Any]:
        """保存最新完整模板；同一 styleId 每次成功保存递增 revision。"""
        key = self._key(context, report_name)
        with self._lock:
            previous = self._states.get(key)
            revision = (
                previous.revision + 1
                if previous is not None and previous.style_id == style_id
                else 1
            )
            state = TemplateStyleState(
                report_name=report_name,
                report_type=report_type,
                style_name=style_name,
                style_id=style_id,
                style_content=deepcopy(style_content),
                revision=revision,
            )
            self._states[key] = state
            return state.to_tool_dict()

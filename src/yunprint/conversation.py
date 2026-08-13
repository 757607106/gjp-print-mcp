"""三个 MCP 工具共享的多轮模板编辑状态。"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import threading
import time
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
    部署时可用同一接口替换为共享存储。通过 TTL 自动清理过期会话，避免
    内存无限增长。
    """

    _DEFAULT_TTL_SECONDS = 7200

    def __init__(self, ttl_seconds: float = _DEFAULT_TTL_SECONDS) -> None:
        self._lock = threading.Lock()
        self._states: dict[tuple[str, str, str, str], TemplateStyleState] = {}
        self._timestamps: dict[tuple[str, str, str, str], float] = {}
        self._ttl_seconds = ttl_seconds

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

    def _cleanup_locked(self) -> None:
        """清理过期条目，必须在持有锁时调用。"""
        if self._ttl_seconds <= 0:
            return
        now = time.monotonic()
        expired = [
            key for key, ts in self._timestamps.items()
            if now - ts > self._ttl_seconds
        ]
        for key in expired:
            self._states.pop(key, None)
            self._timestamps.pop(key, None)

    def _touch_locked(self, key: tuple[str, str, str, str]) -> None:
        """记录或更新条目的最后访问时间。"""
        self._timestamps[key] = time.monotonic()

    def _check_expired_locked(self, key: tuple[str, str, str, str]) -> None:
        """检查单个条目是否过期，过期则删除。"""
        if self._ttl_seconds <= 0:
            return
        ts = self._timestamps.get(key)
        if ts is not None and time.monotonic() - ts > self._ttl_seconds:
            self._states.pop(key, None)
            self._timestamps.pop(key, None)

    def current(
        self,
        context: InvocationContext,
        report_name: str,
    ) -> dict[str, Any] | None:
        """读取当前报表最近一次模板状态。"""
        key = self._key(context, report_name)
        with self._lock:
            self._check_expired_locked(key)
            state = self._states.get(key)
            if state is not None:
                self._touch_locked(key)
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
        key = self._key(context, report_name)
        with self._lock:
            self._cleanup_locked()
            self._states[key] = state
            self._touch_locked(key)
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
            self._cleanup_locked()
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
            self._touch_locked(key)
            return state.to_tool_dict()

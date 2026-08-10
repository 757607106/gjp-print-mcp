"""测试专用服务辅助函数，替代旧 service.generate(auto_strategy=True) 流程。"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

from gjp_common.errors import DomainError

if TYPE_CHECKING:
    from yunprint.catalog import FieldCatalog
    from yunprint.reports import ReportContext
    from yunprint.service import TemplateAgentService
    from .rule_planner import RuleBasedPlanner


UNSUPPORTED_REQUEST_PATTERNS = (
    re.compile(r"(?:生成|增加|添加|插入|需要|使用|绘制|画|显示).{0,8}(?:柱状图|折线图|饼图|图表)"),
    re.compile(r"(?:自由布局|自由绘制)"),
    re.compile(r"(?:两个|多个|第二个|多张).{0,5}明细表"),
    re.compile(r"(?:自定义表达式|任意表达式|脚本表达式)"),
)
QUICK_TABLE_REQUEST_PATTERNS = (
    re.compile(r"(?:列宽|加宽|变宽|宽一点|缩窄|变窄|窄一点)"),
    re.compile(r"(?:修改标题|标题改为|标题设置为|重命名|命名为)"),
    re.compile(r"(?:移动|调整顺序|放到|移到).{0,12}(?:字段|列|前面|后面|之前|之后)"),
    re.compile(r"(?:纸张|A3|A4|A5|横向|纵向)", re.IGNORECASE),
    re.compile(r"(?:行高|字号|字体大小|边框|网格线|竖线|横线|虚线|点线|实线)"),
)


def _extract_user_request_text(message: str) -> str:
    """从交互会话 JSON 中只提取用户原文，避免把系统规则误判为业务能力请求。"""
    try:
        payload = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return message
    if not isinstance(payload, dict) or payload.get("task") != "multi-turn-template-session":
        return message
    conversation = payload.get("conversation")
    if not isinstance(conversation, list):
        return message
    return "\n".join(
        str(item.get("user"))
        for item in conversation
        if isinstance(item, dict) and isinstance(item.get("user"), str)
    )


def _guard_supported_capabilities(message: str) -> None:
    for pattern in UNSUPPORTED_REQUEST_PATTERNS:
        matched = pattern.search(message)
        if matched:
            raise DomainError(
                "CAPABILITY_UNSUPPORTED",
                "当前本地模板验证器尚不能执行：%s" % matched.group(0),
            )


def _requires_quick_table(message: str) -> bool:
    return any(pattern.search(message) for pattern in QUICK_TABLE_REQUEST_PATTERNS)


def generate_draft(
    service: "TemplateAgentService",
    planner: "RuleBasedPlanner",
    message: str,
):
    """测试辅助函数：复现旧 service.generate(auto_strategy=True) 的完整流程。"""
    request_text = _extract_user_request_text(message)
    _guard_supported_capabilities(request_text)

    planning_context = service.report_context.planner_payload() if service.report_context else None
    envelope = (
        planner.plan(message, service.catalog, planning_context)
        if planning_context is not None
        else planner.plan(message, service.catalog)
    )
    if envelope.clarification_needed:
        raise DomainError("FIELD_AMBIGUOUS", envelope.clarification_question or "需要补充字段信息")
    if envelope.plan is None:
        raise DomainError("PLAN_INVALID", "模型未返回可执行计划")

    use_clone = bool(
        service._matches_base_structure(envelope.plan)
        and not _requires_quick_table(request_text)
    )
    return service.execute_plan(envelope.plan, preserve_base=use_clone)

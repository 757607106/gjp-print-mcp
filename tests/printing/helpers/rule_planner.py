"""测试专用规则规划器和辅助函数，不用于生产环境。"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence

from yunprint.catalog import FieldCatalog
from yunprint.domain import (
    AgentEnvelope,
    BorderPlan,
    DomainError,
    PagePlan,
    TableStylePlan,
    TemplatePlan,
)
from yunprint.paper import apply_standard_paper_requirements
from yunprint.planner import (
    _parse_table_style,
    _validate_table_style_plan,
    build_plan,
)


EXPLICIT_FIELD_SELECTION_PHRASES = (
    "包含字段",
    "字段包括",
    "字段为",
    "主表包含",
    "明细包含",
    "要有",
    "只保留",
    "仅保留",
    "不要字段",
    "删除字段",
    "去掉字段",
    "移除字段",
    "增加字段",
    "替换字段",
    "删除",
    "去掉",
    "移除",
    "只保留",
    "仅保留",
    "不要",
    "新增",
)


COMMON_FIELD_ALIASES = {
    "商品全名": ("商品名称", "商品名"),
    "单据备注": ("备注",),
}


def sanitize_user_message(message: str) -> str:
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", message).strip()
    if not value:
        raise DomainError("INPUT_INVALID", "自然语言需求不能为空")
    if len(value) > 4000:
        raise DomainError("INPUT_INVALID", "自然语言需求不能超过 4000 字")
    if "<script" in value.lower() or "javascript:" in value.lower():
        raise DomainError("INPUT_UNSAFE", "输入包含不允许的脚本内容")
    return value


def _session_payload(message: str) -> Dict[str, Any]:
    try:
        value = json.loads(message)
    except (TypeError, json.JSONDecodeError):
        return {}
    if not isinstance(value, dict) or value.get("task") != "multi-turn-template-session":
        return {}
    return value


def _latest_user_message(message: str) -> str:
    session = _session_payload(message)
    conversation = session.get("conversation")
    if isinstance(conversation, list) and conversation:
        last = conversation[-1]
        if isinstance(last, dict) and isinstance(last.get("user"), str):
            return last["user"]
    return message


def has_explicit_field_selection(message: str) -> bool:
    return any(phrase in message for phrase in EXPLICIT_FIELD_SELECTION_PHRASES)


def _page_from_context(planning_context: Optional[Dict[str, Any]]) -> PagePlan:
    base = planning_context.get("basePage") if isinstance(planning_context, dict) else None
    if not isinstance(base, dict) or not isinstance(base.get("marginsCm"), dict):
        return PagePlan()
    margins = base["marginsCm"]
    try:
        return PagePlan(
            paper_name=str(base["paperName"]),
            orientation=str(base["orientation"]),
            width_cm=float(base["widthCm"]),
            height_cm=float(base["heightCm"]),
            margins_cm={
                "top": float(margins["top"]),
                "right": float(margins["right"]),
                "bottom": float(margins["bottom"]),
                "left": float(margins["left"]),
            },
        )
    except (KeyError, TypeError, ValueError):
        return PagePlan()


class RuleBasedPlanner:
    """Offline planner for tests; it never invents fields."""

    def plan(
        self,
        message: str,
        catalog: FieldCatalog,
        planning_context: Optional[Dict[str, Any]] = None,
    ) -> AgentEnvelope:
        safe_message = sanitize_user_message(message)
        latest_message = _latest_user_message(safe_message)
        current_draft = _session_payload(safe_message).get("currentDraftSummary")
        if not isinstance(current_draft, dict):
            current_draft = None
        display_report_name = re.sub(r"\.rwx$", "", catalog.report_name, flags=re.IGNORECASE)
        if display_report_name not in safe_message:
            raise DomainError(
                "REPORT_NOT_FOUND",
                "当前字段目录对应 %s，请在需求中明确报表名称" % display_report_name,
            )

        explicit_field_request = has_explicit_field_selection(latest_message)
        selected = self._matched_fields(latest_message, catalog.fields) if explicit_field_request else []
        assumptions: List[str] = []
        if explicit_field_request and not selected and current_draft is None:
            raise DomainError("FIELD_NOT_FOUND", "明确指定的字段不在当前报表字段目录中")
        if not selected and current_draft is None:
            selected = [item for item in catalog.fields if item.default_recommended]
            assumptions.append("用户未指定完整字段，沿用%s基本样式的推荐字段" % display_report_name)

        if current_draft is not None:
            master_ids = list(current_draft.get("masterFieldIds") or [])
            footer_ids = list(current_draft.get("footerFieldIds") or [])
            detail_columns = [
                dict(item)
                for item in current_draft.get("columns") or []
                if isinstance(item, dict)
            ]
            detail_columns = _apply_rule_column_edits(
                latest_message,
                detail_columns,
                catalog,
            )
            detail_ids = [
                str(item["fieldId"])
                for item in detail_columns
                if item.get("kind") == "field" and isinstance(item.get("fieldId"), str)
            ]
        else:
            master_ids = [
                item.field_id
                for item in selected
                if item.scope == "master" and item.zone == "header"
            ]
            footer_ids = [
                item.field_id
                for item in selected
                if item.scope == "master" and item.zone == "footer"
            ]
            detail_ids = [item.field_id for item in selected if item.scope == "detail"]
            if not detail_ids:
                detail_ids = [item.field_id for item in catalog.default_fields("detail")]
                assumptions.append("未指定明细字段，沿用%s基本样式明细字段" % display_report_name)
            detail_columns = [
                {
                    "kind": "field",
                    "fieldId": field_id,
                    "label": catalog.get(field_id).name,
                    "widthWeight": 1.0,
                }
                for field_id in detail_ids
            ]

        if current_draft is not None:
            total_ids = [
                field_id
                for field_id in current_draft.get("totalFieldIds") or []
                if field_id in detail_ids
            ]
            page = _page_from_summary(current_draft) or _page_from_context(planning_context)
            table_style = _table_style_from_summary(current_draft)
        else:
            total_ids = [
                item.field_id
                for item in catalog.fields
                if item.field_id in detail_ids and item.default_total and item.aggregatable
            ]
            page = _page_from_context(planning_context)
            table_style = TableStylePlan()
        plan = build_plan(
            catalog=catalog,
            title=(
                str(current_draft.get("title") or display_report_name)
                if current_draft is not None
                else display_report_name
            ),
            master_field_ids=master_ids,
            detail_columns=detail_columns,
            total_field_ids=total_ids,
            footer_field_ids=footer_ids,
            page=page,
            confidence=1.0,
            assumptions=assumptions,
            warnings=[],
            cell_options=self._rule_cell_options(
                latest_message,
                self._matched_fields(latest_message, catalog.fields),
            ),
            table_style=table_style,
        )
        apply_standard_paper_requirements(latest_message, plan)
        apply_deterministic_layout_requirements(
            safe_message,
            plan,
            current_draft,
        )
        return AgentEnvelope("1.1", "CREATE_TEMPLATE", False, 1.0, [], assumptions, plan)

    @staticmethod
    def _matched_fields(message: str, fields: Sequence[Any]) -> List[Any]:
        result = []
        for item in fields:
            terms = sorted(
                [item.name]
                + list(item.aliases)
                + list(COMMON_FIELD_ALIASES.get(item.name, ())),
                key=len,
                reverse=True,
            )
            if any(term and term in message for term in terms):
                result.append(item)
        return result

    @staticmethod
    def _rule_cell_options(message: str, fields: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
        options: Dict[str, Dict[str, Any]] = {}
        mentioned = [item for item in fields if item.name and item.name in message]
        clauses = [value for value in re.split(r"[，。；;]", message) if value]
        for item in mentioned:
            related = " ".join(clause for clause in clauses if item.name in clause)
            field_options = options.setdefault(item.field_id, {})
            if "日期" in item.name and "中文日期" in related:
                field_options["formatKind"] = "chinese-date"
            if item.data_type == "number" and any(
                token in related for token in ("0不显示", "零不显示", "为0时不显示")
            ):
                field_options["hideZero"] = True
            if "动态字体" in related:
                field_options["dynamicTextSize"] = True
            if (
                item.scope == "detail"
                and "合并" in related
                and any(token in related for token in ("相同", "一样"))
            ):
                field_options["mergeSameValue"] = True
            if not field_options:
                options.pop(item.field_id, None)
        return options


def _page_from_summary(summary: Dict[str, Any]) -> Optional[PagePlan]:
    raw = summary.get("page")
    if not isinstance(raw, dict) or not isinstance(raw.get("marginsCm"), dict):
        return None
    margins = raw["marginsCm"]
    try:
        return PagePlan(
            paper_name=str(raw["paperName"]),
            orientation=str(raw["orientation"]),
            width_cm=float(raw["widthCm"]),
            height_cm=float(raw["heightCm"]),
            margins_cm={
                "top": float(margins["top"]),
                "right": float(margins["right"]),
                "bottom": float(margins["bottom"]),
                "left": float(margins["left"]),
            },
        )
    except (KeyError, TypeError, ValueError):
        return None


def _table_style_from_summary(summary: Dict[str, Any]) -> TableStylePlan:
    raw = summary.get("tableStyle")
    if not isinstance(raw, dict):
        return TableStylePlan()
    return _parse_table_style(raw)


def _column_terms(column: Dict[str, Any], catalog: FieldCatalog) -> List[str]:
    terms = [str(column.get("label") or "")]
    field_id = column.get("fieldId")
    if column.get("kind") == "field" and isinstance(field_id, str):
        definition = catalog.get(field_id)
        terms.extend([definition.name] + list(definition.aliases))
    if column.get("kind") == "sequence":
        terms.extend(["序号", "行号"])
    return [term for term in terms if term]


def _apply_rule_column_edits(
    message: str,
    columns: List[Dict[str, Any]],
    catalog: FieldCatalog,
) -> List[Dict[str, Any]]:
    """规则规划器只覆盖可确定解释的结构编辑，用于测试和无模型回退。"""
    result = [dict(item) for item in columns]
    matched_detail = [
        item
        for item in RuleBasedPlanner._matched_fields(message, catalog.fields)
        if item.scope == "detail"
    ]

    if any(token in message for token in ("只保留", "仅保留")):
        selected_ids = {item.field_id for item in matched_detail}
        result = [
            item
            for item in result
            if item.get("kind") != "field" or item.get("fieldId") in selected_ids
        ]

    ordinal_match = re.search(r"(?:删除|删掉|去掉|移除)(?:第)?([一二三四五六七八九十\d]+)列", message)
    if not ordinal_match:
        ordinal_match = re.search(r"把第([一二三四五六七八九十\d]+)列(?:删除|删掉|去掉|移除)", message)
    if ordinal_match:
        ordinal = _parse_ordinal(ordinal_match.group(1))
        if ordinal is None or not 1 <= ordinal <= len(result):
            raise DomainError("PLAN_INVALID", "要删除的列序号超出当前表格范围")
        result.pop(ordinal - 1)

    rename_match = re.search(
        r"把?[‘’“”\"']?([^，。；;]{1,20}?)[‘’“”\"']?(?:这一)?列(?:的表头)?(?:修改为|改为|改成|重命名为)"
        r"[‘’“”\"']?([^，。；;]{1,20}?)[‘’“”\"']?(?:这一列|列|栏)?(?:$|[，。；;])",
        message,
    )
    explicit_column_rename = rename_match is not None
    if not rename_match:
        rename_match = re.search(
            r"(?:^|[，。；;])\s*[‘’“”\"']?([^，。；;]{1,20}?)[‘’“”\"']?"
            r"(?:修改为|改为|改成|重命名为)[‘’“”\"']?([^，。；;]{1,20}?)[‘’“”\"']?"
            r"(?=$|[，。；;])",
            message,
        )
    if rename_match:
        old_label = rename_match.group(1).strip(" ‘’“”\"'")
        new_label = rename_match.group(2).strip(" ‘’“”\"'")
        target = next(
            (item for item in result if old_label in _column_terms(item, catalog)),
            None,
        )
        if target is None and explicit_column_rename:
            raise DomainError("FIELD_NOT_FOUND", "要修改表头的列不在当前草稿中")
        if target is not None:
            target["label"] = new_label

    delete_clauses = [
        clause
        for clause in re.split(r"[，。；;]", message)
        if any(token in clause for token in ("删除", "删掉", "去掉", "移除"))
        and "第" not in clause
    ]
    for clause in delete_clauses:
        for item in list(result):
            if any(term in clause for term in _column_terms(item, catalog)):
                result.remove(item)

    adding = any(
        token in message
        for token in ("增加", "新增", "添加", "加一列", "加上", "加个", "加一个")
    )
    if adding:
        existing_ids = {
            item.get("fieldId") for item in result if item.get("kind") == "field"
        }
        for definition in matched_detail:
            if definition.field_id not in existing_ids:
                requested_alias = next(
                    (
                        alias
                        for alias in list(definition.aliases)
                        + list(COMMON_FIELD_ALIASES.get(definition.name, ()))
                        if alias and alias in message
                    ),
                    None,
                )
                result.append(
                    {
                        "kind": "field",
                        "fieldId": definition.field_id,
                        "label": requested_alias or definition.name,
                        "widthWeight": 1.0,
                    }
                )
                existing_ids.add(definition.field_id)
        blank_label = next(
            (token for token in ("签字", "手写", "空白") if token in message),
            None,
        )
        if blank_label and not any(item.get("label") == blank_label for item in result):
            result.append(
                {"kind": "blank", "label": blank_label, "widthWeight": 1.0}
            )
        if not matched_detail and not blank_label:
            raise DomainError("FIELD_NOT_FOUND", "新增列不在当前报表字段目录中")

    if not result:
        raise DomainError("PLAN_INVALID", "模板至少需要一列明细")
    return result


def _parse_ordinal(value: str) -> Optional[int]:
    if value.isdigit():
        return int(value)
    chinese = {
        "一": 1,
        "二": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese.get(value)


def _current_style_value(
    current_summary: Optional[Dict[str, Any]],
    key: str,
    fallback: float,
) -> float:
    if isinstance(current_summary, dict):
        style = current_summary.get("tableStyle")
        if isinstance(style, dict):
            value = style.get(key)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                return float(value)
    return fallback


def _set_exact_column_share(
    plan: TemplatePlan,
    message: str,
    fraction: float,
    target_terms: Sequence[str],
) -> bool:
    fields = plan.detail_tables[0].fields
    target_index = next(
        (
            index
            for index, item in enumerate(fields)
            if item.label in target_terms or item.bind_name in target_terms
        ),
        None,
    )
    if target_index is None:
        return False
    other_total = sum(
        item.width_weight for index, item in enumerate(fields) if index != target_index
    )
    if other_total <= 0:
        raise DomainError("PLAN_INVALID", "单列模板不能设置小于100%的列宽份额")
    shares = []
    for index, item in enumerate(fields):
        if index == target_index:
            shares.append(fraction)
        else:
            shares.append((1.0 - fraction) * item.width_weight / other_total)
    lower = max(0.2 / share for share in shares)
    upper = min(5.0 / share for share in shares)
    if lower > upper:
        raise DomainError("PLAN_INVALID", "当前列数与比例无法满足宽度权重限制")
    scale = min(max(4.0, lower), upper)
    for field, share in zip(fields, shares):
        field.width_weight = round(share * scale, 8)
    return True


def apply_deterministic_layout_requirements(
    message: str,
    plan: TemplatePlan,
    current_summary: Optional[Dict[str, Any]] = None,
) -> None:
    """对常用口语和明确数值做最终确定性解释，避免模型产生累积漂移。"""
    text = _latest_user_message(message)
    style = plan.detail_tables[0].table_style

    last_landscape = text.rfind("横向")
    last_portrait = text.rfind("纵向")
    if max(last_landscape, last_portrait) >= 0:
        plan.page.orientation = "landscape" if last_landscape > last_portrait else "portrait"
        if plan.page.orientation == "landscape" and plan.page.width_cm < plan.page.height_cm:
            plan.page.width_cm, plan.page.height_cm = plan.page.height_cm, plan.page.width_cm
        if plan.page.orientation == "portrait" and plan.page.width_cm > plan.page.height_cm:
            plan.page.width_cm, plan.page.height_cm = plan.page.height_cm, plan.page.width_cm

    size_match = re.search(
        r"(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)?\s*[×xX*]\s*"
        r"(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)?",
        text,
        flags=re.IGNORECASE,
    )
    if size_match:
        first_unit = size_match.group(2) or size_match.group(4) or "cm"
        second_unit = size_match.group(4) or size_match.group(2) or "cm"

        def cm(value: str, unit: str) -> float:
            return float(value) / 10.0 if unit.lower() in {"mm", "毫米"} else float(value)

        plan.page.paper_name = "自定义纸张"
        plan.page.width_cm = cm(size_match.group(1), first_unit)
        plan.page.height_cm = cm(size_match.group(3), second_unit)

    margin_names = {"上": "top", "右": "right", "下": "bottom", "左": "left"}
    current_page = _page_from_summary(current_summary) if isinstance(current_summary, dict) else None
    for chinese_name, key in margin_names.items():
        explicit = re.search(
            chinese_name + r"(?:侧)?(?:页)?边距[^\d]{0,8}(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)",
            text,
            flags=re.IGNORECASE,
        )
        if explicit:
            value = float(explicit.group(1))
            if explicit.group(2).lower() in {"mm", "毫米"}:
                value /= 10.0
            plan.page.margins_cm[key] = value
    if "左边距" in text and any(token in text for token in ("宽一点", "调宽一点", "加宽一点")):
        base = (
            current_page.margins_cm["left"]
            if current_page is not None
            else plan.page.margins_cm["left"]
        )
        plan.page.margins_cm["left"] = base + 0.5

    explicit_height = re.search(
        r"(?:表格)?行高[^\d]{0,8}(\d+(?:\.\d+)?)\s*(cm|厘米|mm|毫米)",
        text,
        flags=re.IGNORECASE,
    )
    if explicit_height:
        height = float(explicit_height.group(1))
        if explicit_height.group(2).lower() in {"mm", "毫米"}:
            height /= 10.0
        style.header_height_cm = height
        style.body_height_cm = height
    elif "行高" in text and "大一倍" in text:
        style.header_height_cm = _current_style_value(
            current_summary, "headerHeightCm", style.header_height_cm
        ) * 2
        style.body_height_cm = _current_style_value(
            current_summary, "bodyHeightCm", style.body_height_cm
        ) * 2
    elif "行高" in text and any(token in text for token in ("大一点", "高一点", "调高一点")):
        style.header_height_cm = _current_style_value(
            current_summary, "headerHeightCm", style.header_height_cm
        ) * 1.25
        style.body_height_cm = _current_style_value(
            current_summary, "bodyHeightCm", style.body_height_cm
        ) * 1.25

    header_font = re.search(r"表头(?:字体|字号|的字)[^\d]{0,8}(\d{1,2})", text)
    body_font = re.search(r"(?:内容|正文)(?:字体|字号|的字)[^\d]{0,8}(\d{1,2})", text)
    if header_font:
        style.header_font_size = int(header_font.group(1))
    elif "表头" in text and any(token in text for token in ("大一号", "放大一号")):
        style.header_font_size = int(
            _current_style_value(current_summary, "headerFontSize", style.header_font_size)
        ) + 1
    if body_font:
        style.body_font_size = int(body_font.group(1))
    elif any(token in text for token in ("内容", "正文")) and any(
        token in text for token in ("小一号", "变小一点", "小一点")
    ):
        style.body_font_size = int(
            _current_style_value(current_summary, "bodyFontSize", style.body_font_size)
        ) - 1

    if any(token in text for token in ("去掉所有边框", "去掉表格的所有边框", "无边框")):
        style.outer = BorderPlan("none", 0)
        style.inner_horizontal = BorderPlan("none", 0)
        style.inner_vertical = BorderPlan("none", 0)
    if any(token in text for token in ("外边框加粗", "外框加粗", "粗外框", "粗外边框")):
        style.outer = BorderPlan("solid", 2)
    if (
        any(token in text for token in ("内部", "内网格", "内部网格", "网格线"))
        and "虚线" in text
    ):
        style.inner_horizontal = BorderPlan("dashed", 1)
        style.inner_vertical = BorderPlan("dashed", 1)
    if "点线" in text and any(token in text for token in ("内部", "内网格", "网格线")):
        style.inner_horizontal = BorderPlan("dotted", 1)
        style.inner_vertical = BorderPlan("dotted", 1)
    if any(token in text for token in ("去掉竖线", "去掉所有竖线", "去掉表格的所有竖线", "无竖线")):
        style.inner_vertical = BorderPlan("none", 0)

    fractions = {
        "一半": 0.5,
        "二分之一": 0.5,
        "三分之一": 1.0 / 3.0,
        "四分之一": 0.25,
    }
    for clause in re.split(r"[，。；;]", text):
        fraction_name = next((name for name in fractions if "占" + name in clause), None)
        if not fraction_name:
            continue
        quoted_terms = re.findall(r"[‘“\"']([^’”\"']+)[’”\"']", clause)
        target_terms = []
        for item in plan.detail_tables[0].fields:
            names = [item.label, item.bind_name]
            aliases = COMMON_FIELD_ALIASES.get(item.bind_name, ())
            if any(name and name in clause for name in names + list(aliases)) or any(
                item.label.endswith(term) or item.bind_name.endswith(term)
                for term in quoted_terms
            ):
                target_terms.append(item.label)
        if target_terms:
            _set_exact_column_share(plan, clause, fractions[fraction_name], target_terms)

    if plan.page.margins_cm["left"] + plan.page.margins_cm["right"] >= plan.page.width_cm:
        raise DomainError("PLAN_INVALID", "左右页边距超过纸张宽度")
    if plan.page.margins_cm["top"] + plan.page.margins_cm["bottom"] >= plan.page.height_cm:
        raise DomainError("PLAN_INVALID", "上下页边距超过纸张高度")
    _validate_table_style_plan(style)


def build_default_delivery_plan(catalog: FieldCatalog) -> TemplatePlan:
    """构建启动时的 A4 送货单草稿，不调用模型。"""
    return build_plan(
        catalog=catalog,
        title="送货单",
        master_field_ids=[],
        detail_columns=[
            {"kind": "sequence", "label": "序号", "widthWeight": 0.6},
            {
                "kind": "field",
                "fieldId": "detail.商品全名",
                "label": "商品名称",
                "widthWeight": 2.4,
            },
            {
                "kind": "field",
                "fieldId": "detail.数量",
                "label": "数量",
                "widthWeight": 1.0,
            },
        ],
        total_field_ids=[],
        footer_field_ids=[],
        page=PagePlan(
            paper_name="A4",
            orientation="portrait",
            width_cm=21.0,
            height_cm=29.7,
            margins_cm={"top": 2.0, "right": 2.0, "bottom": 2.0, "left": 2.0},
        ),
        confidence=1.0,
        assumptions=["启动时使用确定性 A4 送货单默认草稿"],
        warnings=[],
        max_rows_per_page=10,
        table_name=catalog.default_detail_table,
        strategy="quick-table",
        table_style=TableStylePlan(),
    )

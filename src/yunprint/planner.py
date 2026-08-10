"""确定性模板计划构建。"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Protocol

from .catalog import FieldCatalog
from .domain import (
    AgentEnvelope,
    BorderPlan,
    DomainError,
    PagePlan,
    PlannedDetailTable,
    PlannedField,
    TableStylePlan,
    TemplatePlan,
    TextStylePlan,
)


logger = logging.getLogger(__name__)

HORIZONTAL_ALIGN_VALUES = {"default", "left", "center", "right"}
VERTICAL_ALIGN_VALUES = {"default", "top", "middle", "bottom"}


class Planner(Protocol):
    def plan(
        self,
        message: str,
        catalog: FieldCatalog,
        planning_context: Optional[Dict[str, Any]] = None,
    ) -> AgentEnvelope:
        ...


def _required(raw: Dict[str, Any], key: str, expected_type: Any) -> Any:
    if key not in raw or not isinstance(raw[key], expected_type):
        raise DomainError("PLAN_INVALID", "计划字段 %s 缺失或类型错误" % key)
    return raw[key]


def _parse_table_style(raw: Dict[str, Any]) -> TableStylePlan:
    if set(raw) != {
        "headerHeightCm",
        "bodyHeightCm",
        "headerFontSize",
        "bodyFontSize",
        "borders",
    }:
        raise DomainError("PLAN_INVALID", "tableStyle 字段不完整或包含未知属性")
    borders = _required(raw, "borders", dict)
    if set(borders) != {"outer", "innerHorizontal", "innerVertical"}:
        raise DomainError("PLAN_INVALID", "borders 必须包含 outer/innerHorizontal/innerVertical")

    def border(name: str) -> BorderPlan:
        value = _required(borders, name, dict)
        if set(value) != {"style", "width"}:
            raise DomainError("PLAN_INVALID", "%s 边框字段无效" % name)
        style = value.get("style")
        width = value.get("width")
        if style not in {"solid", "dashed", "dotted", "none"}:
            raise DomainError("PLAN_INVALID", "%s 边框线型无效" % name)
        if isinstance(width, bool) or not isinstance(width, int):
            raise DomainError("PLAN_INVALID", "%s 边框宽度必须是整数" % name)
        if style == "none" and width != 0:
            raise DomainError("PLAN_INVALID", "无边框的宽度必须为0")
        if style in {"dashed", "dotted"} and width != 1:
            raise DomainError("PLAN_INVALID", "虚线和点线宽度必须为1")
        if style == "solid" and not 1 <= width <= 5:
            raise DomainError("PLAN_INVALID", "实线宽度必须在1到5之间")
        return BorderPlan(style=style, width=width)

    heights = (raw.get("headerHeightCm"), raw.get("bodyHeightCm"))
    fonts = (raw.get("headerFontSize"), raw.get("bodyFontSize"))
    if any(
        isinstance(value, bool) or not isinstance(value, (int, float))
        for value in heights
    ) or any(isinstance(value, bool) or not isinstance(value, int) for value in fonts):
        raise DomainError("PLAN_INVALID", "行高或字号类型无效")
    header_height = float(heights[0])
    body_height = float(heights[1])
    header_font, body_font = fonts
    if not 0.3 <= header_height <= 3.0 or not 0.3 <= body_height <= 3.0:
        raise DomainError("PLAN_INVALID", "表格行高必须在0.3到3.0cm之间")
    if not 6 <= header_font <= 36 or not 6 <= body_font <= 36:
        raise DomainError("PLAN_INVALID", "表格字号必须在6到36之间")
    return TableStylePlan(
        header_height_cm=header_height,
        body_height_cm=body_height,
        header_font_size=header_font,
        body_font_size=body_font,
        outer=border("outer"),
        inner_horizontal=border("innerHorizontal"),
        inner_vertical=border("innerVertical"),
    )


def build_plan(
    catalog: FieldCatalog,
    title: str,
    master_field_ids: List[str],
    detail_columns: List[Dict[str, Any]],
    total_field_ids: List[str],
    footer_field_ids: List[str],
    page: PagePlan,
    confidence: float,
    assumptions: List[str],
    warnings: List[str],
    max_rows_per_page: int = 10,
    table_name: str = "",
    strategy: str = "quick-table",
    cell_options: Dict[str, Dict[str, Any]] = None,
    table_style: Optional[TableStylePlan] = None,
    title_style: Optional[TextStylePlan] = None,
) -> TemplatePlan:
    cell_options = cell_options or {}
    table_style = table_style or TableStylePlan()
    title_style = title_style or TextStylePlan()
    if not isinstance(title, str) or not title.strip():
        raise DomainError("PLAN_INVALID", "title 必须是非空字符串")

    def planned(
        field_id: str,
        expected_scope: str,
        label: Optional[str] = None,
        weight: float = 1.0,
    ) -> PlannedField:
        definition = catalog.get(field_id)
        if definition.scope != expected_scope:
            raise DomainError("PLAN_INVALID", "字段 %s 的作用域不正确" % field_id)
        option = cell_options.get(field_id, {})
        allowed_option_keys = {
            "formatKind",
            "decimalPlaces",
            "upperDecimalPlaces",
            "prefix",
            "hideZero",
            "dynamicTextSize",
            "mergeSameValue",
            "imageShowType",
            "horizontalAlign",
            "verticalAlign",
        }
        unknown_keys = set(option) - allowed_option_keys
        if unknown_keys:
            raise DomainError(
                "PLAN_INVALID",
                "字段 %s 的 cellOptions 包含未知属性：%s"
                % (field_id, ",".join(sorted(unknown_keys))),
            )
        format_kind = option.get("formatKind", "none")
        allowed_formats = {
            "none",
            "barcode",
            "qrcode",
            "number",
            "amount-in-words",
            "number-uppercase",
            "accounting",
            "accounting-header",
            "accounting-body",
            "chinese-date",
            "english-date",
            "english-number",
        }
        if format_kind not in allowed_formats:
            raise DomainError("PLAN_INVALID", "字段 %s 的 formatKind 无效" % field_id)
        image_show_type = option.get("imageShowType", "stretch")
        if image_show_type not in ("stretch", "scale-width", "scale-height"):
            raise DomainError("PLAN_INVALID", "字段 %s 的 imageShowType 无效" % field_id)
        horizontal_align = option.get("horizontalAlign", "default")
        vertical_align = option.get("verticalAlign", "default")
        if horizontal_align not in HORIZONTAL_ALIGN_VALUES:
            raise DomainError("PLAN_INVALID", "字段 %s 的 horizontalAlign 无效" % field_id)
        if vertical_align not in VERTICAL_ALIGN_VALUES:
            raise DomainError("PLAN_INVALID", "字段 %s 的 verticalAlign 无效" % field_id)
        decimal_places = option.get("decimalPlaces")
        upper_decimal_places = option.get("upperDecimalPlaces")
        if decimal_places is not None and (
            isinstance(decimal_places, bool) or not isinstance(decimal_places, int) or not 0 <= decimal_places <= 8
        ):
            raise DomainError("PLAN_INVALID", "字段 %s 的 decimalPlaces 必须在 0 到 8 之间" % field_id)
        if upper_decimal_places is not None and (
            isinstance(upper_decimal_places, bool)
            or not isinstance(upper_decimal_places, int)
            or not -1 <= upper_decimal_places <= 8
        ):
            raise DomainError("PLAN_INVALID", "字段 %s 的 upperDecimalPlaces 必须在 -1 到 8 之间" % field_id)
        prefix = option.get("prefix", "")
        if not isinstance(prefix, str) or len(prefix) > 30:
            raise DomainError("PLAN_INVALID", "字段 %s 的 prefix 必须是不超过 30 字的字符串" % field_id)
        boolean_keys = ("hideZero", "dynamicTextSize", "mergeSameValue")
        if any(key in option and not isinstance(option[key], bool) for key in boolean_keys):
            raise DomainError("PLAN_INVALID", "字段 %s 的布尔单元格属性类型无效" % field_id)
        if option.get("mergeSameValue", False) and expected_scope != "detail":
            raise DomainError("PLAN_INVALID", "MergeSameValue 仅适用于明细字段：%s" % field_id)
        return PlannedField(
            field_id,
            label or definition.name,
            definition.name,
            definition.scope,
            weight,
            format_kind=format_kind,
            decimal_places=decimal_places,
            upper_decimal_places=upper_decimal_places,
            prefix=prefix,
            hide_zero=option.get("hideZero", False),
            dynamic_text_size=option.get("dynamicTextSize", False),
            merge_same_value=option.get("mergeSameValue", False),
            image_show_type=image_show_type,
            horizontal_align=horizontal_align,
            vertical_align=vertical_align,
        )

    if not detail_columns:
        raise DomainError("PLAN_INVALID", "模板至少需要一列明细")
    detail_planned: List[PlannedField] = []
    detail_field_ids: List[str] = []
    labels = set()
    sequence_count = 0
    for index, raw_column in enumerate(detail_columns):
        if not isinstance(raw_column, dict):
            raise DomainError("PLAN_INVALID", "columns[%d] 必须是对象" % index)
        kind = raw_column.get("kind")
        allowed_keys = {"kind", "label", "widthWeight"}
        if kind == "field":
            allowed_keys.add("fieldId")
        if set(raw_column) != allowed_keys:
            raise DomainError("PLAN_INVALID", "columns[%d] 字段不完整或包含未知属性" % index)
        label = raw_column.get("label")
        if not isinstance(label, str) or not label.strip() or len(label.strip()) > 30:
            raise DomainError("PLAN_INVALID", "列标签必须是1到30字的非空字符串")
        label = label.strip()
        if label in labels:
            raise DomainError("PLAN_INVALID", "同一表格不能包含重复列标签：%s" % label)
        labels.add(label)
        weight_raw = raw_column.get("widthWeight")
        if isinstance(weight_raw, bool):
            raise DomainError("PLAN_INVALID", "列 %s 的宽度权重无效" % label)
        if not isinstance(weight_raw, (int, float)):
            raise DomainError("PLAN_INVALID", "列 %s 的宽度权重无效" % label)
        weight = float(weight_raw)
        if not math.isfinite(weight) or not 0.2 <= weight <= 5:
            raise DomainError("PLAN_INVALID", "列 %s 的宽度权重必须在0.2到5之间" % label)
        if kind == "field":
            field_id = raw_column.get("fieldId")
            if not isinstance(field_id, str):
                raise DomainError("PLAN_INVALID", "业务列 %s 缺少 fieldId" % label)
            detail_field_ids.append(field_id)
            detail_planned.append(planned(field_id, "detail", label=label, weight=weight))
        elif kind == "sequence":
            sequence_count += 1
            detail_planned.append(
                PlannedField("computed.sequence", label, "行号", "detail", weight, kind="sequence")
            )
        elif kind == "blank":
            detail_planned.append(
                PlannedField("blank.%d" % (index + 1), label, "", "detail", weight, kind="blank")
            )
        else:
            raise DomainError("PLAN_INVALID", "不支持的列类型：%s" % kind)
    if sequence_count > 1:
        raise DomainError("PLAN_INVALID", "一个表格最多只能有一个序号列")
    if not detail_field_ids:
        raise DomainError("PLAN_INVALID", "模板至少需要一个真实业务字段列")

    all_ids = master_field_ids + detail_field_ids + footer_field_ids
    if len(all_ids) != len(set(all_ids)):
        raise DomainError("PLAN_INVALID", "计划中存在重复字段")

    selected_ids = set(all_ids)
    unknown_option_ids = set(cell_options) - selected_ids
    if unknown_option_ids:
        raise DomainError(
            "PLAN_INVALID",
            "cellOptions 只能引用已选择字段：%s" % ",".join(sorted(unknown_option_ids)),
        )

    detail_set = set(detail_field_ids)
    if len(total_field_ids) != len(set(total_field_ids)):
        raise DomainError("PLAN_INVALID", "计划中存在重复合计字段")
    for field_id in total_field_ids:
        definition = catalog.get(field_id)
        if field_id not in detail_set:
            raise DomainError("PLAN_INVALID", "合计字段必须先出现在明细列中：%s" % field_id)
        if definition.scope != "detail" or definition.data_type != "number" or not definition.aggregatable:
            raise DomainError("PLAN_INVALID", "字段不可合计：%s" % field_id)

    if not isinstance(page.paper_name, str) or not page.paper_name.strip():
        raise DomainError("PLAN_INVALID", "paperName 必须是非空字符串")
    if page.orientation not in ("portrait", "landscape"):
        raise DomainError("PLAN_INVALID", "orientation 只能是 portrait 或 landscape")
    if not isinstance(page.margins_cm, dict) or set(page.margins_cm) != {
        "top",
        "right",
        "bottom",
        "left",
    }:
        raise DomainError("PLAN_INVALID", "marginsCm 必须包含四个方向")
    page_numbers = [page.width_cm, page.height_cm, *page.margins_cm.values()]
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in page_numbers
    ):
        raise DomainError("PLAN_INVALID", "页面尺寸和边距必须是有限数值")
    if page.width_cm <= 0 or page.height_cm <= 0:
        raise DomainError("PLAN_INVALID", "纸张宽高必须大于 0")
    if any(value < 0 for value in page.margins_cm.values()):
        raise DomainError("PLAN_INVALID", "页边距不能为负数")
    if page.margins_cm["left"] + page.margins_cm["right"] >= page.width_cm:
        raise DomainError("PLAN_INVALID", "左右页边距超过纸张宽度")
    if page.margins_cm["top"] + page.margins_cm["bottom"] >= page.height_cm:
        raise DomainError("PLAN_INVALID", "上下页边距超过纸张高度")
    _validate_table_style_plan(table_style)
    _validate_text_style_plan(title_style, "titleOptions")

    if isinstance(max_rows_per_page, bool) or not isinstance(max_rows_per_page, int):
        raise DomainError("PLAN_INVALID", "maxRowsPerPage 必须是整数")
    if not 1 <= max_rows_per_page <= 100:
        raise DomainError("PLAN_INVALID", "maxRowsPerPage 必须在1到100之间")

    return TemplatePlan(
        report_name=catalog.report_name,
        report_type=catalog.report_type,
        title=title[:100],
        strategy=strategy,
        master_fields=[planned(field_id, "master") for field_id in master_field_ids],
        detail_tables=[
            PlannedDetailTable(
                table_name=table_name or catalog.default_detail_table,
                fields=detail_planned,
                total_field_ids=total_field_ids,
                max_rows_per_page=max_rows_per_page,
                table_style=table_style,
            )
        ],
        footer_fields=[planned(field_id, "master") for field_id in footer_field_ids],
        page=page,
        confidence=confidence,
        assumptions=assumptions,
        warnings=warnings,
        title_style=title_style,
    )


def _validate_text_style_plan(style: TextStylePlan, label: str) -> None:
    if style.horizontal_align not in HORIZONTAL_ALIGN_VALUES:
        raise DomainError("PLAN_INVALID", "%s.horizontalAlign 无效" % label)
    if style.vertical_align not in VERTICAL_ALIGN_VALUES:
        raise DomainError("PLAN_INVALID", "%s.verticalAlign 无效" % label)


def _validate_table_style_plan(style: TableStylePlan) -> None:
    if any(
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        for value in (style.header_height_cm, style.body_height_cm)
    ):
        raise DomainError("PLAN_INVALID", "表格行高必须是有限数值")
    if not 0.3 <= style.header_height_cm <= 3.0 or not 0.3 <= style.body_height_cm <= 3.0:
        raise DomainError("PLAN_INVALID", "表格行高必须在0.3到3.0cm之间")
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in (style.header_font_size, style.body_font_size)
    ):
        raise DomainError("PLAN_INVALID", "表格字号必须是整数")
    if not 6 <= style.header_font_size <= 36 or not 6 <= style.body_font_size <= 36:
        raise DomainError("PLAN_INVALID", "表格字号必须在6到36之间")
    for name, border in (
        ("outer", style.outer),
        ("innerHorizontal", style.inner_horizontal),
        ("innerVertical", style.inner_vertical),
    ):
        if border.style not in {"solid", "dashed", "dotted", "none"}:
            raise DomainError("PLAN_INVALID", "%s 边框线型无效" % name)
        if isinstance(border.width, bool) or not isinstance(border.width, int):
            raise DomainError("PLAN_INVALID", "%s 边框宽度必须是整数" % name)
        if border.style == "none" and border.width != 0:
            raise DomainError("PLAN_INVALID", "无边框的宽度必须为0")
        if border.style in {"dashed", "dotted"} and border.width != 1:
            raise DomainError("PLAN_INVALID", "虚线和点线宽度必须为1")
        if border.style == "solid" and not 1 <= border.width <= 5:
            raise DomainError("PLAN_INVALID", "实线宽度必须在1到5之间")

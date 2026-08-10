"""原生模板模块：负责编译、基础模板属性补丁、结构校验和规范化内容哈希。"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from copy import deepcopy
from typing import Any, Dict, List, Sequence

from .catalog import FieldCatalog, extract_bindings
from .domain import (
    BorderPlan,
    DomainError,
    PagePlan,
    PatchChange,
    PatchExecutionReport,
    PlannedField,
    TableStylePlan,
    TemplatePlan,
    TextStylePlan,
    ValidationResult,
)


logger = logging.getLogger(__name__)


PX_PER_CM = 37.8

FORMAT_KIND_VALUES = {
    "none": 0,
    "amount-in-words": 1,
    "number-uppercase": 2,
    "chinese-date": 3,
    "accounting": 4,
    "number": 5,
    "accounting-header": 6,
    "accounting-body": 7,
    "barcode": 8,
    "qrcode": 9,
    "english-date": 10,
    "english-number": 11,
}

IMAGE_SHOW_TYPE_VALUES = {"stretch": 0, "scale-width": 1, "scale-height": 2}
LINE_STYLE_VALUES = {"solid": 0, "dashed": 1, "dotted": 2}
HORIZONTAL_ALIGN_VALUES = {"left": 0, "right": 1, "center": 2}
VERTICAL_ALIGN_VALUES = {"top": 0, "bottom": 1, "middle": 2}


def content_hash(template: Dict[str, Any]) -> str:
    canonical = json.dumps(template, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _cell(
    width: int,
    text: str = "",
    label: bool = False,
    no_borders: bool = False,
    horz_align: bool = False,
    horizontal_align: str = "default",
    vertical_align: str = "default",
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"OrigWidth": width}
    if text:
        result["CellText"] = text
    if no_borders:
        result.update({"LeftLine": 0, "RightLine": 0, "TopLine": 0, "BottomLine": 0})
    if horz_align:
        horizontal_align = "left" if horizontal_align == "default" else horizontal_align
    _apply_text_alignment(result, horizontal_align, vertical_align)
    if label:
        result["FontStyle"] = "fsBold"
    result["BarcodeType"] = 5
    return result


def _apply_text_alignment(
    cell: Dict[str, Any],
    horizontal_align: str = "default",
    vertical_align: str = "default",
) -> Dict[str, Any]:
    if horizontal_align != "default":
        cell["HorzAlign"] = HORIZONTAL_ALIGN_VALUES[horizontal_align]
    if vertical_align != "default":
        cell["VertAlign"] = VERTICAL_ALIGN_VALUES[vertical_align]
    return cell


def _apply_text_style(cell: Dict[str, Any], style: TextStylePlan) -> Dict[str, Any]:
    return _apply_text_alignment(cell, style.horizontal_align, style.vertical_align)


def _split_width(total: int, weights: Sequence[float]) -> List[int]:
    if not weights:
        return []
    weight_total = sum(weights)
    widths: List[int] = []
    cumulative_weight = 0.0
    previous_boundary = 0
    for weight in weights:
        cumulative_weight += weight
        boundary = int(math.floor(total * cumulative_weight / weight_total + 0.5))
        widths.append(boundary - previous_boundary)
        previous_boundary = boundary
    return widths


def _split_width_largest_remainder(total: int, weights: Sequence[float]) -> List[int]:
    if not weights:
        return []
    weight_total = sum(weights)
    exact = [total * weight / weight_total for weight in weights]
    widths = [int(math.floor(value)) for value in exact]
    remainder = total - sum(widths)
    order = sorted(range(len(weights)), key=lambda index: (-(exact[index] - widths[index]), index))
    for index in order[:remainder]:
        widths[index] += 1
    return widths


def _set_native_line(cell: Dict[str, Any], side: str, border: BorderPlan) -> None:
    visible_key = side + "Line"
    width_key = side + "LineWidth"
    style_key = side + "LineStyle"
    if border.style == "none":
        cell[visible_key] = 0
        cell.pop(width_key, None)
        cell.pop(style_key, None)
        return
    cell.pop(visible_key, None)
    if border.width == 1:
        cell.pop(width_key, None)
    else:
        cell[width_key] = border.width
    style_value = LINE_STYLE_VALUES[border.style]
    if style_value == 0:
        cell.pop(style_key, None)
    else:
        cell[style_key] = style_value


def _style_detail_grid(rows: List[Dict[str, Any]], style: TableStylePlan) -> None:
    row_count = len(rows)
    for row_index, row in enumerate(rows):
        cells = row["Cells"]
        for column_index, cell in enumerate(cells):
            _set_native_line(cell, "Top", style.outer if row_index == 0 else style.inner_horizontal)
            _set_native_line(
                cell,
                "Bottom",
                style.outer if row_index == row_count - 1 else style.inner_horizontal,
            )
            _set_native_line(cell, "Left", style.outer if column_index == 0 else style.inner_vertical)
            _set_native_line(
                cell,
                "Right",
                style.outer if column_index == len(cells) - 1 else style.inner_vertical,
            )


def _row(left: int, top: int, cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"ClassName": "TRow", "Left": left, "Top": top, "Cells": cells}


def _apply_cell_options(cell: Dict[str, Any], field: PlannedField) -> Dict[str, Any]:
    format_value = FORMAT_KIND_VALUES[field.format_kind]
    if format_value != 0:
        cell["FormatKind"] = format_value
    if field.decimal_places is not None and field.decimal_places != 2:
        cell["Decimal"] = field.decimal_places
    if field.upper_decimal_places is not None and field.upper_decimal_places != -1:
        cell["UpperDecimal"] = field.upper_decimal_places
    if field.prefix:
        cell["PreTextFlag"] = field.prefix
    if field.hide_zero:
        cell["DisplayEmptyForZero"] = True
    if field.dynamic_text_size:
        cell["DynamicTextSize"] = True
    if field.merge_same_value:
        cell["MergeSameValue"] = True
    image_show_value = IMAGE_SHOW_TYPE_VALUES[field.image_show_type]
    if image_show_value != 0:
        cell["ImageShowType"] = image_show_value
    _apply_text_alignment(cell, field.horizontal_align, field.vertical_align)
    return cell


def planned_semantic_options(field: PlannedField) -> Dict[str, Any]:
    """提取计划中真正要求执行的显示属性，默认值不算修改要求。"""
    result: Dict[str, Any] = {}
    if field.format_kind != "none":
        result["formatKind"] = field.format_kind
    if field.decimal_places is not None:
        result["decimalPlaces"] = field.decimal_places
    if field.upper_decimal_places is not None:
        result["upperDecimalPlaces"] = field.upper_decimal_places
    if field.prefix:
        result["prefix"] = field.prefix
    if field.hide_zero:
        result["hideZero"] = True
    if field.dynamic_text_size:
        result["dynamicTextSize"] = True
    if field.merge_same_value:
        result["mergeSameValue"] = True
    if field.image_show_type != "stretch":
        result["imageShowType"] = field.image_show_type
    if field.horizontal_align != "default":
        result["horizontalAlign"] = field.horizontal_align
    if field.vertical_align != "default":
        result["verticalAlign"] = field.vertical_align
    return result


def planned_text_options(style: TextStylePlan) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    if style.horizontal_align != "default":
        result["horizontalAlign"] = style.horizontal_align
    if style.vertical_align != "default":
        result["verticalAlign"] = style.vertical_align
    return result


def _effective_native_properties(cell: Dict[str, Any], options: Dict[str, Any]) -> Dict[str, Any]:
    mapping = {
        "formatKind": ("FormatKind", 0),
        "decimalPlaces": ("Decimal", 2),
        "upperDecimalPlaces": ("UpperDecimal", -1),
        "prefix": ("PreTextFlag", ""),
        "hideZero": ("DisplayEmptyForZero", False),
        "dynamicTextSize": ("DynamicTextSize", False),
        "mergeSameValue": ("MergeSameValue", False),
        "imageShowType": ("ImageShowType", 0),
        "horizontalAlign": ("HorzAlign", 0),
        "verticalAlign": ("VertAlign", 0),
    }
    result = {}
    for key in options:
        native_key, default = mapping[key]
        result[native_key] = cell.get(native_key, default)
    return result


def _master_rows(
    fields: Sequence[PlannedField],
    left: int,
    start_top: int,
    table_width: int,
) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    quarter_widths = _split_width(table_width, [1, 1, 1, 1])
    for offset in range(0, len(fields), 2):
        pair = fields[offset : offset + 2]
        cells: List[Dict[str, Any]] = []
        for index in range(2):
            if index < len(pair):
                item = pair[index]
                cells.append(
                    _cell(
                        quarter_widths[index * 2],
                        item.label,
                        label=True,
                        no_borders=True,
                        horz_align=True,
                    )
                )
                cells.append(
                    _apply_cell_options(
                        _cell(
                            quarter_widths[index * 2 + 1],
                            "@" + item.bind_name,
                            no_borders=True,
                            horz_align=True,
                        ),
                        item,
                    )
                )
            else:
                cells.append(_cell(quarter_widths[index * 2], no_borders=True))
                cells.append(_cell(quarter_widths[index * 2 + 1], no_borders=True))
        rows.append(_row(left, start_top + len(rows) * 20, cells))
    return rows


def _page_dimensions(page: PagePlan) -> Dict[str, int]:
    return {
        "width": int(round(page.width_cm * PX_PER_CM)),
        "height": int(round(page.height_cm * PX_PER_CM)),
        "left": int(round(page.margins_cm["left"] * PX_PER_CM)),
        "right": int(round(page.margins_cm["right"] * PX_PER_CM)),
        "top": int(round(page.margins_cm["top"] * PX_PER_CM)),
        "bottom": int(round(page.margins_cm["bottom"] * PX_PER_CM)),
    }


def _native_document(
    report_name: str,
    page: PagePlan,
    rows: List[Dict[str, Any]],
    table_left: int,
    table_top: int,
    table_width: int,
    table_height: int,
    max_rows_per_page: int,
) -> Dict[str, Any]:
    """Wrap deterministic table rows in the native one-page document shape."""
    dims = _page_dimensions(page)
    page_setting: Dict[str, Any] = {
        "PrinterName": "默认打印机",
        "PaperName": page.paper_name,
        "PaperHeightUM": int(round(page.height_cm * 100)),
        "LeftMarginUM": int(round(page.margins_cm["left"] * 100)),
        "TopMarginUM": int(round(page.margins_cm["top"] * 100)),
        "BottomMarginUM": int(round(page.margins_cm["bottom"] * 100)),
        "RightMarginUM": int(round(page.margins_cm["right"] * 100)),
        "FixedRowCount": 1,
        "AutoCalRowCount": 0,
        "ShowTotalInPerPage": 0,
        "MaxRowCount": max_rows_per_page,
    }
    if page.orientation == "landscape":
        page_setting["PaperOrientation"] = 1
    paper_width_um = int(round(page.width_cm * 100))
    if paper_width_um != 2100:
        page_setting["PaperWidthUM"] = paper_width_um
    page_footer_top = dims["height"] - dims["bottom"]
    template_page = {
        "ClassName": "TTemplatePage",
        "Width": dims["width"],
        "Height": dims["height"],
        "TableName": "",
        "ReportElements": [
            {
                "ClassName": "TTableElement",
                "Left": table_left,
                "Top": table_top,
                "Width": table_width,
                "Height": table_height,
                "ElementKind": 0,
                "Rows": rows,
            }
        ],
        "GroupInfo": {},
        "OrderInfoList": [],
        "BandAreas": [
            {
                "ClassName": "TBandArea",
                "IsVisible": True,
                "BandKind": 1,
                "BandTop": 0,
                "BandHeight": table_top,
            },
            {
                "ClassName": "TBandArea",
                "IsVisible": 0,
                "BandKind": 2,
                "BandTop": table_top,
                "BandHeight": 100,
            },
            {
                "ClassName": "TBandArea",
                "IsVisible": True,
                "BandKind": 3,
                "BandTop": table_top,
                "BandHeight": page_footer_top - table_top,
            },
            {
                "ClassName": "TBandArea",
                "IsVisible": 0,
                "BandKind": 4,
                "BandTop": page_footer_top,
                "BandHeight": 100,
            },
            {
                "ClassName": "TBandArea",
                "IsVisible": True,
                "BandKind": 5,
                "BandTop": page_footer_top,
                "BandHeight": dims["bottom"],
            },
        ],
    }
    return {
        "ReportName": report_name,
        "StyleType": "",
        "PageSetting": page_setting,
        "Pages": [template_page],
        "ExpressionFields": [],
        "IsWebPrint": True,
    }


class NativeTemplateCompiler:
    """Compile a validated semantic plan into the observed native quick-table shape."""

    def compile(self, plan: TemplatePlan) -> Dict[str, Any]:
        logger.info(
            "快速模板编译开始 report=%s master=%d detail=%d footer=%d paper=%s orientation=%s",
            plan.report_name,
            len(plan.master_fields),
            len(plan.detail_tables[0].fields),
            len(plan.footer_fields),
            plan.page.paper_name,
            plan.page.orientation,
        )
        page = plan.page
        dims = _page_dimensions(page)
        table_left = dims["left"]
        table_top = dims["top"]
        table_width = dims["width"] - dims["left"] - dims["right"]
        rows: List[Dict[str, Any]] = []

        title_cell = _apply_text_style(
            _cell(table_width, plan.title, label=True, no_borders=True),
            plan.title_style,
        )
        title_cell.update({"OrigHeight": 29, "FontSize": 20})
        rows.append(_row(table_left, table_top, [title_cell]))
        rows.append(_row(table_left, table_top + 29, [_cell(table_width, no_borders=True)]))

        current_top = table_top + 49
        header_rows = _master_rows(plan.master_fields, table_left, current_top, table_width)
        rows.extend(header_rows)
        current_top += len(header_rows) * 20

        detail = plan.detail_tables[0]
        style = detail.table_style
        detail_widths = _split_width_largest_remainder(
            table_width,
            [item.width_weight for item in detail.fields],
        )
        header_height = int(round(style.header_height_cm * PX_PER_CM))
        body_height = int(round(style.body_height_cm * PX_PER_CM))
        detail_rows: List[Dict[str, Any]] = []

        header_cells = []
        for item, width in zip(detail.fields, detail_widths):
            cell = _cell(width, item.label, label=True)
            cell.update({"OrigHeight": header_height, "FontSize": style.header_font_size})
            header_cells.append(cell)
        detail_rows.append(_row(table_left, current_top, header_cells))
        current_top += header_height

        body_cells = []
        for item, width in zip(detail.fields, detail_widths):
            text = "#" + item.bind_name if item.kind in {"field", "sequence"} else ""
            cell = _cell(width, text)
            cell.update({"OrigHeight": body_height, "FontSize": style.body_font_size})
            if item.kind == "field":
                _apply_cell_options(cell, item)
            body_cells.append(cell)
        detail_rows.append(_row(table_left, current_top, body_cells))
        current_top += body_height

        if detail.total_field_ids:
            total_ids = set(detail.total_field_ids)
            total_cells: List[Dict[str, Any]] = []
            for index, (item, width) in enumerate(zip(detail.fields, detail_widths)):
                if item.kind == "field" and item.field_id in total_ids:
                    cell = _apply_cell_options(_cell(width, "^" + item.bind_name), item)
                elif index == 0:
                    cell = _cell(width, "合计", label=True)
                else:
                    cell = _cell(width)
                cell.update({"OrigHeight": body_height, "FontSize": style.body_font_size})
                total_cells.append(cell)
            detail_rows.append(_row(table_left, current_top, total_cells))
            current_top += body_height

        _style_detail_grid(detail_rows, style)
        rows.extend(detail_rows)

        footer_rows = _master_rows(plan.footer_fields, table_left, current_top, table_width)
        rows.extend(footer_rows)
        current_top += len(footer_rows) * 20
        table_height = current_top - table_top

        result = _native_document(
            report_name=plan.report_name,
            page=page,
            rows=rows,
            table_left=table_left,
            table_top=table_top,
            table_width=table_width,
            table_height=table_height,
            max_rows_per_page=detail.max_rows_per_page,
        )
        logger.info(
            "快速模板编译完成 pages=1 tables=1 rows=%d table_width=%d table_height=%d",
            len(rows),
            table_width,
            table_height,
        )
        return result


class NativeTemplatePatcher:
    """Apply safe field-level display options while preserving a native base template."""

    def apply_cell_options(self, template: Dict[str, Any], plan: TemplatePlan) -> Dict[str, Any]:
        result, _ = self.apply_cell_options_with_report(template, plan)
        return result

    def apply_cell_options_with_report(
        self,
        template: Dict[str, Any],
        plan: TemplatePlan,
    ) -> tuple[Dict[str, Any], PatchExecutionReport]:
        logger.info(
            "基础模板属性补丁开始 report=%s pages=%d",
            template.get("ReportName"),
            len(template.get("Pages", [])),
        )
        result = deepcopy(template)
        master_fields = {item.bind_name: item for item in plan.master_fields + plan.footer_fields}
        detail_fields = {
            item.bind_name: item
            for item in plan.detail_tables[0].fields
            if item.kind == "field"
        }
        fields_by_id = {
            item.field_id: item
            for item in plan.master_fields + plan.footer_fields + plan.detail_tables[0].fields
        }
        expected_options = {
            field_id: options
            for field_id, field in fields_by_id.items()
            if (options := planned_semantic_options(field))
        }
        title_options = planned_text_options(plan.title_style)
        if title_options:
            expected_options["template.title"] = title_options
        applied_option_keys: Dict[str, set[str]] = {field_id: set() for field_id in expected_options}
        changes: List[PatchChange] = []
        patched_cells = 0
        changed_properties = set()
        for page_index, page in enumerate(result.get("Pages", [])):
            if not isinstance(page, dict):
                continue
            for element_index, element in enumerate(page.get("ReportElements", [])):
                if not isinstance(element, dict):
                    continue
                for row_index, row in enumerate(element.get("Rows", [])):
                    if not isinstance(row, dict):
                        continue
                    for cell_index, cell in enumerate(row.get("Cells", [])):
                        if not isinstance(cell, dict):
                            continue
                        text = cell.get("CellText")
                        if not isinstance(text, str):
                            continue
                        if title_options and text == plan.title:
                            before = dict(cell)
                            _apply_text_style(cell, plan.title_style)
                            changed = sorted({
                                key
                                for key in set(before) | set(cell)
                                if before.get(key) != cell.get(key)
                            })
                            if changed:
                                patched_cells += 1
                                changed_properties.update(changed)
                            applied_option_keys["template.title"].update(title_options)
                            changes.append(
                                PatchChange(
                                    native_path="Pages[%d].ReportElements[%d].Rows[%d].Cells[%d]"
                                    % (page_index, element_index, row_index, cell_index),
                                    field_id="template.title",
                                    cell_text=text,
                                    semantic_options=title_options,
                                    effective_native_properties=_effective_native_properties(cell, title_options),
                                    changed_native_properties=changed,
                                    status="changed" if changed else "already-satisfied",
                                )
                            )
                        if len(text) < 2:
                            continue
                        field = master_fields.get(text[1:]) if text.startswith("@") else None
                        if text.startswith(("#", "^")):
                            field = detail_fields.get(text[1:])
                        if field is not None:
                            options = expected_options.get(field.field_id, {})
                            before = dict(cell)
                            _apply_cell_options(cell, field)
                            changed = sorted({
                                key
                                for key in set(before) | set(cell)
                                if before.get(key) != cell.get(key)
                            })
                            if changed:
                                patched_cells += 1
                                changed_properties.update(changed)
                            if options:
                                applied_option_keys[field.field_id].update(options)
                                changes.append(
                                    PatchChange(
                                        native_path="Pages[%d].ReportElements[%d].Rows[%d].Cells[%d]"
                                        % (page_index, element_index, row_index, cell_index),
                                        field_id=field.field_id,
                                        cell_text=text,
                                        semantic_options=options,
                                        effective_native_properties=_effective_native_properties(cell, options),
                                        changed_native_properties=changed,
                                        status="changed" if changed else "already-satisfied",
                                    )
                                )
        logger.info(
            "基础模板属性补丁完成 patched_cells=%d changed_properties=%s",
            patched_cells,
            ",".join(sorted(changed_properties)) or "none",
        )
        report = PatchExecutionReport(
            strategy="clone-base-attributes",
            base_content_hash=content_hash(template),
            expected_options=expected_options,
            applied_option_keys={key: sorted(value) for key, value in applied_option_keys.items()},
            changes=changes,
            changed_native_properties=sorted(changed_properties),
        )
        return result, report


def build_compiler_execution_report(
    plan: TemplatePlan,
    template: Dict[str, Any],
    base_content_hash: str,
) -> PatchExecutionReport:
    """为完整重编译结果建立字段属性证据，供计划—执行一致性校验和草稿展示。"""
    all_fields = plan.master_fields + plan.footer_fields + [
        item for item in plan.detail_tables[0].fields if item.kind == "field"
    ]
    by_binding = {
        ("@" if item.scope == "master" else "#", item.bind_name): item
        for item in all_fields
    }
    expected_options = {
        item.field_id: options
        for item in all_fields
        if (options := planned_semantic_options(item))
    }
    title_options = planned_text_options(plan.title_style)
    if title_options:
        expected_options["template.title"] = title_options
    applied_option_keys: Dict[str, set[str]] = {field_id: set() for field_id in expected_options}
    changes: List[PatchChange] = []
    changed_properties = set()
    for page_index, page in enumerate(template.get("Pages", [])):
        if not isinstance(page, dict):
            continue
        for element_index, element in enumerate(page.get("ReportElements", [])):
            if not isinstance(element, dict):
                continue
            for row_index, row in enumerate(element.get("Rows", [])):
                if not isinstance(row, dict):
                    continue
                for cell_index, cell in enumerate(row.get("Cells", [])):
                    if not isinstance(cell, dict):
                        continue
                    text = cell.get("CellText")
                    if not isinstance(text, str):
                        continue
                    if title_options and text == plan.title:
                        applied_option_keys["template.title"].update(title_options)
                        effective = _effective_native_properties(cell, title_options)
                        native_keys = sorted(effective)
                        changed_properties.update(native_keys)
                        changes.append(
                            PatchChange(
                                native_path="Pages[%d].ReportElements[%d].Rows[%d].Cells[%d]"
                                % (page_index, element_index, row_index, cell_index),
                                field_id="template.title",
                                cell_text=text,
                                semantic_options=title_options,
                                effective_native_properties=effective,
                                changed_native_properties=native_keys,
                                status="generated",
                            )
                        )
                    if len(text) < 2 or text[0] not in "@#^":
                        continue
                    lookup_prefix = "#" if text[0] == "^" else text[0]
                    field = by_binding.get((lookup_prefix, text[1:]))
                    if field is None:
                        continue
                    options = expected_options.get(field.field_id, {})
                    if not options:
                        continue
                    applied_option_keys[field.field_id].update(options)
                    effective = _effective_native_properties(cell, options)
                    native_keys = sorted(effective)
                    changed_properties.update(native_keys)
                    changes.append(
                        PatchChange(
                            native_path="Pages[%d].ReportElements[%d].Rows[%d].Cells[%d]"
                            % (page_index, element_index, row_index, cell_index),
                            field_id=field.field_id,
                            cell_text=text,
                            semantic_options=options,
                            effective_native_properties=effective,
                            changed_native_properties=native_keys,
                            status="generated",
                        )
                    )
    return PatchExecutionReport(
        strategy="quick-table-structure",
        base_content_hash=base_content_hash,
        expected_options=expected_options,
        applied_option_keys={key: sorted(value) for key, value in applied_option_keys.items()},
        changes=changes,
        changed_native_properties=sorted(changed_properties),
        layout_evidence=_build_layout_evidence(plan, template),
    )


def _build_layout_evidence(plan: TemplatePlan, template: Dict[str, Any]) -> Dict[str, Any]:
    detail = plan.detail_tables[0]
    pages = template.get("Pages") or []
    page = pages[0] if pages and isinstance(pages[0], dict) else {}
    tables = [
        item
        for item in page.get("ReportElements", [])
        if isinstance(item, dict) and item.get("ClassName") == "TTableElement"
    ]
    table = tables[0] if tables else {}
    title_cell = {}
    for row in (table.get("Rows", []) if isinstance(table, dict) else []):
        if not isinstance(row, dict):
            continue
        for cell in row.get("Cells", []):
            if isinstance(cell, dict) and cell.get("CellText") == plan.title:
                title_cell = cell
                break
        if title_cell:
            break
    labels = [item.label for item in detail.fields]
    header_row = {}
    body_row = {}
    for index, row in enumerate(table.get("Rows", [])):
        if not isinstance(row, dict):
            continue
        texts = [cell.get("CellText", "") for cell in row.get("Cells", []) if isinstance(cell, dict)]
        if texts == labels:
            header_row = row
            if index + 1 < len(table.get("Rows", [])):
                body_row = table["Rows"][index + 1]
            break
    header_cells = header_row.get("Cells", []) if isinstance(header_row, dict) else []
    body_cells = body_row.get("Cells", []) if isinstance(body_row, dict) else []
    table_rows = table.get("Rows", []) if isinstance(table, dict) else []
    detail_row_index = table_rows.index(header_row) if header_row in table_rows else -1
    last_detail_row = {}
    if detail_row_index >= 0:
        detail_row_count = 3 if detail.total_field_ids else 2
        candidate_index = detail_row_index + detail_row_count - 1
        if candidate_index < len(table_rows) and isinstance(table_rows[candidate_index], dict):
            last_detail_row = table_rows[candidate_index]
    last_cells = last_detail_row.get("Cells", []) if isinstance(last_detail_row, dict) else []
    page_setting = template.get("PageSetting") if isinstance(template.get("PageSetting"), dict) else {}
    return {
        "page": {
            "expected": {
                "paperName": plan.page.paper_name,
                "orientation": plan.page.orientation,
                "widthCm": plan.page.width_cm,
                "heightCm": plan.page.height_cm,
                "marginsCm": dict(plan.page.margins_cm),
            },
            "actual": {
                "paperName": page_setting.get("PaperName"),
                "orientation": (
                    "landscape" if page_setting.get("PaperOrientation") == 1 else "portrait"
                ),
                "widthCm": float(page_setting.get("PaperWidthUM", 2100)) / 100.0,
                "heightCm": (
                    float(page_setting["PaperHeightUM"]) / 100.0
                    if isinstance(page_setting.get("PaperHeightUM"), (int, float))
                    else None
                ),
                "marginsCm": {
                    "top": float(page_setting.get("TopMarginUM", 0)) / 100.0,
                    "right": float(page_setting.get("RightMarginUM", 0)) / 100.0,
                    "bottom": float(page_setting.get("BottomMarginUM", 0)) / 100.0,
                    "left": float(page_setting.get("LeftMarginUM", 0)) / 100.0,
                },
                "width": page.get("Width"),
                "height": page.get("Height"),
                "tableLeft": table.get("Left"),
                "tableTop": table.get("Top"),
                "tableWidth": table.get("Width"),
                "tableHeight": table.get("Height"),
            },
        },
        "columns": [
            {
                "kind": item.kind,
                "fieldId": item.field_id if item.kind == "field" else None,
                "label": item.label,
                "widthWeight": item.width_weight,
                "nativeWidth": header_cells[index].get("OrigWidth") if index < len(header_cells) else None,
                "nativeBodyText": body_cells[index].get("CellText", "") if index < len(body_cells) else None,
            }
            for index, item in enumerate(detail.fields)
        ],
        "tableStyle": {
            "expected": {
                "headerHeightCm": detail.table_style.header_height_cm,
                "bodyHeightCm": detail.table_style.body_height_cm,
                "headerFontSize": detail.table_style.header_font_size,
                "bodyFontSize": detail.table_style.body_font_size,
                "outer": vars(detail.table_style.outer),
                "innerHorizontal": vars(detail.table_style.inner_horizontal),
                "innerVertical": vars(detail.table_style.inner_vertical),
            },
            "actual": {
                "headerHeight": header_cells[0].get("OrigHeight") if header_cells else None,
                "bodyHeight": body_cells[0].get("OrigHeight") if body_cells else None,
                "headerFontSize": header_cells[0].get("FontSize") if header_cells else None,
                "bodyFontSize": body_cells[0].get("FontSize") if body_cells else None,
                "borders": {
                    "outerTop": _line_evidence(header_cells[0], "Top") if header_cells else None,
                    "outerLeft": _line_evidence(header_cells[0], "Left") if header_cells else None,
                    "outerRight": _line_evidence(header_cells[-1], "Right") if header_cells else None,
                    "outerBottom": _line_evidence(last_cells[0], "Bottom") if last_cells else None,
                    "innerHorizontal": _line_evidence(header_cells[0], "Bottom") if header_cells else None,
                    "innerVertical": _line_evidence(header_cells[0], "Right") if len(header_cells) > 1 else None,
                },
            },
        },
        "titleOptions": {
            "expected": planned_text_options(plan.title_style),
            "actual": _effective_native_properties(
                title_cell,
                planned_text_options(plan.title_style),
            )
            if title_cell and planned_text_options(plan.title_style)
            else {},
        },
    }


def _line_evidence(cell: Dict[str, Any], side: str) -> Dict[str, Any]:
    visible = cell.get(side + "Line", 1) != 0
    if not visible:
        return {"style": "none", "width": 0}
    style_value = cell.get(side + "LineStyle", 0)
    styles = {value: key for key, value in LINE_STYLE_VALUES.items()}
    return {
        "style": styles.get(style_value, "unknown"),
        "width": cell.get(side + "LineWidth", 1),
    }


class NativeTemplateValidator:
    def validate(
        self,
        template: Dict[str, Any],
        catalog: FieldCatalog,
        allow_legacy_layout: bool = False,
    ) -> ValidationResult:
        logger.info(
            "原生模板校验开始 report=%s pages=%d legacy_layout=%s",
            template.get("ReportName"),
            len(template.get("Pages", [])) if isinstance(template.get("Pages"), list) else 0,
            allow_legacy_layout,
        )
        errors: List[str] = []
        if template.get("ReportName") != catalog.report_name:
            errors.append("ReportName 与字段目录不一致")
        if not isinstance(template.get("PageSetting"), dict):
            errors.append("缺少 PageSetting")
        pages = template.get("Pages")
        if not isinstance(pages, list) or not pages:
            return ValidationResult(False, errors + ["Pages 至少需要一页"])

        for page_index, page in enumerate(pages):
            if not isinstance(page, dict) or page.get("ClassName") != "TTemplatePage":
                errors.append("Pages[%s] 不是 TTemplatePage" % page_index)
                continue
            elements = page.get("ReportElements")
            tables = [item for item in elements or [] if isinstance(item, dict) and item.get("ClassName") == "TTableElement"]
            if len(tables) != 1:
                errors.append("Pages[%s] 必须且只能包含一个 TTableElement" % page_index)
                continue
            table = tables[0]
            page_setting = template.get("PageSetting")
            page_setting = page_setting if isinstance(page_setting, dict) else {}
            native_margin_values = {
                "left": page_setting.get("LeftMarginUM", 0),
                "right": page_setting.get("RightMarginUM", 0),
                "top": page_setting.get("TopMarginUM", 0),
                "bottom": page_setting.get("BottomMarginUM", 0),
            }
            invalid_margins = [
                key
                for key, value in native_margin_values.items()
                if isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ]
            if invalid_margins:
                errors.append("PageSetting 包含无效页边距：%s" % ",".join(invalid_margins))
            margin_px = {
                key: (float(value) / 100.0 * PX_PER_CM if key not in invalid_margins else 0.0)
                for key, value in native_margin_values.items()
            }
            for key in ("Left", "Top", "Width", "Height"):
                value = table.get(key)
                if not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                    errors.append("表格 %s 必须是有限非负数" % key)
            if (
                not allow_legacy_layout
                and table.get("Left", 0) + table.get("Width", 0) > page.get("Width", 0) + 1
            ):
                errors.append("表格超出页面宽度")
            if (
                not allow_legacy_layout
                and table.get("Top", 0) + table.get("Height", 0) > page.get("Height", 0) + 1
            ):
                errors.append("表格超出页面高度")
            if not allow_legacy_layout:
                if table.get("Left", 0) < margin_px["left"] - 1:
                    errors.append("表格越过左页边距")
                if table.get("Top", 0) < margin_px["top"] - 1:
                    errors.append("表格越过上页边距")
                if (
                    table.get("Left", 0) + table.get("Width", 0)
                    > page.get("Width", 0) - margin_px["right"] + 1
                ):
                    errors.append("表格越过右页边距")
                if (
                    table.get("Top", 0) + table.get("Height", 0)
                    > page.get("Height", 0) - margin_px["bottom"] + 1
                ):
                    errors.append("表格越过下页边距")
            for row_index, row in enumerate(table.get("Rows") or []):
                cells = row.get("Cells") if isinstance(row, dict) else None
                if not isinstance(cells, list) or not cells:
                    errors.append("Rows[%s] 缺少 Cells" % row_index)
                    continue
                widths = [cell.get("OrigWidth") for cell in cells if isinstance(cell, dict)]
                if len(widths) != len(cells) or any(not isinstance(value, (int, float)) or value <= 0 for value in widths):
                    errors.append("Rows[%s] 包含无效 OrigWidth" % row_index)
                elif not allow_legacy_layout and abs(sum(widths) - table.get("Width", 0)) > 1:
                    errors.append("Rows[%s] 单元格宽度之和与表格宽度不一致" % row_index)
                if not allow_legacy_layout:
                    heights = [cell.get("OrigHeight") for cell in cells if isinstance(cell, dict)]
                    explicit_heights = [value for value in heights if value is not None]
                    if explicit_heights and (
                        len(explicit_heights) != len(cells)
                        or any(not isinstance(value, (int, float)) or value <= 0 for value in explicit_heights)
                        or len(set(explicit_heights)) != 1
                    ):
                        errors.append("Rows[%s] 包含不一致的 OrigHeight" % row_index)
                    font_sizes = [cell.get("FontSize") for cell in cells if isinstance(cell, dict)]
                    explicit_fonts = [value for value in font_sizes if value is not None]
                    if explicit_fonts and (
                        len(explicit_fonts) != len(cells)
                        or any(not isinstance(value, (int, float)) or not 6 <= value <= 36 for value in explicit_fonts)
                    ):
                        errors.append("Rows[%s] 包含无效 FontSize" % row_index)

        bindings = extract_bindings(template)
        seen_detail = set(bindings["detail"])
        for scope in ("master", "detail"):
            for name in bindings[scope]:
                field_id = "%s.%s" % (scope, name)
                if scope == "detail" and name == "行号":
                    continue
                try:
                    definition = catalog.get(field_id)
                    if definition.scope != scope:
                        errors.append("字段作用域不一致：%s" % field_id)
                except ValueError:
                    errors.append("字段目录中不存在绑定：%s" % field_id)
        for name in bindings["total"]:
            field_id = "detail.%s" % name
            try:
                definition = catalog.get(field_id)
                if name not in seen_detail:
                    errors.append("合计字段未出现在明细绑定中：%s" % name)
                if not definition.aggregatable or definition.data_type != "number":
                    errors.append("字段不可合计：%s" % field_id)
            except ValueError:
                errors.append("字段目录中不存在合计绑定：%s" % field_id)
        result = ValidationResult(not errors, errors)
        if errors:
            logger.warning("原生模板校验失败 errors=%d", len(errors))
        else:
            logger.info("原生模板校验通过 bindings_master=%d bindings_detail=%d bindings_total=%d", *(len(bindings[key]) for key in ("master", "detail", "total")))
        return result

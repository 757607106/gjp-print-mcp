"""应用服务模块：串联确定性编译或克隆、静态校验并返回已验证草稿。"""

from __future__ import annotations

import json
import logging
from typing import Optional, TYPE_CHECKING

from .catalog import FieldCatalog, extract_bindings
from .domain import DomainError, DraftResult, TemplatePlan
from .native import (
    FORMAT_KIND_VALUES,
    IMAGE_SHOW_TYPE_VALUES,
    HORIZONTAL_ALIGN_VALUES,
    NativeTemplateCompiler,
    NativeTemplatePatcher,
    NativeTemplateValidator,
    VERTICAL_ALIGN_VALUES,
    build_compiler_execution_report,
    content_hash,
)
from gjp_common.logging_config import context_logging_enabled

if TYPE_CHECKING:
    from .reports import ReportContext


logger = logging.getLogger(__name__)


class TemplateAgentService:
    def __init__(
        self,
        catalog: FieldCatalog,
        compiler: NativeTemplateCompiler = None,
        patcher: NativeTemplatePatcher = None,
        validator: NativeTemplateValidator = None,
        report_context: Optional["ReportContext"] = None,
    ):
        self.catalog = catalog
        self.compiler = compiler or NativeTemplateCompiler()
        self.patcher = patcher or NativeTemplatePatcher()
        self.validator = validator or NativeTemplateValidator()
        self.report_context = report_context

    def execute_plan(
        self,
        plan: TemplatePlan,
        preserve_base: bool = False,
        base_content_hash: Optional[str] = None,
    ) -> DraftResult:
        """执行结构化计划，不再从自然语言关键词推断执行策略。

        当计划与真实基础模板结构完全一致时，可以安全地保留基础模板并只
        应用单元格属性；其余情况统一走确定性编译器。这个选择只依赖结构
        对比，不依赖任何用户措辞。
        """
        use_clone = bool(
            preserve_base
            and self.report_context is not None
            and self._matches_base_structure(plan)
        )
        effective_base_hash = base_content_hash
        execution_report = None
        if use_clone:
            plan.strategy = "clone-base"
            effective_base_hash = self.report_context.base_hash
            native_template, execution_report = self.patcher.apply_cell_options_with_report(
                self.report_context.base_template,
                plan,
            )
        else:
            plan.strategy = "quick-table"
            native_template = self.compiler.compile(plan)
            if effective_base_hash is None and self.report_context is not None:
                effective_base_hash = self.report_context.base_hash
            execution_report = build_compiler_execution_report(
                plan,
                native_template,
                effective_base_hash or "none",
            )
        validation = self.validator.validate(
            native_template,
            self.catalog,
            allow_legacy_layout=use_clone,
        )
        if not validation.valid:
            raise DomainError("TEMPLATE_INVALID", "；".join(validation.errors))
        bindings = extract_bindings(native_template)
        self._validate_plan_execution(plan, bindings, execution_report)
        return DraftResult(
            plan=plan,
            native_template=native_template,
            content_hash=content_hash(native_template),
            validation=validation,
            bindings=bindings,
            base_content_hash=effective_base_hash,
            execution_report=execution_report,
        )

    def _matches_base_structure(self, plan) -> bool:
        assert self.report_context is not None
        if any(item.kind != "field" for item in plan.detail_tables[0].fields):
            return False
        expected = self.report_context.bindings
        planned_master = [item.bind_name for item in plan.master_fields + plan.footer_fields]
        planned_detail = [item.bind_name for item in plan.detail_tables[0].fields]
        planned_total = [self.catalog.get(field_id).name for field_id in plan.detail_tables[0].total_field_ids]
        page = self.report_context.page
        page_matches = (
            plan.page.paper_name == page.paper_name
            and plan.page.orientation == page.orientation
            and abs(plan.page.width_cm - page.width_cm) < 0.001
            and abs(plan.page.height_cm - page.height_cm) < 0.001
            and all(abs(plan.page.margins_cm[key] - page.margins_cm[key]) < 0.001 for key in page.margins_cm)
        )
        return (
            planned_master == expected["master"]
            and planned_detail == expected["detail"]
            and set(planned_total) == set(expected["total"])
            and plan.title == self.report_context.profile.logical_name
            and page_matches
        )

    def _validate_plan_execution(self, plan, bindings, execution_report) -> None:
        expected_bindings = {
            "master": [item.bind_name for item in plan.master_fields + plan.footer_fields],
            "detail": [
                item.bind_name
                for item in plan.detail_tables[0].fields
                if item.kind in {"field", "sequence"}
            ],
            "total": [self.catalog.get(field_id).name for field_id in plan.detail_tables[0].total_field_ids],
        }
        bindings_match = (
            bindings.get("master") == expected_bindings["master"]
            and bindings.get("detail") == expected_bindings["detail"]
            and set(bindings.get("total", [])) == set(expected_bindings["total"])
        )
        if not bindings_match:
            raise DomainError(
                "PLAN_EXECUTION_MISMATCH",
                "最终模板字段与计划不一致：expected=%s actual=%s"
                % (
                    json.dumps(expected_bindings, ensure_ascii=False, separators=(",", ":")),
                    json.dumps(bindings, ensure_ascii=False, separators=(",", ":")),
                ),
            )
        if execution_report is None:
            return
        layout = execution_report.layout_evidence
        if layout:
            layout_errors = []
            page_actual = layout.get("page", {}).get("actual", {})
            if page_actual.get("paperName") != plan.page.paper_name:
                layout_errors.append("纸张名称未执行")
            if page_actual.get("orientation") != plan.page.orientation:
                layout_errors.append("纸张方向未执行")
            for key, expected in (
                ("widthCm", plan.page.width_cm),
                ("heightCm", plan.page.height_cm),
            ):
                actual = page_actual.get(key)
                if not isinstance(actual, (int, float)) or abs(actual - expected) > 0.001:
                    layout_errors.append("页面尺寸未执行：%s" % key)
            actual_margins = page_actual.get("marginsCm", {})
            for key, expected in plan.page.margins_cm.items():
                actual = actual_margins.get(key)
                if not isinstance(actual, (int, float)) or abs(actual - expected) > 0.001:
                    layout_errors.append("页边距未执行：%s" % key)
            columns = layout.get("columns", [])
            for planned, actual in zip(plan.detail_tables[0].fields, columns):
                expected_text = (
                    "#" + planned.bind_name
                    if planned.kind in {"field", "sequence"}
                    else ""
                )
                if actual.get("kind") != planned.kind or actual.get("label") != planned.label:
                    layout_errors.append("列类型或表头未执行：%s" % planned.label)
                if actual.get("nativeBodyText") != expected_text:
                    layout_errors.append("列绑定未执行：%s" % planned.label)
                if not isinstance(actual.get("nativeWidth"), (int, float)) or actual["nativeWidth"] <= 0:
                    layout_errors.append("列宽未执行：%s" % planned.label)
            if len(columns) != len(plan.detail_tables[0].fields):
                layout_errors.append("列数量与计划不一致")
            style = plan.detail_tables[0].table_style
            style_actual = layout.get("tableStyle", {}).get("actual", {})
            if style_actual.get("headerHeight") != int(round(style.header_height_cm * 37.8)):
                layout_errors.append("表头行高未执行")
            if style_actual.get("bodyHeight") != int(round(style.body_height_cm * 37.8)):
                layout_errors.append("内容行高未执行")
            if style_actual.get("headerFontSize") != style.header_font_size:
                layout_errors.append("表头字号未执行")
            if style_actual.get("bodyFontSize") != style.body_font_size:
                layout_errors.append("内容字号未执行")
            actual_borders = style_actual.get("borders", {})
            expected_borders = {
                "outerTop": vars(style.outer),
                "outerLeft": vars(style.outer),
                "outerRight": vars(style.outer),
                "outerBottom": vars(style.outer),
                "innerHorizontal": vars(style.inner_horizontal),
            }
            if len(columns) > 1:
                expected_borders["innerVertical"] = vars(style.inner_vertical)
            for key, expected in expected_borders.items():
                if actual_borders.get(key) != expected:
                    layout_errors.append("边框未执行：%s" % key)
            if layout_errors:
                raise DomainError("PLAN_EXECUTION_MISMATCH", "；".join(layout_errors))
        missing = []
        for field_id, options in execution_report.expected_options.items():
            applied = set(execution_report.applied_option_keys.get(field_id, []))
            for option_key in options:
                if option_key not in applied:
                    missing.append("%s.%s" % (field_id, option_key))
        if missing:
            raise DomainError(
                "PLAN_EXECUTION_MISMATCH",
                "以下计划属性没有写入任何原生单元格：%s" % "、".join(missing),
            )
        mismatches = []
        for field_id, options in execution_report.expected_options.items():
            expected_native = _expected_native_properties(options)
            field_changes = [
                item for item in execution_report.changes if item.field_id == field_id
            ]
            if not field_changes:
                mismatches.append("%s 没有原生路径证据" % field_id)
                continue
            for change in field_changes:
                for native_key, expected_value in expected_native.items():
                    actual_value = change.effective_native_properties.get(native_key)
                    if actual_value != expected_value:
                        mismatches.append(
                            "%s %s expected=%s actual=%s"
                            % (change.native_path, native_key, expected_value, actual_value)
                        )
        if mismatches:
            raise DomainError(
                "PLAN_EXECUTION_MISMATCH",
                "原生单元格属性与计划不一致：%s" % "；".join(mismatches),
            )

def _expected_native_properties(options: dict) -> dict:
    mapping = {
        "formatKind": ("FormatKind", lambda value: FORMAT_KIND_VALUES[value]),
        "decimalPlaces": ("Decimal", lambda value: value),
        "upperDecimalPlaces": ("UpperDecimal", lambda value: value),
        "prefix": ("PreTextFlag", lambda value: value),
        "hideZero": ("DisplayEmptyForZero", lambda value: value),
        "dynamicTextSize": ("DynamicTextSize", lambda value: value),
        "mergeSameValue": ("MergeSameValue", lambda value: value),
        "imageShowType": ("ImageShowType", lambda value: IMAGE_SHOW_TYPE_VALUES[value]),
        "horizontalAlign": ("HorzAlign", lambda value: HORIZONTAL_ALIGN_VALUES[value]),
        "verticalAlign": ("VertAlign", lambda value: VERTICAL_ALIGN_VALUES[value]),
    }
    return {
        mapping[key][0]: mapping[key][1](value)
        for key, value in options.items()
    }

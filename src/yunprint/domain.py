"""打印模板领域模型：字段、计划、草稿和校验结果。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from gjp_common.errors import DomainError


@dataclass(frozen=True)
class FieldDefinition:
    field_id: str
    report_name: str
    report_type: int
    table_name: str
    scope: str
    name: str
    data_type: str
    aliases: List[str]
    aggregatable: bool
    default_recommended: bool = False
    default_total: bool = False
    zone: str = "header"
    default_order: int = 0
    source: str = "metadata"

    def to_model_dict(self) -> Dict[str, Any]:
        return {
            "fieldId": self.field_id,
            "tableName": self.table_name,
            "scope": self.scope,
            "name": self.name,
            "dataType": self.data_type,
            "aliases": self.aliases,
            "aggregatable": self.aggregatable,
            "defaultRecommended": self.default_recommended,
            "defaultTotal": self.default_total,
            "zone": self.zone,
        }


@dataclass
class PlannedField:
    field_id: str
    label: str
    bind_name: str
    scope: str
    width_weight: float = 1.0
    format_kind: str = "none"
    decimal_places: Optional[int] = None
    upper_decimal_places: Optional[int] = None
    prefix: str = ""
    hide_zero: bool = False
    dynamic_text_size: bool = False
    merge_same_value: bool = False
    image_show_type: str = "stretch"
    horizontal_align: str = "default"
    vertical_align: str = "default"
    kind: str = "field"


@dataclass
class BorderPlan:
    style: str = "solid"
    width: int = 1


@dataclass
class TextStylePlan:
    horizontal_align: str = "default"
    vertical_align: str = "default"


@dataclass
class TableStylePlan:
    """明细表结构样式。"""

    header_height_cm: float = 0.7
    body_height_cm: float = 0.7
    header_font_size: int = 10
    body_font_size: int = 9
    outer: BorderPlan = field(default_factory=BorderPlan)
    inner_horizontal: BorderPlan = field(default_factory=BorderPlan)
    inner_vertical: BorderPlan = field(default_factory=BorderPlan)


@dataclass
class PlannedDetailTable:
    table_name: str
    fields: List[PlannedField]
    total_field_ids: List[str] = field(default_factory=list)
    max_rows_per_page: int = 10
    table_style: TableStylePlan = field(default_factory=TableStylePlan)


@dataclass
class PagePlan:
    paper_name: str = "自定义纸张"
    orientation: str = "portrait"
    width_cm: float = 21.0
    height_cm: float = 13.9
    margins_cm: Dict[str, float] = field(
        default_factory=lambda: {"top": 0.5, "right": 0.5, "bottom": 0.5, "left": 0.5}
    )


@dataclass
class TemplatePlan:
    report_name: str
    report_type: int
    title: str
    strategy: str
    master_fields: List[PlannedField]
    detail_tables: List[PlannedDetailTable]
    footer_fields: List[PlannedField]
    page: PagePlan
    confidence: float
    assumptions: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    title_style: TextStylePlan = field(default_factory=TextStylePlan)

    @property
    def intent(self) -> str:
        return "create"

    def to_dict(self) -> Dict[str, Any]:
        result = asdict(self)
        result["intent"] = self.intent
        return result

    def to_protocol_dict(self) -> Dict[str, Any]:
        """序列化为唯一受支持的 1.1 语义计划形状。"""
        detail = self.detail_tables[0]

        def options(item: PlannedField) -> Dict[str, Any]:
            value: Dict[str, Any] = {}
            if item.format_kind != "none":
                value["formatKind"] = item.format_kind
            if item.decimal_places is not None:
                value["decimalPlaces"] = item.decimal_places
            if item.upper_decimal_places is not None:
                value["upperDecimalPlaces"] = item.upper_decimal_places
            if item.prefix:
                value["prefix"] = item.prefix
            if item.hide_zero:
                value["hideZero"] = True
            if item.dynamic_text_size:
                value["dynamicTextSize"] = True
            if item.merge_same_value:
                value["mergeSameValue"] = True
            if item.image_show_type != "stretch":
                value["imageShowType"] = item.image_show_type
            if item.horizontal_align != "default":
                value["horizontalAlign"] = item.horizontal_align
            if item.vertical_align != "default":
                value["verticalAlign"] = item.vertical_align
            return value

        def text_options(style: TextStylePlan) -> Dict[str, Any]:
            value: Dict[str, Any] = {}
            if style.horizontal_align != "default":
                value["horizontalAlign"] = style.horizontal_align
            if style.vertical_align != "default":
                value["verticalAlign"] = style.vertical_align
            return value

        selected_fields = self.master_fields + detail.fields + self.footer_fields
        cell_options = {
            item.field_id: value
            for item in selected_fields
            if item.kind == "field" and (value := options(item))
        }
        style = detail.table_style
        return {
            "reportName": self.report_name,
            "reportType": self.report_type,
            "title": self.title,
            "titleOptions": text_options(self.title_style),
            "strategy": self.strategy,
            "masterFieldIds": [item.field_id for item in self.master_fields],
            "detailTables": [
                {
                    "tableName": detail.table_name,
                    "columns": [
                        {
                            "kind": item.kind,
                            **(
                                {"fieldId": item.field_id}
                                if item.kind == "field"
                                else {}
                            ),
                            "label": item.label,
                            "widthWeight": item.width_weight,
                        }
                        for item in detail.fields
                    ],
                    "totalFieldIds": list(detail.total_field_ids),
                    "maxRowsPerPage": detail.max_rows_per_page,
                    "tableStyle": {
                        "headerHeightCm": style.header_height_cm,
                        "bodyHeightCm": style.body_height_cm,
                        "headerFontSize": style.header_font_size,
                        "bodyFontSize": style.body_font_size,
                        "borders": {
                            "outer": asdict(style.outer),
                            "innerHorizontal": asdict(style.inner_horizontal),
                            "innerVertical": asdict(style.inner_vertical),
                        },
                    },
                }
            ],
            "footerFieldIds": [item.field_id for item in self.footer_fields],
            "cellOptions": cell_options,
            "page": {
                "paperName": self.page.paper_name,
                "orientation": self.page.orientation,
                "widthCm": self.page.width_cm,
                "heightCm": self.page.height_cm,
                "marginsCm": dict(self.page.margins_cm),
            },
        }


@dataclass
class AgentEnvelope:
    schema_version: str
    intent: str
    clarification_needed: bool
    confidence: float
    warnings: List[str]
    assumptions: List[str]
    plan: Optional[TemplatePlan]
    clarification_question: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": self.schema_version,
            "intent": self.intent,
            "clarificationNeeded": self.clarification_needed,
            "clarificationQuestion": self.clarification_question,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "plan": self.plan.to_protocol_dict() if self.plan else None,
        }


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PatchChange:
    """单个原生单元格对计划属性的执行证据。"""

    native_path: str
    field_id: str
    cell_text: str
    semantic_options: Dict[str, Any]
    effective_native_properties: Dict[str, Any]
    changed_native_properties: List[str]
    status: str


@dataclass
class PatchExecutionReport:
    """基础模板属性补丁的计划—执行一致性报告。"""

    strategy: str
    base_content_hash: str
    expected_options: Dict[str, Dict[str, Any]]
    applied_option_keys: Dict[str, List[str]]
    changes: List[PatchChange]
    changed_native_properties: List[str]
    layout_evidence: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DraftResult:
    plan: TemplatePlan
    native_template: Dict[str, Any]
    content_hash: str
    validation: ValidationResult
    bindings: Dict[str, List[str]]
    base_content_hash: Optional[str] = None
    execution_report: Optional[PatchExecutionReport] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schemaVersion": "1.1",
            "plan": self.plan.to_protocol_dict(),
            "nativeTemplate": self.native_template,
            "compiledContentHash": self.content_hash,
            "validation": self.validation.to_dict(),
            "bindings": self.bindings,
            "baseContentHash": self.base_content_hash,
            "executionReport": self.execution_report.to_dict() if self.execution_report else None,
        }

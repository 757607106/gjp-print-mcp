"""模板 JSON 生成逻辑使用的 Pydantic 计划模型。"""

import typing
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Pydantic 模板计划输入模型
# ---------------------------------------------------------------------------

def _relax_numeric_schema(schema: dict) -> None:
    """递归修改 JSON Schema，让 integer/number/boolean 字段也接受 string。

    LLM 常把数字和布尔值序列化为字符串，严格 JSON Schema 会拒绝。
    此函数把 {"type": "integer"} 改写为
    {"anyOf": [{"type": "integer", ...}, {"type": "string"}]}，
    对 anyOf 中含数值/布尔的也追加 string 选项。
    """
    if not isinstance(schema, dict):
        return
    for def_schema in schema.get("$defs", {}).values():
        _relax_numeric_schema(def_schema)
    for prop in schema.get("properties", {}).values():
        _relax_numeric_schema(prop)
    items = schema.get("items")
    if isinstance(items, dict):
        _relax_numeric_schema(items)
    addl = schema.get("additionalProperties")
    if isinstance(addl, dict):
        _relax_numeric_schema(addl)
    t = schema.get("type")
    if t in ("integer", "number", "boolean"):
        rest = {k: v for k, v in schema.items() if k != "type"}
        schema.clear()
        schema["anyOf"] = [{"type": t, **rest}, {"type": "string"}]
        return
    any_of = schema.get("anyOf")
    if any_of:
        has_numeric = any(
            isinstance(sub, dict) and sub.get("type") in ("integer", "number", "boolean")
            for sub in any_of
        )
        has_string = any(
            isinstance(sub, dict) and sub.get("type") == "string"
            for sub in any_of
        )
        if has_numeric and not has_string:
            any_of.append({"type": "string"})


def _coerce_target_type(annotation: Any) -> type | None:
    """从字段注解提取需要 coerce 的目标类型（int/float/bool）。"""
    if annotation is bool:
        return bool
    if annotation is int:
        return int
    if annotation is float:
        return float
    origin = typing.get_origin(annotation)
    if origin is typing.Union:
        args = [a for a in typing.get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _coerce_target_type(args[0])
    return None


def _coerce_value(value: Any, target: type) -> Any:
    """尝试将字符串值转换为目标类型，失败则原样返回由 Pydantic 校验报错。"""
    if not isinstance(value, str):
        return value
    if target is bool:
        lower = value.lower()
        if lower in ("true", "1", "yes"):
            return True
        if lower in ("false", "0", "no"):
            return False
        return value
    if target is int:
        try:
            return int(value)
        except ValueError:
            return value
    if target is float:
        try:
            return float(value)
        except ValueError:
            return value
    return value


class ToolInput(BaseModel):
    """模板计划输入基类：严格模式禁止额外字段。

    schema 放宽和 model_validator 使 LLM 传入的字符串数字/布尔值能被自动转换。
    """

    model_config = ConfigDict(
        populate_by_name=True,
        extra="forbid",
        json_schema_extra=_relax_numeric_schema,
    )

    @model_validator(mode="before")
    @classmethod
    def _coerce_string_fields(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field_name, field_info in cls.model_fields.items():
            alias = field_info.alias or field_name
            key = alias if alias in data else (field_name if field_name in data else None)
            if key is None:
                continue
            target = _coerce_target_type(field_info.annotation)
            if target is not None and isinstance(data[key], str):
                data[key] = _coerce_value(data[key], target)
        return data


class BorderInput(ToolInput):
    style: Literal["solid", "dashed", "dotted", "none"]
    width: int = Field(ge=0, le=5)


class TableStyleInput(ToolInput):
    header_height_cm: float = Field(alias="headerHeightCm", ge=0.3, le=3.0)
    body_height_cm: float = Field(alias="bodyHeightCm", ge=0.3, le=3.0)
    header_font_size: int = Field(alias="headerFontSize", ge=6, le=36)
    body_font_size: int = Field(alias="bodyFontSize", ge=6, le=36)
    outer: BorderInput
    inner_horizontal: BorderInput = Field(alias="innerHorizontal")
    inner_vertical: BorderInput = Field(alias="innerVertical")


class TextStyleInput(ToolInput):
    horizontal_align: Optional[Literal["default", "left", "center", "right"]] = Field(
        default=None,
        alias="horizontalAlign",
        description="Horizontal text alignment. Use left/center/right only when the user asks for alignment.",
    )
    vertical_align: Optional[Literal["default", "top", "middle", "bottom"]] = Field(
        default=None,
        alias="verticalAlign",
        description="Vertical text alignment. Use top/middle/bottom only when the user asks for alignment.",
    )


class PageInput(ToolInput):
    paper_name: str = Field(alias="paperName", min_length=1)
    orientation: Literal["portrait", "landscape"]
    width_cm: float = Field(alias="widthCm", gt=0)
    height_cm: float = Field(alias="heightCm", gt=0)
    margins_cm: dict[Literal["top", "right", "bottom", "left"], float] = Field(
        alias="marginsCm",
    )

    @field_validator("margins_cm", mode="before")
    @classmethod
    def _coerce_margin_values(cls, v: Any) -> Any:
        if isinstance(v, dict):
            return {k: float(val) if isinstance(val, str) else val for k, val in v.items()}
        return v


class ColumnInput(ToolInput):
    kind: Literal["field", "sequence", "blank"]
    field_id: Optional[str] = Field(default=None, alias="fieldId")
    label: str = Field(min_length=1, max_length=30)
    width_weight: float = Field(alias="widthWeight", ge=0.2, le=5.0)


class CellOptionsInput(ToolInput):
    format_kind: Optional[
        Literal[
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
        ]
    ] = Field(default=None, alias="formatKind")
    decimal_places: Optional[int] = Field(default=None, alias="decimalPlaces", ge=0, le=8)
    upper_decimal_places: Optional[int] = Field(
        default=None,
        alias="upperDecimalPlaces",
        ge=-1,
        le=8,
    )
    prefix: Optional[str] = Field(default=None, max_length=30)
    hide_zero: Optional[bool] = Field(default=None, alias="hideZero")
    dynamic_text_size: Optional[bool] = Field(default=None, alias="dynamicTextSize")
    merge_same_value: Optional[bool] = Field(default=None, alias="mergeSameValue")
    image_show_type: Optional[Literal["stretch", "scale-width", "scale-height"]] = Field(
        default=None,
        alias="imageShowType",
    )
    horizontal_align: Optional[Literal["default", "left", "center", "right"]] = Field(
        default=None,
        alias="horizontalAlign",
    )
    vertical_align: Optional[Literal["default", "top", "middle", "bottom"]] = Field(
        default=None,
        alias="verticalAlign",
    )


class TemplatePlanInput(ToolInput):
    """完整可编辑计划：由确定性模板 JSON 编译器接收。"""

    title: str = Field(min_length=1, max_length=100)
    title_options: TextStyleInput = Field(
        default_factory=TextStyleInput,
        alias="titleOptions",
    )
    master_field_ids: list[str] = Field(alias="masterFieldIds")
    columns: list[ColumnInput] = Field(min_length=1)
    total_field_ids: list[str] = Field(alias="totalFieldIds")
    footer_field_ids: list[str] = Field(alias="footerFieldIds")
    cell_options: dict[str, CellOptionsInput] = Field(alias="cellOptions")
    page: PageInput
    max_rows_per_page: int = Field(alias="maxRowsPerPage", ge=1, le=100)
    table_style: TableStyleInput = Field(alias="tableStyle")

import pytest

from tests.printing.helpers.rule_planner import (
    RuleBasedPlanner,
    apply_deterministic_layout_requirements,
    build_default_delivery_plan,
    has_explicit_field_selection,
    sanitize_user_message,
)
from yunprint.catalog import FieldCatalog
from yunprint.domain import BorderPlan, DomainError, PagePlan, TableStylePlan
from yunprint.planner import build_plan


def test_rule_planner_uses_default_fields_without_hallucination():
    catalog = FieldCatalog.sales_default()
    envelope = RuleBasedPlanner().plan("生成一张销售单打印模板", catalog)
    planned_ids = {
        item.field_id for item in envelope.plan.master_fields + envelope.plan.footer_fields
    }
    planned_ids.update(item.field_id for item in envelope.plan.detail_tables[0].fields)
    assert planned_ids == {item.field_id for item in catalog.fields}
    assert envelope.plan.detail_tables[0].total_field_ids == ["detail.数量", "detail.金额"]


def test_input_guard_rejects_scripts_and_long_input():
    with pytest.raises(DomainError):
        sanitize_user_message("<script>alert(1)</script>")
    with pytest.raises(DomainError):
        sanitize_user_message("销" * 4001)


def test_explicit_field_selection_is_not_overridden():
    assert has_explicit_field_selection("生成销售单，只保留金额字段") is True
    assert has_explicit_field_selection("生成销售单，金额为0时不显示") is False


def test_merge_same_value_rejects_master_field():
    catalog = FieldCatalog.sales_default()
    with pytest.raises(DomainError, match="仅适用于明细字段"):
        build_plan(
            catalog=catalog,
            title="销售单",
            master_field_ids=["master.购买单位"],
            detail_columns=[
                {
                    "kind": "field",
                    "fieldId": "detail.数量",
                    "label": "数量",
                    "widthWeight": 1.0,
                }
            ],
            total_field_ids=["detail.数量"],
            footer_field_ids=[],
            page=PagePlan(),
            confidence=1,
            assumptions=[],
            warnings=[],
            cell_options={"master.购买单位": {"mergeSameValue": True}},
        )


def test_column_protocol_supports_sequence_field_and_blank_without_binding():
    plan = build_plan(
        catalog=FieldCatalog.sales_default(),
        title="送货单",
        master_field_ids=[],
        detail_columns=[
            {"kind": "sequence", "label": "序号", "widthWeight": 0.6},
            {
                "kind": "field",
                "fieldId": "detail.商品全名",
                "label": "商品详情",
                "widthWeight": 2.4,
            },
            {"kind": "blank", "label": "签字", "widthWeight": 1.0},
        ],
        total_field_ids=[],
        footer_field_ids=[],
        page=PagePlan(),
        confidence=1,
        assumptions=[],
        warnings=[],
    )
    columns = plan.to_protocol_dict()["detailTables"][0]["columns"]
    assert [item["kind"] for item in columns] == ["sequence", "field", "blank"]
    assert "fieldId" not in columns[0]
    assert columns[1]["fieldId"] == "detail.商品全名"
    assert "fieldId" not in columns[2]


@pytest.mark.parametrize(
    "columns, message",
    [
        (
            [
                {"kind": "field", "fieldId": "detail.数量", "label": "数量", "widthWeight": 1},
                {"kind": "field", "fieldId": "detail.金额", "label": "数量", "widthWeight": 1},
            ],
            "重复列标签",
        ),
        (
            [
                {"kind": "field", "fieldId": "detail.数量", "label": "数量", "widthWeight": 1},
                {"kind": "field", "fieldId": "detail.数量", "label": "数量2", "widthWeight": 1},
            ],
            "重复字段",
        ),
        (
            [
                {"kind": "sequence", "label": "序号", "widthWeight": 1},
                {"kind": "sequence", "label": "行号", "widthWeight": 1},
                {"kind": "field", "fieldId": "detail.数量", "label": "数量", "widthWeight": 1},
            ],
            "最多只能有一个序号列",
        ),
    ],
)
def test_column_protocol_rejects_duplicate_semantics(columns, message):
    with pytest.raises(DomainError, match=message):
        build_plan(
            catalog=FieldCatalog.sales_default(),
            title="销售单",
            master_field_ids=[],
            detail_columns=columns,
            total_field_ids=[],
            footer_field_ids=[],
            page=PagePlan(),
            confidence=1,
            assumptions=[],
            warnings=[],
        )


def test_explicit_custom_page_margin_and_relative_style_rules_are_deterministic():
    catalog = FieldCatalog.sales_default()
    plan = build_default_delivery_plan(catalog)
    current = {
        "page": {
            "paperName": "A4",
            "orientation": "portrait",
            "widthCm": 21,
            "heightCm": 29.7,
            "marginsCm": {"top": 2, "right": 2, "bottom": 2, "left": 2},
        },
        "tableStyle": {
            "headerHeightCm": 0.7,
            "bodyHeightCm": 0.7,
            "headerFontSize": 10,
            "bodyFontSize": 9,
        },
    }
    apply_deterministic_layout_requirements(
        "长宽设定为20cm × 15cm，左边距设为3cm，行高大一点，表头大一号，内容小一点",
        plan,
        current,
    )
    assert plan.page.paper_name == "自定义纸张"
    assert (plan.page.width_cm, plan.page.height_cm) == (20, 15)
    assert plan.page.margins_cm["left"] == 3
    style = plan.detail_tables[0].table_style
    assert style.header_height_cm == pytest.approx(0.875)
    assert style.body_height_cm == pytest.approx(0.875)
    assert style.header_font_size == 11
    assert style.body_font_size == 8


def test_invalid_border_combination_is_rejected_without_coercion():
    with pytest.raises(DomainError, match="虚线和点线宽度必须为1"):
        build_plan(
            catalog=FieldCatalog.sales_default(),
            title="销售单",
            master_field_ids=[],
            detail_columns=[
                {
                    "kind": "field",
                    "fieldId": "detail.数量",
                    "label": "数量",
                    "widthWeight": 1,
                }
            ],
            total_field_ids=[],
            footer_field_ids=[],
            page=PagePlan(),
            confidence=1,
            assumptions=[],
            warnings=[],
            table_style=TableStylePlan(inner_horizontal=BorderPlan("dotted", 2)),
        )

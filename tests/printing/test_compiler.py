from tests.printing.helpers.rule_planner import (
    RuleBasedPlanner,
    apply_deterministic_layout_requirements,
    build_default_delivery_plan,
)
from yunprint.catalog import FieldCatalog, extract_bindings
from yunprint.domain import PagePlan, TextStylePlan
from yunprint.native import (
    NativeTemplateCompiler,
    NativeTemplatePatcher,
    NativeTemplateValidator,
    content_hash,
)
from yunprint.planner import build_plan


def _compile_default():
    catalog = FieldCatalog.sales_default()
    envelope = RuleBasedPlanner().plan("生成一张销售单打印模板", catalog)
    return catalog, envelope.plan, NativeTemplateCompiler().compile(envelope.plan)


def test_compiler_emits_deterministic_11_sales_shape():
    catalog, plan, template = _compile_default()
    page = template["Pages"][0]
    table = page["ReportElements"][0]
    assert template["ReportName"] == "销售单"
    assert template["PageSetting"]["PaperHeightUM"] == 1390
    assert page["Width"] == 794
    assert page["Height"] == 525
    assert table["Left"] == 19
    assert table["Top"] == 19
    assert table["Width"] == 756
    assert table["Height"] == 247
    assert len(table["Rows"]) == 11
    assert [cell["OrigWidth"] for cell in table["Rows"][5]["Cells"]] == [95, 95, 95, 95, 94, 94, 94, 94]
    assert {cell["OrigHeight"] for cell in table["Rows"][5]["Cells"]} == {26}
    assert {cell["FontSize"] for cell in table["Rows"][5]["Cells"]} == {10}
    assert page["TableName"] == ""
    assert "PaperOrientation" not in template["PageSetting"]
    assert "PaperWidthUM" not in template["PageSetting"]
    assert extract_bindings(template) == {
        "master": [
            "公司全名",
            "发货仓库",
            "录单日期",
            "单据编号",
            "购买单位",
            "公司电话",
            "收款账户",
            "收款金额",
            "优惠金额",
            "制单人",
            "经手人",
        ],
        "detail": ["商品编号", "商品全名", "仓库全名", "单位", "数量", "单价", "金额", "单据备注"],
        "total": ["数量", "金额"],
    }
    assert NativeTemplateValidator().validate(template, catalog).valid is True
    assert content_hash(template) == content_hash(NativeTemplateCompiler().compile(plan))


def test_each_row_width_equals_table_width():
    _, _, template = _compile_default()
    table = template["Pages"][0]["ReportElements"][0]
    assert all(sum(cell["OrigWidth"] for cell in row["Cells"]) == table["Width"] for row in table["Rows"])


def test_a5_landscape_is_compiled_deterministically():
    catalog = FieldCatalog.sales_default()
    plan = RuleBasedPlanner().plan("生成一张 A5 横向销售单打印模板", catalog).plan
    template = NativeTemplateCompiler().compile(plan)
    assert template["PageSetting"]["PaperName"] == "A5"
    assert template["PageSetting"]["PaperOrientation"] == 1
    assert template["Pages"][0]["Width"] == 794
    assert template["Pages"][0]["Height"] == 559


def test_custom_page_and_four_margins_close_against_printable_area():
    catalog = FieldCatalog.sales_default()
    plan = build_default_delivery_plan(catalog)
    plan.page = PagePlan(
        paper_name="自定义纸张",
        orientation="portrait",
        width_cm=20,
        height_cm=15,
        margins_cm={"top": 0.5, "right": 1.0, "bottom": 1.5, "left": 2.0},
    )
    template = NativeTemplateCompiler().compile(plan)
    setting = template["PageSetting"]
    page = template["Pages"][0]
    table = page["ReportElements"][0]
    assert setting["PaperWidthUM"] == 2000
    assert setting["PaperHeightUM"] == 1500
    assert (
        setting["TopMarginUM"],
        setting["RightMarginUM"],
        setting["BottomMarginUM"],
        setting["LeftMarginUM"],
    ) == (50, 100, 150, 200)
    assert table["Left"] == round(2.0 * 37.8)
    assert table["Top"] == round(0.5 * 37.8)
    assert table["Left"] + table["Width"] <= page["Width"] - round(1.0 * 37.8) + 1
    assert table["Top"] + table["Height"] <= page["Height"] - round(1.5 * 37.8) + 1
    assert NativeTemplateValidator().validate(template, catalog).valid is True


def test_cell_options_compile_to_observed_native_properties():
    catalog = FieldCatalog.sales_default()
    message = (
        "生成一张销售单模板，录单日期用中文日期，金额为0时不显示，"
        "商品全名使用动态字体并将相同内容合并"
    )
    plan = RuleBasedPlanner().plan(message, catalog).plan
    template = NativeTemplateCompiler().compile(plan)
    cells = [
        cell
        for row in template["Pages"][0]["ReportElements"][0]["Rows"]
        for cell in row["Cells"]
    ]
    date_cell = next(cell for cell in cells if cell.get("CellText") == "@录单日期")
    amount_cell = next(cell for cell in cells if cell.get("CellText") == "#金额")
    product_cell = next(cell for cell in cells if cell.get("CellText") == "#商品全名")
    assert date_cell["FormatKind"] == 3
    assert amount_cell["DisplayEmptyForZero"] is True
    assert product_cell["DynamicTextSize"] is True
    assert product_cell["MergeSameValue"] is True


def test_prefix_decimal_and_image_display_mapping():
    catalog = FieldCatalog.sales_default()
    plan = build_plan(
        catalog=catalog,
        title="销售单",
        master_field_ids=["master.录单日期"],
        detail_columns=[
            {
                "kind": "field",
                "fieldId": "detail.商品全名",
                "label": "商品全名",
                "widthWeight": 1.0,
            },
            {
                "kind": "field",
                "fieldId": "detail.金额",
                "label": "金额",
                "widthWeight": 1.0,
            },
        ],
        total_field_ids=["detail.金额"],
        footer_field_ids=[],
        page=PagePlan(),
        confidence=1,
        assumptions=[],
        warnings=[],
        cell_options={
            "master.录单日期": {"prefix": "日期："},
            "detail.金额": {"formatKind": "number", "decimalPlaces": 0},
            "detail.商品全名": {"imageShowType": "scale-width"},
        },
    )
    template = NativeTemplateCompiler().compile(plan)
    cells = [
        cell
        for row in template["Pages"][0]["ReportElements"][0]["Rows"]
        for cell in row["Cells"]
    ]
    date_cell = next(cell for cell in cells if cell.get("CellText") == "@录单日期")
    amount_cell = next(cell for cell in cells if cell.get("CellText") == "#金额")
    product_cell = next(cell for cell in cells if cell.get("CellText") == "#商品全名")
    assert date_cell["PreTextFlag"] == "日期："
    assert amount_cell["FormatKind"] == 5
    assert amount_cell["Decimal"] == 0
    assert product_cell["ImageShowType"] == 1


def test_alignment_options_compile_to_native_properties():
    catalog = FieldCatalog.sales_default()
    plan = build_plan(
        catalog=catalog,
        title="销售单",
        master_field_ids=["master.录单日期"],
        detail_columns=[
            {
                "kind": "field",
                "fieldId": "detail.商品全名",
                "label": "商品全名",
                "widthWeight": 1.0,
            },
        ],
        total_field_ids=[],
        footer_field_ids=[],
        page=PagePlan(),
        confidence=1,
        assumptions=[],
        warnings=[],
        cell_options={"master.录单日期": {"horizontalAlign": "left"}},
        title_style=TextStylePlan(horizontal_align="left"),
    )

    template = NativeTemplateCompiler().compile(plan)
    cells = [
        cell
        for row in template["Pages"][0]["ReportElements"][0]["Rows"]
        for cell in row["Cells"]
    ]

    assert next(cell for cell in cells if cell.get("CellText") == "销售单")["HorzAlign"] == 0
    assert next(cell for cell in cells if cell.get("CellText") == "@录单日期")["HorzAlign"] == 0


def test_clone_base_preserves_layout_and_applies_only_cell_options():
    catalog, _, source = _compile_default()
    plan = RuleBasedPlanner().plan(
        "生成销售单模板，录单日期用中文日期，金额为0时不显示",
        catalog,
    ).plan
    plan.title_style = TextStylePlan(horizontal_align="left")
    next(item for item in plan.master_fields if item.bind_name == "录单日期").horizontal_align = "left"
    cloned = NativeTemplatePatcher().apply_cell_options(source, plan)
    assert content_hash(source) == content_hash(NativeTemplateCompiler().compile(_compile_default()[1]))
    assert cloned["Pages"][0]["Width"] == source["Pages"][0]["Width"]
    cells = [
        cell
        for row in cloned["Pages"][0]["ReportElements"][0]["Rows"]
        for cell in row["Cells"]
    ]
    assert next(cell for cell in cells if cell.get("CellText") == "销售单")["HorzAlign"] == 0
    assert next(cell for cell in cells if cell.get("CellText") == "@录单日期")["HorzAlign"] == 0
    assert next(cell for cell in cells if cell.get("CellText") == "@录单日期")["FormatKind"] == 3
    assert next(cell for cell in cells if cell.get("CellText") == "#金额")["DisplayEmptyForZero"] is True


def test_legacy_clone_accepts_native_auto_layout_but_strict_mode_rejects_it():
    catalog, _, source = _compile_default()
    source["ReportName"] = "销售单.rwx"
    catalog.report_name = "销售单.rwx"
    table = source["Pages"][0]["ReportElements"][0]
    table["Width"] = 0
    strict = NativeTemplateValidator().validate(source, catalog)
    compatible = NativeTemplateValidator().validate(source, catalog, allow_legacy_layout=True)
    assert strict.valid is False
    assert compatible.valid is True


def test_rule_planner_matches_native_rwx_report_name():
    catalog = FieldCatalog.sales_default()
    catalog.report_name = "销售单.rwx"
    plan = RuleBasedPlanner().plan("生成销售单测试模板", catalog).plan
    assert plan.report_name == "销售单.rwx"


def test_sequence_field_and_blank_compile_to_distinct_native_cells():
    catalog = FieldCatalog.sales_default()
    plan = build_plan(
        catalog=catalog,
        title="签收单",
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
    template = NativeTemplateCompiler().compile(plan)
    table = template["Pages"][0]["ReportElements"][0]
    header_index = next(
        index
        for index, row in enumerate(table["Rows"])
        if [cell.get("CellText", "") for cell in row["Cells"]]
        == ["序号", "商品详情", "签字"]
    )
    body = table["Rows"][header_index + 1]["Cells"]
    assert [cell.get("CellText", "") for cell in body] == ["#行号", "#商品全名", ""]
    assert extract_bindings(template)["detail"] == ["行号", "商品全名"]
    assert sum(cell["OrigWidth"] for cell in body) == table["Width"]


def test_style_requirements_reflow_rows_fonts_and_native_lines():
    catalog = FieldCatalog.sales_default()
    plan = build_default_delivery_plan(catalog)
    apply_deterministic_layout_requirements(
        "商品名称改成商品详情，删除第三列，行高变大一倍，外框加粗，"
        "内部细虚线，去掉竖线，表头大一号，内容小一点",
        plan,
    )
    plan.detail_tables[0].fields[1].label = "商品详情"
    plan.detail_tables[0].fields.pop(2)
    template = NativeTemplateCompiler().compile(plan)
    table = template["Pages"][0]["ReportElements"][0]
    header_index = next(
        index
        for index, row in enumerate(table["Rows"])
        if [cell.get("CellText", "") for cell in row["Cells"]] == ["序号", "商品详情"]
    )
    header = table["Rows"][header_index]
    body = table["Rows"][header_index + 1]
    assert {cell["OrigHeight"] for cell in header["Cells"]} == {53}
    assert {cell["OrigHeight"] for cell in body["Cells"]} == {53}
    assert {cell["FontSize"] for cell in header["Cells"]} == {11}
    assert {cell["FontSize"] for cell in body["Cells"]} == {8}
    assert header["Cells"][0]["TopLineWidth"] == 2
    assert header["Cells"][0]["BottomLineStyle"] == 1
    assert header["Cells"][0]["RightLine"] == 0
    assert header["Cells"][-1]["RightLineWidth"] == 2
    assert body["Top"] == header["Top"] + 53
    assert table["Height"] >= body["Top"] + 53 - table["Top"]

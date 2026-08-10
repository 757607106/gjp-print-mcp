import json

import pytest

from gjp_common.errors import DomainError
from yunprint.native import PX_PER_CM
from yunprint.reports import merge_report_data
from yunprint.service import TemplateAgentService
from tests.printing.helpers.live_templates import REPORT_FIXTURES, live_context
from tests.printing.helpers.rule_planner import RuleBasedPlanner
from tests.printing.helpers.test_service import generate_draft


def test_live_template_fixtures_build_report_contexts():
    assert list(REPORT_FIXTURES) == ["sales", "purchase", "payment", "sales-order", "inventory-status"]
    for slug, fixture in REPORT_FIXTURES.items():
        context = live_context(slug)
        assert context.profile.logical_name == fixture["logical_name"]
        assert context.base_hash
        assert len(context.base_template["Pages"]) >= 1
        assert context.catalog.fields


def test_partial_custom_paper_size_keeps_template_height():
    context = live_context("sales")
    setting = context.base_template["PageSetting"]
    page = context.base_template["Pages"][0]

    assert "PaperWidthUM" not in setting
    assert context.page.paper_name == "自定义纸张"
    assert context.page.width_cm == round(page["Width"] / PX_PER_CM, 1)
    assert context.page.height_cm == setting["PaperHeightUM"] / 100


def test_report_data_adds_authoritative_missing_field_without_values():
    context = live_context("payment")
    report_data = {
        "reportName": "付款单",
        "masterFields": [{"name": "核销人", "columnType": "String", "value": "绝不能保留的姓名"}],
        "gridList": [
            {
                "detailName": "付款明细",
                "detailFields": [{"name": "核销状态", "columnType": "String"}],
                "detailData": {"itemList": [{"核销状态": "绝不能保留的业务值"}]},
            }
        ],
    }
    merged = merge_report_data(context, report_data)
    assert merged.catalog.get("master.核销人").source == "report-data"
    assert merged.catalog.get("detail.核销状态").table_name == "付款明细"
    serialized = json.dumps(merged.catalog.model_payload(), ensure_ascii=False)
    assert "绝不能保留的姓名" not in serialized
    assert "绝不能保留的业务值" not in serialized

    planner = RuleBasedPlanner()
    service = TemplateAgentService(merged.catalog, report_context=merged)
    draft = generate_draft(service, planner, "生成付款单，只保留核销状态字段")
    assert draft.plan.strategy == "quick-table"
    assert draft.bindings["detail"] == ["核销状态"]


def test_report_data_accepts_data_field_and_data_type_aliases():
    context = live_context("sales")
    report_data = {
        "reportName": "销售单",
        "masterFields": [{"dataField": "送货地址", "dataType": "String", "value": "不得保留"}],
        "gridList": [
            {
                "detailName": "销售明细",
                "detailFields": [{"dataField": "税额", "dataType": "Money"}],
                "detailData": {"itemList": [{"税额": 12.34}]},
            }
        ],
    }
    merged = merge_report_data(context, report_data)
    assert merged.catalog.get("master.送货地址").data_type == "string"
    assert merged.catalog.get("detail.税额").data_type == "number"
    serialized = json.dumps(merged.catalog.model_payload(), ensure_ascii=False)
    assert "不得保留" not in serialized
    assert "12.34" not in serialized


def test_structural_selection_recompiles_instead_of_silently_cloning():
    context = live_context("payment")
    planner = RuleBasedPlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    draft = generate_draft(service, planner, "生成付款单，只保留金额和单据备注")
    assert draft.plan.strategy == "quick-table"
    assert len(draft.native_template["Pages"]) == 1
    assert "科目全名" not in draft.bindings["detail"]
    assert draft.execution_report.strategy == "quick-table-structure"


@pytest.mark.parametrize(
    ("slug", "logical_name", "native_name", "page_count"),
    [
        ("sales", "销售单", "销售单", 1),
        ("purchase", "进货单", "进货单.rwx", 1),
        ("payment", "付款单", "付款单.rwx", 2),
        ("sales-order", "销售订单", "销售订单.rwx", 1),
        ("inventory-status", "库存状况表", "库存状况表.rwx", 1),
    ],
)
def test_each_live_fixture_generates_from_its_own_template(slug, logical_name, native_name, page_count):
    context = live_context(slug)
    planner = RuleBasedPlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    draft = generate_draft(service, planner, "生成%s模板" % logical_name)
    assert draft.native_template["ReportName"] == native_name
    assert len(draft.native_template["Pages"]) == page_count
    assert draft.plan.strategy == "clone-base"


def test_explicit_unknown_field_is_rejected_instead_of_using_defaults():
    context = live_context("payment")
    planner = RuleBasedPlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    with pytest.raises(DomainError, match="字段目录"):
        generate_draft(service, planner, "生成付款单，只保留完全不存在字段")


def test_unsupported_layout_capability_is_rejected_before_planning():
    context = live_context("payment")
    planner = RuleBasedPlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    with pytest.raises(DomainError) as exc_info:
        generate_draft(service, planner, "生成付款单并增加柱状图")
    assert exc_info.value.code == "CAPABILITY_UNSUPPORTED"


def test_explicit_width_request_never_uses_attribute_only_clone():
    context = live_context("payment")
    planner = RuleBasedPlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    draft = generate_draft(service, planner, "生成付款单，金额列宽一点")
    assert draft.plan.strategy == "quick-table"
    assert draft.execution_report.strategy == "quick-table-structure"


def test_changed_title_is_compiled_instead_of_silently_ignored():
    class ChangedTitlePlanner:
        def plan(self, message, catalog, planning_context=None):
            envelope = RuleBasedPlanner().plan(message, catalog, planning_context)
            envelope.plan.title = "付款申请单"
            return envelope

    context = live_context("payment")
    planner = ChangedTitlePlanner()
    service = TemplateAgentService(context.catalog, report_context=context)
    draft = generate_draft(service, planner, "生成付款单，标题改为付款申请单")
    assert draft.plan.strategy == "quick-table"
    title_cell = draft.native_template["Pages"][0]["ReportElements"][0]["Rows"][0]["Cells"][0]
    assert title_cell["CellText"] == "付款申请单"

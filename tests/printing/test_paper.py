from tests.printing.helpers.rule_planner import RuleBasedPlanner
from yunprint.catalog import FieldCatalog


def test_a4_landscape_uses_deterministic_standard_dimensions():
    plan = RuleBasedPlanner().plan("生成销售单模板，改成A4横向", FieldCatalog.sales_default()).plan

    assert plan.page.paper_name == "A4"
    assert plan.page.orientation == "landscape"
    assert plan.page.width_cm == 29.7
    assert plan.page.height_cm == 21.0

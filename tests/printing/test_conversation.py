"""多轮模板状态的隔离与复制测试。"""

from gjp_common.context import InvocationContext
from yunprint.conversation import TemplateConversationStore


def _context(session_id: str) -> InvocationContext:
    return InvocationContext(
        tenant_id="tenant",
        subject_id="subject",
        account_id="account",
        session_id=session_id,
    )


def test_conversation_state_is_isolated_by_session_and_report():
    store = TemplateConversationStore()
    context_a = _context("session-a")
    context_b = _context("session-b")

    store.record_created(
        context_a,
        report_name="销售单",
        report_type=1,
        style_name="模板A",
        style_id="style-a",
    )

    assert store.current(context_a, "销售单")["styleId"] == "style-a"
    assert store.current(context_a, "采购单") is None
    assert store.current(context_b, "销售单") is None


def test_saved_template_uses_defensive_copies_and_increments_revision():
    store = TemplateConversationStore()
    context = _context("session-a")
    template = {"ReportName": "销售单", "Pages": [{"PageIndex": 0}]}

    first = store.record_saved(
        context,
        report_name="销售单",
        report_type=1,
        style_name="模板A",
        style_id="style-a",
        style_content=template,
    )
    template["Pages"][0]["PageIndex"] = 99
    first["styleContent"]["Pages"][0]["PageIndex"] = 88

    restored = store.current(context, "销售单")
    second = store.record_saved(
        context,
        report_name="销售单",
        report_type=1,
        style_name="模板A",
        style_id="style-a",
        style_content=restored["styleContent"],
    )

    assert restored["styleContent"]["Pages"][0]["PageIndex"] == 0
    assert restored["revision"] == 1
    assert second["revision"] == 2


def test_saving_another_style_starts_a_new_revision_sequence():
    store = TemplateConversationStore()
    context = _context("session-a")

    store.record_saved(
        context,
        report_name="销售单",
        report_type=1,
        style_name="模板A",
        style_id="style-a",
        style_content={"Pages": []},
    )
    current = store.record_saved(
        context,
        report_name="销售单",
        report_type=1,
        style_name="模板B",
        style_id="style-b",
        style_content={"Pages": [{"PageIndex": 0}]},
    )

    assert current["styleId"] == "style-b"
    assert current["revision"] == 1

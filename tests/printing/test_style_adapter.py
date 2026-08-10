"""模板样式 Adapter 动态凭据注入测试。"""

from __future__ import annotations

from gjp_common.connections import (
    BusinessApiCredential,
    TenantApiConnection,
)
from gjp_common.context import InvocationContext
from yunprint.adapters import YunPrintAccessTokenAdapter


class StaticConnectionProvider:
    def resolve(self, _context: InvocationContext) -> TenantApiConnection:
        return TenantApiConnection(
            product="print",
            base_url="https://example.test",
            credential=BusinessApiCredential(
                kind="business_token",
                value="dynamic-session-token",
            ),
        )


class RecordingRepository:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def new_style(self, *args):
        self.calls.append(("new_style", *args))
        return {"id": "style-1"}

    def save_style(self, *args):
        self.calls.append(("save_style", *args))
        return None


def test_adapter_injects_current_connection_token_into_style_writes():
    repository = RecordingRepository()
    adapter = YunPrintAccessTokenAdapter(
        StaticConnectionProvider(),
        repository_factory=lambda _base_url: repository,
    )
    context = InvocationContext(
        tenant_id="tenant",
        subject_id="subject",
        account_id="account",
    )
    template = {"ReportName": "销售单", "Pages": []}

    adapter.new_style(context, "销售单", 1, "图片还原模板")
    adapter.save_style(context, "销售单", 1, "图片还原模板", "style-1", template)

    assert repository.calls == [
        (
            "new_style",
            "dynamic-session-token",
            "销售单",
            1,
            "图片还原模板",
        ),
        (
            "save_style",
            "dynamic-session-token",
            "销售单",
            1,
            "图片还原模板",
            "style-1",
            template,
        ),
    ]

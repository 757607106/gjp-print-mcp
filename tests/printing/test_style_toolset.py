"""打印模板样式 MCP 工具测试。"""

from __future__ import annotations

import json
from typing import Any

from gjp_common.context import InvocationContext, InvocationContextStore
from yunprint.toolset import PRINT_MCP_TOOL_NAMES, PrintToolSet

REPORT_NAME = "销售单"


def _valid_template(report_name: str = REPORT_NAME) -> dict:
    """构造符合云打印原生格式的测试模板。"""
    return {
        "ReportName": report_name,
        "StyleType": "",
        "PageSetting": {"PrinterName": "默认打印机", "PaperName": "A4"},
        "Pages": [{
            "ClassName": "TTemplatePage",
            "Width": 794, "Height": 1123, "PageIndex": 0,
            "ReportElements": [],
            "GroupInfo": {},
            "OrderInfoList": [],
            "BandAreas": [
                {"ClassName": "TBandArea", "IsVisible": True, "BandKind": 1, "BandTop": 0, "BandHeight": 76},
                {"ClassName": "TBandArea", "IsVisible": False, "BandKind": 2, "BandTop": 76, "BandHeight": 100},
                {"ClassName": "TBandArea", "IsVisible": True, "BandKind": 3, "BandTop": 76, "BandHeight": 971},
                {"ClassName": "TBandArea", "IsVisible": False, "BandKind": 4, "BandTop": 1047, "BandHeight": 100},
                {"ClassName": "TBandArea", "IsVisible": True, "BandKind": 5, "BandTop": 1047, "BandHeight": 76},
            ],
        }],
        "ExpressionFields": [],
        "IsWebPrint": True,
    }


class FakePrintApi:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    async def get_print_info(self, context, report_name: str, report_type: int) -> dict:
        self.calls.append(("get_print_info", context, report_name, report_type))
        return {
            "styleInfo": {
                "styleNames": [
                    {
                        "label": "系统样式",
                        "value": "style-1",
                        "styleObj": {"isBaseStyle": True},
                    }
                ]
            }
        }

    async def new_style(
        self,
        context,
        report_name: str,
        report_type: int,
        style_name: str,
    ) -> dict:
        self.calls.append(("new_style", context, report_name, report_type, style_name))
        return {
            "id": "2086707921336647680",
            "reportName": report_name,
            "reportType": report_type,
            "styleName": style_name,
        }

    async def save_style(
        self,
        context,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict,
    ) -> dict:
        self.calls.append(
            (
                "save_style",
                context,
                report_name,
                report_type,
                style_name,
                style_id,
                style_content,
            )
        )
        return {"saved": True}


def _toolset(*scopes: str) -> tuple[PrintToolSet, FakePrintApi]:
    context = InvocationContext(
        tenant_id="tenant",
        subject_id="subject",
        account_id="account",
        scopes=frozenset(scopes),
    )
    api = FakePrintApi()
    return (
        PrintToolSet(
            api=api,
            contexts=InvocationContextStore(default=context),
            report_name_resolver=lambda _ctx: REPORT_NAME,
        ),
        api,
    )


def test_style_tools_are_published_without_token_or_report_name():
    toolset, _ = _toolset("print:read", "print:write")

    assert PRINT_MCP_TOOL_NAMES == {"getPrintInfo", "newStyle", "saveStyle"}
    exported = {tool.name: tool for tool in toolset.executable_tools()}
    for name in ("getPrintInfo", "newStyle", "saveStyle"):
        schema_text = json.dumps(exported[name].input_schema).casefold()
        assert "token" not in schema_text
        assert "report_name" not in schema_text

    assert set(exported["getPrintInfo"].input_schema["properties"]) == set()
    assert set(exported["saveStyle"].input_schema["required"]) == {
        "report_type",
        "style_name",
        "style_id",
        "style_content",
    }


async def test_get_print_info_uses_header_report_name():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.get_print_info()

    assert result["ok"] is True
    assert result["reportType"] == 1
    assert result["reportName"] == REPORT_NAME
    assert result["currentStyle"] is None
    assert result["styles"][0] == {
        "id": "style-1",
        "name": "系统样式",
        "isBaseStyle": True,
        "order": 0,
        "raw": {
            "label": "系统样式",
            "value": "style-1",
            "styleObj": {"isBaseStyle": True},
        },
    }
    assert api.calls[0][2:] == (REPORT_NAME, 1)


async def test_new_style_returns_values_required_by_save_style():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.new_style("1", " 图片还原模板 ")

    assert result == {
        "ok": True,
        "message": "打印模板样式已创建，请继续调用 saveStyle 保存模板内容",
        "styleId": "2086707921336647680",
        "reportName": REPORT_NAME,
        "reportType": 1,
        "styleName": "图片还原模板",
        "revision": 0,
    }
    assert api.calls[0][2:] == (REPORT_NAME, 1, "图片还原模板")


async def test_new_style_requires_write_scope():
    toolset, api = _toolset("print:read")

    result = await toolset.new_style(1, "图片还原模板")

    assert result["ok"] is False
    assert result["error"]["code"] == "CAPABILITY_FORBIDDEN"
    assert api.calls == []


async def test_save_style_passes_native_template_object():
    toolset, api = _toolset("print:read", "print:write")
    template = _valid_template()

    result = await toolset.save_style(
        1,
        "图片还原模板",
        "2086707921336647680",
        template,
    )

    assert result["ok"] is True
    assert result["styleId"] == "2086707921336647680"
    assert result["revision"] == 1
    assert result["apiResult"] == {"saved": True}
    assert api.calls[0][2:] == (
        REPORT_NAME,
        1,
        "图片还原模板",
        "2086707921336647680",
        template,
    )


async def test_save_style_rejects_empty_template_before_remote_call():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.save_style(1, "图片还原模板", "style-1", {})

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert api.calls == []


async def test_save_style_rejects_non_native_format():
    """拒绝 version/components 等自定义格式。"""
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.save_style(1, "图片还原模板", "style-1", {
        "version": "1.0.0",
        "page": {"width": 210, "height": 297},
        "components": [{"type": "text", "content": "标题"}],
    })

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "ReportName" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_rejects_missing_pages():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.save_style(1, "图片还原模板", "style-1", {
        "ReportName": REPORT_NAME,
    })

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "Pages" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_rejects_page_without_classname():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.save_style(1, "图片还原模板", "style-1", {
        "ReportName": REPORT_NAME,
        "Pages": [{"BandAreas": []}],
    })

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "ClassName" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_rejects_page_without_bandareas():
    toolset, api = _toolset("print:read", "print:write")

    result = await toolset.save_style(1, "图片还原模板", "style-1", {
        "ReportName": REPORT_NAME,
        "Pages": [{"ClassName": "TTemplatePage"}],
    })

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "BandAreas" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_rejects_multiple_tables_per_page():
    """拒绝单页面包含多个 TTableElement 表格元素。"""
    toolset, api = _toolset("print:read", "print:write")
    template = _valid_template()
    template["Pages"][0]["ReportElements"] = [
        {"ClassName": "TTableElement", "Rows": []},
        {"ClassName": "TTableElement", "Rows": []},
    ]

    result = await toolset.save_style(1, "图片还原模板", "style-1", template)

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "TTableElement" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_rejects_template_without_field_bindings():
    """拒绝有表格行但无字段绑定（@/#/^）的模板，防止固化数据值。"""
    toolset, api = _toolset("print:read", "print:write")
    template = _valid_template()
    template["Pages"][0]["ReportElements"] = [{
        "ClassName": "TTableElement",
        "Rows": [
            {"Cells": [{"CellText": "报价单位：小简有限公司"}, {"CellText": "1"}]},
        ],
    }]

    result = await toolset.save_style(1, "报价单", "style-1", template)

    assert result["ok"] is False
    assert result["error"]["code"] == "STYLE_CONTENT_INVALID"
    assert "字段绑定" in result["error"]["message"]
    assert api.calls == []


async def test_save_style_accepts_template_with_field_bindings():
    """有字段绑定（@/#/^）的模板通过校验。"""
    toolset, api = _toolset("print:read", "print:write")
    template = _valid_template()
    template["Pages"][0]["ReportElements"] = [{
        "ClassName": "TTableElement",
        "Rows": [
            {"Cells": [{"CellText": "公司全名"}, {"CellText": "@公司全名"}]},
        ],
    }]

    result = await toolset.save_style(1, "报价单", "style-1", template)

    assert result["ok"] is True
    assert api.calls != []


async def test_multi_turn_edit_restores_latest_template_and_reuses_style_id():
    toolset, _api = _toolset("print:read", "print:write")
    style_id = "2086707921336647680"
    first_template = _valid_template()
    edited_template = _valid_template()

    created = await toolset.new_style(1, "图片还原模板")
    first_saved = await toolset.save_style(
        created["reportType"],
        created["styleName"],
        created["styleId"],
        first_template,
    )
    first_info = await toolset.get_print_info()
    second_saved = await toolset.save_style(
        first_info["currentStyle"]["reportType"],
        first_info["currentStyle"]["styleName"],
        first_info["currentStyle"]["styleId"],
        edited_template,
    )
    second_info = await toolset.get_print_info()

    assert created["styleId"] == style_id
    assert first_saved["revision"] == 1
    assert first_info["currentStyle"]["styleContent"] == first_template
    assert second_saved["styleId"] == style_id
    assert second_saved["revision"] == 2
    assert second_info["currentStyle"] == {
        "reportName": REPORT_NAME,
        "reportType": 1,
        "styleName": "图片还原模板",
        "styleId": style_id,
        "revision": 2,
        "hasContent": True,
        "styleContent": edited_template,
    }

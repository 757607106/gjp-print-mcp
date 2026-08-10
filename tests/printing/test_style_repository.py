"""模板样式业务 API 请求契约测试。"""

from __future__ import annotations

import json
from typing import Any

import pytest

from gjp_common.errors import DomainError
from yunprint.repository import YunPrintRepository


def test_repository_requires_https():
    with pytest.raises(DomainError):
        YunPrintRepository("http://example.test")


def test_get_print_info_uses_complete_style_payload(monkeypatch: pytest.MonkeyPatch):
    repository = YunPrintRepository("https://example.test")
    captured: dict[str, Any] = {}

    def fake_post(path: str, payload: dict[str, Any], *, allow_retries: bool = True):
        captured.update(path=path, payload=payload, allow_retries=allow_retries)
        return {"styleInfo": {"styleNames": []}}

    monkeypatch.setattr(repository, "_post_result", fake_post)

    result = repository.get_print_info("secret-token", "销售单", 1)

    assert result == {"styleInfo": {"styleNames": []}}
    assert captured == {
        "path": "ElectronPrintApi/GetPrintInfo",
        "payload": {
            "token": "secret-token",
            "reportName": "销售单",
            "reportType": 1,
            "styleName": "",
            "styleId": "",
            "styleContent": "",
            "isDynamicBaseStyle": "",
            "baseStyleContent": "",
            "isPublic": False,
        },
        "allow_retries": True,
    }


def test_new_style_uses_non_retrying_write_contract(monkeypatch: pytest.MonkeyPatch):
    repository = YunPrintRepository("https://example.test")
    captured: dict[str, Any] = {}
    created = {
        "id": "2086707921336647680",
        "reportName": "销售单",
        "reportType": 1,
        "styleName": "图片还原模板",
    }

    def fake_post(path: str, payload: dict[str, Any], *, allow_retries: bool = True):
        captured.update(path=path, payload=payload, allow_retries=allow_retries)
        return created

    monkeypatch.setattr(repository, "_post_result", fake_post)

    assert repository.new_style("secret-token", "销售单", 1, "图片还原模板") == created
    assert captured["path"] == "ElectronPrintApi/NewStyle"
    assert captured["allow_retries"] is False
    assert captured["payload"] == {
        "token": "secret-token",
        "reportName": "销售单",
        "reportType": 1,
        "styleName": "图片还原模板",
        "styleId": "",
        "styleContent": "",
        "isDynamicBaseStyle": "",
        "baseStyleContent": "",
        "isPublic": False,
    }


def test_new_style_requires_returned_template_id(monkeypatch: pytest.MonkeyPatch):
    repository = YunPrintRepository("https://example.test")
    monkeypatch.setattr(
        repository,
        "_post_result",
        lambda *_args, **_kwargs: {"styleName": "缺少 ID"},
    )

    with pytest.raises(DomainError) as exc:
        repository.new_style("secret-token", "销售单", 1, "缺少 ID")

    assert exc.value.code == "YUNPRINT_RESPONSE_INVALID"


def test_save_style_serializes_template_and_disables_retries(monkeypatch: pytest.MonkeyPatch):
    repository = YunPrintRepository("https://example.test")
    captured: dict[str, Any] = {}
    template = {"ReportName": "销售单", "Pages": [{"PageIndex": 0}]}

    def fake_post(path: str, payload: dict[str, Any], *, allow_retries: bool = True):
        captured.update(path=path, payload=payload, allow_retries=allow_retries)
        return {"saved": True}

    monkeypatch.setattr(repository, "_post_result", fake_post)

    result = repository.save_style(
        "secret-token",
        "销售单",
        1,
        "图片还原模板",
        "2086707921336647680",
        template,
    )

    assert result == {"saved": True}
    assert captured["path"] == "ElectronPrintApi/SaveStyle"
    assert captured["allow_retries"] is False
    payload = captured["payload"]
    assert json.loads(payload["styleContent"]) == template
    assert payload | {"styleContent": "<content>"} == {
        "token": "secret-token",
        "reportName": "销售单",
        "reportType": 1,
        "styleName": "图片还原模板",
        "styleId": "2086707921336647680",
        "styleContent": "<content>",
        "isDynamicBaseStyle": "",
        "baseStyleContent": "",
        "isPublic": False,
    }


def test_debug_payload_redacts_token_and_template_content():
    safe = YunPrintRepository._safe_log_payload(
        {"token": "secret-token", "styleContent": "{\"Pages\":[]}"}
    )

    assert safe == {
        "token": "<redacted>",
        "styleContent": "<omitted:12 chars>",
    }

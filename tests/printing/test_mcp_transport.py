"""Streamable HTTP 会话与工具发布的端到端测试。"""

from urllib.parse import quote

from mcp.types import LATEST_PROTOCOL_VERSION
from starlette.testclient import TestClient

from yunprint.app import create_print_app


def test_streamable_http_issues_session_and_only_lists_three_tools(monkeypatch):
    """token 和 reportName 都由请求头注入，工具参数不含两者。"""
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    headers = {
        "Authorization": "Bearer test-token",
        "X-Report-Name": quote("销售单"),
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": LATEST_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1.0"},
        },
    }

    with TestClient(create_print_app()) as client:
        initialized = client.post("/mcp", headers=headers, json=initialize)
        assert initialized.status_code == 200
        session_id = initialized.headers["mcp-session-id"]
        session_headers = {**headers, "Mcp-Session-Id": session_id}

        notification = client.post(
            "/mcp",
            headers=session_headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
                "params": {},
            },
        )
        assert notification.status_code == 202

        response = client.post(
            "/mcp",
            headers=session_headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 200
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert tool_names == {"get_print_info", "new_style", "save_style"}

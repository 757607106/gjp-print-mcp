"""yunprint.app 对外入口的身份解析与 Bearer 连接存储测试。

云打印令牌是 opaque 字符串（非 JWT），服务端不解析结构，直接注入业务 API。
reportName 由 X-Report-Name 头传入，与 token 一样不进入工具参数。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from gjp_common.context import InvocationContextStore
from gjp_common.errors import DomainError
from gjp_common.mcp import StaticToolSetResolver
from yunprint.adapters import YunPrintAccessTokenAdapter
from yunprint.app import (
    BearerConnectionStore,
    OpaqueTokenIdentityResolver,
    _bearer_token_from_mcp_context,
    _context_from_token,
    _mcp_session_hint,
    _report_name_from_mcp_context,
)
from yunprint.toolset import PrintToolSet


def _mcp_request(
    authorization: str | None = None,
    session_id: str | None = None,
    report_name: str | None = None,
) -> SimpleNamespace:
    headers: dict[str, str] = {}
    if authorization is not None:
        headers["authorization"] = authorization
    if session_id is not None:
        headers["mcp-session-id"] = session_id
    if report_name is not None:
        headers["x-report-name"] = report_name
    return SimpleNamespace(request=SimpleNamespace(headers=headers))


# --- opaque token 上下文派生 ---


def test_context_from_token_fixed_identity():
    context = _context_from_token("382b2a49dcaea837")
    assert context.tenant_id == "local"
    assert context.subject_id == "local"
    assert context.account_id == "local"
    assert context.session_id.startswith("print-")
    assert "print:read" in context.scopes
    assert "print:write" in context.scopes


def test_context_from_token_isolates_sessions():
    ctx_a = _context_from_token("token-a")
    ctx_b = _context_from_token("token-b")
    assert ctx_a.session_id != ctx_b.session_id
    assert _context_from_token("token-a").session_id == ctx_a.session_id


def test_context_from_same_token_isolates_mcp_sessions():
    ctx_a = _context_from_token("token-a", "conversation-a")
    ctx_b = _context_from_token("token-a", "conversation-b")

    assert ctx_a.session_id != ctx_b.session_id
    assert _context_from_token("token-a", "conversation-a") == ctx_a


def test_mcp_session_hint_reads_standard_header():
    assert (
        _mcp_session_hint(_mcp_request("Bearer token", "mcp-session-a"))
        == "mcp-session-a"
    )
    assert _mcp_session_hint(_mcp_request("Bearer token")) == ""


# --- X-Report-Name 头解析 ---


def test_report_name_from_mcp_context_reads_header():
    assert (
        _report_name_from_mcp_context(
            _mcp_request("Bearer token", report_name="销售单")
        )
        == "销售单"
    )
    assert _report_name_from_mcp_context(_mcp_request("Bearer token")) == ""


def test_report_name_from_mcp_context_strips_whitespace():
    assert (
        _report_name_from_mcp_context(
            _mcp_request("Bearer token", report_name="  销售单  ")
        )
        == "销售单"
    )


def test_report_name_decodes_single_url_encoded_header():
    from urllib.parse import quote

    encoded = quote("销售单")
    assert (
        _report_name_from_mcp_context(
            _mcp_request("Bearer token", report_name=encoded)
        )
        == "销售单"
    )


# --- Bearer 头解析 ---


def test_bearer_token_missing_header():
    with pytest.raises(DomainError) as exc:
        _bearer_token_from_mcp_context(_mcp_request(None))
    assert exc.value.code == "MCP_UNAUTHORIZED"


def test_bearer_token_non_bearer_scheme():
    with pytest.raises(DomainError) as exc:
        _bearer_token_from_mcp_context(_mcp_request("Basic abc"))
    assert exc.value.code == "MCP_UNAUTHORIZED"


def test_bearer_token_empty_value():
    with pytest.raises(DomainError) as exc:
        _bearer_token_from_mcp_context(_mcp_request("Bearer "))
    assert exc.value.code == "MCP_UNAUTHORIZED"


def test_bearer_token_returns_token():
    token = _bearer_token_from_mcp_context(_mcp_request("Bearer 382b2a49dcaea837"))
    assert token == "382b2a49dcaea837"


# --- OpaqueTokenIdentityResolver ---


def test_opaque_resolver_registers_bearer_and_report_name(monkeypatch):
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    store = BearerConnectionStore()
    resolver = OpaqueTokenIdentityResolver(store)

    context = resolver.resolve(
        _mcp_request("Bearer 382b2a49dcaea837", report_name="销售单")
    )

    assert context.tenant_id == "local"
    connection = store.resolve(context)
    assert connection.credential.value == "382b2a49dcaea837"
    assert store.get_report_name(context) == "销售单"


def test_opaque_resolver_separates_same_token_mcp_sessions(monkeypatch):
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    store = BearerConnectionStore()
    resolver = OpaqueTokenIdentityResolver(store)

    context_a = resolver.resolve(
        _mcp_request("Bearer shared-token", "session-a", report_name="销售单")
    )
    context_b = resolver.resolve(
        _mcp_request("Bearer shared-token", "session-b", report_name="采购单")
    )

    assert context_a.session_id != context_b.session_id
    assert store.resolve(context_a).credential.value == "shared-token"
    assert store.resolve(context_b).credential.value == "shared-token"
    assert store.get_report_name(context_a) == "销售单"
    assert store.get_report_name(context_b) == "采购单"


def test_opaque_resolver_isolates_account_tokens_even_with_same_session_hint(
    monkeypatch,
):
    """多账号对接中，同名 MCP 会话不得导致 Token 串用。"""
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    store = BearerConnectionStore()
    resolver = OpaqueTokenIdentityResolver(store)

    context_a = resolver.resolve(
        _mcp_request("Bearer account-token-a", "session-1", report_name="销售单")
    )
    context_b = resolver.resolve(
        _mcp_request("Bearer account-token-b", "session-1", report_name="采购单")
    )

    assert context_a.session_id != context_b.session_id
    assert store.resolve(context_a).credential.value == "account-token-a"
    assert store.resolve(context_b).credential.value == "account-token-b"
    assert store.get_report_name(context_a) == "销售单"
    assert store.get_report_name(context_b) == "采购单"


def test_opaque_resolver_missing_authorization():
    store = BearerConnectionStore()
    resolver = OpaqueTokenIdentityResolver(store)
    with pytest.raises(DomainError) as exc:
        resolver.resolve(_mcp_request(None))
    assert exc.value.code == "MCP_UNAUTHORIZED"


def test_opaque_resolver_handles_missing_report_name(monkeypatch):
    """未传 X-Report-Name 时 reportName 为空字符串，由工具层校验。"""
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    store = BearerConnectionStore()
    resolver = OpaqueTokenIdentityResolver(store)

    context = resolver.resolve(_mcp_request("Bearer token-only"))

    assert store.get_report_name(context) == ""


# --- BearerConnectionStore ---


def test_store_resolve_missing_bearer():
    store = BearerConnectionStore()
    context = _context_from_token("382b2a49dcaea837")
    with pytest.raises(DomainError) as exc:
        store.resolve(context)
    assert exc.value.code == "BUSINESS_CREDENTIAL_REQUIRED"


def test_store_resolve_missing_base_url(monkeypatch):
    monkeypatch.delenv("YUNPRINT_BASE_URL", raising=False)
    store = BearerConnectionStore()
    token = "382b2a49dcaea837"
    context = _context_from_token(token)
    store.register(context, token)
    with pytest.raises(DomainError) as exc:
        store.resolve(context)
    assert exc.value.code == "BUSINESS_CONNECTION_INVALID"


def test_store_get_report_name_empty_when_not_registered():
    store = BearerConnectionStore()
    context = _context_from_token("token")
    assert store.get_report_name(context) == ""


# --- StaticToolSetResolver 单实例复用 ---


def test_static_toolset_resolver_returns_same_instance(monkeypatch):
    """消除双重实例化后，schema 与 runtime 共用同一 PrintToolSet。"""
    monkeypatch.setenv("YUNPRINT_BASE_URL", "https://example.test")
    store = BearerConnectionStore()
    toolset = PrintToolSet(
        api=YunPrintAccessTokenAdapter(connection_provider=store),
        contexts=InvocationContextStore(),
        report_name_resolver=store.get_report_name,
    )
    resolver = StaticToolSetResolver(toolset)

    ctx_a = _context_from_token("token-a")
    ctx_b = _context_from_token("token-b")

    assert resolver.resolve(ctx_a) is toolset
    assert resolver.resolve(ctx_b) is toolset

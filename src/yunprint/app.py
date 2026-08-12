"""对外打印 MCP 服务入口。

MCP 客户端在 Authorization 头传云打印访问令牌（opaque token），在
X-Report-Name 头传报表分类名称。两者均由对接方按入口动态传入，不进入
工具参数。服务端不解析令牌结构，直接注入业务 API 调用。

身份用固定 local 上下文，session_id 优先由 MCP 会话标识与令牌哈希派生。
base_url 部署级固定（YUNPRINT_BASE_URL）。

运行方式：

    export YUNPRINT_BASE_URL=https://yunprint.gmgrasp.com.cn
    uv run uvicorn yunprint.app:app --host 0.0.0.0 --port 8931 --workers 1
"""

from __future__ import annotations

import hashlib
import logging
import threading
from urllib.parse import unquote
from typing import Any, Callable

from gjp_common.config import get_env_value
from gjp_common.connections import BusinessApiCredential, TenantApiConnection
from gjp_common.context import InvocationContext, InvocationContextStore
from gjp_common.errors import DomainError
from gjp_common.logging_config import configure_logging

from .adapters import UnavailablePrintApi, YunPrintAccessTokenAdapter
from .mcp_service import create_print_mcp_service
from .toolset import PrintToolSet

logger = logging.getLogger(__name__)


def _bearer_token_from_mcp_context(mcp_request_context: Any) -> str:
    """从 MCP HTTP 请求头读取 Bearer Token。"""
    request = getattr(mcp_request_context, "request", None)
    headers = getattr(request, "headers", None)
    authorization = headers.get("authorization", "") if headers is not None else ""
    if not authorization:
        raise DomainError("MCP_UNAUTHORIZED", "缺少 Authorization: Bearer <token>")
    scheme, _, token = authorization.partition(" ")
    if scheme.casefold() != "bearer" or not token.strip():
        raise DomainError("MCP_UNAUTHORIZED", "Authorization 必须使用 Bearer token")
    return token.strip()


def _report_name_from_mcp_context(mcp_request_context: Any) -> str:
    """从 MCP HTTP 请求头读取 X-Report-Name（URL 解码）。

    HTTP 头不支持非 ASCII 字符，对接方需对 reportName 做 URL 编码。
    """
    request = getattr(mcp_request_context, "request", None)
    headers = getattr(request, "headers", None)
    raw = headers.get("x-report-name", "").strip() if headers is not None else ""
    return unquote(raw) if raw else ""


def _mcp_session_hint(mcp_request_context: Any) -> str:
    """读取 Streamable HTTP 标准 Mcp-Session-Id。"""
    request = getattr(mcp_request_context, "request", None)
    headers = getattr(request, "headers", None)
    return headers.get("mcp-session-id", "").strip() if headers is not None else ""


def _context_from_token(token: str, session_hint: str = "") -> InvocationContext:
    """从 opaque token 派生无凭据的调用上下文。"""
    session_material = token if not session_hint else token + "\0" + session_hint
    digest = hashlib.sha256(session_material.encode("utf-8")).hexdigest()[:16]
    return InvocationContext(
        tenant_id="local",
        subject_id="local",
        account_id="local",
        session_id="print-" + digest,
        scopes=frozenset({"print:read", "print:write"}),
    )


class BearerConnectionStore:
    """按调用身份保存当前 MCP Bearer 和 reportName。

    Bearer 和 reportName 只存在于服务端内存，不进入 InvocationContext、Tool
    Schema 或模型上下文；单进程装配使用，多副本部署应替换为共享会话存储。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._bearers: dict[tuple[str, str, str], str] = {}
        self._report_names: dict[tuple[str, str, str], str] = {}

    @staticmethod
    def _key(context: InvocationContext) -> tuple[str, str, str]:
        return (context.tenant_id, context.account_id, context.session_id)

    def register(
        self,
        context: InvocationContext,
        bearer: str,
        report_name: str = "",
    ) -> None:
        with self._lock:
            self._bearers[self._key(context)] = bearer
            if report_name:
                self._report_names[self._key(context)] = report_name

    def resolve(self, context: InvocationContext) -> TenantApiConnection:
        with self._lock:
            bearer = self._bearers.get(self._key(context), "")
        if not bearer:
            raise DomainError("BUSINESS_CREDENTIAL_REQUIRED", "当前会话缺少云打印 Bearer")
        base_url = get_env_value("YUNPRINT_BASE_URL").strip()
        if not base_url:
            raise DomainError("BUSINESS_CONNECTION_INVALID", "未配置 YUNPRINT_BASE_URL")
        return TenantApiConnection(
            product="print",
            base_url=base_url,
            credential=BusinessApiCredential(kind="business_token", value=bearer),
        )

    def get_report_name(self, context: InvocationContext) -> str:
        """返回当前会话的 reportName，由 MCP 请求头注入。"""
        with self._lock:
            return self._report_names.get(self._key(context), "")


class OpaqueTokenIdentityResolver:
    """把 Authorization 头的 token 和 X-Report-Name 头映射为调用上下文。

    不解析令牌结构、不验签；令牌有效性由云打印 API 自身验证。reportName
    由对接方按入口动态传入，存入会话存储供工具读取。
    """

    def __init__(self, store: BearerConnectionStore) -> None:
        self._store = store

    def resolve(self, mcp_request_context: Any) -> InvocationContext:
        token = _bearer_token_from_mcp_context(mcp_request_context)
        report_name = _report_name_from_mcp_context(mcp_request_context)
        context = _context_from_token(token, _mcp_session_hint(mcp_request_context))
        context.require_scope("print:read")
        self._store.register(context, token, report_name)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "MCP 身份解析注入 reportName=%s token=%s",
                report_name or "<空>",
                token,
            )
        return context


class PrintToolSetResolver:
    """返回共享多轮编辑状态的三个模板样式工具。"""

    def __init__(
        self,
        store: BearerConnectionStore,
        *,
        timeout_seconds: float = 30,
    ) -> None:
        self._toolset = PrintToolSet(
            api=YunPrintAccessTokenAdapter(
                connection_provider=store,
                timeout_seconds=timeout_seconds,
            ),
            contexts=InvocationContextStore(),
            report_name_resolver=store.get_report_name,
        )

    def resolve(self, _context: InvocationContext) -> PrintToolSet:
        return self._toolset


class _LazyPrintApp:
    """让 uvicorn 导入模块时不立即读取部署配置。"""

    def __init__(self, factory: Callable[[], Any]) -> None:
        self._factory = factory
        self._app: Any | None = None

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if self._app is None:
            self._app = self._factory()
        await self._app(scope, receive, send)


def create_print_app() -> Any:
    """装配固定云打印 URL、opaque 令牌身份解析的打印 MCP 应用。"""
    configure_logging()
    timeout_seconds = float(get_env_value("YUNPRINT_TIMEOUT_SECONDS", "30") or 30)
    if timeout_seconds <= 0:
        raise DomainError("BUSINESS_CONNECTION_INVALID", "超时时间必须大于 0")

    store = BearerConnectionStore()
    schema_toolset = PrintToolSet(
        api=UnavailablePrintApi(),
        contexts=InvocationContextStore(),
    )
    return create_print_mcp_service(
        schema_toolset=schema_toolset,
        identity_resolver=OpaqueTokenIdentityResolver(store),
        toolset_resolver=PrintToolSetResolver(
            store,
            timeout_seconds=timeout_seconds,
        ),
    )


app = _LazyPrintApp(create_print_app)

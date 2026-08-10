"""服务端租户业务连接。

业务系统地址和鉴权材料由 SaaS 后端在会话建立阶段提供。它们只在服务端
Provider、Adapter 和 HTTP 执行器之间传递，不属于 InvocationContext、模型输入
或 Tool JSON Schema。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

from .context import InvocationContext
from .errors import DomainError


CredentialKind = Literal["business_token", "bearer", "cookie"]
ProductKind = Literal["print"]


def normalize_business_api_base_url(value: str) -> str:
    """校验并规范化服务端登记的租户业务 API 地址。"""
    normalized = value.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DomainError("BUSINESS_CONNECTION_INVALID", "业务 API 地址必须是有效的 HTTPS 地址")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise DomainError(
            "BUSINESS_CONNECTION_INVALID",
            "业务 API 地址不能包含用户信息、查询参数或片段",
        )
    return normalized


@dataclass(frozen=True, repr=False)
class BusinessApiCredential:
    """一次业务 API 会话使用的服务端凭据；repr 永远不输出秘密值。"""

    kind: CredentialKind
    value: str

    def __post_init__(self) -> None:
        if self.kind not in {"business_token", "bearer", "cookie"}:
            raise DomainError("BUSINESS_CREDENTIAL_INVALID", "不支持的业务 API 鉴权类型")
        if not self.value.strip():
            raise DomainError("BUSINESS_CREDENTIAL_REQUIRED", "业务端未提供当前会话的鉴权信息")

    def __repr__(self) -> str:
        return "BusinessApiCredential(kind=%r, value=<redacted>)" % self.kind


@dataclass(frozen=True, repr=False)
class TenantApiConnection:
    """当前租户会话对应的业务 API 地址与鉴权材料。"""

    product: ProductKind
    base_url: str
    credential: BusinessApiCredential

    def __post_init__(self) -> None:
        if self.product != "print":
            raise DomainError("BUSINESS_CONNECTION_INVALID", "业务连接产品类型无效")
        object.__setattr__(
            self,
            "base_url",
            normalize_business_api_base_url(self.base_url),
        )

    def require_product(self, product: ProductKind) -> None:
        if self.product != product:
            raise DomainError("BUSINESS_CONNECTION_MISMATCH", "当前会话绑定了其他产品的业务连接")

    def url_for(self, path: str) -> str:
        """只允许 Adapter 提供固定相对路径，禁止任意完整 URL。"""
        normalized = path.strip()
        if (
            not normalized.startswith("/")
            or normalized.startswith("//")
            or "?" in normalized
            or "#" in normalized
            or "://" in normalized
        ):
            raise DomainError("BUSINESS_API_PATH_INVALID", "业务 API 路径无效")
        return self.base_url + normalized

    def __repr__(self) -> str:
        return (
            "TenantApiConnection(product=%r, base_url=%r, credential=<redacted>)"
            % (self.product, self.base_url)
        )


class TenantApiConnectionProvider(Protocol):
    """由 SaaS 会话存储实现的业务连接解析入口。"""

    def resolve(self, context: InvocationContext) -> TenantApiConnection:
        ...

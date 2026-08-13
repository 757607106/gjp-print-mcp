"""云打印三个模板样式 API 的异步 HTTP 客户端。"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

import httpx

from gjp_common.errors import DomainError
from gjp_common.logging_config import (
    clip_log_text,
    elapsed_ms,
)


logger = logging.getLogger(__name__)


class YunPrintRepository:
    """只访问 GetPrintInfo、NewStyle 和 SaveStyle。"""

    def __init__(self, base_url: str, timeout_seconds: float = 30, max_retries: int = 3):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        if not self.base_url.startswith("https://"):
            raise DomainError("YUNPRINT_CONFIG_INVALID", "云打印地址必须使用 HTTPS")

    async def _post_result(
        self,
        path: str,
        payload: dict[str, Any],
        *,
        allow_retries: bool = True,
    ) -> Any:
        """发送 POST 请求并解析云打印业务信封，支持异步重试。"""
        started = time.perf_counter()
        url = self.base_url + "/" + path.lstrip("/")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        logger.info("云打印接口请求开始 api=%s", path)
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "云打印接口请求 method=POST url=%s headers=%s body=%s",
                url,
                json.dumps(headers, ensure_ascii=False),
                clip_log_text(
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        max_attempts = self.max_retries if allow_retries else 1
        body: dict[str, Any] | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                    response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                body = response.json()
                break
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status >= 500 and attempt < max_attempts:
                    logger.warning(
                        "云打印接口HTTP %d，第%d次重试 api=%s",
                        status,
                        attempt,
                        path,
                    )
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                logger.error("云打印接口HTTP失败 api=%s status=%s", path, status)
                raise DomainError(
                    "YUNPRINT_REQUEST_FAILED",
                    "云打印接口返回 HTTP %s" % status,
                ) from exc
            except (httpx.TimeoutException, httpx.ConnectError, httpx.ReadError) as exc:
                if attempt < max_attempts:
                    logger.warning(
                        "云打印接口网络失败，第%d次重试 api=%s",
                        attempt,
                        path,
                    )
                    await asyncio.sleep(0.5 * (2 ** (attempt - 1)))
                    continue
                logger.error("云打印接口网络失败 api=%s", path)
                raise DomainError(
                    "YUNPRINT_REQUEST_FAILED",
                    "云打印接口网络不可用或超时",
                ) from exc
            except json.JSONDecodeError as exc:
                logger.error("云打印接口响应解析失败 api=%s", path)
                raise DomainError(
                    "YUNPRINT_RESPONSE_INVALID",
                    "云打印接口返回的不是 JSON",
                ) from exc

        assert body is not None
        result = body.get("result") if isinstance(body, dict) else None
        if not isinstance(result, dict) or not isinstance(result.get("success"), bool):
            raise DomainError("YUNPRINT_RESPONSE_INVALID", "云打印接口响应信封无效")
        if not result["success"]:
            logger.error("云打印接口业务失败 api=%s", path)
            raise DomainError(
                "YUNPRINT_REQUEST_FAILED",
                str(result.get("message") or "云打印接口失败"),
            )
        logger.info(
            "云打印接口请求完成 api=%s elapsed=%dms",
            path,
            elapsed_ms(started),
        )
        if logger.isEnabledFor(logging.DEBUG):
            logger.debug(
                "云打印接口响应 url=%s body=%s",
                url,
                clip_log_text(json.dumps(body, ensure_ascii=False)),
            )
        return result.get("data")

    async def get_print_info(
        self,
        token: str,
        report_name: str,
        report_type: int,
        is_dynamic_base_style: bool | str = "",
    ) -> dict[str, Any]:
        data = await self._post_result(
            "ElectronPrintApi/GetPrintInfo",
            {
                "token": token,
                "reportName": report_name,
                "reportType": report_type,
                "styleName": "",
                "styleId": "",
                "styleContent": "",
                "isDynamicBaseStyle": is_dynamic_base_style,
                "baseStyleContent": "",
                "isPublic": False,
            },
        )
        if not isinstance(data, dict):
            raise DomainError("YUNPRINT_RESPONSE_INVALID", "打印信息不是对象")
        return data

    async def new_style(
        self,
        token: str,
        report_name: str,
        report_type: int,
        style_name: str,
    ) -> dict[str, Any]:
        """在指定报表分类下创建空白模板样式并返回样式记录。"""
        data = await self._post_result(
            "ElectronPrintApi/NewStyle",
            {
                "token": token,
                "reportName": report_name,
                "reportType": report_type,
                "styleName": style_name,
                "styleId": "",
                "styleContent": "",
                "isDynamicBaseStyle": "",
                "baseStyleContent": "",
                "isPublic": False,
            },
            allow_retries=False,
        )
        if not isinstance(data, dict):
            raise DomainError("YUNPRINT_RESPONSE_INVALID", "新增样式结果不是对象")
        style_id = data.get("id")
        if not isinstance(style_id, str) or not style_id.strip():
            raise DomainError("YUNPRINT_RESPONSE_INVALID", "新增样式结果缺少模板 ID")
        return data

    async def save_style(
        self,
        token: str,
        report_name: str,
        report_type: int,
        style_name: str,
        style_id: str,
        style_content: dict[str, Any],
    ) -> Any:
        """把模板生成逻辑输出的 JSON 对象保存到已创建的样式。"""
        try:
            serialized_content = json.dumps(
                style_content,
                ensure_ascii=False,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise DomainError(
                "STYLE_CONTENT_INVALID",
                "模板样式不是可序列化的 JSON 对象",
            ) from exc
        return await self._post_result(
            "ElectronPrintApi/SaveStyle",
            {
                "token": token,
                "reportName": report_name,
                "reportType": report_type,
                "styleName": style_name,
                "styleId": style_id,
                "styleContent": serialized_content,
                "isDynamicBaseStyle": "",
                "baseStyleContent": "",
                "isPublic": False,
            },
            allow_retries=False,
        )

    @staticmethod
    def style_records(print_info: dict[str, Any]) -> list[dict[str, Any]]:
        """把 GetPrintInfo 中的样式列表整理为模型易用的摘要。"""
        style_info = print_info.get("styleInfo")
        style_names = style_info.get("styleNames") if isinstance(style_info, dict) else None
        if not isinstance(style_names, list):
            return []
        records: list[dict[str, Any]] = []
        for index, item in enumerate(style_names):
            if not isinstance(item, dict):
                continue
            style_id = item.get("value")
            if not isinstance(style_id, str) or not style_id:
                continue
            style_obj = item.get("styleObj") if isinstance(item.get("styleObj"), dict) else {}
            records.append(
                {
                    "id": style_id,
                    "name": str(
                        item.get("label")
                        or item.get("text")
                        or style_obj.get("styleName")
                        or style_obj.get("name")
                        or style_id
                    ),
                    "isBaseStyle": style_obj.get("isBaseStyle") is True,
                    "order": index,
                    "raw": item,
                },
            )
        return records

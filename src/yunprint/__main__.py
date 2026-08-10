"""本地参考入口。

HTTP 模式启动对外 opaque Token 入口（yunprint.app）：Agent 平台在
Authorization 头传入云打印 Token，Token 不会进入工具 Schema。

启动方式：

    uv run python -m yunprint                # HTTP：Bearer header 模式，默认 127.0.0.1:8931
    uv run python -m yunprint --port 8000    # 指定 HTTP 端口
"""

from __future__ import annotations

import argparse

from gjp_common.logging_config import configure_logging

from .app import create_print_app


def main() -> None:
    parser = argparse.ArgumentParser(description="本地参考打印 MCP 服务")
    parser.add_argument("--host", default="127.0.0.1", help="HTTP 监听地址")
    parser.add_argument("--port", type=int, default=8931, help="HTTP 监听端口")
    args = parser.parse_args()

    configure_logging()
    import uvicorn

    uvicorn.run(create_print_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()

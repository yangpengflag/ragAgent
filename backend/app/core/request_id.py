"""request_id 中间件。

入站读取 `X-Request-ID`（大小写不敏感由 Starlette 头解析保证），缺失则生成；
写入 contextvar 供日志使用；出站写回响应头。
"""

from __future__ import annotations

import re
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.core.logging import get_logger
from app.core.request_context import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

# 仅接受有限字符集且限长：避免超长值膨胀每条日志，也避免控制字符注入响应头/日志
_VALID_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        incoming = (request.headers.get(REQUEST_ID_HEADER) or "").strip()
        request_id = incoming if _VALID_REQUEST_ID.match(incoming) else uuid4().hex

        token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
            response.headers[REQUEST_ID_HEADER] = request_id
            # 必须在 reset 之前记录，否则日志拿不到 request_id
            get_logger().info(
                "request handled", method=request.method, path=request.url.path
            )
            return response
        finally:
            request_id_var.reset(token)

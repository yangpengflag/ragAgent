"""API 层共享依赖。

成功响应统一携带 `request_id`（`project-scaffold` R2）；把它做成依赖而不是
每个端点各写一遍，避免逐处遗漏。
"""

from __future__ import annotations

from fastapi import Request

from app.core.request_context import request_id_var


def current_request_id(request: Request) -> str:
    """当前请求的 `request_id`（优先取中间件写入的 state，退化到 contextvar）。"""
    value = getattr(request.state, "request_id", None) or request_id_var.get()
    return str(value or "")

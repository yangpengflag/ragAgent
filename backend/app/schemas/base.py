"""成功响应基类。

`project-scaffold` 的 R2 要求 `request_id` 同时出现在日志、响应头与**响应体**
（成功与错误响应均包含）。把该字段放进基类并设为**必填**，可以让"忘记带上
request_id"在构造响应时立刻失败，而不是悄悄返回一个不合规的响应。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ApiResponse(BaseModel):
    """所有成功响应的基类：顶层携带 `request_id`。"""

    request_id: str = Field(description="请求追踪 ID")

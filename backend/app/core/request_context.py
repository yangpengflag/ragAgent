"""请求上下文（contextvar）。

供中间件写入、日志处理器读取，实现 request_id 跨层透传。
"""

from __future__ import annotations

from contextvars import ContextVar

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

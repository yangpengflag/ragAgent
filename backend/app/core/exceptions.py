"""统一异常层次与错误码。

约定见 `design.md` D6：异常层次保持精简；错误码常量与 `.codebuddy/rules/api-conventions.md`
的错误码表对齐——**状态码→错误码映射表即为这些常量的消费者**，因此并非预防性全量定义。
配置类异常不面向 HTTP 调用方（启动期使用）。
"""

from __future__ import annotations

from http import HTTPStatus
from typing import Any


class ErrorCode:
    """语义化错误码（snake_case），供调用方条件分支。"""

    NOT_FOUND = "not_found"
    VALIDATION_ERROR = "validation_error"
    INTERNAL_ERROR = "internal_error"
    BAD_REQUEST = "bad_request"
    METHOD_NOT_ALLOWED = "method_not_allowed"
    UNAUTHORIZED = "unauthorized"
    ACCESS_DENIED = "access_denied"
    CONFLICT = "conflict"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"


class AppError(Exception):
    """业务异常基类：携带 HTTP 状态码与错误码，由全局处理器转为统一信封。"""

    status_code: int = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code: str = ErrorCode.INTERNAL_ERROR

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(AppError):
    """目标资源不存在。"""

    status_code = HTTPStatus.NOT_FOUND
    error_code = ErrorCode.NOT_FOUND


class ConfigurationError(Exception):
    """配置错误（启动期，不面向 HTTP 调用方）。"""


class MissingConfigurationError(ConfigurationError):
    """必需配置缺失。错误消息中列出缺失的环境变量名。"""


class InvalidConfigurationError(ConfigurationError):
    """配置存在但无法解析（如端口写成非数字）。"""

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
    TOKEN_EXPIRED = "token_expired"
    ACCESS_DENIED = "access_denied"
    CONFLICT = "conflict"
    FILE_TOO_LARGE = "file_too_large"
    UNSUPPORTED_FILE_TYPE = "unsupported_file_type"
    RATE_LIMITED = "rate_limited"
    UPSTREAM_UNAVAILABLE = "upstream_unavailable"
    SECURITY_VIOLATION = "security_violation"


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


class ConflictError(AppError):
    """与当前状态冲突（用户名已存在、最后一个管理员保护等）。409 `conflict`。"""

    status_code = HTTPStatus.CONFLICT
    error_code = ErrorCode.CONFLICT


class TokenExpiredError(AppError):
    """令牌已过期。与"签名无效/格式非法"区分（401 `token_expired`）：
    客户端可凭刷新令牌恢复，其余 401 一律要求重新登录。"""

    status_code = HTTPStatus.UNAUTHORIZED
    error_code = ErrorCode.TOKEN_EXPIRED


class AccessDeniedError(AppError):
    """已认证但权限不足（或来源不被允许）。403 `access_denied`，与 401 区分。"""

    status_code = HTTPStatus.FORBIDDEN
    error_code = ErrorCode.ACCESS_DENIED


class SecurityViolationError(AppError):
    """安全边界被突破（如检索返回未授权知识库内容）。

    500 `security_violation`：明确区别于普通 `internal_error`，
    便于监控把「权限过滤失效」识别为安全事件并告警。
    响应 message 不暴露内部细节（详情只进日志，带 request_id）。
    """

    status_code = HTTPStatus.INTERNAL_SERVER_ERROR
    error_code = ErrorCode.SECURITY_VIOLATION


class ConfigurationError(Exception):
    """配置错误（启动期，不面向 HTTP 调用方）。"""


class MissingConfigurationError(ConfigurationError):
    """必需配置缺失。错误消息中列出缺失的环境变量名。"""


class InvalidConfigurationError(ConfigurationError):
    """配置存在但无法解析（如端口写成非数字）。"""

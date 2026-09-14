"""全局异常处理器。

把所有异常统一为 `{ request_id, error_code, message, details? }` 信封；
500 时响应不含堆栈，堆栈只进日志。
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.exceptions import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.request_context import request_id_var

REQUEST_ID_HEADER = "X-Request-ID"

# 框架抛出的 HTTPException（如未知路由 404）也要落入统一信封。
# 映射与 <harness>/rules/api-conventions.md 的错误码表保持一致。
_ERROR_CODE_BY_STATUS: dict[int, str] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.ACCESS_DENIED,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    413: ErrorCode.FILE_TOO_LARGE,
    415: ErrorCode.UNSUPPORTED_FILE_TYPE,
    422: ErrorCode.VALIDATION_ERROR,
    429: ErrorCode.RATE_LIMITED,
    503: ErrorCode.UPSTREAM_UNAVAILABLE,
}


def _error_code_for_status(status_code: int) -> str:
    """按语义映射错误码：客户端错误不给 `internal_error`，上游不可用不给 `internal_error`。"""
    if status_code in _ERROR_CODE_BY_STATUS:
        return _ERROR_CODE_BY_STATUS[status_code]
    return ErrorCode.INTERNAL_ERROR if status_code >= 500 else ErrorCode.BAD_REQUEST


def _request_id(request: Request) -> str:
    """优先取自 request.state（异常路径下 contextvar 可能已 reset）。"""
    return getattr(request.state, "request_id", None) or request_id_var.get() or ""


def _envelope(
    request: Request,
    *,
    error_code: str,
    message: str,
    details: Any = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "request_id": _request_id(request),
        "error_code": error_code,
        "message": message,
    }
    if details is not None:
        payload["details"] = details
    return payload


def _json(request: Request, status_code: int, payload: dict[str, Any]) -> JSONResponse:
    response = JSONResponse(status_code=status_code, content=payload)
    request_id = _request_id(request)
    if request_id:
        response.headers[REQUEST_ID_HEADER] = request_id
    return response


def app_error_response(request: Request, exc: AppError) -> JSONResponse:
    """把 AppError 转为统一错误信封响应。

    独立成公共 helper：路由需要在**返回前**附加 Cookie 变更等副作用时，
    直接调用它而不是 raise——异常一旦传播，FastAPI 会丢弃路由的 Response
    参数上已做的修改（如清除刷新令牌 Cookie）。
    """
    return _json(
        request,
        exc.status_code,
        _envelope(
            request,
            error_code=exc.error_code,
            message=exc.message,
            details=exc.details,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    """注册 AppError / 校验失败 / 未预期异常三类处理器。"""

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return app_error_response(request, exc)

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return _json(
            request,
            exc.status_code,
            _envelope(
                request,
                error_code=_error_code_for_status(exc.status_code),
                message=str(exc.detail),
            ),
        )

    # FastAPI 的 HTTPException 是 Starlette 的子类，若只注册父类会被 FastAPI
    # 内置处理器抢先（返回裸 {"detail": ...}）。两者都注册，共用同一处理逻辑。
    @app.exception_handler(FastAPIHTTPException)
    async def _handle_fastapi_http_exception(
        request: Request, exc: FastAPIHTTPException
    ) -> JSONResponse:
        return _json(
            request,
            exc.status_code,
            _envelope(
                request,
                error_code=_error_code_for_status(exc.status_code),
                message=str(exc.detail),
            ),
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        details: dict[str, str] = {}
        for err in exc.errors():
            location = [str(part) for part in err["loc"]]
            # 去掉首段的来源标记（query / body / path），保留字段路径
            field = ".".join(location[1:]) or ".".join(location)
            details[field] = err["msg"]
        return _json(
            request,
            422,
            _envelope(
                request,
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Request validation failed",
                details=details,
            ),
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        get_logger().error(
            "unhandled exception", path=request.url.path, exc_info=exc
        )
        return _json(
            request,
            500,
            _envelope(
                request,
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Internal server error",
            ),
        )

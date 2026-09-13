"""认证路由：login / refresh / logout（`me` 随 §6 鉴权依赖落地）。

契约见 `specs/authentication/spec.md`：
- 刷新令牌只走 HttpOnly Cookie（Path 覆盖刷新与登出），响应体不出现刷新令牌
- 刷新只从 Cookie 读令牌，请求体中的令牌不被采纳
- 刷新校验来源（Origin / Referer），非法来源 403 `access_denied`
- 401 类刷新失败清除 Cookie；503（撤销存储不可用）不清除，可稍后重试
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.api.deps import CurrentUserDep, current_request_id, get_auth_service
from app.core.config import get_settings
from app.core.db import get_db
from app.core.error_handlers import app_error_response
from app.core.exceptions import AccessDeniedError, TokenExpiredError
from app.schemas.auth import (
    LoginRequest,
    LoginResponse,
    LogoutResponse,
    MeResponse,
    RefreshResponse,
    UserSummary,
)
from app.services.auth_service import (
    AuthService,
    InvalidCredentialsError,
    LoginResult,
    RefreshResult,
    resolve_origin,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Annotated 依赖别名（规避 B008；生成器依赖不可写进参数默认值）
SessionDep = Annotated[Session, Depends(get_db)]
AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
RequestIdDep = Annotated[str, Depends(current_request_id)]


def _refresh_cookie_kwargs() -> dict[str, object]:
    settings = get_settings()
    return {
        "key": settings.refresh_cookie_name,
        "max_age": settings.jwt_refresh_token_expire_days * 86400,
        "httponly": True,
        "path": settings.refresh_cookie_path,
        "secure": settings.refresh_cookie_secure,
        "samesite": settings.refresh_cookie_samesite,
    }


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(value=token, **_refresh_cookie_kwargs())  # type: ignore[arg-type]


def _clear_refresh_cookie(response: Response) -> None:
    settings = get_settings()
    response.delete_cookie(
        key=settings.refresh_cookie_name, path=settings.refresh_cookie_path
    )


def _clear_cookie_on(response: Response) -> None:
    """同 `_clear_refresh_cookie`，但可直接用于手工构造的错误响应。"""
    _clear_refresh_cookie(response)


def _allowed_origins() -> list[str]:
    return [
        origin.strip()
        for origin in get_settings().app_cors_origins.split(",")
        if origin.strip()
    ]


def _enforce_allowed_origin(request: Request) -> None:
    """刷新接口的 CSRF 来源校验（design D5，tasks 5.9）。

    两者都缺失视为非浏览器客户端，放行交由刷新令牌校验决定结果。
    """
    origin = resolve_origin(
        request.headers.get("origin"), request.headers.get("referer")
    )
    if origin is None:
        return
    if origin not in _allowed_origins():
        raise AccessDeniedError("来源不被允许")


def _client_host(request: Request) -> str:
    """限流键用的对端地址（spec：不信任可伪造的转发头，本期无反向代理）。"""
    return request.client.host if request.client else "unknown"


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    response: Response,
    request: Request,
    session: SessionDep,
    service: AuthServiceDep,
    request_id: RequestIdDep,
) -> LoginResponse:
    result: LoginResult = service.login(
        session,
        username=payload.username,
        password=payload.password,
        client_host=_client_host(request),
    )
    _set_refresh_cookie(response, result.refresh_token)
    return LoginResponse(
        request_id=request_id,
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
        user=UserSummary(
            id=result.user.id,
            username=result.user.username,
            display_name=result.user.display_name,
            system_role=result.user.system_role,
        ),
    )


@router.post("/refresh", response_model=RefreshResponse)
def refresh(
    response: Response,
    request: Request,
    session: SessionDep,
    service: AuthServiceDep,
    request_id: RequestIdDep,
) -> RefreshResponse | JSONResponse:
    _enforce_allowed_origin(request)

    settings = get_settings()
    token = request.cookies.get(settings.refresh_cookie_name)
    try:
        result: RefreshResult = service.refresh(session, refresh_token=token)
    except (InvalidCredentialsError, TokenExpiredError) as exc:
        # 401 类失败：客户端的刷新令牌已不可用，清掉 Cookie 避免反复无效请求；
        # 503（撤销存储不可用）不清除——令牌仍有效，可稍后重试。
        # 注意：错误响应必须"自己构造并返回"，且 Cookie 直接挂在它身上——
        # 无论是 raise 还是改 Response 参数，Cookie 变更都会被 FastAPI 丢弃。
        error = app_error_response(request, exc)
        _clear_cookie_on(error)
        return error
    _set_refresh_cookie(response, result.refresh_token)
    return RefreshResponse(
        request_id=request_id,
        access_token=result.access_token,
        token_type=result.token_type,
        expires_in=result.expires_in,
    )


@router.post("/logout", response_model=LogoutResponse)
def logout(
    response: Response,
    request: Request,
    service: AuthServiceDep,
    request_id: RequestIdDep,
) -> LogoutResponse:
    settings = get_settings()
    service.logout(refresh_token=request.cookies.get(settings.refresh_cookie_name))
    _clear_refresh_cookie(response)
    return LogoutResponse(request_id=request_id)


@router.get("/me", response_model=MeResponse)
def me(account: CurrentUserDep, request_id: RequestIdDep) -> MeResponse:
    """当前登录态查询（§6.5）：永不含密码字段。"""
    return MeResponse(
        request_id=request_id,
        user=UserSummary(
            id=str(account.id),
            username=account.username,
            display_name=account.display_name,
            system_role=account.system_role,
        ),
    )

"""API 层共享依赖。

成功响应统一携带 `request_id`（`project-scaffold` R2）；把它做成依赖而不是
每个端点各写一遍，避免逐处遗漏。

认证依赖（auth-and-users §5）：存储端口与应用服务在此装配（5.19），
测试用 `app.dependency_overrides` 替换任一环节即可，无需真实中间件。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.request_context import request_id_var
from app.services.auth_service import AuthConfig, AuthService
from app.services.ports import RateLimitStore, RevocationStore


def current_request_id(request: Request) -> str:
    """当前请求的 `request_id`（优先取中间件写入的 state，退化到 contextvar）。"""
    value = getattr(request.state, "request_id", None) or request_id_var.get()
    return str(value or "")


@lru_cache
def get_revocation_store() -> RevocationStore:
    """撤销名单端口（fail-closed 语义，见 design D9）。"""
    from app.integrations.redis_stores import RedisRevocationStore, build_redis_client

    return RedisRevocationStore(build_redis_client())


@lru_cache
def get_rate_limit_store() -> RateLimitStore:
    """登录限流端口（fail-open 语义，见 design D9）。"""
    from app.integrations.redis_stores import RedisRateLimitStore, build_redis_client

    return RedisRateLimitStore(build_redis_client())


def get_auth_config() -> AuthConfig:
    """由 Settings 组装认证参数（§4.7 收敛：参数只在 Settings 与此处出现）。"""
    settings = get_settings()
    return AuthConfig(
        secret_key=settings.app_secret_key,
        algorithm=settings.jwt_algorithm,
        access_token_ttl_min=settings.jwt_access_token_expire_min,
        refresh_token_ttl_days=settings.jwt_refresh_token_expire_days,
        login_max_failures=settings.rate_limit_login_max_failures,
        login_window_min=settings.rate_limit_login_window_min,
    )


# Annotated 风格：FastAPI 官方推荐；同时规避 B008（生成器依赖不能写进参数默认值）
SessionDep = Annotated[Session, Depends(get_db)]
RevocationStoreDep = Annotated[RevocationStore, Depends(get_revocation_store)]
RateLimitStoreDep = Annotated[RateLimitStore, Depends(get_rate_limit_store)]
AuthConfigDep = Annotated[AuthConfig, Depends(get_auth_config)]


def get_auth_service(
    session: SessionDep,
    revocations: RevocationStoreDep,
    rate_limits: RateLimitStoreDep,
    config: AuthConfigDep,
) -> AuthService:
    return AuthService(revocations, rate_limits, config)

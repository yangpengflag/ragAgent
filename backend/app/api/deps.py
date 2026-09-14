"""API 层共享依赖。

成功响应统一携带 `request_id`（`project-scaffold` R2）；把它做成依赖而不是
每个端点各写一遍，避免逐处遗漏。

认证依赖（auth-and-users §5）：存储端口与应用服务在此装配（5.19），
测试用 `app.dependency_overrides` 替换任一环节即可，无需真实中间件。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.exceptions import AccessDeniedError, AppError, TokenExpiredError
from app.core.request_context import request_id_var
from app.core.security import TokenType, decode_token
from app.integrations.storage import FileStorage
from app.models.user import Account
from app.services.auth_service import AuthConfig, AuthService, InvalidCredentialsError
from app.services.document_service import DEFAULT_ALLOWED_EXTS
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


# ---------------------------------------------------------------- 鉴权依赖（§6）
# auto_error=False：缺失凭据时拿 None，由我们抛统一信封的 401，
# 避免 FastAPI 默认的裸 {"detail": ...} 响应绕过错误码约定。
_bearer_scheme = HTTPBearer(auto_error=False)

CredentialsDep = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer_scheme)]


def get_current_user(
    session: SessionDep,
    credentials: CredentialsDep,
) -> Account:
    """解析 Bearer 访问令牌并返回当前账号（§6.2）。

    校验签名与过期后**查库**确认账号存在且启用（design D6）——
    停用 / 软删对已签发的访问令牌立即生效，而非等令牌自然过期。
    用 select 而非 session.get：后者命中 identity map 时绕过软删过滤。
    """
    if credentials is None:
        raise InvalidCredentialsError("未认证")

    try:
        claims = decode_token(
            token=credentials.credentials,
            expected_type=TokenType.ACCESS,
            secret_key=get_settings().app_secret_key,
            algorithm=get_settings().jwt_algorithm,
        )
    except TokenExpiredError:
        raise  # 过期保持专属错误码（客户端可走刷新）
    except AppError as exc:  # 签名无效/格式非法/类型不符 → 统一 401 unauthorized
        raise InvalidCredentialsError("未认证") from exc

    account = session.execute(
        select(Account).where(Account.id == claims.account_id)
    ).scalar_one_or_none()
    if account is None or not account.is_active:
        raise InvalidCredentialsError("未认证")
    return account


CurrentUserDep = Annotated[Account, Depends(get_current_user)]


def require_role(*allowed_roles: str) -> Callable[..., Account]:
    """按「所需角色集合」参数化的角色依赖（design D7）。

    角色不足返回 403 `access_denied`，与未认证 401 严格区分。
    """

    def dependency(account: CurrentUserDep) -> Account:
        if account.system_role not in allowed_roles:
            raise AccessDeniedError("权限不足")
        return account

    return dependency


# ---------------------------------------------------------------- 文档上传依赖
# storage 与上传限额依赖化，便于测试用 `dependency_overrides` 替换为临时目录 / 小限额。


@lru_cache
def get_document_storage() -> FileStorage:
    """文档文件存储（默认本地文件系统，根目录来自配置）。"""
    from app.integrations.storage import LocalFileStorage

    return LocalFileStorage(get_settings().storage_local_root)


DocumentStorageDep = Annotated[FileStorage, Depends(get_document_storage)]


def get_upload_limits() -> tuple[int, frozenset[str]]:
    """上传大小上限（字节）与格式白名单。"""
    settings = get_settings()
    max_bytes = settings.upload_max_size_mb * 1024 * 1024
    return max_bytes, frozenset(DEFAULT_ALLOWED_EXTS)


UploadLimitsDep = Annotated[tuple[int, frozenset[str]], Depends(get_upload_limits)]

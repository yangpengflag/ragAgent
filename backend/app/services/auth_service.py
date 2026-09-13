"""认证服务：登录 / 刷新（轮换 + 撤销）/ 登出 / 登录失败限流 / 初始管理员引导。

对应 design.md D1/D4/D5/D8/D9/D10/D11/D14 与 tasks.md §5。
所有存储依赖走 `ports.py` 的 Protocol：撤销名单 fail-closed、限流 fail-open；
本模块不 import Redis 客户端（5.19：单测零真实中间件）。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Final
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import AppError, ErrorCode, TokenExpiredError
from app.core.logging import get_logger
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from app.models.user import Account
from app.services.ports import RateLimitStore, RevocationStore, StoreUnavailableError

logger = get_logger()

# 统一失败文案：用户名不存在与密码错误对外不可区分（spec：不暴露账号是否存在）
_INVALID_CREDENTIALS_MESSAGE: Final = "用户名或密码错误"


class InvalidCredentialsError(AppError):
    """凭据错误 / 刷新令牌无效。401 `unauthorized`。"""

    status_code = 401
    error_code = ErrorCode.UNAUTHORIZED


class RateLimitedError(AppError):
    """登录失败次数达到阈值。429 `rate_limited`。"""

    status_code = 429
    error_code = ErrorCode.RATE_LIMITED


@dataclass(frozen=True, slots=True)
class AuthConfig:
    """认证参数（§4.7 收敛：这里只做透传，不散写默认值）。"""

    secret_key: str
    algorithm: str
    access_token_ttl_min: int
    refresh_token_ttl_days: int
    login_max_failures: int
    login_window_min: int


@dataclass(frozen=True, slots=True)
class UserInfo:
    """账号摘要（响应体 `user`；永不含密码字段）。"""

    id: str
    username: str
    display_name: str
    system_role: str


@dataclass(frozen=True, slots=True)
class LoginResult:
    access_token: str
    token_type: str
    expires_in: int
    user: UserInfo
    refresh_token: str


@dataclass(frozen=True, slots=True)
class RefreshResult:
    """刷新结果：不含 `user`（spec 明确，账号信息走 /auth/me）。"""

    access_token: str
    token_type: str
    expires_in: int
    refresh_token: str
    user: UserInfo | None = None


@dataclass(frozen=True, slots=True)
class LogoutInfo:
    """登出结果：仅携带账号标识供审计；令牌本身绝不回传。"""

    account_id: str | None


def summarize(account: Account) -> UserInfo:
    return UserInfo(
        id=str(account.id),
        username=account.username,
        display_name=account.display_name,
        system_role=account.system_role,
    )


def resolve_origin(origin: str | None, referer: str | None) -> str | None:
    """从 `Origin`（优先）或 `Referer` 提取请求来源。

    返回 None 表示"两者都缺失"（非浏览器客户端，放行）。
    `Referer` 取 scheme://host[:port]，与 `APP_CORS_ORIGINS` 的条目同形。
    """
    if origin and origin.strip():
        return origin.strip()
    if referer and referer.strip():
        parsed = urlparse(referer.strip())
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


class AuthService:
    def __init__(
        self,
        revocations: RevocationStore,
        rate_limits: RateLimitStore,
        config: AuthConfig,
    ) -> None:
        self._revocations = revocations
        self._rate_limits = rate_limits
        self._config = config

    # ---------------------------------------------------------------- 内部工具
    def _rate_key(self, username: str, client_host: str) -> str:
        return f"login-fail:{username.lower().strip()}:{client_host}"

    def _window_seconds(self) -> int:
        return self._config.login_window_min * 60

    def _rate_count(self, key: str) -> int:
        """fail-open 读取失败计数；存储不可用按 0 处理并告警（design D9）。"""
        try:
            return self._rate_limits.count(key)
        except StoreUnavailableError:
            logger.warning(
                "login rate limit store unavailable, failing open", key=key
            )
            return 0

    def _rate_increment(self, key: str) -> None:
        try:
            self._rate_limits.increment(key, window_seconds=self._window_seconds())
        except StoreUnavailableError:
            logger.warning(
                "login rate limit store unavailable, failure not recorded", key=key
            )

    def _rate_reset(self, key: str) -> None:
        try:
            self._rate_limits.reset(key)
        except StoreUnavailableError:
            logger.warning(
                "login rate limit store unavailable, count not reset", key=key
            )

    # ---------------------------------------------------------------- 登录
    def login(
        self, session: Session, *, username: str, password: str, client_host: str
    ) -> LoginResult:
        key = self._rate_key(username, client_host)
        if self._rate_count(key) >= self._config.login_max_failures:
            # 达阈值后拒绝且不再进行密码校验（spec：防止以爆破方式验证凭据）
            logger.info("login rate limited", username=username, client=client_host)
            raise RateLimitedError("登录尝试过于频繁，请稍后再试")

        account = session.execute(
            select(Account).where(Account.username == username)
        ).scalar_one_or_none()

        # 注意分支顺序：先"账号不可用"统一拒绝，再做密码校验，
        # 保证不存在与密码错误走同一条返回路径（含同样的失败计数副作用）。
        if (
            account is None
            or not account.is_active
            or not verify_password(password, account.password_hash)
        ):
            self._rate_increment(key)
            logger.info("login failed", username=username, client=client_host)
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE)

        self._rate_reset(key)
        cfg = self._config
        access_token = create_access_token(
            account_id=account.id,
            system_role=account.system_role,
            secret_key=cfg.secret_key,
            algorithm=cfg.algorithm,
            expires_min=cfg.access_token_ttl_min,
        )
        refresh_token = create_refresh_token(
            account_id=account.id,
            session_epoch=account.session_epoch,
            secret_key=cfg.secret_key,
            algorithm=cfg.algorithm,
            expires_days=cfg.refresh_token_ttl_days,
        )
        logger.info(
            "login succeeded",
            username=account.username,
            account_id=str(account.id),
            client=client_host,
        )
        return LoginResult(
            access_token=access_token,
            token_type="Bearer",
            expires_in=cfg.access_token_ttl_min * 60,
            user=summarize(account),
            refresh_token=refresh_token,
        )

    # ---------------------------------------------------------------- 刷新
    def refresh(
        self, session: Session, *, refresh_token: str | None, client_host: str = "unknown"
    ) -> RefreshResult:
        cfg = self._config
        if not refresh_token:
            logger.warning("refresh rejected: no token", client=client_host)
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE)

        try:
            claims = decode_token(
                token=refresh_token,
                expected_type=TokenType.REFRESH,
                secret_key=cfg.secret_key,
                algorithm=cfg.algorithm,
            )
        except TokenExpiredError:
            logger.warning("refresh rejected: expired token", client=client_host)
            raise
        except AppError as exc:
            logger.warning(
                "refresh rejected: invalid token", client=client_host
            )
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE) from exc

        # 撤销名单不可用 → 异常冒泡为 503（fail-closed，design D9）
        if self._revocations.is_revoked(claims.jti):
            logger.warning(
                "refresh rejected: revoked jti",
                account_id=str(claims.account_id),
                client=client_host,
            )
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE)

        # 全局软删过滤使已删账号查不到 → 与"不存在"同路拒绝。
        # 用 select 而非 session.get：后者命中 identity map 时会绕过过滤器。
        account = session.execute(
            select(Account).where(Account.id == claims.account_id)
        ).scalar_one_or_none()
        if account is None or not account.is_active:
            logger.warning(
                "refresh rejected: account unavailable",
                account_id=str(claims.account_id),
                client=client_host,
            )
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE)

        # 会话纪元（design D14）：重置密码/停用/软删/改角色都会 +1，
        # 旧令牌携带的 epoch 落后即失效。
        if claims.session_epoch != account.session_epoch:
            logger.warning(
                "refresh rejected: stale session epoch",
                account_id=str(account.id),
                client=client_host,
            )
            raise InvalidCredentialsError(_INVALID_CREDENTIALS_MESSAGE)

        # 轮换：拉黑旧 jti（TTL = 剩余寿命），签发新 jti。
        # 拉黑失败必须整体失败（design D4 的代价条款）——异常继续冒泡成 503。
        remaining = int(claims.expires_at.timestamp() - time.time())
        self._revocations.revoke(claims.jti, ttl_seconds=max(remaining, 1))

        access_token = create_access_token(
            account_id=account.id,
            system_role=account.system_role,
            secret_key=cfg.secret_key,
            algorithm=cfg.algorithm,
            expires_min=cfg.access_token_ttl_min,
        )
        new_refresh = create_refresh_token(
            account_id=account.id,
            session_epoch=account.session_epoch,
            secret_key=cfg.secret_key,
            algorithm=cfg.algorithm,
            expires_days=cfg.refresh_token_ttl_days,
        )
        return RefreshResult(
            access_token=access_token,
            token_type="Bearer",
            expires_in=cfg.access_token_ttl_min * 60,
            refresh_token=new_refresh,
        )

    # ---------------------------------------------------------------- 登出
    def logout(
        self, *, refresh_token: str | None, client_host: str = "unknown"
    ) -> LogoutInfo:
        """撤销当前 Cookie 携带的刷新令牌；幂等（spec：无令牌/无效令牌也成功）。

        撤销存储不可用 → 冒泡成 503（fail-closed）。
        """
        if not refresh_token:
            return LogoutInfo(account_id=None)
        try:
            claims = decode_token(
                token=refresh_token,
                expected_type=TokenType.REFRESH,
                secret_key=self._config.secret_key,
                algorithm=self._config.algorithm,
            )
        except AppError:
            # 无法解析的令牌谈不上撤销；幂等返回成功
            return LogoutInfo(account_id=None)

        remaining = int(claims.expires_at.timestamp() - time.time())
        self._revocations.revoke(claims.jti, ttl_seconds=max(remaining, 1))
        logger.info("logout", account_id=str(claims.account_id), client=client_host)
        return LogoutInfo(account_id=str(claims.account_id))


# ---------------------------------------------------------------- 初始管理员引导
def bootstrap_admin(
    session: Session, *, username: str | None, password: str | None
) -> str:
    """启动期引导初始管理员（design D10）。

    返回状态：`created` / `exists` / `table_not_empty` / `not_configured`。
    并发或重复启动撞唯一约束时按"已存在"处理，绝不因此启动失败。
    日志只记用户名，不记密码。
    """
    if not username or not password:
        has_any = session.execute(select(Account.id).limit(1)).scalar_one_or_none()
        if has_any is None:
            logger.info(
                "bootstrap admin skipped: accounts table empty and "
                "BOOTSTRAP_ADMIN_USERNAME/BOOTSTRAP_ADMIN_PASSWORD not configured"
            )
        return "not_configured"

    if session.execute(select(Account.id).limit(1)).scalar_one_or_none() is not None:
        logger.info("bootstrap admin skipped: accounts table not empty")
        return "table_not_empty"

    from app.core.security import hash_password, validate_password_strength

    validate_password_strength(password, username=username)
    admin = Account(
        username=username,
        display_name=username,
        password_hash=hash_password(password),
        system_role="ADMIN",
    )
    session.add(admin)
    try:
        session.commit()
    except Exception:
        # 并发启动时另一实例已创建同一用户名 → 视为已存在
        session.rollback()
        logger.info("bootstrap admin already exists", username=username)
        return "exists"
    logger.info("bootstrap admin created", username=username)
    return "created"

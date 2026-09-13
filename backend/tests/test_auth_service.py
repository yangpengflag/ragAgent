"""§5 红灯：认证服务（tasks 5.1–5.8, 5.13–5.16）。

服务层为纯业务逻辑：端口全部用内存替身，DB 用内存 SQLite，零真实中间件（5.19）。
HTTP 契约（Cookie 属性、响应形状、来源校验）见 `test_auth_routes.py`。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ErrorCode, TokenExpiredError
from app.core.security import (
    TokenType,
    create_refresh_token,
    decode_token,
    hash_password,
)
from app.models.user import Account
from app.services.auth_service import (
    AuthConfig,
    AuthService,
    InvalidCredentialsError,
    RateLimitedError,
)
from app.services.ports import (
    InMemoryRateLimitStore,
    InMemoryRevocationStore,
    RateLimitStore,
    StoreUnavailableError,
)

SECRET = "unit-test-secret-key-0123456789abcdef"
PASSWORD = "correct-horse-42"


def make_config(**overrides: object) -> AuthConfig:
    values: dict[str, object] = {
        "secret_key": SECRET,
        "algorithm": "HS256",
        "access_token_ttl_min": 15,
        "refresh_token_ttl_days": 7,
        "login_max_failures": 5,
        "login_window_min": 15,
    }
    values.update(overrides)
    return AuthConfig(**values)  # type: ignore[arg-type]


@pytest.fixture
def revocations() -> InMemoryRevocationStore:
    return InMemoryRevocationStore()


@pytest.fixture
def rate_limits() -> InMemoryRateLimitStore:
    return InMemoryRateLimitStore()


@pytest.fixture
def service(
    revocations: InMemoryRevocationStore, rate_limits: InMemoryRateLimitStore
) -> AuthService:
    return AuthService(revocations, rate_limits, make_config())


@pytest.fixture
def account(sqlite_session: Session) -> Iterator[Account]:
    """启用状态的常规账号（MEMBER）。"""
    acc = Account(
        username="alice",
        display_name="Alice",
        password_hash=hash_password(PASSWORD),
    )
    sqlite_session.add(acc)
    sqlite_session.commit()
    return acc


def issue_tokens(
    service: AuthService, session: Session, account: Account
) -> tuple[str, str]:
    """经由真实登录路径拿一对令牌。"""
    result = service.login(
        session, username=account.username, password=PASSWORD, client_host="10.0.0.1"
    )
    return result.access_token, result.refresh_token


class TestLogin:
    def test_success_returns_tokens_and_user(
        self,
        service: AuthService,
        sqlite_session: Session,
        account: Account,
    ) -> None:
        result = service.login(
            sqlite_session, username="alice", password=PASSWORD, client_host="10.0.0.1"
        )
        assert result.token_type == "Bearer"
        assert result.expires_in == 15 * 60
        assert result.user.id == str(account.id)
        assert result.user.username == "alice"
        assert result.user.system_role == "MEMBER"
        assert "password" not in str(result.user.__dict__) if hasattr(
            result.user, "__dict__"
        ) else True

        access = decode_token(
            token=result.access_token,
            expected_type=TokenType.ACCESS,
            secret_key=SECRET,
            algorithm="HS256",
        )
        assert access.account_id == account.id
        assert access.system_role == "MEMBER"
        refresh = decode_token(
            token=result.refresh_token,
            expected_type=TokenType.REFRESH,
            secret_key=SECRET,
            algorithm="HS256",
        )
        assert refresh.account_id == account.id
        assert refresh.session_epoch == 0

    def test_wrong_password_and_unknown_username_share_same_message(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        """两种失败对外必须不可区分（spec：不暴露账号是否存在）。"""
        with pytest.raises(InvalidCredentialsError) as wrong_password:
            service.login(
                sqlite_session, username="alice", password="wrong-password-1",
                client_host="10.0.0.1",
            )
        with pytest.raises(InvalidCredentialsError) as unknown_user:
            service.login(
                sqlite_session, username="nobody", password=PASSWORD,
                client_host="10.0.0.1",
            )
        assert wrong_password.value.status_code == 401
        assert wrong_password.value.error_code == ErrorCode.UNAUTHORIZED
        assert str(wrong_password.value) == str(unknown_user.value)

    def test_inactive_account_rejected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        account.is_active = False
        sqlite_session.commit()
        with pytest.raises(InvalidCredentialsError):
            service.login(
                sqlite_session, username="alice", password=PASSWORD,
                client_host="10.0.0.1",
            )

    def test_soft_deleted_account_rejected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        account.soft_delete()
        sqlite_session.commit()
        with pytest.raises(InvalidCredentialsError):
            service.login(
                sqlite_session, username="alice", password=PASSWORD,
                client_host="10.0.0.1",
            )

    def test_failure_increments_rate_counter(
        self, service: AuthService, sqlite_session: Session, rate_limits: RateLimitStore
    ) -> None:
        with pytest.raises(InvalidCredentialsError):
            service.login(
                sqlite_session, username="alice", password="wrong-password-1",
                client_host="10.0.0.1",
            )
        assert rate_limits.count("login-fail:alice:10.0.0.1") == 1

    def test_success_resets_rate_counter(
        self, service: AuthService, sqlite_session: Session,
        account: Account, rate_limits: RateLimitStore,
    ) -> None:
        service.login(
            sqlite_session, username="alice", password=PASSWORD, client_host="10.0.0.1"
        )
        assert rate_limits.count("login-fail:alice:10.0.0.1") == 0


class TestRefresh:
    def test_valid_refresh_rotates_and_blacklists_old_jti(
        self, service: AuthService, sqlite_session: Session, account: Account,
        revocations: InMemoryRevocationStore,
    ) -> None:
        _, old_refresh = issue_tokens(service, sqlite_session, account)
        result = service.refresh(sqlite_session, refresh_token=old_refresh)

        assert result.token_type == "Bearer"
        assert result.expires_in == 15 * 60
        assert result.user is None  # 刷新响应不含 user（spec 明确）

        new_refresh = result.refresh_token
        assert new_refresh != old_refresh  # 轮换

        old_jti = decode_token(
            token=old_refresh, expected_type=TokenType.REFRESH,
            secret_key=SECRET, algorithm="HS256",
        ).jti
        new_jti = decode_token(
            token=new_refresh, expected_type=TokenType.REFRESH,
            secret_key=SECRET, algorithm="HS256",
        ).jti
        assert revocations.is_revoked(old_jti)
        assert not revocations.is_revoked(new_jti)

        # 轮换后旧令牌不可再用
        with pytest.raises(InvalidCredentialsError):
            service.refresh(sqlite_session, refresh_token=old_refresh)

    def test_missing_token_rejected(
        self, service: AuthService, sqlite_session: Session
    ) -> None:
        with pytest.raises(InvalidCredentialsError) as exc_info:
            service.refresh(sqlite_session, refresh_token=None)
        assert exc_info.value.status_code == 401

    def test_expired_token_reports_token_expired(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        from datetime import UTC, datetime, timedelta

        expired = create_refresh_token(
            account_id=account.id,
            session_epoch=account.session_epoch,
            secret_key=SECRET,
            algorithm="HS256",
            expires_days=7,
            now=datetime.now(UTC) - timedelta(days=8),
        )
        with pytest.raises(TokenExpiredError):
            service.refresh(sqlite_session, refresh_token=expired)

    def test_epoch_mismatch_rejected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        """模拟"重置密码/停用/改角色后 epoch +1"：旧令牌必须立即失效。"""
        _, old_refresh = issue_tokens(service, sqlite_session, account)
        account.session_epoch += 1
        sqlite_session.commit()
        with pytest.raises(InvalidCredentialsError):
            service.refresh(sqlite_session, refresh_token=old_refresh)

    def test_disabled_account_rejected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        _, old_refresh = issue_tokens(service, sqlite_session, account)
        account.is_active = False
        sqlite_session.commit()
        with pytest.raises(InvalidCredentialsError):
            service.refresh(sqlite_session, refresh_token=old_refresh)

    def test_soft_deleted_account_rejected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        _, old_refresh = issue_tokens(service, sqlite_session, account)
        account.soft_delete()
        sqlite_session.commit()
        with pytest.raises(InvalidCredentialsError):
            service.refresh(sqlite_session, refresh_token=old_refresh)

    def test_epoch_increments_do_not_affect_reissued_tokens(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        """变更后重新登录签发的新令牌应携带新 epoch，可正常刷新。"""
        account.session_epoch += 1
        sqlite_session.commit()
        _, refresh_token = issue_tokens(service, sqlite_session, account)
        result = service.refresh(sqlite_session, refresh_token=refresh_token)
        assert result.access_token


class TestLogout:
    def test_logout_revokes_only_current_session(
        self, service: AuthService, sqlite_session: Session, account: Account,
        revocations: InMemoryRevocationStore,
    ) -> None:
        _, other_client_token = issue_tokens(service, sqlite_session, account)
        _, this_client_token = issue_tokens(service, sqlite_session, account)

        info = service.logout(refresh_token=this_client_token)
        assert info.account_id == str(account.id)

        assert revocations.is_revoked(
            decode_token(
                token=this_client_token, expected_type=TokenType.REFRESH,
                secret_key=SECRET, algorithm="HS256",
            ).jti
        )
        # 其他客户端的会话不受影响
        result = service.refresh(sqlite_session, refresh_token=other_client_token)
        assert result.access_token

    def test_logout_is_idempotent_without_token(
        self, service: AuthService
    ) -> None:
        info = service.logout(refresh_token=None)
        assert info.account_id is None

    def test_second_logout_is_idempotent(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        _, refresh_token = issue_tokens(service, sqlite_session, account)
        service.logout(refresh_token=refresh_token)
        info = service.logout(refresh_token=refresh_token)
        assert info.account_id == str(account.id)  # 重复登出不报错

    def test_logout_with_garbage_token_is_idempotent(
        self, service: AuthService
    ) -> None:
        info = service.logout(refresh_token="not-a-jwt")
        assert info.account_id is None


class TestRateLimiting:
    def test_threshold_blocks_even_correct_credentials(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        for _ in range(5):
            with pytest.raises(InvalidCredentialsError):
                service.login(
                    sqlite_session, username="alice", password="wrong-password-1",
                    client_host="10.0.0.1",
                )
        with pytest.raises(RateLimitedError) as exc_info:
            service.login(
                sqlite_session, username="alice", password=PASSWORD,
                client_host="10.0.0.1",
            )
        assert exc_info.value.status_code == 429
        assert exc_info.value.error_code == ErrorCode.RATE_LIMITED

    def test_different_client_host_not_affected(
        self, service: AuthService, sqlite_session: Session, account: Account
    ) -> None:
        for _ in range(5):
            with pytest.raises(InvalidCredentialsError):
                service.login(
                    sqlite_session, username="alice", password="wrong-password-1",
                    client_host="10.0.0.1",
                )
        # 另一来源不受该来源的失败计数影响
        result = service.login(
            sqlite_session, username="alice", password=PASSWORD, client_host="10.0.0.2"
        )
        assert result.access_token

    def test_window_expiry_restores_access(
        self, sqlite_session: Session, account: Account
    ) -> None:
        now = {"value": 0.0}

        def fake_now() -> float:
            return now["value"]

        store = InMemoryRateLimitStore(now=fake_now)
        service = AuthService(
            InMemoryRevocationStore(), store, make_config(login_window_min=1)
        )
        for _ in range(5):
            with pytest.raises(InvalidCredentialsError):
                service.login(
                    sqlite_session, username="alice", password="wrong-password-1",
                    client_host="10.0.0.1",
                )
        with pytest.raises(RateLimitedError):
            service.login(
                sqlite_session, username="alice", password=PASSWORD,
                client_host="10.0.0.1",
            )
        now["value"] = 61.0  # 越过 60s 窗口
        result = service.login(
            sqlite_session, username="alice", password=PASSWORD, client_host="10.0.0.1"
        )
        assert result.access_token


class _FailingRevocations:
    def revoke(self, jti: str, *, ttl_seconds: int) -> None:
        raise StoreUnavailableError("redis down")

    def is_revoked(self, jti: str) -> bool:
        raise StoreUnavailableError("redis down")


class _FailingRateLimits:
    def count(self, key: str) -> int:
        raise StoreUnavailableError("redis down")

    def increment(self, key: str, *, window_seconds: int) -> int:
        raise StoreUnavailableError("redis down")

    def reset(self, key: str) -> None:
        raise StoreUnavailableError("redis down")


class TestStorageFailureModes:
    """design D9：撤销 fail-closed（503）、限流 fail-open（放行 + 告警）。"""

    def test_revocation_store_down_fails_refresh_closed(
        self, sqlite_session: Session, account: Account
    ) -> None:
        service = AuthService(_FailingRevocations(), InMemoryRateLimitStore(),
                              make_config())
        login = AuthService(
            InMemoryRevocationStore(), InMemoryRateLimitStore(), make_config()
        ).login(
            sqlite_session, username=account.username, password=PASSWORD,
            client_host="10.0.0.1",
        )
        with pytest.raises(StoreUnavailableError) as exc_info:
            service.refresh(sqlite_session, refresh_token=login.refresh_token)
        assert exc_info.value.status_code == 503
        assert exc_info.value.error_code == ErrorCode.UPSTREAM_UNAVAILABLE

    def test_rate_limit_store_down_fails_login_open(
        self, sqlite_session: Session, account: Account, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """structlog 走 stdout 输出，用 capsys 断言告警日志。"""
        service = AuthService(
            InMemoryRevocationStore(), _FailingRateLimits(), make_config()
        )
        result = service.login(
            sqlite_session, username=account.username, password=PASSWORD,
            client_host="10.0.0.1",
        )
        assert result.access_token
        assert "rate limit" in capsys.readouterr().out.lower()

    def test_rate_limit_store_down_still_fails_on_bad_credentials(
        self, sqlite_session: Session, account: Account
    ) -> None:
        """限流 fail-open 只放宽计数，不放宽凭据校验。"""
        service = AuthService(
            InMemoryRevocationStore(), _FailingRateLimits(), make_config()
        )
        with pytest.raises(InvalidCredentialsError):
            service.login(
                sqlite_session, username="alice", password="wrong-password-1",
                client_host="10.0.0.1",
            )

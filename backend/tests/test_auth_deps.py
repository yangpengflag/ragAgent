"""§6.1–6.5 红灯：鉴权依赖与 /auth/me。

用临时挂载的 probe 路由验证 `require_role`；`/auth/me` 本身即受保护路由。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import APIRouter, Depends
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import (
    CurrentUserDep,
    get_db,
    get_rate_limit_store,
    get_revocation_store,
    require_role,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
)
from app.main import create_app
from app.models.user import Account
from app.services.ports import InMemoryRateLimitStore, InMemoryRevocationStore

PASSWORD = "correct-horse-42"

# 令牌必须用应用真实配置的密钥签发（get_current_user 用 get_settings 校验）
from app.core.config import load_settings  # noqa: E402

_settings = load_settings()
SECRET = _settings.app_secret_key
_ALGORITHM = _settings.jwt_algorithm


@pytest.fixture
def account(sqlite_session: Session) -> Account:
    acc = Account(
        username="alice",
        display_name="Alice",
        password_hash=hash_password(PASSWORD),
        system_role="MEMBER",
    )
    sqlite_session.add(acc)
    sqlite_session.commit()
    return acc


@pytest.fixture
def client(sqlite_session: Session, account: Account) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: sqlite_session
    app.dependency_overrides[get_revocation_store] = lambda: InMemoryRevocationStore()
    app.dependency_overrides[get_rate_limit_store] = lambda: InMemoryRateLimitStore()

    # probe 路由：挂一个 ADMIN-only 端点来验证 require_role（不污染生产路由）。
    # 注意 CurrentUserDep/require_role 必须在模块级导入——本文件启用了
    # `from __future__ import annotations`，函数内导入的名字无法被 FastAPI 的
    # 注解解析（get_type_hints 只查模块全局），参数会被误判为请求体字段 → 422。
    probe = APIRouter()

    @probe.get(
        "/api/v1/_probe/admin-only", dependencies=[Depends(require_role("ADMIN"))]
    )
    def admin_only(target: CurrentUserDep) -> dict[str, str]:
        return {"username": target.username}

    app.include_router(probe)
    return TestClient(app)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _valid_access(account: Account) -> str:
    return create_access_token(
        account_id=account.id,
        system_role=account.system_role,
        secret_key=SECRET,
        algorithm="HS256",
        expires_min=15,
    )


class TestGetCurrentUser:
    def test_missing_token_is_401_unauthorized(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me")
        assert response.status_code == 401
        assert response.json()["error_code"] == "unauthorized"

    def test_malformed_token_is_401_unauthorized(self, client: TestClient) -> None:
        response = client.get("/api/v1/auth/me", headers=_bearer("not-a-jwt"))
        assert response.status_code == 401
        assert response.json()["error_code"] == "unauthorized"

    def test_expired_token_is_401_token_expired(
        self, client: TestClient, account: Account
    ) -> None:
        token = create_access_token(
            account_id=account.id,
            system_role=account.system_role,
            secret_key=SECRET,
            algorithm="HS256",
            expires_min=15,
            now=datetime.now(UTC) - timedelta(minutes=20),
        )
        response = client.get("/api/v1/auth/me", headers=_bearer(token))
        assert response.status_code == 401
        assert response.json()["error_code"] == "token_expired"

    def test_tampered_token_is_401_unauthorized(
        self, client: TestClient, account: Account
    ) -> None:
        token = _valid_access(account)
        head, body, signature = token.split(".")
        tampered = ("A" if signature[0] != "A" else "B") + signature[1:]
        response = client.get(
            "/api/v1/auth/me", headers=_bearer(f"{head}.{body}.{tampered}")
        )
        assert response.status_code == 401
        assert response.json()["error_code"] == "unauthorized"

    def test_refresh_token_cannot_act_as_access_token(
        self, client: TestClient, account: Account
    ) -> None:
        token = create_refresh_token(
            account_id=account.id,
            session_epoch=account.session_epoch,
            secret_key=SECRET,
            algorithm="HS256",
            expires_days=7,
        )
        response = client.get("/api/v1/auth/me", headers=_bearer(token))
        assert response.status_code == 401
        assert response.json()["error_code"] == "unauthorized"

    def test_valid_token_returns_account(
        self, client: TestClient, account: Account
    ) -> None:
        response = client.get("/api/v1/auth/me", headers=_bearer(_valid_access(account)))
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"request_id", "user"}
        assert set(body["user"]) == {"id", "username", "display_name", "system_role"}
        assert body["user"]["username"] == "alice"
        # 无任何密码字段
        assert "password" not in body["user"]

    def test_disabled_account_rejected_despite_valid_token(
        self, client: TestClient, sqlite_session: Session, account: Account
    ) -> None:
        """6.3：鉴权必须校验账号当前状态——停用后有效期内令牌立即失效。"""
        account.is_active = False
        sqlite_session.commit()
        response = client.get("/api/v1/auth/me", headers=_bearer(_valid_access(account)))
        assert response.status_code == 401


class TestRequireRole:
    def test_member_gets_403_access_denied_on_admin_route(
        self, client: TestClient, account: Account
    ) -> None:
        response = client.get(
            "/api/v1/_probe/admin-only", headers=_bearer(_valid_access(account))
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "access_denied"

    def test_admin_passes_role_check(
        self, client: TestClient, sqlite_session: Session, account: Account
    ) -> None:
        account.system_role = "ADMIN"
        sqlite_session.commit()
        response = client.get(
            "/api/v1/_probe/admin-only", headers=_bearer(_valid_access(account))
        )
        assert response.status_code == 200
        assert response.json()["username"] == "alice"

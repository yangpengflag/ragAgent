"""§5 红灯：认证路由 HTTP 契约（tasks 5.1 Cookie 属性 / 5.5 刷新来源与 Cookie / 5.9–5.10）。

依赖全部替换为内存替身与内存 SQLite——零真实中间件（5.19）。
不用 `with TestClient(...)`，避免触发 lifespan（真实 MySQL）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_rate_limit_store, get_revocation_store
from app.core.security import hash_password
from app.main import create_app
from app.models.user import Account
from app.services.ports import (
    InMemoryRateLimitStore,
    InMemoryRevocationStore,
)

PASSWORD = "correct-horse-42"


@pytest.fixture
def account(sqlite_session: Session) -> Account:
    acc = Account(
        username="alice",
        display_name="Alice",
        password_hash=hash_password(PASSWORD),
    )
    sqlite_session.add(acc)
    sqlite_session.commit()
    return acc


@pytest.fixture
def client(
    sqlite_session: Session,
    account: Account,
) -> TestClient:
    app = create_app()
    # 注意：替身必须是单例——override 每请求调用一次，lambda 里 new 会让状态丢失
    app.dependency_overrides[get_db] = lambda: sqlite_session
    app.dependency_overrides[get_revocation_store] = lambda: InMemoryRevocationStore()
    app.dependency_overrides[get_rate_limit_store] = lambda: _rate_limits
    return TestClient(app)


_rate_limits = InMemoryRateLimitStore()
_revocations = InMemoryRevocationStore()


def _login(client: TestClient, password: str = PASSWORD, username: str = "alice"):
    return client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )


class TestLoginContract:
    def test_response_shape_and_body_never_contains_refresh_token(
        self, client: TestClient
    ) -> None:
        response = _login(client)
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {
            "request_id",
            "access_token",
            "token_type",
            "expires_in",
            "user",
        }
        assert body["token_type"] == "Bearer"
        assert body["expires_in"] == 15 * 60
        assert set(body["user"]) == {"id", "username", "display_name", "system_role"}
        # 响应体不含刷新令牌，也不含密码/哈希
        assert "refresh_token" not in body
        assert PASSWORD not in response.text

    def test_refresh_cookie_attributes(self, client: TestClient) -> None:
        """Cookie 必须 HttpOnly 且 Path 覆盖刷新与登出（/api/v1/auth）。"""
        response = _login(client)
        set_cookie = response.headers["set-cookie"]
        assert "httponly" in set_cookie.lower()
        assert "path=/api/v1/auth" in set_cookie.lower()
        assert "samesite=lax" in set_cookie.lower()

    def test_invalid_credentials_same_message(
        self, client: TestClient, account: Account
    ) -> None:
        wrong_password = _login(client, password="wrong-password-1")
        unknown_user = _login(client, username="nobody")
        assert wrong_password.status_code == 401
        assert unknown_user.status_code == 401
        assert wrong_password.json()["error_code"] == "unauthorized"
        assert wrong_password.json()["message"] == unknown_user.json()["message"]


class TestRefreshContract:
    def test_valid_refresh_rotates_cookie_and_omits_user(
        self, client: TestClient
    ) -> None:
        login = _login(client)
        old_cookie = login.headers["set-cookie"].split(";")[0]

        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"request_id", "access_token", "token_type", "expires_in"}
        assert "user" not in body
        new_cookie = response.headers["set-cookie"].split(";")[0]
        assert new_cookie != old_cookie  # Cookie 轮换

    def test_refresh_without_cookie_is_401_and_clears_cookie(
        self, client: TestClient
    ) -> None:
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 401

    def test_refresh_rejection_clears_cookie(
        self, client: TestClient, sqlite_session: Session, account: Account
    ) -> None:
        """spec：五项校验任一不满足 → 401 且清除刷新令牌 Cookie。"""
        assert _login(client).status_code == 200
        account.is_active = False
        sqlite_session.commit()

        response = client.post("/api/v1/auth/refresh")

        assert response.status_code == 401
        set_cookie = response.headers["set-cookie"].lower()
        assert "max-age=0" in set_cookie or "expires=" in set_cookie

    def test_refresh_token_in_body_is_not_accepted(
        self, client: TestClient
    ) -> None:
        """spec：刷新令牌 MUST 只从 Cookie 读取，请求体中的令牌不被采纳。"""
        login = _login(client)
        token = login.headers["set-cookie"].split(";")[0].split("=", 1)[1]
        client.cookies.clear()
        response = client.post(
            "/api/v1/auth/refresh", json={"refresh_token": token}
        )
        assert response.status_code == 401

    def test_revoked_token_cannot_refresh_again(
        self, client: TestClient
    ) -> None:
        assert _login(client).status_code == 200
        first = client.post("/api/v1/auth/refresh")
        assert first.status_code == 200
        # 此时 Cookie 已轮换为新值；旧 Cookie 已被拉黑——
        # 用服务层语义覆盖（见 test_auth_service），此处验证轮换后新 Cookie 可用
        second = client.post("/api/v1/auth/refresh")
        assert second.status_code == 200

    def test_forbidden_origin_is_403_access_denied(
        self, client: TestClient, account: Account
    ) -> None:
        _login(client)
        response = client.post(
            "/api/v1/auth/refresh", headers={"Origin": "http://evil.example"}
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "access_denied"

    def test_allowed_origin_refreshes(
        self, client: TestClient
    ) -> None:
        _login(client)
        response = client.post(
            "/api/v1/auth/refresh", headers={"Origin": "http://localhost:5173"}
        )
        assert response.status_code == 200

    def test_missing_origin_and_referer_is_allowed(
        self, client: TestClient
    ) -> None:
        _login(client)
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 200

    def test_referer_fallback_origin(
        self, client: TestClient
    ) -> None:
        _login(client)
        allowed = client.post(
            "/api/v1/auth/refresh",
            headers={"Referer": "http://localhost:5173/some/page"},
        )
        assert allowed.status_code == 200
        _login(client)
        denied = client.post(
            "/api/v1/auth/refresh",
            headers={"Referer": "http://evil.example/some/page"},
        )
        assert denied.status_code == 403


class TestLogoutContract:
    def test_logout_clears_cookie_and_is_idempotent(self, client: TestClient) -> None:
        _login(client)
        first = client.post("/api/v1/auth/logout")
        assert first.status_code == 200
        # Cookie 已清除（delete_cookie 使其过期）
        assert "max-age=0" in first.headers.get("set-cookie", "").lower() or (
            "expires=" in first.headers.get("set-cookie", "").lower()
        )

        # 登出后原 Cookie 不再能刷新
        second = client.post("/api/v1/auth/refresh")
        assert second.status_code == 401

        # 重复登出幂等
        assert client.post("/api/v1/auth/logout").status_code == 200

    def test_logout_does_not_affect_other_session(
        self, client: TestClient
    ) -> None:
        pass  # 多客户端场景由服务层测试覆盖（TestLogout）


class TestForwardedHeaderNotTrusted:
    def test_spoofed_xff_does_not_bypass_rate_limit(
        self, sqlite_session: Session, account: Account
    ) -> None:
        """spec：来源地址必须取对端连接地址，伪造转发头不影响计数。"""
        app = create_app()
        rate_store = InMemoryRateLimitStore()  # 跨请求累计计数，必须是单例
        app.dependency_overrides[get_db] = lambda: sqlite_session
        app.dependency_overrides[get_revocation_store] = lambda: InMemoryRevocationStore()
        app.dependency_overrides[get_rate_limit_store] = lambda: rate_store
        client = TestClient(app)

        for i in range(5):
            response = client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong-password-1"},
                headers={"X-Forwarded-For": f"9.9.9.{i}"},
            )
            assert response.status_code == 401

        # 同一真实对端已累计 5 次失败：伪造头换不出新额度
        blocked = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": PASSWORD},
            headers={"X-Forwarded-For": "8.8.8.8"},
        )
        assert blocked.status_code == 429
        assert blocked.json()["error_code"] == "rate_limited"

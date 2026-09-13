"""§6.7–6.9 红灯：账号管理路由。

契约见 `specs/identity/spec.md`。管理员操作全部经真实登录路径拿令牌，
顺带覆盖「重置密码 / 停用后旧会话失效」（design D14 联动）。
"""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_rate_limit_store, get_revocation_store
from app.core.config import load_settings
from app.core.security import hash_password
from app.main import create_app
from app.models.user import Account
from app.services.ports import InMemoryRateLimitStore, InMemoryRevocationStore

PASSWORD = "correct-horse-42"
_settings = load_settings()
_SECRET = _settings.app_secret_key
_ALGORITHM = _settings.jwt_algorithm


@pytest.fixture
def accounts(sqlite_session: Session) -> dict[str, Account]:
    """一个 ADMIN 与一个 MEMBER。"""
    admin = Account(
        username="root",
        display_name="Root",
        password_hash=hash_password(PASSWORD),
        system_role="ADMIN",
    )
    member = Account(
        username="alice",
        display_name="Alice",
        password_hash=hash_password(PASSWORD),
        system_role="MEMBER",
    )
    sqlite_session.add_all([admin, member])
    sqlite_session.commit()
    return {"admin": admin, "member": member}


@pytest.fixture
def client(sqlite_session: Session, accounts: dict[str, Account]) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: sqlite_session
    app.dependency_overrides[get_revocation_store] = lambda: InMemoryRevocationStore()
    app.dependency_overrides[get_rate_limit_store] = lambda: InMemoryRateLimitStore()
    return TestClient(app)


def _login(client: TestClient, username: str) -> str:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _auth(client: TestClient, username: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_login(client, username)}"}


class TestAuthorization:
    def test_anonymous_gets_401(self, client: TestClient) -> None:
        assert client.get("/api/v1/users").status_code == 401

    def test_member_gets_403(self, client: TestClient) -> None:
        response = client.get("/api/v1/users", headers=_auth(client, "alice"))
        assert response.status_code == 403
        assert response.json()["error_code"] == "access_denied"


class TestCreateAccount:
    def test_create_returns_summary_without_password(
        self, client: TestClient
    ) -> None:
        response = client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={
                "username": "bob",
                "display_name": "Bob",
                "password": "bob-password-123",
            },
        )
        assert response.status_code == 201
        body = response.json()
        assert body["username"] == "bob"
        assert body["is_active"] is True
        assert body["system_role"] == "MEMBER"  # 默认成员（spec）
        assert "password" not in body
        assert "bob-password-123" not in response.text

    def test_duplicate_username_is_409(self, client: TestClient) -> None:
        first = client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob", "display_name": "B", "password": "bob-password-1"},
        )
        assert first.status_code == 201
        second = client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob", "display_name": "B2", "password": "bob-password-2"},
        )
        assert second.status_code == 409
        assert second.json()["error_code"] == "conflict"

    def test_weak_password_is_422_with_rule_id(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob", "display_name": "B", "password": "zz9"},
        )
        assert response.status_code == 422
        assert response.json()["error_code"] == "validation_error"
        assert response.json()["details"]["rule"] == "password_too_short"
        assert "zz9" not in response.text  # 不回显密码

    def test_password_same_as_username_is_422(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob-username-x", "display_name": "B",
                  "password": "bob-username-x"},
        )
        assert response.status_code == 422
        assert response.json()["details"]["rule"] == "password_same_as_username"


class TestListAndDetail:
    def test_list_envelope_excludes_soft_deleted(
        self, client: TestClient, sqlite_session: Session,
        accounts: dict[str, Account],
    ) -> None:
        accounts["member"].soft_delete()
        sqlite_session.commit()
        response = client.get("/api/v1/users", headers=_auth(client, "root"))
        assert response.status_code == 200
        body = response.json()
        assert set(body) == {"request_id", "items", "page", "size", "total", "has_more"}
        usernames = [item["username"] for item in body["items"]]
        assert "alice" not in usernames  # 软删不在列表
        assert body["total"] == 1  # total 也不计软删

    def test_detail_404_for_missing_and_soft_deleted(
        self, client: TestClient, sqlite_session: Session,
        accounts: dict[str, Account],
    ) -> None:
        missing = client.get(
            f"/api/v1/users/{uuid.uuid4()}", headers=_auth(client, "root")
        )
        assert missing.status_code == 404

        target_id = accounts["member"].id
        accounts["member"].soft_delete()
        sqlite_session.commit()
        deleted = client.get(f"/api/v1/users/{target_id}", headers=_auth(client, "root"))
        assert deleted.status_code == 404


class TestUpdateAndLifecycle:
    def test_update_display_name_and_username_immutable(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        account_id = accounts["member"].id
        response = client.patch(
            f"/api/v1/users/{account_id}",
            headers=_auth(client, "root"),
            json={"display_name": "Alice Chen", "username": "hacked"},
        )
        assert response.status_code == 200
        assert response.json()["display_name"] == "Alice Chen"
        assert response.json()["username"] == "alice"  # 用户名不可改

    def test_empty_display_name_is_422(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        response = client.patch(
            f"/api/v1/users/{accounts['member'].id}",
            headers=_auth(client, "root"),
            json={"display_name": ""},
        )
        assert response.status_code == 422

    def test_deactivate_then_activate_restores_login(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        account_id = accounts["member"].id
        assert client.post(
            f"/api/v1/users/{account_id}/deactivate", headers=_auth(client, "root")
        ).status_code == 200
        # 停用后无法登录
        denied = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        assert denied.status_code == 401
        # 重新启用后恢复
        assert client.post(
            f"/api/v1/users/{account_id}/activate", headers=_auth(client, "root")
        ).status_code == 200
        restored = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        assert restored.status_code == 200

    def test_reset_password_invalidates_old_credentials_and_sessions(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        """spec：重置后旧密码立即失效；design D14：既有刷新令牌不可续期。

        管理员请求用**独立 client**：cookie jar 按 client 隔离，
        若复用同一 client，root 的登录会覆盖 alice 的刷新 Cookie，
        导致后面的刷新验证失去意义。
        """
        account_id = accounts["member"].id
        assert _login(client, "alice")  # alice 的旧会话 Cookie 留在 client 中
        admin_client = TestClient(client.app)
        response = admin_client.post(
            f"/api/v1/users/{account_id}/reset-password",
            headers=_auth(admin_client, "root"),
            json={"new_password": "brand-new-password-9"},
        )
        assert response.status_code == 200
        assert "brand-new-password-9" not in response.text  # 不回显

        old_login = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        assert old_login.status_code == 401  # 旧密码失效
        # 旧刷新令牌（Cookie 仍为重置前登录所发）不可续期
        assert client.post("/api/v1/auth/refresh").status_code == 401

    def test_soft_deleted_account_cannot_log_in(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        account_id = accounts["member"].id
        response = client.delete(
            f"/api/v1/users/{account_id}", headers=_auth(client, "root")
        )
        assert response.status_code == 200
        denied = client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": PASSWORD},
        )
        assert denied.status_code == 401

    def test_logs_do_not_contain_password(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob", "display_name": "B", "password": "bob-secret-pw-1"},
        )
        client.post(
            "/api/v1/users",
            headers=_auth(client, "root"),
            json={"username": "bob", "display_name": "B", "password": "x"},  # 422 路径
        )
        output = capsys.readouterr().out
        assert "bob-secret-pw-1" not in output


class TestLastAdminProtection:
    """6.9：最后一个已启用 ADMIN 不可停用/软删/降级。"""

    def _admin_id(self, accounts: dict[str, Account]) -> object:
        return accounts["admin"].id

    def test_cannot_deactivate_last_admin(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        response = client.post(
            f"/api/v1/users/{self._admin_id(accounts)}/deactivate",
            headers=_auth(client, "root"),
        )
        assert response.status_code == 409
        assert response.json()["error_code"] == "conflict"
        assert accounts["admin"].is_active is True

    def test_cannot_demote_last_admin(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        response = client.patch(
            f"/api/v1/users/{self._admin_id(accounts)}",
            headers=_auth(client, "root"),
            json={"system_role": "MEMBER"},
        )
        assert response.status_code == 409
        assert accounts["admin"].system_role == "ADMIN"

    def test_cannot_soft_delete_last_admin(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        response = client.delete(
            f"/api/v1/users/{self._admin_id(accounts)}", headers=_auth(client, "root")
        )
        assert response.status_code == 409
        assert accounts["admin"].deleted_at is None

    def test_second_admin_allows_demotion(
        self, client: TestClient, sqlite_session: Session,
        accounts: dict[str, Account],
    ) -> None:
        sqlite_session.add(
            Account(
                username="root2",
                display_name="Root2",
                password_hash=hash_password(PASSWORD),
                system_role="ADMIN",
            )
        )
        sqlite_session.commit()
        response = client.patch(
            f"/api/v1/users/{self._admin_id(accounts)}",
            headers=_auth(client, "root"),
            json={"system_role": "MEMBER"},
        )
        assert response.status_code == 200
        assert accounts["admin"].system_role == "MEMBER"

    def test_concurrent_deactivate_and_demote_keep_one_admin(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        """串行化模拟并发：两次操作至少一次被拒，且管理员仍启用。"""
        admin_id = self._admin_id(accounts)
        first = client.post(
            f"/api/v1/users/{admin_id}/deactivate", headers=_auth(client, "root")
        )
        second = client.patch(
            f"/api/v1/users/{admin_id}",
            headers=_auth(client, "root"),
            json={"system_role": "MEMBER"},
        )
        rejected = [r for r in (first, second) if r.status_code == 409]
        assert len(rejected) >= 1
        assert accounts["admin"].is_active is True
        assert accounts["admin"].system_role == "ADMIN"

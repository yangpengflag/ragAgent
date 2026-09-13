"""§6.11/6.12 红灯：认证与账号管理审计日志。

spec「认证事件审计」：登录成功/失败、限流触发、刷新失败、登出、账号写操作
均产生结构化日志且含 `request_id`；密码与令牌原文不出现。
structlog 走 stdout，用 capsys 断言。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_rate_limit_store, get_revocation_store
from app.core.security import hash_password
from app.main import create_app
from app.models.user import Account
from app.services.ports import InMemoryRateLimitStore, InMemoryRevocationStore

PASSWORD = "correct-horse-42"


@pytest.fixture
def accounts(sqlite_session: Session) -> dict[str, Account]:
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
def rate_store() -> InMemoryRateLimitStore:
    """每个测试一个新实例：跨测试共享会残留失败计数，但也必须
    在单个测试内保持单例（override 每请求调用一次）。"""
    return InMemoryRateLimitStore()


@pytest.fixture
def client(
    sqlite_session: Session, accounts: dict[str, Account], rate_store: InMemoryRateLimitStore
) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: sqlite_session
    app.dependency_overrides[get_revocation_store] = lambda: InMemoryRevocationStore()
    app.dependency_overrides[get_rate_limit_store] = lambda: rate_store
    return TestClient(app)


def _events(output: str) -> list[dict[str, object]]:
    events = []
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("{"):
            events.append(json.loads(line))
    return events


def _auth(client: TestClient, username: str = "root") -> dict[str, str]:
    response = client.post(
        "/api/v1/auth/login", json={"username": username, "password": PASSWORD}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestAuthAuditLogs:
    def test_login_success_failure_and_rate_limit_logged(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()  # 清掉 fixture 阶段输出
        assert client.post(
            "/api/v1/auth/login",
            json={"username": "alice", "password": "wrong-password-1"},
        ).status_code == 401
        assert client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
        ).status_code == 200

        events = _events(capsys.readouterr().out)
        names = [str(e.get("event")) for e in events]
        assert "login failed" in names
        assert "login succeeded" in names

        failed = next(e for e in events if e.get("event") == "login failed")
        assert failed["username"] == "alice"
        assert failed["client"] == "testclient"
        assert failed["request_id"]  # request_id 已注入
        # 失败日志不含密码
        assert "wrong-password-1" not in json.dumps(events)

        # 限流触发也留痕（成功登录已清零计数：重新累计 5 次失败后再尝试）
        for _ in range(5):
            client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "wrong-password-1"},
            )
        capsys.readouterr()
        blocked = client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
        )
        assert blocked.status_code == 429
        names = [
            str(e.get("event"))
            for e in _events(capsys.readouterr().out)
        ]
        assert "login rate limited" in names

    def test_refresh_failure_logged(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        capsys.readouterr()
        response = client.post("/api/v1/auth/refresh")
        assert response.status_code == 401
        names = [str(e.get("event")) for e in _events(capsys.readouterr().out)]
        assert "refresh rejected: no token" in names

    def test_logout_logged(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
        ).status_code == 200
        capsys.readouterr()
        assert client.post("/api/v1/auth/logout").status_code == 200
        events = _events(capsys.readouterr().out)
        logout = next(e for e in events if e.get("event") == "logout")
        assert logout["account_id"]
        assert logout["client"]
        # 令牌原文不落日志
        assert "eyJ" not in json.dumps(events)


class TestAccountWriteAuditLogs:
    def test_write_ops_logged_with_request_id_and_no_password(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        headers = _auth(client)
        capsys.readouterr()

        created = client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "bob", "display_name": "B", "password": "bob-secret-pw-9"},
        )
        assert created.status_code == 201
        deleted = client.delete(
            f"/api/v1/users/{created.json()['id']}", headers=headers
        )
        assert deleted.status_code == 200

        events = _events(capsys.readouterr().out)
        names = [str(e.get("event")) for e in events]
        assert "account created" in names
        assert "account deleted" in names
        created_event = next(e for e in events if e.get("event") == "account created")
        assert created_event["request_id"]
        assert created_event["client"] == "testclient"
        # 密码不落日志（成功路径）
        assert "bob-secret-pw-9" not in json.dumps(events)

    def test_reset_password_log_has_no_password(
        self, client: TestClient, accounts: dict[str, Account],
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        headers = _auth(client)
        capsys.readouterr()
        response = client.post(
            f"/api/v1/users/{accounts['member'].id}/reset-password",
            headers=headers,
            json={"new_password": "reset-secret-pw-77"},
        )
        assert response.status_code == 200
        assert "reset-secret-pw-77" not in response.text
        output = capsys.readouterr().out
        assert "reset-secret-pw-77" not in output
        names = [str(e.get("event")) for e in _events(output)]
        assert "account password reset" in names

    def test_password_too_long_reports_rule_id(
        self, client: TestClient, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """密码 >128 曾被 pydantic 抢跑导致 rule 标识不可达——现在统一走策略。"""
        headers = _auth(client)
        response = client.post(
            "/api/v1/users",
            headers=headers,
            json={"username": "bob", "display_name": "B", "password": "x" * 129},
        )
        assert response.status_code == 422
        assert response.json()["details"]["rule"] == "password_too_long"


class TestPromotion:
    def test_promoted_member_gains_admin_capability(
        self, client: TestClient, accounts: dict[str, Account]
    ) -> None:
        """identity spec「提升为管理员」：改角色后必须真的具备 ADMIN 能力。"""
        account_id = accounts["member"].id
        response = client.patch(
            f"/api/v1/users/{account_id}",
            headers=_auth(client),
            json={"system_role": "ADMIN"},
        )
        assert response.status_code == 200
        assert response.json()["system_role"] == "ADMIN"

        # 用 alice 的新令牌访问 ADMIN-only 接口
        login = client.post(
            "/api/v1/auth/login", json={"username": "alice", "password": PASSWORD}
        )
        token = login.json()["access_token"]
        listed = client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
        assert listed.status_code == 200

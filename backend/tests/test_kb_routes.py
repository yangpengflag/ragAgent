"""知识库路由红灯（knowledge-base-crud 任务 4.1）。

路由层只验契约：状态码、响应形状与权限。业务逻辑由服务层测试覆盖。
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.exceptions import AccessDeniedError
from app.core.ids import uuid7
from app.main import create_app
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account, SystemRole
from app.models.user_kb_grant import KbRole, UserKbGrant
from app.services import kb_service


def _user(
    session: Session, username: str = "alice", role: SystemRole = SystemRole.MEMBER
) -> Account:
    account = Account(
        username=username,
        display_name=username.title(),
        password_hash="$argon2id$placeholder",
        system_role=role,
    )
    session.add(account)
    session.flush()
    return account


def _kb(session: Session, name: str = "产品文档库") -> KnowledgeBase:
    return kb_service.create_kb(
        session,
        name=name,
        description="描述",
        embedding_model="qwen3.7-text-embedding",
        embed_dim=1024,
    )


class _Fixture:
    """把会话与"当前用户"注入应用，避免走真实鉴权。"""

    def __init__(self, session: Session, account: Account | None) -> None:
        self.session = session
        self.account = account
        self.app = create_app()
        self.app.dependency_overrides[get_db] = lambda: session
        self.app.dependency_overrides[get_current_user] = self._current_user
        self.client = TestClient(self.app)

    def _current_user(self) -> Account:
        if self.account is None:
            raise AccessDeniedError("权限不足（测试替身）")
        return self.account


def _as(session: Session, account: Account | None) -> TestClient:
    return _Fixture(session, account).client


def test_create_returns_201_with_fields(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    client = _as(sqlite_session, admin)

    response = client.post(
        "/api/v1/knowledge-bases",
        json={
            "name": "产品文档库",
            "description": "描述",
            "embedding_model": "qwen3.7-text-embedding",
            "embed_dim": 1024,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["name"] == "产品文档库"
    assert body["embed_dim"] == 1024
    assert body["request_id"]
    # 不暴露内部派生列
    assert "name_active" not in body


def test_create_duplicate_returns_409(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    _kb(sqlite_session, "重名")
    client = _as(sqlite_session, admin)

    response = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "重名", "embedding_model": "m", "embed_dim": 1024},
    )

    assert response.status_code == 409
    assert response.json()["error_code"] == "conflict"


def test_member_cannot_create(sqlite_session: Session):
    member = _user(sqlite_session, "alice", SystemRole.MEMBER)
    client = _as(sqlite_session, member)

    response = client.post(
        "/api/v1/knowledge-bases",
        json={"name": "库", "embedding_model": "m", "embed_dim": 1024},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "access_denied"


def test_list_returns_items(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    _kb(sqlite_session, "A")
    client = _as(sqlite_session, admin)

    body = client.get("/api/v1/knowledge-bases").json()

    assert [item["name"] for item in body["items"]] == ["A"]


def test_detail_and_update(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _as(sqlite_session, admin)

    assert client.get(f"/api/v1/knowledge-bases/{kb.id}").status_code == 200

    updated = client.patch(
        f"/api/v1/knowledge-bases/{kb.id}", json={"name": "新名称"}
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "新名称"


def test_detail_missing_returns_404(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    client = _as(sqlite_session, admin)

    response = client.get(f"/api/v1/knowledge-bases/{uuid7()}")

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_soft_delete_hides_from_list(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _as(sqlite_session, admin)

    assert client.delete(f"/api/v1/knowledge-bases/{kb.id}").status_code == 200
    assert client.get("/api/v1/knowledge-bases").json()["items"] == []


def test_kb_admin_can_update_own_kb(sqlite_session: Session):
    """库级管理员可管理本库（K3）。"""
    kb_admin = _user(sqlite_session, "owner", SystemRole.MEMBER)
    kb = _kb(sqlite_session)
    sqlite_session.add(
        UserKbGrant(user_id=kb_admin.id, kb_id=kb.id, role=KbRole.KB_ADMIN)
    )
    sqlite_session.commit()
    client = _as(sqlite_session, kb_admin)

    response = client.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"name": "本库改名"})

    assert response.status_code == 200
    assert response.json()["name"] == "本库改名"


def test_kb_admin_cannot_touch_other_kb(sqlite_session: Session):
    """库级管理员不能跨库（K3）。"""
    kb_admin = _user(sqlite_session, "owner", SystemRole.MEMBER)
    own = _kb(sqlite_session, "本库")
    other = _kb(sqlite_session, "他库")
    sqlite_session.add(UserKbGrant(user_id=kb_admin.id, kb_id=own.id, role=KbRole.KB_ADMIN))
    sqlite_session.commit()
    client = _as(sqlite_session, kb_admin)

    response = client.patch(
        f"/api/v1/knowledge-bases/{other.id}", json={"name": "跨库改名"}
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "access_denied"


def test_viewer_cannot_update(sqlite_session: Session):
    viewer = _user(sqlite_session, "viewer", SystemRole.MEMBER)
    kb = _kb(sqlite_session)
    sqlite_session.add(UserKbGrant(user_id=viewer.id, kb_id=kb.id, role=KbRole.VIEWER))
    sqlite_session.commit()
    client = _as(sqlite_session, viewer)

    assert (
        client.patch(f"/api/v1/knowledge-bases/{kb.id}", json={"name": "x"}).status_code
        == 403
    )


def test_app_is_used_for_every_case(sqlite_session: Session):
    """守卫：确认测试确实打到了真实应用（而非空壳）。"""
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    client = _as(sqlite_session, admin)
    assert isinstance(create_app(), FastAPI)
    assert client.get("/openapi.json").status_code == 200

"""成员授权路由红灯（knowledge-base-crud 任务 4.3）。

覆盖：授予 / 改角色 / 移除 / 列举，以及"非管理者不得操作"。
"""

from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

# tests/ 目录被 pytest 插入 sys.path（无 __init__.py），可直接复用同目录装配
from test_kb_routes import _Fixture, _kb, _user

from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account, SystemRole
from app.models.user_kb_grant import KbRole, UserKbGrant
from app.services import kb_service


def _client(session: Session, account: Account | None) -> TestClient:
    return _Fixture(session, account).client


def _member(session: Session, username: str = "bob") -> Account:
    return _user(session, username, SystemRole.MEMBER)


def test_grant_member_returns_membership(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    bob = _member(sqlite_session)
    client = _client(sqlite_session, admin)

    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(bob.id)
    assert body["role"] == "VIEWER"
    assert body["request_id"]


def test_grant_twice_overwrites_role(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    bob = _member(sqlite_session)
    client = _client(sqlite_session, admin)

    client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )
    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "EDITOR"},
    )

    assert response.json()["role"] == "EDITOR"
    listed = client.get(f"/api/v1/knowledge-bases/{kb.id}/members").json()
    assert len(listed["items"]) == 1


def test_list_members_returns_role(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    bob = _member(sqlite_session)
    client = _client(sqlite_session, admin)
    client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "KB_ADMIN"},
    )

    body = client.get(f"/api/v1/knowledge-bases/{kb.id}/members").json()

    assert body["items"] == [
        {
            "user_id": str(bob.id),
            "username": "bob",
            "display_name": "Bob",
            "role": "KB_ADMIN",
        }
    ]


def test_revoke_member_removes_membership(sqlite_session: Session):
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    bob = _member(sqlite_session)
    client = _client(sqlite_session, admin)
    client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )

    response = client.delete(f"/api/v1/knowledge-bases/{kb.id}/members/{bob.id}")

    assert response.status_code == 200
    assert client.get(f"/api/v1/knowledge-bases/{kb.id}/members").json()["items"] == []


def test_grant_unknown_user_returns_404(sqlite_session: Session):
    from app.core.ids import uuid7

    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    client = _client(sqlite_session, admin)

    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(uuid7()), "role": "VIEWER"},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_editor_cannot_manage_members(sqlite_session: Session):
    """EDITOR 无管理权（K3）。"""
    kb: KnowledgeBase = _kb(sqlite_session)
    editor = _user(sqlite_session, "ed", SystemRole.MEMBER)
    bob = _member(sqlite_session, "bob2")
    sqlite_session.add(UserKbGrant(user_id=editor.id, kb_id=kb.id, role=KbRole.EDITOR))
    sqlite_session.commit()
    client = _client(sqlite_session, editor)

    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )

    assert response.status_code == 403
    assert response.json()["error_code"] == "access_denied"


def test_kb_admin_can_manage_own_members(sqlite_session: Session):
    kb = _kb(sqlite_session)
    owner = _user(sqlite_session, "owner", SystemRole.MEMBER)
    bob = _member(sqlite_session, "bob3")
    sqlite_session.add(
        UserKbGrant(user_id=owner.id, kb_id=kb.id, role=KbRole.KB_ADMIN)
    )
    sqlite_session.commit()
    client = _client(sqlite_session, owner)

    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )

    assert response.status_code == 200


def test_member_ops_on_soft_deleted_kb_are_rejected(sqlite_session: Session):
    """软删库不可再操作：对 ADMIN 表现为 404（资源已不存在）。

    注意区分两类拒绝：库级管理员在**未软删但无授权**的库上是 403；
    库被软删后对所有人都是"不存在"（404），而不是"无权"（403）——
    后者会向无授权者泄露"该库是否曾存在"。
    """
    admin = _user(sqlite_session, "root", SystemRole.ADMIN)
    kb = _kb(sqlite_session)
    bob = _member(sqlite_session, "bob4")
    client = _client(sqlite_session, admin)
    kb_service.soft_delete_kb(sqlite_session, kb.id)

    response = client.put(
        f"/api/v1/knowledge-bases/{kb.id}/members",
        json={"user_id": str(bob.id), "role": "VIEWER"},
    )

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"

"""知识库授权服务红灯（knowledge-base-crud 任务 2.3）。

授权是检索阶段权限过滤的**唯一真相源**：授予立即生效、撤销立即失效。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.ids import uuid7
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account
from app.models.user_kb_grant import KbRole, UserKbGrant
from app.services import kb_grant_service, kb_service


def _kb(sqlite_session: Session, name: str = "库") -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session,
        name=name,
        description=None,
        embedding_model="qwen3.7-text-embedding",
        embed_dim=1024,
    )


def _user(sqlite_session: Session, username: str = "alice") -> Account:
    account = Account(
        username=username,
        display_name=username.title(),
        password_hash="$argon2id$placeholder",
    )
    sqlite_session.add(account)
    sqlite_session.flush()
    return account


def test_grant_creates_membership(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)

    grant = kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )

    assert grant.role == KbRole.VIEWER
    assert kb_grant_service.list_members(sqlite_session, kb.id) == [(user, KbRole.VIEWER)]


def test_grant_is_idempotent_and_overwrites_role(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)

    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.EDITOR
    )

    members = kb_grant_service.list_members(sqlite_session, kb.id)
    assert len(members) == 1
    assert members[0][1] == KbRole.EDITOR


def test_revoke_removes_membership_and_is_idempotent(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )

    kb_grant_service.revoke_grant(sqlite_session, user_id=user.id, kb_id=kb.id)
    assert kb_grant_service.list_members(sqlite_session, kb.id) == []

    # 再次撤销不报错（幂等）
    kb_grant_service.revoke_grant(sqlite_session, user_id=user.id, kb_id=kb.id)


def test_list_members_excludes_other_kbs(sqlite_session: Session):
    kb_a = _kb(sqlite_session, name="A")
    kb_b = _kb(sqlite_session, name="B")
    alice = _user(sqlite_session, "alice")
    bob = _user(sqlite_session, "bob")
    kb_grant_service.grant_role(
        sqlite_session, user_id=alice.id, kb_id=kb_a.id, role=KbRole.VIEWER
    )
    kb_grant_service.grant_role(
        sqlite_session, user_id=bob.id, kb_id=kb_b.id, role=KbRole.KB_ADMIN
    )

    assert [m[0].username for m in kb_grant_service.list_members(sqlite_session, kb_a.id)] == [
        "alice"
    ]


def test_grant_unknown_user_raises_not_found(sqlite_session: Session):
    kb = _kb(sqlite_session)

    with pytest.raises(NotFoundError):
        kb_grant_service.grant_role(
            sqlite_session, user_id=uuid7(), kb_id=kb.id, role=KbRole.VIEWER
        )


def test_grant_soft_deleted_kb_raises_not_found(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)
    kb_service.soft_delete_kb(sqlite_session, kb.id)

    with pytest.raises(NotFoundError):
        kb_grant_service.grant_role(
            sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
        )


def test_role_of_returns_current_role(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.KB_ADMIN
    )

    assert (
        kb_grant_service.role_of(sqlite_session, user_id=user.id, kb_id=kb.id)
        == KbRole.KB_ADMIN
    )


def test_role_of_returns_none_without_grant(sqlite_session: Session):
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)

    assert kb_grant_service.role_of(sqlite_session, user_id=user.id, kb_id=kb.id) is None


def test_grant_rows_are_removed_not_soft_deleted(sqlite_session: Session):
    """撤销是删行：授权表没有软删字段，避免"漏过滤即越权"。"""
    kb = _kb(sqlite_session)
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )
    kb_grant_service.revoke_grant(sqlite_session, user_id=user.id, kb_id=kb.id)

    remaining = (
        sqlite_session.query(UserKbGrant)
        .filter(UserKbGrant.user_id == user.id, UserKbGrant.kb_id == kb.id)
        .count()
    )
    assert remaining == 0

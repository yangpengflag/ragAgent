"""授权集合读取红灯（knowledge-base-crud 任务 3.1 / 3.3）。

这是检索阶段权限过滤的**数据落点**：

- 返回用户在业务库中的全部有效授权
- **软删知识库必须被排除**（design K5：否则"库已删仍被检索"就是越权窗口）
- 提供二次鉴权查询：判断某用户能否访问指定知识库 / 指定候选集合
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account
from app.models.user_kb_grant import KbRole
from app.services import kb_grant_service, kb_service
from app.services.kb_grant_reader import SessionKbGrantReader, build_kb_access_resolver


def _kb(sqlite_session: Session, name: str) -> KnowledgeBase:
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


def test_kb_ids_for_user_returns_all_grants(sqlite_session: Session):
    kb_a = _kb(sqlite_session, "A")
    kb_b = _kb(sqlite_session, "B")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb_a.id, role=KbRole.VIEWER
    )
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb_b.id, role=KbRole.KB_ADMIN
    )

    ids = kb_grant_service.kb_ids_for_user(sqlite_session, user_id=user.id)

    assert sorted(ids) == sorted([str(kb_a.id), str(kb_b.id)])


def test_kb_ids_for_user_excludes_soft_deleted_kb(sqlite_session: Session):
    """软删库不得出现在授权集合中（K5）。"""
    alive = _kb(sqlite_session, "在库")
    gone = _kb(sqlite_session, "已删")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=alive.id, role=KbRole.VIEWER
    )
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=gone.id, role=KbRole.VIEWER
    )
    kb_service.soft_delete_kb(sqlite_session, gone.id)

    assert kb_grant_service.kb_ids_for_user(sqlite_session, user_id=user.id) == [
        str(alive.id)
    ]


def test_kb_ids_for_user_empty_without_grants(sqlite_session: Session):
    user = _user(sqlite_session)

    assert kb_grant_service.kb_ids_for_user(sqlite_session, user_id=user.id) == []


def test_can_access_kb_reflects_grant(sqlite_session: Session):
    kb = _kb(sqlite_session, "库")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )

    assert kb_grant_service.can_access_kb(
        sqlite_session, user_id=user.id, kb_id=kb.id
    )
    # 未授权的库（这里用另一个未授权库）
    other = _kb(sqlite_session, "他库")
    assert not kb_grant_service.can_access_kb(
        sqlite_session, user_id=user.id, kb_id=other.id
    )


def test_can_access_kb_false_for_soft_deleted_kb(sqlite_session: Session):
    kb = _kb(sqlite_session, "库")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )
    kb_service.soft_delete_kb(sqlite_session, kb.id)

    assert not kb_grant_service.can_access_kb(
        sqlite_session, user_id=user.id, kb_id=kb.id
    )


def test_reader_adapter_implements_port(sqlite_session: Session):
    """`SessionKbGrantReader` 必须满足 `KbGrantReader` 端口（结构化类型）。"""
    from app.services.kb_access import KbGrantReader

    reader = SessionKbGrantReader(lambda: sqlite_session)
    assert isinstance(reader, KbGrantReader)


def test_reader_adapter_reads_through_session(sqlite_session: Session):
    kb = _kb(sqlite_session, "库")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )

    reader = SessionKbGrantReader(lambda: sqlite_session)
    assert reader.kb_ids_for_user(str(user.id)) == [str(kb.id)]


def test_reader_adapter_rejects_invalid_user_id(sqlite_session: Session):
    """端口契约是字符串 user_id：非法 UUID 应显式失败而不是静默返回空集合。"""
    reader = SessionKbGrantReader(lambda: sqlite_session)
    with pytest.raises(ValueError):
        reader.kb_ids_for_user("not-a-uuid")


def test_build_resolver_reads_real_grants(sqlite_session: Session, monkeypatch):
    """装配出的 resolver 必须从业务库读到真授权（而非端口替身）。"""
    import app.core.db as db

    monkeypatch.setattr(db, "get_session_factory", lambda: (lambda: sqlite_session))
    kb = _kb(sqlite_session, "库")
    user = _user(sqlite_session)
    kb_grant_service.grant_role(
        sqlite_session, user_id=user.id, kb_id=kb.id, role=KbRole.VIEWER
    )

    resolver = build_kb_access_resolver()

    assert resolver.authorized_kb_ids(str(user.id)) == [str(kb.id)]

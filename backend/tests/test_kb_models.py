"""知识库与授权模型红灯（knowledge-base-crud 任务 1.1 / 1.3）。

在 SQLite 内存库上验证（不依赖 MySQL）：

- 知识库名称：**活跃唯一、软删让位**（与账号同款派生列方案）
- 软删的知识库不出现在任何授权集合中（避免"库已删仍被检索"的越权窗口）
- 同一用户在同一知识库只持一个角色
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import INCLUDE_SOFT_DELETED
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account
from app.models.user_kb_grant import KbRole, UserKbGrant


def _new_kb(name: str = "产品文档库", **overrides: object) -> KnowledgeBase:
    payload: dict[str, object] = {
        "name": name,
        "description": "用于检索问答的知识库",
        "embedding_model": "qwen3.7-text-embedding",
        "embed_dim": 1024,
    }
    payload.update(overrides)
    return KnowledgeBase(**payload)  # type: ignore[arg-type]


def _new_account(username: str = "alice") -> Account:
    return Account(
        username=username,
        display_name=username.title(),
        password_hash="$argon2id$placeholder",
    )


def test_kb_public_fields_and_defaults(sqlite_session):
    kb = _new_kb()
    sqlite_session.add(kb)
    sqlite_session.commit()

    assert isinstance(kb.id, uuid.UUID)
    assert kb.created_at is not None and kb.deleted_at is None
    assert kb.name == "产品文档库"
    assert kb.embedding_model == "qwen3.7-text-embedding"
    assert kb.embed_dim == 1024


def test_active_kb_name_is_unique(sqlite_session):
    sqlite_session.add(_new_kb("同名库"))
    sqlite_session.commit()

    sqlite_session.add(_new_kb("同名库"))
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()


def test_soft_deleted_kb_name_can_be_reused(sqlite_session):
    first = _new_kb("可复用库")
    sqlite_session.add(first)
    sqlite_session.commit()
    first.soft_delete()
    sqlite_session.commit()

    second = _new_kb("可复用库")
    sqlite_session.add(second)
    sqlite_session.commit()

    assert second.id != first.id


def test_soft_deleted_kb_is_invisible_by_default(sqlite_session):
    kb = _new_kb()
    sqlite_session.add(kb)
    sqlite_session.commit()
    kb_id = kb.id
    kb.soft_delete()
    sqlite_session.commit()
    # 清掉 identity map：否则 session.get 直接返回内存中那个已软删的实例
    sqlite_session.expire_all()

    assert sqlite_session.get(KnowledgeBase, kb_id) is None
    # 逃生通道仍可查到（审计/对账用）
    found = (
        sqlite_session.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.id == kb_id)
            .execution_options(**{INCLUDE_SOFT_DELETED: True})
        )
        .scalars()
        .one_or_none()
    )
    assert found is not None


def test_one_role_per_user_per_kb(sqlite_session: Session):
    kb = _new_kb()
    account = _new_account()
    sqlite_session.add_all([kb, account])
    sqlite_session.commit()

    sqlite_session.add(UserKbGrant(user_id=account.id, kb_id=kb.id, role=KbRole.VIEWER))
    sqlite_session.commit()

    # 同库再授一次：覆盖而非新增（复合主键相同）
    grant = sqlite_session.get(UserKbGrant, {"user_id": account.id, "kb_id": kb.id})
    assert grant is not None
    grant.role = KbRole.EDITOR
    sqlite_session.commit()

    rows = (
        sqlite_session.execute(
            select(UserKbGrant).where(UserKbGrant.user_id == account.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1
    assert rows[0].role == KbRole.EDITOR


def test_grant_rows_survive_kb_soft_delete(sqlite_session: Session):
    """软删知识库后授权行保留（撤销靠删行，库软删不级联删授权）。

    注意：软删过滤只在 `KnowledgeBase` 作为**主实体**时由全局钩子附加；
    JOIN 场景必须显式加 `deleted_at IS NULL`——这正是仓储层
    `kb_ids_for_user` 的责任（任务 3.1 会断言"软删库不出现在授权集合"）。
    """
    kb = _new_kb()
    account = _new_account()
    sqlite_session.add_all([kb, account])
    sqlite_session.commit()
    sqlite_session.add(UserKbGrant(user_id=account.id, kb_id=kb.id, role=KbRole.VIEWER))
    sqlite_session.commit()
    kb.soft_delete()
    sqlite_session.commit()
    sqlite_session.expire_all()

    rows = (
        sqlite_session.execute(
            select(UserKbGrant).where(UserKbGrant.user_id == account.id)
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1

    # 带显式过滤时，软删库被排除（仓储实现将采用这一写法）
    visible = (
        sqlite_session.execute(
            select(UserKbGrant)
            .join(KnowledgeBase, KnowledgeBase.id == UserKbGrant.kb_id)
            .where(
                UserKbGrant.user_id == account.id,
                KnowledgeBase.deleted_at.is_(None),
            )
        )
        .scalars()
        .all()
    )
    assert visible == []

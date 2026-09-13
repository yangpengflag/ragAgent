"""知识库授权服务（库级角色）。

授权记录是检索阶段权限过滤的**唯一真相源**：授予立即生效、撤销立即失效。
撤销采用**删行**而非软删——授权行一旦漏过滤就是越权窗口，软删在这里只有风险没有收益。
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.logging import get_logger
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account
from app.models.user_kb_grant import KbRole, UserKbGrant

logger = get_logger()


def _exists(session: Session, model: type, entity_id: uuid.UUID) -> bool:
    """存在性检查用 select 而非 `Session.get`。

    `get()` 会命中 identity map 直接返回内存中那个**已软删**的实例，
    而 select 会走全局软删过滤——这正是我们想要的行为。
    """
    return (
        session.execute(
            select(model.id).where(model.id == entity_id)  # type: ignore[attr-defined]
        ).first()
        is not None
    )


def _load_active(session: Session, *, user_id: uuid.UUID, kb_id: uuid.UUID) -> None:
    """校验用户与知识库均存在且未软删。"""
    if not _exists(session, Account, user_id):
        raise NotFoundError("用户不存在")
    if not _exists(session, KnowledgeBase, kb_id):
        raise NotFoundError("知识库不存在")


def grant_role(
    session: Session, *, user_id: uuid.UUID, kb_id: uuid.UUID, role: KbRole
) -> UserKbGrant:
    """授予或覆盖用户在某库的角色（同一用户同一库只持一个角色）。"""
    _load_active(session, user_id=user_id, kb_id=kb_id)
    grant = session.get(UserKbGrant, {"user_id": user_id, "kb_id": kb_id})  # 授权表无软删
    if grant is None:
        grant = UserKbGrant(user_id=user_id, kb_id=kb_id, role=role)
        session.add(grant)
    else:
        grant.role = role
    session.flush()
    logger.info(
        "kb grant upserted",
        user_id=str(user_id),
        kb_id=str(kb_id),
        role=str(role),
    )
    return grant


def revoke_grant(session: Session, *, user_id: uuid.UUID, kb_id: uuid.UUID) -> None:
    """撤销授权（删行）。幂等：无授权记录时不报错。"""
    session.execute(
        delete(UserKbGrant).where(
            UserKbGrant.user_id == user_id, UserKbGrant.kb_id == kb_id
        )
    )
    session.flush()
    logger.info("kb grant revoked", user_id=str(user_id), kb_id=str(kb_id))


def role_of(
    session: Session, *, user_id: uuid.UUID, kb_id: uuid.UUID
) -> KbRole | None:
    """用户在某库的当前角色；无授权返回 None（供路由层做权限判定）。"""
    grant = session.get(UserKbGrant, {"user_id": user_id, "kb_id": kb_id})
    return None if grant is None else grant.role


def kb_ids_for_user(session: Session, *, user_id: uuid.UUID) -> list[str]:
    """用户在业务库中的全部有效授权（检索阶段过滤的输入）。

    必须**显式排除已软删的知识库**：软删过滤只在知识库作为主实体时由全局钩子
    附加，JOIN 场景不会自动带上；漏掉这一条件是"库已删仍被检索"的越权窗口。
    """
    rows = session.execute(
        select(UserKbGrant.kb_id)
        .join(KnowledgeBase, KnowledgeBase.id == UserKbGrant.kb_id)
        .where(
            UserKbGrant.user_id == user_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    ).scalars().all()
    return [str(kb_id) for kb_id in rows]


def can_access_kb(session: Session, *, user_id: uuid.UUID, kb_id: uuid.UUID) -> bool:
    """二次鉴权：用户当前是否可访问该知识库（软删库一律不可访问）。

    供返回引用 / chunk 原文前复核使用——检索阶段过滤之外的一道独立校验。
    """
    row = session.execute(
        select(UserKbGrant.kb_id)
        .join(KnowledgeBase, KnowledgeBase.id == UserKbGrant.kb_id)
        .where(
            UserKbGrant.user_id == user_id,
            UserKbGrant.kb_id == kb_id,
            KnowledgeBase.deleted_at.is_(None),
        )
    ).first()
    return row is not None


def list_members(session: Session, kb_id: uuid.UUID) -> list[tuple[Account, KbRole]]:
    """列出某库的成员及其角色（按用户名排序，保证结果稳定）。"""
    rows = session.execute(
        select(Account, UserKbGrant.role)
        .join(UserKbGrant, UserKbGrant.user_id == Account.id)
        .where(UserKbGrant.kb_id == kb_id)
        .order_by(Account.username)
    ).all()
    return [(row[0], row[1]) for row in rows]

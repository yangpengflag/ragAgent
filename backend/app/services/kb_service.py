"""知识库服务（CRUD + 软删）。

写操作与账号服务同构：唯一冲突 → 409 `conflict`、不存在 → 404 `not_found`、
软删为标记式。服务层不感知 HTTP，权限判定由路由依赖负责。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.models.knowledge_base import KnowledgeBase

logger = get_logger()


def create_kb(
    session: Session,
    *,
    name: str,
    description: str | None = None,
    embedding_model: str,
    embed_dim: int,
) -> KnowledgeBase:
    """创建知识库。名称在活跃范围内唯一（冲突 → 409）。"""
    kb = KnowledgeBase(
        name=name,
        description=description,
        embedding_model=embedding_model,
        embed_dim=embed_dim,
    )
    session.add(kb)
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        logger.info("create kb rejected: duplicate name", name=name)
        raise ConflictError("知识库名称已存在") from exc
    logger.info("kb created", kb_id=str(kb.id), name=name)
    return kb


def list_kbs(session: Session) -> list[KnowledgeBase]:
    """列出全部未软删的知识库（软删过滤由全局钩子附加）。"""
    return list(session.execute(select(KnowledgeBase)).scalars().all())


def get_kb(session: Session, kb_id: uuid.UUID) -> KnowledgeBase:
    """按 id 取知识库；不存在或被软删 → 404。"""
    kb = session.get(KnowledgeBase, kb_id)
    if kb is None:
        raise NotFoundError("知识库不存在")
    return kb


def update_kb(
    session: Session,
    kb_id: uuid.UUID,
    *,
    name: str | None = None,
    description: str | None = None,
    embedding_model: str | None = None,
    embed_dim: int | None = None,
) -> KnowledgeBase:
    """局部更新；未传的字段保持不变。名称冲突 → 409。"""
    kb = get_kb(session, kb_id)
    if name is not None:
        kb.name = name
    if description is not None:
        kb.description = description
    if embedding_model is not None:
        kb.embedding_model = embedding_model
    if embed_dim is not None:
        kb.embed_dim = embed_dim
    try:
        session.flush()
    except IntegrityError as exc:
        session.rollback()
        logger.info("update kb rejected: duplicate name", kb_id=str(kb_id))
        raise ConflictError("知识库名称已存在") from exc
    return kb


def soft_delete_kb(session: Session, kb_id: uuid.UUID) -> None:
    """软删知识库；不存在 → 404。

    授权行不级联删除（保留审计），但软删库不再出现在授权集合里——
    由仓储查询显式排除（见 `KbGrantRepository.kb_ids_for_user`）。
    """
    kb = get_kb(session, kb_id)
    kb.soft_delete()
    session.flush()
    logger.info("kb soft deleted", kb_id=str(kb_id))

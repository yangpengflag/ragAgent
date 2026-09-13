"""知识库服务红灯（knowledge-base-crud 任务 2.1）。

服务层为纯业务逻辑：DB 用内存 SQLite，零真实中间件。
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.ids import uuid7
from app.models.knowledge_base import KnowledgeBase
from app.services import kb_service


def _create(
    sqlite_session: Session, name: str = "产品文档库", **overrides: object
) -> KnowledgeBase:
    payload: dict[str, object] = {
        "name": name,
        "description": "描述",
        "embedding_model": "qwen3.7-text-embedding",
        "embed_dim": 1024,
    }
    payload.update(overrides)
    return kb_service.create_kb(sqlite_session, **payload)  # type: ignore[arg-type]


def test_create_returns_kb_with_generated_fields(sqlite_session: Session):
    kb = _create(sqlite_session)

    assert kb.id is not None
    assert kb.created_at is not None and kb.deleted_at is None
    assert kb.name == "产品文档库"
    assert kb.embed_dim == 1024


def test_create_duplicate_name_conflicts(sqlite_session: Session):
    _create(sqlite_session, name="重名库")

    with pytest.raises(ConflictError):
        _create(sqlite_session, name="重名库")


def test_soft_deleted_name_can_be_reused(sqlite_session: Session):
    first = _create(sqlite_session, name="可复用")
    kb_service.soft_delete_kb(sqlite_session, first.id)

    second = _create(sqlite_session, name="可复用")

    assert second.id != first.id


def test_list_returns_only_active(sqlite_session: Session):
    active = _create(sqlite_session, name="在库")
    gone = _create(sqlite_session, name="已删")
    kb_service.soft_delete_kb(sqlite_session, gone.id)

    items = kb_service.list_kbs(sqlite_session)

    assert [kb.id for kb in items] == [active.id]


def test_get_returns_kb(sqlite_session: Session):
    kb = _create(sqlite_session)

    assert kb_service.get_kb(sqlite_session, kb.id).id == kb.id


def test_get_missing_raises_not_found(sqlite_session: Session):
    with pytest.raises(NotFoundError):
        kb_service.get_kb(sqlite_session, uuid7())


def test_update_changes_fields(sqlite_session: Session):
    kb = _create(sqlite_session)

    updated = kb_service.update_kb(sqlite_session, kb.id, name="新名称", description="新描述")

    assert updated.name == "新名称"
    assert updated.description == "新描述"


def test_soft_delete_marks_and_hides(sqlite_session: Session):
    kb = _create(sqlite_session)

    kb_service.soft_delete_kb(sqlite_session, kb.id)

    assert kb_service.list_kbs(sqlite_session) == []

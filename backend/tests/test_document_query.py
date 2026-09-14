"""文档列表/详情/软删红灯（document-upload-and-parse 任务 3.5）。

列表排除软删、按库过滤；详情不存在 → 404；软删标记式且隐藏。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.core.ids import uuid7
from app.integrations.storage import LocalFileStorage
from app.models.document import Document
from app.models.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session, name="产品文档库", embedding_model="m", embed_dim=128
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _uploaded(
    session: Session, kb: KnowledgeBase, storage: LocalFileStorage, name="a.pdf"
) -> Document:
    return document_service.create_document(
        session,
        kb_id=kb.id,
        filename=name,
        content_type="application/pdf",
        data=b"%PDF-1.4",
        storage=storage,
        allowed_exts=frozenset({"pdf", "docx"}),
        upload_max_bytes=1024,
    )


def test_list_returns_only_active_in_kb(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    active = _uploaded(sqlite_session, kb, storage, "a.pdf")
    gone = _uploaded(sqlite_session, kb, storage, "b.pdf")
    document_service.soft_delete_document(sqlite_session, kb.id, gone.id)

    items = document_service.list_documents(sqlite_session, kb.id)

    assert [d.id for d in items] == [active.id]


def test_list_filters_by_kb(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    _uploaded(sqlite_session, kb, storage, "a.pdf")
    other = kb_service.create_kb(
        sqlite_session, name="另一库", embedding_model="m", embed_dim=128
    )
    _uploaded(sqlite_session, other, storage, "b.pdf")

    items = document_service.list_documents(sqlite_session, kb.id)

    assert len(items) == 1
    assert items[0].filename == "a.pdf"


def test_list_empty(sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage):
    assert document_service.list_documents(sqlite_session, kb.id) == []


def test_get_document_returns_doc(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)

    assert document_service.get_document(sqlite_session, kb.id, doc.id).id == doc.id


def test_get_document_missing_raises_not_found(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    with pytest.raises(NotFoundError):
        document_service.get_document(sqlite_session, kb.id, uuid7())


def test_get_document_from_other_kb_raises_not_found(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    other = kb_service.create_kb(
        sqlite_session, name="另一库", embedding_model="m", embed_dim=128
    )

    with pytest.raises(NotFoundError):
        document_service.get_document(sqlite_session, other.id, doc.id)


def test_soft_delete_marks_and_hides(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)

    document_service.soft_delete_document(sqlite_session, kb.id, doc.id)

    assert doc.deleted_at is not None
    assert document_service.list_documents(sqlite_session, kb.id) == []


def test_soft_delete_missing_raises_not_found(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    with pytest.raises(NotFoundError):
        document_service.soft_delete_document(sqlite_session, kb.id, uuid7())
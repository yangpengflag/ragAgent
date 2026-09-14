"""文档服务红灯（document-upload-and-parse 任务 3.1）。

服务层只做哈希去重 / 大小 / 类型校验与建记录（权限预检在路由层），
用内存 SQLite + 本地临时存储，零真实中间件。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import (
    ConflictError,
    FileTooLargeError,
    UnsupportedFileTypeError,
)
from app.integrations.storage import LocalFileStorage
from app.models.document import DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service

ALLOWED = frozenset({"pdf", "docx"})


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session,
        name="产品文档库",
        embedding_model="qwen3.7-text-embedding",
        embed_dim=1024,
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _create_doc(session: Session, kb: KnowledgeBase, storage: LocalFileStorage, **kw):
    payload: dict[str, object] = {
        "kb_id": kb.id,
        "filename": "政策.pdf",
        "content_type": "application/pdf",
        "data": b"%PDF-1.4 fake content",
        "storage": storage,
        "allowed_exts": ALLOWED,
        "upload_max_bytes": 1024,
    }
    payload.update(kw)
    return document_service.create_document(session, **payload)  # type: ignore[arg-type]


def test_create_returns_document_with_job(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _create_doc(sqlite_session, kb, storage)

    assert doc.id is not None
    assert doc.status == DocumentStatus.UPLOADED
    assert doc.file_size == len(b"%PDF-1.4 fake content")
    assert doc.raw_path is not None and doc.raw_path.endswith("raw.pdf")

    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.document_id == doc.id
    assert job.status == IngestJobStatus.PENDING


def test_create_persists_raw_file(tmp_path: Path, sqlite_session: Session, kb: KnowledgeBase):
    storage = LocalFileStorage(root=tmp_path)
    doc = _create_doc(sqlite_session, kb, storage)

    assert doc.raw_path is not None
    assert storage.open_raw(doc.raw_path) == b"%PDF-1.4 fake content"


def test_create_duplicate_in_same_kb_conflicts(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    first = _create_doc(sqlite_session, kb, storage)
    # 解析成功后再次上传同内容 → 409
    first.status = DocumentStatus.PARSED

    with pytest.raises(ConflictError):
        _create_doc(sqlite_session, kb, storage)


def test_same_hash_in_different_kb_allowed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    _create_doc(sqlite_session, kb, storage)
    other = kb_service.create_kb(
        sqlite_session, name="另一库", embedding_model="m", embed_dim=128
    )

    doc = _create_doc(sqlite_session, other, storage)

    assert doc.kb_id == other.id


def test_failed_doc_not_deduped(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    failed = _create_doc(sqlite_session, kb, storage)
    failed.status = DocumentStatus.FAILED

    retry = _create_doc(sqlite_session, kb, storage)

    assert retry.id != failed.id


def test_create_unsupported_extension_raises(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    with pytest.raises(UnsupportedFileTypeError):
        _create_doc(sqlite_session, kb, storage, filename="note.txt")


def test_create_oversized_raises(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    with pytest.raises(FileTooLargeError):
        _create_doc(
            sqlite_session, kb, storage, upload_max_bytes=4, data=b"0123456789"
        )


def test_soft_deleted_doc_not_deduped(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    gone = _create_doc(sqlite_session, kb, storage)
    gone.status = DocumentStatus.PARSED
    gone.soft_delete()

    doc = _create_doc(sqlite_session, kb, storage)

    assert doc.id != gone.id
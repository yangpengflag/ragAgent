"""Celery `document_parse` 任务红灯（document-upload-and-parse 任务 4.1）。

任务核心 `_parse_document` 用内存 SQLite + 本地临时存储 + MinerU 替身，
覆盖：非 `UPLOADED` 短路（幂等）、`RUNNING→SUCCESS` 推进、异常时文档与
job 均 `FAILED` 且记错误、文档缺失直接忽略。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UpstreamError
from app.core.ids import uuid7
from app.integrations.mineru import ParseResult
from app.integrations.storage import LocalFileStorage
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service
from app.tasks.ingest import _parse_document


class FakeMineru:
    def __init__(self, error: Exception | None = None) -> None:
        self.error = error
        self.calls: list[str] = []

    def parse(self, *, filename: str, data: bytes) -> ParseResult:
        self.calls.append(filename)
        if self.error is not None:
            raise self.error
        return ParseResult(content_list=b'{"blocks": []}')


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session, name="产品文档库", embedding_model="m", embed_dim=128
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _uploaded(session: Session, kb: KnowledgeBase, storage: LocalFileStorage) -> Document:
    return document_service.create_document(
        session,
        kb_id=kb.id,
        filename="政策.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4 fake",
        storage=storage,
        allowed_exts=frozenset({"pdf", "docx"}),
        upload_max_bytes=1024,
    )


def test_short_circuit_when_not_uploaded(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.PARSED
    mineru = FakeMineru()

    ran = _parse_document(sqlite_session, doc.id, storage, mineru)

    assert ran is False
    assert mineru.calls == []


def test_short_circuit_when_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.FAILED
    mineru = FakeMineru()

    ran = _parse_document(sqlite_session, doc.id, storage, mineru)

    assert ran is False
    assert mineru.calls == []


def test_missing_document_ignored(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    mineru = FakeMineru()

    ran = _parse_document(sqlite_session, uuid7(), storage, mineru)

    assert ran is False


def test_advances_uploaded_to_parsed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    mineru = FakeMineru()

    ran = _parse_document(sqlite_session, doc.id, storage, mineru)

    assert ran is True
    assert doc.status == DocumentStatus.PARSED
    assert doc.artifact_path is not None
    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.status == IngestJobStatus.SUCCESS


def test_failure_marks_doc_and_job_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    mineru = FakeMineru(error=UpstreamError("上游超时"))

    ran = _parse_document(sqlite_session, doc.id, storage, mineru)

    assert ran is True
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message == "上游超时"
    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.status == IngestJobStatus.FAILED
    assert job.error == "上游超时"


# ------------------- 中断重放：任务层护栏（fix-ingest-state-and-embedding-contract）


def test_task_replays_document_left_in_parsing(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    """任务层白名单必须放行 `PARSING`——否则中断文档在到达服务层前就被拦掉。"""
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.PARSING
    sqlite_session.flush()
    mineru = FakeMineru()

    ran = _parse_document(sqlite_session, doc.id, storage, mineru)

    assert ran is True
    assert doc.status == DocumentStatus.PARSED
    assert mineru.calls == ["政策.pdf"]
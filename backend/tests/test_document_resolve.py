"""解析编排红灯（document-upload-and-parse 任务 3.3）。

验证状态机推进 `UPLOADED→PARSED` / `UPLOADED→FAILED`；置 `PARSED` 前先落盘产物；
`ingest_job` 同步更新；对非 `UPLOADED` 文档重放幂等。
MinerU 客户端用替身，避免真实网络。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.exceptions import UpstreamError
from app.integrations.mineru import ParseResult
from app.integrations.storage import LocalFileStorage
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service


class FakeMineru:
    def __init__(self, result: ParseResult | None = None, error: Exception | None = None) -> None:
        self.result = result or ParseResult(content_list=b'{"blocks": [{"type": "text"}]}')
        self.error = error
        self.calls: list[str] = []

    def parse(self, *, filename: str, data: bytes) -> ParseResult:
        self.calls.append(filename)
        if self.error is not None:
            raise self.error
        return self.result


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


def test_resolve_success_advances_status(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    mineru = FakeMineru()

    document_service.resolve_parse(sqlite_session, doc, storage, mineru)

    assert doc.status == DocumentStatus.PARSED
    assert doc.artifact_path is not None and doc.artifact_path.endswith("content_list.json")
    assert storage.open_artifact(doc.artifact_path) == b'{"blocks": [{"type": "text"}]}'

    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.status == IngestJobStatus.SUCCESS
    assert job.progress_total == 1


def test_resolve_failure_marks_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    mineru = FakeMineru(error=UpstreamError("MinerU 解析失败"))

    document_service.resolve_parse(sqlite_session, doc, storage, mineru)

    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message
    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.status == IngestJobStatus.FAILED
    assert job.error


def test_resolve_not_uploaded_is_idempotent(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.PARSED
    mineru = FakeMineru()

    document_service.resolve_parse(sqlite_session, doc, storage, mineru)

    assert mineru.calls == []


def test_resolve_idempotent_on_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.FAILED
    mineru = FakeMineru()

    document_service.resolve_parse(sqlite_session, doc, storage, mineru)

    assert mineru.calls == []


# ------------------- 瞬态可见性与中断重放（fix-ingest-state-and-embedding-contract）


def test_parse_marks_parsing_and_commits_before_io(
    sqlite_session: Session,
    kb: KnowledgeBase,
    storage: LocalFileStorage,
    commit_spy,
):
    """瞬态 `PARSING` 必须在调用 MinerU **之前**置位并提交（spec：对外可见）。"""
    doc = _uploaded(sqlite_session, kb, storage)
    spy = commit_spy(sqlite_session, doc)
    status_at_io: list[DocumentStatus] = []
    commits_at_io: list[int] = []

    class RecordingMineru:
        def parse(self, *, filename: str, data: bytes) -> ParseResult:
            status_at_io.append(doc.status)
            commits_at_io.append(len(spy.statuses))
            return ParseResult(content_list=b'{"blocks": [{"type": "text"}]}')

    document_service.resolve_parse(
        sqlite_session, doc, storage, RecordingMineru(), commit=spy
    )

    # 首次阶段提交时状态已是 PARSING
    assert spy.statuses
    assert spy.statuses[0] == DocumentStatus.PARSING
    # 进入外部 I/O 时：状态为 PARSING，且此前已发生提交
    assert status_at_io == [DocumentStatus.PARSING]
    assert commits_at_io == [1]
    assert doc.status == DocumentStatus.PARSED


def test_resolve_parse_replays_from_parsing(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    """进程在解析中被杀留下的 `PARSING` 文档必须可被重新驱动（不永久卡死）。"""
    doc = _uploaded(sqlite_session, kb, storage)
    doc.status = DocumentStatus.PARSING
    sqlite_session.flush()
    mineru = FakeMineru()

    document_service.resolve_parse(sqlite_session, doc, storage, mineru)

    assert mineru.calls == ["政策.pdf"]
    assert doc.status == DocumentStatus.PARSED
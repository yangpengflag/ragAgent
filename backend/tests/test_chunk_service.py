"""chunk_service 红灯（document-chunking 任务 3.1–3.4）。

服务层驱动切分状态机（PARSED → CHUNKING → PARSED/FAILED），事务内落 Child+Parent，
软删同事务清 chunks。用内存 SQLite + 本地临时存储 + 确定性 TokenCounter，
零真实中间件；`build_chunks` 用 `domain/chunking` 纯函数，不碰网络。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.chunking.models import ChunkConfig, TokenCounter
from app.integrations.mineru import ParseResult
from app.integrations.storage import LocalFileStorage
from app.models import Chunk, Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import chunk_service, document_service, kb_service

ALLOWED = frozenset({"pdf", "docx"})

ARTIFACT = json.dumps(
    [
        {"type": "text", "text": "第一章", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "这是文档正文，用于切分验证。", "page_idx": 0},
    ]
).encode()


class WordCounter(TokenCounter):
    """确定性计数：token = 按空白切分的词数。"""

    def count(self, text: str) -> int:
        return len(text.split())


def _cfg() -> ChunkConfig:
    return ChunkConfig(
        text_target_tokens=8,
        text_max_tokens=10,
        list_target_tokens=8,
        list_max_tokens=10,
        table_target_tokens=16,
        table_max_tokens=20,
        code_target_tokens=12,
        code_max_tokens=16,
        equation_target_tokens=4,
        equation_max_tokens=6,
    )


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session, name="产品文档库", embedding_model="m", embed_dim=128
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _parsed_doc(
    session: Session,
    kb: KnowledgeBase,
    storage: LocalFileStorage,
    *,
    artifact: bytes = ARTIFACT,
    status: DocumentStatus = DocumentStatus.PARSED,
) -> Document:
    doc = document_service.create_document(
        session,
        kb_id=kb.id,
        filename="政策.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4",
        storage=storage,
        allowed_exts=ALLOWED,
        upload_max_bytes=1024,
    )
    doc.status = status
    if status is DocumentStatus.PARSED:
        doc.artifact_path = storage.save_artifact(
            kb_id=str(kb.id), document_id=str(doc.id), name="content_list.json", data=artifact
        )
    session.flush()
    return doc


def _chunks_of(session: Session, document_id: object) -> list[Chunk]:
    return list(
        session.execute(select(Chunk).where(Chunk.document_id == document_id)).scalars().all()
    )


def _job(session: Session, document_id: object) -> IngestJob:
    return session.scalar(select(IngestJob).where(IngestJob.document_id == document_id))


# ---------------------------------------------------------------- 3.1 切分驱动


def test_resolve_chunking_parsed_to_parsed_with_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage)

    ran = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is True
    assert doc.status == DocumentStatus.PARSED
    chunks = _chunks_of(sqlite_session, doc.id)
    assert len(chunks) >= 2
    assert all(c.kb_id == kb.id and c.document_id == doc.id for c in chunks)
    assert any(c.is_recallable for c in chunks)
    job = _job(sqlite_session, doc.id)
    assert job is not None
    assert job.stage == "CHUNK"
    assert job.status == IngestJobStatus.SUCCESS


def test_resolve_chunking_kills_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage, status=DocumentStatus.FAILED)

    ran = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is False
    assert _chunks_of(sqlite_session, doc.id) == []


# ---------------------------------------------------------------- 3.2 幂等


def test_resolve_chunking_idempotent_replay(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage)
    counter = WordCounter()
    first = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=counter
    )
    count_after_first = len(_chunks_of(sqlite_session, doc.id))
    assert first is True

    second = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=counter
    )

    assert second is False
    assert len(_chunks_of(sqlite_session, doc.id)) == count_after_first
    assert doc.status == DocumentStatus.PARSED


# ---------------------------------------------------------------- 3.3 失败回滚


def test_resolve_chunking_failure_marks_failed_no_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage, artifact=b"{not valid json")

    ran = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is True
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message
    assert _chunks_of(sqlite_session, doc.id) == []
    job = _job(sqlite_session, doc.id)
    assert job.status == IngestJobStatus.FAILED
    assert job.error


# ---------------------------------------------------------------- 3.4 软删接线


def test_soft_delete_document_also_deletes_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage)
    chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )
    assert _chunks_of(sqlite_session, doc.id) != []

    document_service.soft_delete_document(sqlite_session, kb.id, doc.id)

    assert doc.deleted_at is not None
    assert _chunks_of(sqlite_session, doc.id) == []


def test_soft_delete_repeat_is_idempotent(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc(sqlite_session, kb, storage)
    chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )
    document_service.soft_delete_document(sqlite_session, kb.id, doc.id)
    first_deleted_at = doc.deleted_at

    # 幂等：重复软删不掉错误、不改变删除时间、无残留活跃 chunks
    document_service.soft_delete_document(sqlite_session, kb.id, doc.id)

    assert doc.deleted_at == first_deleted_at
    assert _chunks_of(sqlite_session, doc.id) == []


class _FakeMineru:
    """返回固定 content_list 的最后一段：uploaded → artifact 落盘。"""

    def parse(self, *, filename: str, data: bytes) -> ParseResult:
        return ParseResult(content_list=ARTIFACT)


def test_full_ingest_chain_and_soft_delete_hides_doc_and_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    """6.2 离线集成验证：UPLOADED → PARSED（切分前）→ CHUNKING → PARSED（chunks 落库）。"""
    doc = document_service.create_document(
        sqlite_session,
        kb_id=kb.id,
        filename="政策.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4",
        storage=storage,
        allowed_exts=ALLOWED,
        upload_max_bytes=1024,
    )
    assert doc.status == DocumentStatus.UPLOADED

    # 解析段：UPLOADED → PARSED，产物落盘
    document_service.resolve_parse(sqlite_session, doc, storage, _FakeMineru())
    assert doc.status == DocumentStatus.PARSED
    assert _chunks_of(sqlite_session, doc.id) == []

    # 切分段：PARSED →（CHUNKING 瞬态）→ PARSED，chunks 落库
    chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )
    assert doc.status == DocumentStatus.PARSED
    chunks = _chunks_of(sqlite_session, doc.id)
    assert len(chunks) >= 2
    job = _job(sqlite_session, doc.id)
    assert job.stage == "CHUNK"
    assert job.status == IngestJobStatus.SUCCESS

    # 软删后：文档与 chunks 均不在列表 / 二次查询中出现
    document_service.soft_delete_document(sqlite_session, kb.id, doc.id)
    assert document_service.list_documents(sqlite_session, kb.id) == []
    assert _chunks_of(sqlite_session, doc.id) == []


# ------------------- 瞬态可见性与中断重放（fix-ingest-state-and-embedding-contract）


def test_chunking_commits_chunking_before_reading_artifact(
    sqlite_session: Session,
    kb: KnowledgeBase,
    storage: LocalFileStorage,
    commit_spy,
    monkeypatch: pytest.MonkeyPatch,
):
    """瞬态 `CHUNKING` 必须在读取解析产物（外部 I/O 同类）**之前**提交。"""
    doc = _parsed_doc(sqlite_session, kb, storage)
    spy = commit_spy(sqlite_session, doc)
    observed: list[tuple[DocumentStatus, int]] = []
    real_open = storage.open_artifact

    def recording_open(rel_path: str) -> bytes:
        observed.append((doc.status, len(spy.statuses)))
        return real_open(rel_path)

    monkeypatch.setattr(storage, "open_artifact", recording_open)

    chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter(), commit=spy
    )

    assert spy.statuses
    assert spy.statuses[0] == DocumentStatus.CHUNKING
    assert observed
    assert observed[0][0] == DocumentStatus.CHUNKING
    assert observed[0][1] >= 1
    assert doc.status == DocumentStatus.PARSED


def test_resolve_chunking_replays_from_chunking_without_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    """`CHUNKING` 残留（切分中进程被杀、无 chunks）必须可重放。"""
    doc = _parsed_doc(sqlite_session, kb, storage)
    doc.status = DocumentStatus.CHUNKING
    sqlite_session.flush()

    ran = chunk_service.resolve_chunking(
        sqlite_session, doc, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is True
    assert doc.status == DocumentStatus.PARSED
    assert len(_chunks_of(sqlite_session, doc.id)) >= 2
"""切分 Celery 任务红灯（document-chunking 任务 4.1–4.2）。

任务核心 `_chunk_document` / 编排助手 `_schedule_chunk` 用内存 SQLite + 本地存储
+ 确定性 TokenCounter：覆盖 PARSED 推进、已切分 / FAILED 短路幂等、PARSED 才分派
切分任务（job.stage 推进到 CHUNK）。不依赖真实 broker。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.chunking.models import ChunkConfig, TokenCounter
from app.integrations.storage import LocalFileStorage
from app.models import Chunk, Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import document_service, kb_service
from app.tasks.ingest import _chunk_document, _schedule_chunk

ALLOWED = frozenset({"pdf", "docx"})

ARTIFACT = json.dumps(
    [
        {"type": "text", "text": "第一章", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "这是文档正文，用于切分验证。", "page_idx": 0},
    ]
).encode()


class WordCounter(TokenCounter):
    def count(self, text: str) -> int:
        return len(text.split())


def _cfg() -> ChunkConfig:
    return ChunkConfig(text_target_tokens=8, text_max_tokens=10)


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        sqlite_session, name="产品文档库", embedding_model="m", embed_dim=128
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _doc(
    session: Session,
    kb: KnowledgeBase,
    storage: LocalFileStorage,
    *,
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
            kb_id=str(kb.id), document_id=str(doc.id), name="content_list.json", data=ARTIFACT
        )
    session.flush()
    return doc


def _chunks(session: Session, document_id: object) -> list[Chunk]:
    return list(
        session.execute(select(Chunk).where(Chunk.document_id == document_id)).scalars().all()
    )


# ---------------------------------------------------------------- 4.1 切分任务


def test_chunk_document_advances_parsed_doc(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _doc(sqlite_session, kb, storage)

    ran = _chunk_document(
        sqlite_session, doc.id, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is True
    assert doc.status == DocumentStatus.PARSED
    assert len(_chunks(sqlite_session, doc.id)) >= 2
    job = sqlite_session.scalar(select(IngestJob).where(IngestJob.document_id == doc.id))
    assert job is not None
    assert job.stage == "CHUNK"
    assert job.status == IngestJobStatus.SUCCESS


def test_chunk_document_short_circuit_when_not_parsed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _doc(sqlite_session, kb, storage, status=DocumentStatus.UPLOADED)

    ran = _chunk_document(
        sqlite_session, doc.id, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is False
    assert _chunks(sqlite_session, doc.id) == []
    assert doc.status == DocumentStatus.UPLOADED


def test_chunk_document_short_circuit_when_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _doc(sqlite_session, kb, storage, status=DocumentStatus.FAILED)

    ran = _chunk_document(
        sqlite_session, doc.id, storage, cfg=_cfg(), counter=WordCounter()
    )

    assert ran is False
    assert _chunks(sqlite_session, doc.id) == []


def test_chunk_document_idempotent_when_already_chunked(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _doc(sqlite_session, kb, storage)
    counter = WordCounter()
    _chunk_document(sqlite_session, doc.id, storage, cfg=_cfg(), counter=counter)
    count = len(_chunks(sqlite_session, doc.id))

    again = _chunk_document(sqlite_session, doc.id, storage, cfg=_cfg(), counter=counter)

    assert again is False
    assert len(_chunks(sqlite_session, doc.id)) == count


def test_chunk_document_missing_document_ignored(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    assert _chunk_document(sqlite_session, kb.id, storage) is False


# ---------------------------------------------------------------- 4.2 任务编排


def test_schedule_chunk_dispatches_when_parsed(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    from app.tasks import ingest as ingest_module

    monkeypatch.setattr(ingest_module.document_chunk, "delay", lambda cid: calls.append(cid))

    assert _schedule_chunk(document_id="d1", is_parsed=True) is True
    assert calls == ["d1"]


def test_schedule_chunk_no_dispatch_when_not_parsed(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    from app.tasks import ingest as ingest_module

    monkeypatch.setattr(ingest_module.document_chunk, "delay", lambda cid: calls.append(cid))

    assert _schedule_chunk(document_id="d1", is_parsed=False) is False
    assert calls == []
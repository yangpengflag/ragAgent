"""向量化 Celery 任务红灯（document-embedding-index 任务 4.1–4.2）。

覆盖 `_embed_document` 推进到 READY 与短路幂等，以及切分成功后 `_schedule_embed` /
`_is_embeddable` 的编排判定。用内存 SQLite + 本地存储 + monkeypatch 掉向量集成侧，
不依赖真实 broker / Milvus。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.integrations.milvus as milvus_integration
import app.integrations.vectorstore as vectorstore_integration
from app.domain.chunking.models import ChunkConfig, TokenCounter
from app.integrations.storage import LocalFileStorage
from app.models import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.services import chunk_service, document_service, kb_service
from app.tasks.ingest import (
    _embed_document,
    _is_embeddable,
    _schedule_embed,
)

ALLOWED = frozenset({"pdf", "docx"})

ARTIFACT = json.dumps(
    [
        {"type": "text", "text": "第一章", "text_level": 1, "page_idx": 0},
        {"type": "text", "text": "这是文档正文，用于向量化验证。", "page_idx": 0},
    ]
).encode()


class WordCounter(TokenCounter):
    def count(self, text: str) -> int:
        return len(text.split())


def _cfg() -> ChunkConfig:
    return ChunkConfig(text_target_tokens=8, text_max_tokens=10)


@pytest.fixture
def kb(sqlite_session: Session) -> KnowledgeBase:
    from app.core.config import get_settings

    return kb_service.create_kb(
        sqlite_session,
        name="产品文档库",
        embedding_model="m",
        embed_dim=get_settings().dashscope_embed_dim,  # 与全局配置一致，避开 D6 混维度拒绝
    )


@pytest.fixture
def storage(tmp_path: Path) -> LocalFileStorage:
    return LocalFileStorage(root=tmp_path)


def _parsed_doc_with_chunks(
    session: Session, kb: KnowledgeBase, storage: LocalFileStorage
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
    doc.status = DocumentStatus.PARSED
    doc.artifact_path = storage.save_artifact(
        kb_id=str(kb.id), document_id=str(doc.id), name="content_list.json", data=ARTIFACT
    )
    session.flush()
    chunk_service.resolve_chunking(session, doc, storage, cfg=_cfg(), counter=WordCounter())
    return doc


def _patch_vector_ops(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: dict = {"ensure": 0, "delete": 0, "write": []}

    def ensure(*a, **k) -> None:
        calls["ensure"] += 1

    def delete(*a, **k) -> None:
        calls["delete"] += 1

    def write(*a, **k) -> None:
        calls["write"].append((a, k))

    monkeypatch.setattr(milvus_integration, "ensure_collection", ensure)
    monkeypatch.setattr(milvus_integration, "delete_document_vectors", delete)
    monkeypatch.setattr(vectorstore_integration, "write_chunk_vectors", write)
    return calls


# ---------------------------------------------------------------- 4.1 向量化任务


def test_embed_document_advances_to_ready(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    calls = _patch_vector_ops(monkeypatch)

    ran = _embed_document(sqlite_session, doc.id)

    assert ran is True
    assert doc.status == DocumentStatus.READY
    assert len(calls["write"]) == 1
    job = sqlite_session.scalar(select(IngestJob).where(IngestJob.document_id == doc.id))
    assert job is not None
    assert job.stage == "EMBED"
    assert job.status == IngestJobStatus.SUCCESS


def test_embed_document_short_circuits_when_not_ready(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    doc.status = DocumentStatus.UPLOADED  # 原料/状态未就绪
    calls = _patch_vector_ops(monkeypatch)

    assert _embed_document(sqlite_session, doc.id) is False
    assert calls["write"] == []


def test_embed_document_short_circuits_when_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    doc.status = DocumentStatus.FAILED
    calls = _patch_vector_ops(monkeypatch)

    assert _embed_document(sqlite_session, doc.id) is False
    assert calls["write"] == []


def test_embed_document_missing_ignored(
    sqlite_session: Session, monkeypatch
):
    from app.core.ids import uuid7

    _patch_vector_ops(monkeypatch)  # 无副作用：文档不存在直接短路

    assert _embed_document(sqlite_session, uuid7()) is False


# ---------------------------------------------------------------- 4.2 任务编排


def test_is_embeddable_true_when_ready(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    assert _is_embeddable(sqlite_session, doc.id) is True


def test_is_embeddable_false_when_not_parsed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    doc.status = DocumentStatus.UPLOADED
    assert _is_embeddable(sqlite_session, doc.id) is False


def test_schedule_embed_dispatches_when_ready(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    from app.tasks import ingest as ingest_module

    monkeypatch.setattr(ingest_module.document_embed, "delay", lambda cid: calls.append(cid))

    assert _schedule_embed(document_id="d1", is_ready=True) is True
    assert calls == ["d1"]


def test_schedule_embed_no_dispatch_when_not_ready(monkeypatch: pytest.MonkeyPatch):
    calls: list[str] = []
    from app.tasks import ingest as ingest_module

    monkeypatch.setattr(ingest_module.document_embed, "delay", lambda cid: calls.append(cid))

    assert _schedule_embed(document_id="d1", is_ready=False) is False
    assert calls == []
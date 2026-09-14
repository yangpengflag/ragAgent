"""向量化服务红灯（document-embedding-index 任务 3.1–3.4）。

覆盖状态机推进（`PARSED→EMBEDDING→READY`）、幂等重放、失败补偿，以及软删清向量
接线（`clear_document_vectors` 尽力而为、不阻塞）。用内存 SQLite + monkeypatch 掉
Milvus / embedding 集成侧，零真实外部中间件。
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
from app.services import chunk_service, document_service, index_service, kb_service

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
    """monkeypatch 掉向量集成侧，返回记录调用的容器。"""
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


# ---------------------------------------------------------------- 3.1 推进到 READY


def test_resolve_indexing_advances_to_ready(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    assert doc.status == DocumentStatus.PARSED
    calls = _patch_vector_ops(monkeypatch)

    ran = index_service.resolve_indexing(sqlite_session, doc)

    assert ran is True
    assert doc.status == DocumentStatus.READY
    # 先显式建表 + 幂等清旧向量 + 写
    assert calls["ensure"] == 1
    assert calls["delete"] == 1
    assert len(calls["write"]) == 1
    rows = calls["write"][0][0][1]  # write 的第二个位置参数：rows (settings, rows)
    assert rows and all(row.kb_id == str(kb.id) for row in rows)
    assert all(row.document_id == str(doc.id) for row in rows)
    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job is not None
    assert job.stage == "EMBED"
    assert job.status == IngestJobStatus.SUCCESS
    assert job.progress_total == len(rows)


# ---------------------------------------------------------------- 3.2 幂等与重放


def test_resolve_indexing_short_circuit_when_not_parsed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    doc.status = DocumentStatus.UPLOADED
    calls = _patch_vector_ops(monkeypatch)

    assert index_service.resolve_indexing(sqlite_session, doc) is False
    assert calls["write"] == []


def test_resolve_indexing_short_circuit_when_no_recallable_chunks(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = document_service.create_document(
        sqlite_session,
        kb_id=kb.id,
        filename="空.pdf",
        content_type="application/pdf",
        data=b"%PDF-1.4",
        storage=storage,
        allowed_exts=ALLOWED,
        upload_max_bytes=1024,
    )
    doc.status = DocumentStatus.PARSED
    sqlite_session.flush()
    calls = _patch_vector_ops(monkeypatch)

    assert index_service.resolve_indexing(sqlite_session, doc) is False
    assert calls["write"] == []


def test_resolve_indexing_replay_is_idempotent(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    calls = _patch_vector_ops(monkeypatch)
    assert index_service.resolve_indexing(sqlite_session, doc) is True
    assert doc.status == DocumentStatus.READY
    writes_after_first = len(calls["write"])

    # 已 READY：重放短路，不重复编码/写入
    assert index_service.resolve_indexing(sqlite_session, doc) is False
    assert len(calls["write"]) == writes_after_first


# ---------------------------------------------------------------- 3.3 失败补偿


def test_resolve_indexing_rejects_dim_mismatch(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch,
):
    """D6 禁止混维度：库 embed_dim 与全局配置不一致时显式拒绝，不写 Milvus。"""
    from app.core.config import get_settings

    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    calls = _patch_vector_ops(monkeypatch)
    # 库声明的 dim 与当前配置暴露的 dim 不同 —— 模拟混维度
    monkeypatch.setattr(
        index_service, "get_settings", _settings(dim=get_settings().dashscope_embed_dim + 1)
    )

    assert index_service.resolve_indexing(sqlite_session, doc) is True  # 异常被捕获
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message and "embed_dim" in doc.error_message
    assert calls["ensure"] == 0
    assert calls["write"] == []


def _settings(dim: int):
    class _S:
        def __init__(self, dim: int) -> None:
            self.dashscope_embed_dim = dim

        def __getattr__(self, name: str):
            raise AttributeError(name)

    return lambda: _S(dim)


def test_resolve_indexing_failure_sets_failed(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    _patch_vector_ops(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("embed upstream down")

    monkeypatch.setattr(vectorstore_integration, "write_chunk_vectors", boom)

    assert index_service.resolve_indexing(sqlite_session, doc) is True  # 异常被捕获
    assert doc.status == DocumentStatus.FAILED
    assert doc.error_message and "embed upstream down" in doc.error_message
    job = sqlite_session.scalar(
        select(IngestJob).where(IngestJob.document_id == doc.id)
    )
    assert job.status == IngestJobStatus.FAILED
    assert job.error and "embed upstream down" in job.error


# ---------------------------------------------------------------- 3.4 软删清向量


def test_clear_document_vectors_calls_milvus_delete(monkeypatch):
    deleted: dict = {}

    def fake_delete(settings, kb_id, document_id) -> None:
        deleted["kb_id"] = kb_id
        deleted["document_id"] = document_id

    monkeypatch.setattr(milvus_integration, "delete_document_vectors", fake_delete)

    index_service.clear_document_vectors(object(), "kb-1", "doc-1")

    assert deleted == {"kb_id": "kb-1", "document_id": "doc-1"}


def test_clear_document_vectors_failure_is_non_blocking(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("milvus unreachable")

    monkeypatch.setattr(milvus_integration, "delete_document_vectors", boom)

    # 清向量失败不抛错（仅记日志），软删主流程不中断
    index_service.clear_document_vectors(object(), "kb-1", "doc-1")


# ------------------- 瞬态可见性与中断重放（fix-ingest-state-and-embedding-contract）


def test_indexing_commits_embedding_before_vector_io(
    sqlite_session: Session,
    kb: KnowledgeBase,
    storage: LocalFileStorage,
    monkeypatch: pytest.MonkeyPatch,
    commit_spy,
):
    """瞬态 `EMBEDDING` 必须在首次接触向量库（`ensure_collection`）**之前**提交。"""
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    spy = commit_spy(sqlite_session, doc)
    observed: list[tuple[DocumentStatus, int]] = []

    def recording_ensure(*a, **k) -> None:
        observed.append((doc.status, len(spy.statuses)))

    monkeypatch.setattr(milvus_integration, "ensure_collection", recording_ensure)
    monkeypatch.setattr(milvus_integration, "delete_document_vectors", lambda *a, **k: None)
    monkeypatch.setattr(vectorstore_integration, "write_chunk_vectors", lambda *a, **k: None)

    index_service.resolve_indexing(sqlite_session, doc, commit=spy)

    assert spy.statuses
    assert spy.statuses[0] == DocumentStatus.EMBEDDING
    assert observed
    assert observed[0][0] == DocumentStatus.EMBEDDING
    assert observed[0][1] >= 1
    assert doc.status == DocumentStatus.READY


def test_resolve_indexing_replays_from_embedding(
    sqlite_session: Session, kb: KnowledgeBase, storage: LocalFileStorage, monkeypatch
):
    """`EMBEDDING` 残留（向量化中进程被杀）必须可重放，且先清旧向量再写。"""
    doc = _parsed_doc_with_chunks(sqlite_session, kb, storage)
    doc.status = DocumentStatus.EMBEDDING
    sqlite_session.flush()
    calls = _patch_vector_ops(monkeypatch)

    assert index_service.resolve_indexing(sqlite_session, doc) is True
    assert doc.status == DocumentStatus.READY
    assert calls["ensure"] == 1
    assert calls["delete"] == 1
    assert len(calls["write"]) == 1
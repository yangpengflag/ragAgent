"""文档与入库任务模型红灯（document-upload-and-parse 任务 1.1 / 1.3）。

模型层只验数据契约：
- `Document` 上传即 `UPLOADED`；软删默认被全局过滤
- `IngestJob` 上传即 `PENDING`，与文档 1:1（`document_id` 唯一）
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Document, DocumentStatus, IngestJob, IngestJobStatus, KnowledgeBase
from app.services import kb_service


def _kb(session: Session) -> KnowledgeBase:
    return kb_service.create_kb(
        session,
        name="产品文档库",
        description="描述",
        embedding_model="qwen3.7-text-embedding",
        embed_dim=1024,
    )


def test_document_defaults_to_uploaded(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = Document(
        kb_id=kb.id,
        filename="政策.pdf",
        file_hash="a" * 64,
        file_size=1024,
        content_type="application/pdf",
    )
    sqlite_session.add(doc)
    sqlite_session.flush()

    assert doc.status == DocumentStatus.UPLOADED


def test_document_status_includes_embedding_ready():
    """document-embedding-index 任务 1.1：状态机含 EMBEDDING / READY 终态。"""
    assert DocumentStatus.EMBEDDING == "EMBEDDING"
    assert DocumentStatus.READY == "READY"


def test_soft_deleted_document_is_filtered(sqlite_session: Session):
    kb = _kb(sqlite_session)
    live = Document(
        kb_id=kb.id, filename="活跃.pdf", file_hash="b" * 64, file_size=1,
        content_type="application/pdf",
    )
    gone = Document(
        kb_id=kb.id, filename="已删.pdf", file_hash="c" * 64, file_size=1,
        content_type="application/pdf",
    )
    sqlite_session.add_all([live, gone])
    sqlite_session.flush()
    gone.soft_delete()
    sqlite_session.commit()

    active = list(sqlite_session.execute(select(Document)).scalars().all())

    assert [d.filename for d in active] == ["活跃.pdf"]


def test_ingest_job_defaults_to_pending(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = Document(
        kb_id=kb.id, filename="政策.pdf", file_hash="d" * 64, file_size=1,
        content_type="application/pdf",
    )
    sqlite_session.add(doc)
    sqlite_session.flush()
    job = IngestJob(document_id=doc.id, kb_id=kb.id)
    sqlite_session.add(job)
    sqlite_session.flush()

    assert job.status == IngestJobStatus.PENDING
    assert job.progress_current == 0
    assert job.progress_total == 0


def test_ingest_job_document_id_is_unique(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = Document(
        kb_id=kb.id, filename="政策.pdf", file_hash="e" * 64, file_size=1,
        content_type="application/pdf",
    )
    sqlite_session.add(doc)
    sqlite_session.flush()
    sqlite_session.add(IngestJob(document_id=doc.id, kb_id=kb.id))
    sqlite_session.flush()

    duplicate = IngestJob(document_id=doc.id, kb_id=kb.id)
    sqlite_session.add(duplicate)
    try:
        sqlite_session.flush()
    except IntegrityError:
        return  # 唯一约束生效
    raise AssertionError("IngestJob 允许了同一 document 的重复 job")
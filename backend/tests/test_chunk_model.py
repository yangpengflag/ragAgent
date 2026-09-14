"""chunks 模型红灯（document-chunking 任务 1.2）。

模型层只验数据契约：
- `Chunk` 默认 `is_recallable=False`、`section_path` 默认空串、`bbox`/`page_idx`/`parent_id` 可空
- `parent_id` 自关联可空（无父子自立）
- `bbox` JSON 读写往返
- 软删默认被全局过滤
- 按 `document_id` 归属可查
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.ids import uuid7
from app.models import Chunk, Document, DocumentStatus
from app.services import kb_service


def _doc(session: Session, kb) -> Document:
    doc = Document(
        id=uuid7(),
        kb_id=kb.id,
        filename="政策.pdf",
        file_hash="a" * 64,
        file_size=1,
        content_type="application/pdf",
        status=DocumentStatus.PARSED,
    )
    session.add(doc)
    session.flush()
    return doc


def _kb(session: Session):
    return kb_service.create_kb(
        session, name="产品文档库", embedding_model="qwen3.7-text-embedding", embed_dim=1024
    )


def test_chunk_has_uuid7_id(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)
    chunk = Chunk(
        kb_id=kb.id, document_id=doc.id, content="正文", section_path="1 / 1.1",
        page_idx=2, bbox=[10, 20, 30, 40], block_type="text",
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()

    assert chunk.id is not None
    assert isinstance(chunk.id, uuid.UUID)
    assert chunk.id.version == 7
    assert chunk.is_recallable is False


def test_chunk_defaults(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)

    chunk = Chunk(kb_id=kb.id, document_id=doc.id, content="正文", block_type="list")
    sqlite_session.add(chunk)
    sqlite_session.flush()

    assert chunk.is_recallable is False
    assert chunk.section_path == ""
    assert chunk.page_idx is None
    assert chunk.bbox is None
    assert chunk.parent_id is None


def test_parent_id_self_relation(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)

    parent = Chunk(kb_id=kb.id, document_id=doc.id, content="父块", block_type="text")
    child = Chunk(
        kb_id=kb.id, document_id=doc.id, content="子块", block_type="text",
        is_recallable=True,
    )
    sqlite_session.add_all([parent, child])
    sqlite_session.flush()
    child.parent_id = parent.id
    sqlite_session.commit()

    loaded = sqlite_session.get(Chunk, child.id)
    assert loaded.parent_id == parent.id


def test_bbox_round_trip(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)
    chunk = Chunk(
        kb_id=kb.id, document_id=doc.id, content="正文", block_type="text",
        bbox=[0.1, 0.2, 0.3, 0.4],
    )
    sqlite_session.add(chunk)
    sqlite_session.flush()
    sqlite_session.expire_all()

    loaded = sqlite_session.get(Chunk, chunk.id)
    assert loaded.bbox == [0.1, 0.2, 0.3, 0.4]


def test_chunk_soft_delete_is_filtered(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)
    live = Chunk(kb_id=kb.id, document_id=doc.id, content="活跃", block_type="text")
    gone = Chunk(kb_id=kb.id, document_id=doc.id, content="已删", block_type="text")
    sqlite_session.add_all([live, gone])
    sqlite_session.flush()
    gone.soft_delete()
    sqlite_session.commit()

    active = list(sqlite_session.execute(select(Chunk)).scalars().all())
    assert [c.content for c in active] == ["活跃"]

    all_rows = list(
        sqlite_session.execute(
            select(Chunk).execution_options(include_soft_deleted=True)
        ).scalars().all()
    )
    assert len(all_rows) == 2


def test_chunk_countable_by_document(sqlite_session: Session):
    kb = _kb(sqlite_session)
    doc = _doc(sqlite_session, kb)
    c1 = Chunk(kb_id=kb.id, document_id=doc.id, content="段落一", block_type="text")
    c2 = Chunk(kb_id=kb.id, document_id=doc.id, content="段落二", block_type="text")
    sqlite_session.add_all([c1, c2])
    sqlite_session.commit()

    count = sqlite_session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == doc.id)
    )
    assert count == 2
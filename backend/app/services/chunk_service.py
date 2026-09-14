"""切分服务：驱动文档切分状态机并在事务内落 Child + Parent。

状态机（design D3）：`PARSED → CHUNKING → PARSED / FAILED`。
- 入口护栏：非 `PARSED` 返回 False（幂等）；`PARSED` 但已有 chunks 视为已切分，短路（幂等）。
- 事务语义：`build_chunks` 为纯函数，先完整构建内存行，再一次性 `add_all + flush`，
  故输入/解析/切分任一环节失败都不可能留下半套 chunks；失败仅把文档与 job 置 `FAILED`
  并保留错误信息（可修复后重放）。
- job 是状态真相：stage 推进到 `CHUNK`，成功 `SUCCESS`、失败 `FAILED`。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import chunk_config_from_settings, get_settings
from app.core.logging import get_logger
from app.domain.chunking.builder import build_chunks
from app.domain.chunking.models import (
    Block,
    ChunkConfig,
    TiktokenTokenCounter,
    TokenCounter,
    blocks_from_json,
)
from app.integrations.storage import FileStorage
from app.models import Chunk
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.services.commit_point import commit_stage

logger = get_logger()


def resolve_chunking(
    session: Session,
    document: Document,
    storage: FileStorage,
    *,
    cfg: ChunkConfig | None = None,
    counter: TokenCounter | None = None,
    commit: Callable[[], None] | None = None,
) -> bool:
    """驱动一次切分：`PARSED → CHUNKING → PARSED / FAILED`，并同步 `ingest_job`。

    - 入口校验：`PARSED` 或 `CHUNKING`（且尚未产出 chunks）才推进——`CHUNKING` 残留
      表示上次切分未完成，允许重放；其余状态或已切分短路（幂等）
    - 阶段提交：置 `CHUNKING` + job `RUNNING` 后**立即提交**，使进行中状态对外可见
    - 成功：chunks 一次落库，文档回 `PARSED`，job → `SUCCESS`（stage `CHUNK`）
    - 失败：文档与 job 均置 `FAILED` 并记错误，不留半套 chunks
    """
    if document.status not in (DocumentStatus.PARSED, DocumentStatus.CHUNKING):
        return False
    if _has_chunks(session, document.id):
        logger.info("chunking skipped: already chunked", document_id=str(document.id))
        return False

    job = session.scalar(select(IngestJob).where(IngestJob.document_id == document.id))
    if job is None:
        raise RuntimeError("缺失 ingest_job，切分任务无法推进")
    job.stage = "CHUNK"
    job.status = IngestJobStatus.RUNNING
    job.started_at = utcnow()
    document.status = DocumentStatus.CHUNKING
    commit_stage(session, commit)

    try:
        if document.artifact_path is None:
            raise RuntimeError("文档缺少解析产物，无法切分")
        data = storage.open_artifact(document.artifact_path)
        rows = _build_rows(document, blocks_from_json(data), cfg, counter)
        session.add_all(rows)
        session.flush()
        document.status = DocumentStatus.PARSED
        job.status = IngestJobStatus.SUCCESS
        job.progress_current = len(rows)
        job.progress_total = len(rows)
    except Exception as exc:
        logger.error("chunking failed", document_id=str(document.id), error=str(exc))
        _fail(document, job, exc)
    finally:
        job.finished_at = utcnow()
        session.flush()
    return True


def _build_rows(
    document: Document,
    blocks: list[Block],
    cfg: ChunkConfig | None,
    counter: TokenCounter | None,
) -> list[Chunk]:
    """把解析块切成领域 Chunk 并转成待入库的 `Chunk` 模型行（同一事务一次落库）。"""
    config = cfg if cfg is not None else chunk_config_from_settings(get_settings())
    token_counter: TokenCounter = counter if counter is not None else TiktokenTokenCounter()
    chunks = build_chunks(blocks, config, token_counter)
    rows: list[Chunk] = []
    for item in chunks:
        rows.append(
            Chunk(
                id=uuid.UUID(item.id),
                kb_id=document.kb_id,
                document_id=document.id,
                parent_id=uuid.UUID(item.parent_id) if item.parent_id else None,
                content=item.content,
                section_path=item.section_path,
                page_idx=item.page_idx,
                bbox=item.bbox,
                block_type=item.block_type,
                is_recallable=item.is_recallable,
            )
        )
    return rows


def _has_chunks(session: Session, document_id: uuid.UUID) -> bool:
    count = session.scalar(
        select(func.count()).select_from(Chunk).where(Chunk.document_id == document_id)
    )
    return bool(count)


def _fail(document: Document, job: IngestJob, exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    document.status = DocumentStatus.FAILED
    document.error_message = message
    job.status = IngestJobStatus.FAILED
    job.error = message
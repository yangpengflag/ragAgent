"""向量化服务：驱动文档状态机 `PARSED → EMBEDDING → READY / FAILED`（design D2/D3/D5）。

- 入口护栏：非 `PARSED` 返回 False（幂等）；`PARSED` 但无可召回 chunk 视为原料未就绪，短路。
- 过程：`ensure_collection`（显式建表）→ 幂等清旧向量（先删后写）→ 编码 + 写 Milvus → `READY`。
- 失败：文档与 job 置 `FAILED` 并保留错误；已写向量以 `document_id` 可辨识，
  重放开头再清旧向量收敛一致。
- job 是状态真相：stage 推进到 `EMBED`，成功 `SUCCESS`、失败 `FAILED`。
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

# 通过模块引用访问集成侧函数，便于测试 monkeypatch（pytest 惯例）
import app.integrations.milvus as _milvus_integration
import app.integrations.vectorstore as _vectorstore_integration
from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.integrations.vectorstore import ChunkVectorRow
from app.models import Chunk, KnowledgeBase
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.services.commit_point import commit_stage

logger = get_logger()


def _recallable_rows(session: Session, document: Document) -> list[ChunkVectorRow]:
    """取某文档全部 `is_recallable` 的 child chunk 为待写向量行。

    主键 `chunk_id` 用 UUID hex（design：`Chunk.id` 以 UUID hex 呈现并与 MySQL/Milvus
    复用链路对齐）；`kb_id` / `document_id` 用 `str(uuid)`（带横线），与检索侧 `kb_id`
    过滤值（`kb_grant_service.kb_ids_for_user` 返回 `str`）保持一致。
    """
    chunks = session.scalars(
        select(Chunk).where(
            Chunk.document_id == document.id, Chunk.is_recallable.is_(True)
        )
    ).all()
    return [
        ChunkVectorRow(
            chunk_id=chunk.id.hex,
            content=chunk.content,
            kb_id=str(document.kb_id),
            document_id=str(document.id),
        )
        for chunk in chunks
    ]


def resolve_indexing(
    session: Session,
    document: Document,
    *,
    commit: Callable[[], None] | None = None,
) -> bool:
    """驱动一次向量化：`PARSED → EMBEDDING → READY / FAILED`，并同步 `ingest_job`。

    - 入口校验：`PARSED` 或 `EMBEDDING`（且含可召回 chunk）才推进——`EMBEDDING` 残留
      表示上次向量化未完成，允许重放（写前先清同文档旧向量，收敛为只剩本批次）
    - 阶段提交：置 `EMBEDDING` + job `RUNNING` 后**立即提交**，使进行中状态对外可见
    - 成功：先显式建 collection、幂等清旧向量，再编码写 Milvus → `READY`
    - 失败：业务失败时文档与 job 均置 `FAILED` 并记错误，不留半套索引；
      缺 job 等数据契约错误抛出并保持瞬态，以便修复后重放
    """
    if document.status not in (DocumentStatus.PARSED, DocumentStatus.EMBEDDING):
        return False
    rows = _recallable_rows(session, document)
    if not rows:
        logger.info("indexing skipped: no recallable chunks", document_id=str(document.id))
        return False

    settings = get_settings()
    job = session.scalar(select(IngestJob).where(IngestJob.document_id == document.id))
    if job is None:
        raise RuntimeError("缺失 ingest_job，向量化任务无法推进")
    job.stage = "EMBED"
    job.status = IngestJobStatus.RUNNING
    job.started_at = utcnow()
    document.status = DocumentStatus.EMBEDDING
    commit_stage(session, commit)

    # D6 禁止混维度：库声明维度必须与全局配置一致，否则显式拒绝（fail-fast 于写 Milvus 前）
    if (dim_mismatch := _dim_mismatch(session, document, settings)) is not None:
        _fail(document, job, dim_mismatch)
        job.finished_at = utcnow()
        session.flush()
        return True

    try:
        _milvus_integration.ensure_collection(settings)
        # 先删后写：幂等清旧向量，重放收敛为只剩本批次存活（D3）
        _milvus_integration.delete_document_vectors(
            settings, str(document.kb_id), str(document.id)
        )
        _vectorstore_integration.write_chunk_vectors(settings, rows)
        document.status = DocumentStatus.READY
        job.status = IngestJobStatus.SUCCESS
        job.progress_current = len(rows)
        job.progress_total = len(rows)
    except Exception as exc:
        logger.error("indexing failed", document_id=str(document.id), error=str(exc))
        _fail(document, job, exc)
    finally:
        job.finished_at = utcnow()
        session.flush()
    return True


def _dim_mismatch(
    session: Session, document: Document, settings: Settings
) -> Exception | None:
    """D6：库声明维度与全局配置不一致时返回异常，否则 None（显式拒绝而非静默混写）。"""
    kb = session.get(KnowledgeBase, document.kb_id)
    expected = settings.dashscope_embed_dim
    if kb is not None and kb.embed_dim != expected:
        return RuntimeError(
            f"embed_dim mismatch: kb={kb.embed_dim} config={expected}"
        )
    return None


def clear_document_vectors(settings: object, kb_id: object, document_id: object) -> None:
    """尽力清理某文档的 Milvus 向量（design D4：清向量失败不阻塞软删）。

    软删流程：MySQL 软删 document + chunks 提交后调用；Milvus 删除是外部副作用、
    无法进事务，失败仅记日志、留待对账任务兜底，绝不向软删调用方抛错。
    """
    try:
        _milvus_integration.delete_document_vectors(
            settings, str(kb_id), str(document_id)  # type: ignore[arg-type]
        )
    except Exception as exc:  # noqa: BLE001 - 外部副作用失败不阻断主流程
        logger.error(
            "clear document vectors failed",
            document_id=str(document_id),
            error=str(exc),
        )


def _fail(document: Document, job: IngestJob, exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    document.status = DocumentStatus.FAILED
    document.error_message = message
    job.status = IngestJobStatus.FAILED
    job.error = message
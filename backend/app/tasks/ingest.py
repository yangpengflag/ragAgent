"""文档解析 Celery 任务（design D6：幂等，状态为真相，错误兜底写库）。

`document_parse(document_id)` 是 Celery 薄壳：自建会话 + 装配存储/MinerU，
调度真正的编排逻辑 `_parse_document` 并把状态推进到 MySQL（真相来源）。
任务体不感知 HTTP；重入/并发由状态护栏兜底——`UPLOADED`/`PARSING` 均可推进，
瞬态残留可重放（fix-ingest-state-and-embedding-contract）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_session_factory
from app.core.logging import get_logger
from app.domain.chunking.models import ChunkConfig, TokenCounter
from app.integrations.mineru import MineruClient
from app.integrations.storage import LocalFileStorage
from app.models import Chunk
from app.models.document import Document, DocumentStatus
from app.services import chunk_service, document_service, index_service
from app.tasks import celery

logger = get_logger()


def _parse_document(
    session: Session,
    document_id: uuid.UUID,
    storage: LocalFileStorage,
    mineru: MineruClient,
) -> bool:
    """推进一次解析；`UPLOADED` 或 `PARSING` 才进入，其余状态与文档缺失短路（幂等）。

    `PARSING` 是"上次解析未完成"的残留（进程被杀）：必须放行，否则中断文档会永久卡死。
    """
    document = session.get(Document, document_id)
    if document is None or document.status not in (
        DocumentStatus.UPLOADED,
        DocumentStatus.PARSING,
    ):
        return False
    document_service.resolve_parse(session, document, storage, mineru)
    return True


def _is_parsed(session: Session, document_id: uuid.UUID) -> bool:
    """文档当前是否为 `PARSED`（切分前置条件；job 是状态真相）。"""
    return (
        session.scalar(
            select(Document.status).where(Document.id == document_id)
        )
        == DocumentStatus.PARSED
    )


def _schedule_chunk(document_id: str, *, is_parsed: bool) -> bool:
    """`PARSED` 文档才分派切分任务（task 编排）。返回是否分派。"""
    if not is_parsed:
        return False
    document_chunk.delay(document_id)
    return True


def _is_embeddable(session: Session, document_id: uuid.UUID) -> bool:
    """文档是否为可向量化的准备态（`PARSED` 或 `EMBEDDING` 且含 `is_recallable` chunk）。

    状态与原料是否就绪一起判定（重放幂等：仅就绪才分派向量化任务）。
    放行 `EMBEDDING` 是为了让"向量化中被中断"的文档也能被重新分派（可重放）。
    """
    document = session.get(Document, document_id)
    if document is None or document.status not in (
        DocumentStatus.PARSED,
        DocumentStatus.EMBEDDING,
    ):
        return False
    has_recallable = session.scalar(
        select(1)
        .select_from(Chunk)
        .where(
            Chunk.document_id == document_id,
            Chunk.is_recallable.is_(True),
        )
        .limit(1)
    )
    return bool(has_recallable)


def _schedule_embed(document_id: str, *, is_ready: bool) -> bool:
    """可向量化文档才分派向量化任务（task 编排）。返回是否分派。"""
    if not is_ready:
        return False
    document_embed.delay(document_id)
    return True


def _embed_document(session: Session, document_id: uuid.UUID) -> bool:
    """推进一次向量化；文档缺失 / 非就绪 / 已就绪 → 短路 False（幂等）。"""
    document = session.get(Document, document_id)
    if document is None:
        return False
    return index_service.resolve_indexing(session, document)


def _chunk_document(
    session: Session,
    document_id: uuid.UUID,
    storage: LocalFileStorage,
    *,
    cfg: ChunkConfig | None = None,
    counter: TokenCounter | None = None,
) -> bool:
    """推进一次切分；文档缺失 / 非 `PARSED` / 已切分 → 短路 False（幂等）。"""
    document = session.get(Document, document_id)
    if document is None:
        return False
    return chunk_service.resolve_chunking(
        session, document, storage, cfg=cfg, counter=counter
    )


def _build_storage() -> LocalFileStorage:
    settings = get_settings()
    return LocalFileStorage(settings.storage_local_root)


def _build_mineru() -> MineruClient:
    settings = get_settings()
    token = settings.mineru_api_token
    if not token:
        from app.core.exceptions import InvalidConfigurationError

        raise InvalidConfigurationError("缺少必需配置项: MINERU_API_TOKEN")
    return MineruClient(
        base_url=settings.mineru_api_base,
        token=token,
        model_version=settings.mineru_model_version,
        timeout_sec=settings.mineru_http_timeout_sec,
        max_polls=max(
            1, round(settings.mineru_poll_timeout_sec / settings.mineru_poll_interval_sec)
        ),
        poll_interval_sec=settings.mineru_poll_interval_sec,
    )


@celery.task(name="document_parse", bind=True, max_retries=0)
def document_parse(self, document_id: str) -> None:
    """解析一篇 `UPLOADED` / `PARSING` 文档并推进状态；解析成功后分派切分任务。

    业务失败（上游异常等）写入文档与 job 并置 `FAILED`，不重试；数据契约被破坏
    （缺失原始文件路径 / 缺失 ingest_job）则抛出——此时文档保持瞬态、可修复后重放，
    不被钉死为 `FAILED`（spec：documents「解析状态机推进」的失败语义）。
    `IngestJob` 是入库进度的真相来源：RESOLVE → `PARSED`（job stage `PARSE`）
    → commit 后按状态分派 `document_chunk`。
    """
    did = uuid.UUID(document_id)
    session = get_session_factory()()
    try:
        _parse_document(session, did, _build_storage(), _build_mineru())
        session.commit()
        _schedule_chunk(document_id, is_parsed=_is_parsed(session, did))
    except Exception as exc:  # 兜底：确保未捕获异常也落下痕迹并可见
        session.rollback()
        logger.error("document_parse failed", document_id=document_id, error=str(exc))
        raise
    finally:
        session.close()


@celery.task(name="document_chunk", bind=True, max_retries=0)
def document_chunk(self, document_id: str) -> None:
    """切分一篇 `PARSED` / `CHUNKING` 文档并落 chunks；已切分 / `FAILED` 短路幂等。

    结论写入文档、job 与 `chunks`（同为 MySQL 事务），不重试。
    切分成功后若原料就绪（`PARSED` 且含 recallable chunks），分派向量化任务。
    """
    did = uuid.UUID(document_id)
    session = get_session_factory()()
    try:
        _chunk_document(session, did, _build_storage())
        session.commit()
        _schedule_embed(document_id, is_ready=_is_embeddable(session, did))
    except Exception as exc:  # 兜底：确保未捕获异常也落下痕迹并可见
        session.rollback()
        logger.error("document_chunk failed", document_id=document_id, error=str(exc))
        raise
    finally:
        session.close()


@celery.task(name="document_embed", bind=True, max_retries=0)
def document_embed(self, document_id: str) -> None:
    """向量化一篇原料就绪（`PARSED` / `EMBEDDING` 且含 chunks）文档并写 Milvus → `READY`。

    非就绪 / 已 `READY` / `FAILED` 短路幂等；状态与 `ingest_job` 由 `index_service`
    推进（MySQL 为真相），失败置 `FAILED`，不重试（可修复后重放）。
    """
    session = get_session_factory()()
    try:
        _embed_document(session, uuid.UUID(document_id))
        session.commit()
    except Exception as exc:  # 兜底：确保未捕获异常也落下痕迹并可见
        session.rollback()
        logger.error("document_embed failed", document_id=document_id, error=str(exc))
        raise
    finally:
        session.close()
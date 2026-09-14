"""文档服务（上传创建 + 查询 + 软删）。

本 change 覆盖解析段：`UPLOADED → PARSING → PARSED / FAILED`。服务层纯业务逻辑，
不做权限预检（路由依赖负责）；文件 I/O 通过传入的 `FileStorage` 抽象，DB 走 SQLAlchemy。

校验顺序（design D8 + D3）：格式白名单（415）→ 大小上限（413）→ 库内哈希去重（409）。
权限 `EDITOR` / `KB_ADMIN` 由路由层 `require_kb_role` 接线。
"""

from __future__ import annotations

import uuid
from hashlib import sha256
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, load_only

from app.core.exceptions import (
    ConflictError,
    FileTooLargeError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.core.ids import uuid7
from app.integrations.mineru import MineruClient
from app.integrations.storage import FileStorage
from app.models import Chunk
from app.models.base import utcnow
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus

# 上传格式白名单（design D8：收敛为 MinerU 云端 API 真正支持的 pdf / docx）
DEFAULT_ALLOWED_EXTS = frozenset({"pdf", "docx"})


def create_document(
    session: Session,
    *,
    kb_id: uuid.UUID,
    filename: str,
    content_type: str | None,
    data: bytes,
    storage: FileStorage,
    allowed_exts: frozenset[str],
    upload_max_bytes: int,
) -> Document:
    """上传创建文档：类型/大小校验后，库内哈希去重，同一事务建 `Document` + `IngestJob`。

    - 扩展名不在白名单 → 415 `UnsupportedFileTypeError`
    - 超过大小上限 → 413 `FileTooLargeError`
    - 库内已有**活跃且 PARSED** 同哈希文档 → 409 `ConflictError`（软删 / FAILED 不占去重）
    """
    _validate_size(data, upload_max_bytes)
    ext = _validate_extension(filename, allowed_exts)

    digest = sha256(data).hexdigest()
    existing = _find_parsed_duplicate(session, kb_id, digest)
    if existing is not None:
        raise ConflictError("库内已存在内容相同的文档")

    document_id = uuid7()
    raw_path = storage.save_raw(
        kb_id=str(kb_id), document_id=str(document_id), filename=filename, data=data
    )
    document = Document(
        id=document_id,
        kb_id=kb_id,
        filename=Path(filename).name,
        file_hash=digest,
        file_size=len(data),
        content_type=_clean_content_type(content_type, ext),
        status=DocumentStatus.UPLOADED,
        raw_path=raw_path,
    )
    job = IngestJob(
        document_id=document_id,
        kb_id=kb_id,
        stage="PARSE",
        status=IngestJobStatus.PENDING,
    )
    session.add(document)
    session.add(job)
    session.flush()
    return document


def _validate_size(data: bytes, upload_max_bytes: int) -> None:
    if len(data) > upload_max_bytes:
        raise FileTooLargeError(
            f"文件超过大小上限 {upload_max_bytes} 字节"
        )


def _validate_extension(filename: str, allowed_exts: frozenset[str]) -> str:
    ext = Path(filename).suffix.lstrip(".").lower()
    if ext not in allowed_exts:
        raise UnsupportedFileTypeError(f"不支持的文件类型: .{ext if ext else '(无)'}")
    return ext


def _find_parsed_duplicate(
    session: Session, kb_id: uuid.UUID, digest: str
) -> Document | None:
    """库内活跃且 `PARSED` 的同哈希文档。软删由全局过滤排除。"""
    return session.scalar(
        select(Document).where(
            Document.kb_id == kb_id,
            Document.file_hash == digest,
            Document.status == DocumentStatus.PARSED,
        )
    )


def _clean_content_type(content_type: str | None, ext: str) -> str | None:
    """归一化 content_type：显式传入时采用；否则按已知扩展名兜底，未知留空。"""
    if content_type:
        return content_type
    known: dict[str, str] = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }
    return known.get(f".{ext}")


def resolve_parse(
    session: Session,
    document: Document,
    storage: FileStorage,
    mineru: MineruClient,
) -> None:
    """驱动一次解析：`UPLOADED → PARSED / FAILED`，并同步 `ingest_job`。

    - 入口校验：非 `UPLOADED` 直接返回（幂等，design D6 —— 状态即重放护栏）
    - 成功：产物先落盘拿到 `artifact_path`，再置 `PARSED`，job → `SUCCESS`
    - 失败：文档与 job 均置 `FAILED` 并记错误信息（job 是状态真相）
    """
    if document.status != DocumentStatus.UPLOADED:
        return

    raw_path = document.raw_path
    if raw_path is None:
        raise RuntimeError("文档缺少原始文件路径，无法解析")
    job = session.scalar(
        select(IngestJob).where(IngestJob.document_id == document.id)
    )
    if job is None:
        raise RuntimeError("缺失 ingest_job，入库任务无法推进")
    job.status = IngestJobStatus.RUNNING
    job.started_at = utcnow()

    try:
        result = mineru.parse(filename=document.filename, data=storage.open_raw(raw_path))
        artifact_path = storage.save_artifact(
            kb_id=str(document.kb_id),
            document_id=str(document.id),
            name="content_list.json",
            data=result.content_list,
        )
        document.artifact_path = artifact_path
        document.status = DocumentStatus.PARSED
        if result.page_count is not None:
            document.page_count = result.page_count
        job.progress_current = 1
        job.progress_total = 1
        job.status = IngestJobStatus.SUCCESS
    except Exception as exc:
        _fail(document, job, exc)
    finally:
        job.finished_at = utcnow()
        session.flush()


def _fail(document: Document, job: IngestJob, exc: Exception) -> None:
    message = str(exc) or exc.__class__.__name__
    document.status = DocumentStatus.FAILED
    document.error_message = message
    job.status = IngestJobStatus.FAILED
    job.error = message


def list_documents(session: Session, kb_id: uuid.UUID) -> list[Document]:
    """列出某库内全部未软删文档（软删过滤由全局钩子附加）。"""
    return list(
        session.execute(
            select(Document).where(Document.kb_id == kb_id).order_by(Document.created_at)
        ).scalars().all()
    )


def get_document(session: Session, kb_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    """按 id 取库内文档；不存在、被软删或不属于该库 → 404。"""
    document = session.get(Document, document_id)
    if document is None or document.kb_id != kb_id:
        raise NotFoundError("文档不存在")
    return document


def soft_delete_document(session: Session, kb_id: uuid.UUID, document_id: uuid.UUID) -> None:
    """软删文档及其全部 chunks；不存在 → 404。

    幂等：文档已软删时仍可再次调用（不覆盖原始删除时间、不重复清 chunks）。
    用 `include_soft_deleted` 显式取出已删文档，避免被全局软删过滤遮挡。
    不物理删文件（清理归 ops 对账任务）。
    """
    document = session.scalar(
        select(Document)
        .execution_options(include_soft_deleted=True)
        .where(Document.id == document_id, Document.kb_id == kb_id)
    )
    if document is None:
        raise NotFoundError("文档不存在")
    document.soft_delete()
    _soft_delete_chunks(session, document_id)
    session.flush()


def _soft_delete_chunks(session: Session, document_id: uuid.UUID) -> None:
    """软删某文档全部活跃 chunks（用 `load_only` 排除大字段 `content`）。

    chunks 软删幂等：复用 `Chunk.soft_delete`，已删行由全局过滤排除、不会重复处理。
    """
    chunks = list(
        session.execute(
            select(Chunk)
            .options(load_only(Chunk.id, Chunk.deleted_at))
            .where(Chunk.document_id == document_id)
        ).scalars().all()
    )
    for chunk in chunks:
        chunk.soft_delete()


def job_status_of(session: Session, document_id: uuid.UUID) -> str | None:
    """某文档的入库任务状态字符串；无 job 返回 None（供响应展示）。"""
    status = session.scalar(
        select(IngestJob.status).where(IngestJob.document_id == document_id)
    )
    return status.value if status is not None else None


def job_stage_of(session: Session, document_id: uuid.UUID) -> str | None:
    """某文档的入库任务阶段字符串（如 `PARSE` / `CHUNK`）；无 job 返回 None。"""
    return session.scalar(
        select(IngestJob.stage).where(IngestJob.document_id == document_id)
    )
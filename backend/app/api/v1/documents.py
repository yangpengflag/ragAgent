"""文档路由（上传 / 列表 / 详情 / 软删）。

路由层只做参数声明、依赖装配与响应组装；业务逻辑在 `document_service`。
权限（design D7）：上传/软删需对库持 `EDITOR` / `KB_ADMIN`（或系统 `ADMIN`），
列表/详情只需「可访问该库」。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, File, Path, UploadFile
from sqlalchemy.orm import Session

from app.api.deps import (
    DocumentStorageDep,
    SessionDep,
    UploadLimitsDep,
    current_request_id,
)
from app.api.v1.dependency_kb import KbAccessDep, require_kb_role
from app.core.config import get_settings
from app.models.document import Document
from app.models.user_kb_grant import KbRole
from app.schemas.document import (
    DeleteDocumentResponse,
    DocumentResponse,
    DocumentSummary,
    ListDocumentsResponse,
)
from app.services import document_service, index_service, kb_service
from app.tasks.ingest import document_parse

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["documents"])

RequestIdDep = Annotated[str, Depends(current_request_id)]
# 写操作所需的库级角色：EDITOR / KB_ADMIN
KbWriteDep = Annotated[uuid.UUID, Depends(require_kb_role(KbRole.EDITOR, KbRole.KB_ADMIN))]


def _document_payload(
    doc: Document, session: Session, request_id: str
) -> DocumentResponse:
    return DocumentResponse(
        request_id=request_id,
        id=str(doc.id),
        kb_id=str(doc.kb_id),
        filename=doc.filename,
        file_size=doc.file_size,
        content_type=doc.content_type,
        status=str(doc.status),
        page_count=doc.page_count,
        error_message=doc.error_message,
        job_status=document_service.job_status_of(session, doc.id),
        job_stage=document_service.job_stage_of(session, doc.id),
        created_at=doc.created_at.isoformat(),
    )


def _summary(doc: Document, session: Session) -> DocumentSummary:
    return DocumentSummary(
        id=str(doc.id),
        filename=doc.filename,
        status=str(doc.status),
        file_size=doc.file_size,
        page_count=doc.page_count,
        job_status=document_service.job_status_of(session, doc.id),
        job_stage=document_service.job_stage_of(session, doc.id),
        created_at=doc.created_at.isoformat(),
    )


@router.post(
    "/{kb_id}/documents",
    status_code=201,
    response_model=DocumentResponse,
)
def upload_document(
    kb_id: KbWriteDep,
    session: SessionDep,
    request_id: RequestIdDep,
    storage: DocumentStorageDep,
    upload_limits: UploadLimitsDep,
    file: Annotated[UploadFile, File(description="要解析的文档（pdf / docx）")],
) -> DocumentResponse:
    max_bytes, allowed_exts = upload_limits
    # 权限对系统 ADMIN 恒放行，但需显式确认库存在 → 404
    kb_service.get_kb(session, kb_id)
    data = file.file.read()
    document = document_service.create_document(
        session,
        kb_id=kb_id,
        filename=file.filename or "untitled",
        content_type=file.content_type,
        data=data,
        storage=storage,
        allowed_exts=allowed_exts,
        upload_max_bytes=max_bytes,
    )
    # 先提交落库，再分派首个解析任务（Celery worker 另起会话）——
    # 否则 worker 可能早于 DB 提交读到 404，任务幂等短路导致链路空转
    session.commit()
    document_parse.delay(str(document.id))
    return _document_payload(document, session, request_id)


@router.get("/{kb_id}/documents", response_model=ListDocumentsResponse)
def list_documents(
    kb_id: KbAccessDep, session: SessionDep, request_id: RequestIdDep
) -> ListDocumentsResponse:
    documents = document_service.list_documents(session, kb_id)
    return ListDocumentsResponse(
        request_id=request_id,
        items=[_summary(doc, session) for doc in documents],
    )


@router.get("/{kb_id}/documents/{document_id}", response_model=DocumentResponse)
def get_document(
    kb_id: KbAccessDep,
    document_id: Annotated[uuid.UUID, Path(description="文档 ID")],
    session: SessionDep,
    request_id: RequestIdDep,
) -> DocumentResponse:
    document = document_service.get_document(session, kb_id, document_id)
    return _document_payload(document, session, request_id)


@router.delete("/{kb_id}/documents/{document_id}", response_model=DeleteDocumentResponse)
def delete_document(
    kb_id: KbWriteDep,
    document_id: Annotated[uuid.UUID, Path(description="文档 ID")],
    session: SessionDep,
    request_id: RequestIdDep,
) -> DeleteDocumentResponse:
    document_service.soft_delete_document(session, kb_id, document_id)
    # design D4：DB 软删先提交，再尽力清 Milvus 向量（失败不阻塞软删、仅记日志）
    session.commit()
    index_service.clear_document_vectors(get_settings(), kb_id, document_id)
    return DeleteDocumentResponse(request_id=request_id, id=str(document_id), deleted=True)
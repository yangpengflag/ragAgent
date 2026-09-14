"""文档请求/响应模型。

字段名与后端 JSON 一致（snake_case）；响应携带入库任务状态（`job_status`）
供前端展示解析进度。
"""

from __future__ import annotations

from pydantic import BaseModel

from app.schemas.base import ApiResponse


class DocumentResponse(ApiResponse):
    """单个文档响应（上传成功 / 详情共用）。"""

    id: str
    kb_id: str
    filename: str
    file_size: int
    content_type: str | None
    status: str
    page_count: int | None
    error_message: str | None
    job_status: str | None
    job_stage: str | None
    created_at: str


class DocumentSummary(BaseModel):
    """列表项摘要。"""

    id: str
    filename: str
    status: str
    file_size: int
    page_count: int | None
    job_status: str | None
    job_stage: str | None
    created_at: str


class ListDocumentsResponse(ApiResponse):
    items: list[DocumentSummary]


class DeleteDocumentResponse(ApiResponse):
    id: str
    deleted: bool
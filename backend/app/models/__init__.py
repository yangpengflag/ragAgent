"""模型包：导入即注册进 `Base.metadata`（Alembic 的 target_metadata 依赖它）。

新增模型时**必须**在此导出，否则 autogenerate 与 `create_all` 都看不到它。
"""

from __future__ import annotations

from app.models.base import Base, BaseModel
from app.models.chunk import Chunk
from app.models.document import Document, DocumentStatus
from app.models.ingest_job import IngestJob, IngestJobStatus
from app.models.knowledge_base import KnowledgeBase
from app.models.user import Account, SystemRole
from app.models.user_kb_grant import KbRole, UserKbGrant

__all__ = [
    "Account",
    "Base",
    "BaseModel",
    "Chunk",
    "Document",
    "DocumentStatus",
    "IngestJob",
    "IngestJobStatus",
    "KbRole",
    "KnowledgeBase",
    "SystemRole",
    "UserKbGrant",
]

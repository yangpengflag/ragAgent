"""入库任务模型。

一次文档入库的全景任务（design D2）：上传即建、与文档 1:1，本 change 推进到
解析段（`PARSED`）。MySQL 是状态的真相来源（`api-conventions.md` 异步任务约定）；
切分 / 向量化 change 复用同一 job 续推 stage，不另建记录。
"""

from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, BaseModel


class IngestJobStatus(enum.StrEnum):
    """入库任务生命周期。"""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class IngestJob(BaseModel):
    """一次入库任务（解析 → 切分 → 向量化 → 写入，本 change 到解析段）。"""

    __tablename__ = "ingest_jobs"

    # 1:1：一篇文档只允许一条进行中的入库任务
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("documents.id", name="fk_ingest_jobs_document_id"),
        nullable=False,
        unique=True,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("knowledge_bases.id", name="fk_ingest_jobs_kb_id"),
        nullable=False,
        index=True,
    )
    # 当前阶段；本 change 固定为 PARSE，切分/向量化 change 追加
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="PARSE")
    status: Mapped[IngestJobStatus] = mapped_column(
        SQLEnum(
            IngestJobStatus,
            name="ingest_job_status",
            native_enum=False,
            length=16,
            validate_strings=True,
        ),
        nullable=False,
        default=IngestJobStatus.PENDING,
    )
    progress_current: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    progress_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<IngestJob doc={self.document_id} stage={self.stage} status={self.status}>"
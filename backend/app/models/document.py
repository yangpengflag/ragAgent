"""文档模型。

文档唯一归属于一个知识库（权限与检索的隔离单元）。状态机只到解析段的
四个态（design D1）：`UPLOADED → PARSING → PARSED / FAILED`，后续
`CHUNKING / EMBEDDING / READY` 由切分与向量化 change 追加枚举值。

原始文件与解析产物路径由 `FileStorage` 决定（`<root>/<kb_id>/<doc_id>/`），
这里只存相对路径，不拼绝对根（根属于配置，见 design D4）。
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, BaseModel

# SHA-256 十六进制长度为 64；文件名/Mime/路径均设上限防滥用
FILE_HASH_MAX_LENGTH = 64
FILENAME_MAX_LENGTH = 255
CONTENT_TYPE_MAX_LENGTH = 100
STORAGE_PATH_MAX_LENGTH = 1024


class DocumentStatus(enum.StrEnum):
    """文档解析状态机（解析段）。

    追加后续态（`CHUNKING` / `EMBEDDING` / `READY`）时需评估存量兼容，
    见 `database-conventions.md` 枚举约定。
    """

    UPLOADED = "UPLOADED"
    PARSING = "PARSING"
    PARSED = "PARSED"
    # 切分中瞬态：切分落库完成后回 PARSED（= 索引原料就绪）
    CHUNKING = "CHUNKING"
    # 向量化中瞬态：编码 + 写 Milvus 完成后置 READY（= 可检索终态）
    EMBEDDING = "EMBEDDING"
    READY = "READY"
    FAILED = "FAILED"


class Document(BaseModel):
    """知识库内的一篇文档。"""

    __tablename__ = "documents"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("knowledge_bases.id", name="fk_documents_kb_id"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(FILENAME_MAX_LENGTH), nullable=False)
    # SHA-256：库内去重键（相同内容去重，见 design D3）
    file_hash: Mapped[str] = mapped_column(String(FILE_HASH_MAX_LENGTH), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    content_type: Mapped[str | None] = mapped_column(
        String(CONTENT_TYPE_MAX_LENGTH), nullable=True
    )
    status: Mapped[DocumentStatus] = mapped_column(
        SQLEnum(
            DocumentStatus,
            name="document_status",
            native_enum=False,
            length=16,
            validate_strings=True,
        ),
        nullable=False,
        default=DocumentStatus.UPLOADED,
    )
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    raw_path: Mapped[str | None] = mapped_column(String(STORAGE_PATH_MAX_LENGTH), nullable=True)
    artifact_path: Mapped[str | None] = mapped_column(
        String(STORAGE_PATH_MAX_LENGTH), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<Document {self.filename} status={self.status}>"
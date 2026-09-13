"""SQLAlchemy 声明式基类与公共字段约定。

约定见 `design.md` D7：
- 主键 UUID v7，MySQL 存 `BINARY(16)`，SQLite 回退 `CHAR(32)`（内存库测试用）
- 时间由应用层生成 naive UTC，禁止 `func.now()` / `CURRENT_TIMESTAMP`
- 软删只提供字段与方法，不注册全局查询过滤
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BINARY, CHAR, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

from app.core.ids import uuid7


def utcnow() -> datetime:
    """当前 UTC 时间（naive，避免 MySQL DATETIME 的时区歧义）。"""
    return datetime.now(UTC).replace(tzinfo=None)


class GUID(TypeDecorator[uuid.UUID]):
    """UUID ↔ BINARY(16)；SQLite 方言回退为 CHAR(32) 以支持内存库测试。"""

    impl = BINARY(16)
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:
        if dialect.name == "sqlite":
            return dialect.type_descriptor(CHAR(32))
        return dialect.type_descriptor(BINARY(16))

    def process_bind_param(self, value: Any, dialect: Any) -> Any:
        if value is None:
            return None
        identifier = value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))
        return identifier.hex if dialect.name == "sqlite" else identifier.bytes

    def process_result_value(self, value: Any, dialect: Any) -> uuid.UUID | None:
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(hex=value) if dialect.name == "sqlite" else uuid.UUID(bytes=value)


class Base(DeclarativeBase):
    """所有模型的声明式基类。"""


class BaseModel(Base):
    """公共字段：UUID v7 主键、创建时间（不可更新）、更新时间、软删标记。"""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(GUID, primary_key=True, default=uuid7)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utcnow, onupdate=utcnow, nullable=False
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def soft_delete(self) -> None:
        """标记式删除：写入 deleted_at，不物理删除行。"""
        self.deleted_at = utcnow()

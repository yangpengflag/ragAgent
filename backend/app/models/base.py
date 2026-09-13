"""SQLAlchemy 声明式基类与公共字段约定。

约定见 `design.md` D7 与 `auth-and-users/design.md` D15：

- 主键 UUID v7，MySQL 存 `BINARY(16)`，SQLite 回退 `CHAR(32)`（内存库测试用）
- 时间由应用层生成 naive UTC，禁止 `func.now()` / `CURRENT_TIMESTAMP`
- 软删为标记式，并提供**全局查询过滤**（默认查不到已软删行），
  需要连已软删一起查时用语句级执行选项 `include_soft_deleted`
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import BINARY, CHAR, DateTime, event
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, with_loader_criteria
from sqlalchemy.types import TypeDecorator

from app.core.ids import uuid7

# 逃生通道的执行选项名：置 True 时本次查询**包含**已软删行
INCLUDE_SOFT_DELETED = "include_soft_deleted"


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
    # 软删过滤条件会出现在几乎每次查询上，因此建索引
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)

    def soft_delete(self) -> None:
        """标记式删除：写入 `deleted_at`，不物理删除行。

        幂等：已软删的记录再次调用不会覆盖原始删除时间（否则审计时间会被不断改写）。
        """
        if self.deleted_at is None:
            self.deleted_at = utcnow()


@event.listens_for(Session, "do_orm_execute")
def _exclude_soft_deleted(state: Any) -> None:
    """为所有 ORM SELECT 自动附加 `deleted_at IS NULL`。

    这是"软删"这个约定真正生效的地方：如果只加字段不加过滤，每个查询点都要记得
    手写 `deleted_at IS NULL`，迟早会漏（漏了就会把已删账号当成有效账号，
    或把已删文档重新召回）。

    需要连已软删一起查时，显式声明语句级执行选项：

        session.execute(select(Account).execution_options(include_soft_deleted=True))

    逃生通道刻意做成**语句级**而非会话级上下文管理器：`Session` 没有公开的
    "读取当前 execution_options" 的 API，会话级开关要么依赖私有属性、要么在嵌套时
    无法正确恢复。语句级更显式，也能被 grep 到。

    经实测，`Session.get()`（按主键加载）同样经过本事件、也受过滤，
    因此业务代码用 `select()` 或 `get()` 都不会漏出已软删行。
    """
    if not state.is_select or state.execution_options.get(INCLUDE_SOFT_DELETED):
        return
    state.statement = state.statement.options(
        with_loader_criteria(
            BaseModel,
            lambda cls: cls.deleted_at.is_(None),
            include_aliases=True,
        )
    )

"""知识库授权模型。

一个用户在一个知识库**只持一个角色**，这是业务事实，因此直接用复合主键
`(user_id, kb_id)` 表达——无需额外唯一索引，也天然阻止重复授权行。

刻意**不继承 `BaseModel`**：基类会带 UUID v7 代理主键与软删字段，与
"复合主键表达业务事实"相冲突（会变成三列复合键），且授权撤销是**删行**
而非软删（撤销必须立即生效，软删行若漏过滤就是越权窗口）。

库级角色与系统级角色（`SystemRole`）是两层：系统级看"是不是管理员"，
库级看"在这个库里能做什么"。
"""

from __future__ import annotations

import enum
import uuid

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, Base


class KbRole(enum.StrEnum):
    """库级角色（授权维度）。

    - `KB_ADMIN`：管理本库信息与成员
    - `EDITOR`：上传与维护文档（写入动作的业务校验随 ingest change 落地）
    - `VIEWER`：仅检索与问答
    """

    KB_ADMIN = "KB_ADMIN"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"


class UserKbGrant(Base):
    """用户对某知识库的授权记录（库级粒度）。"""

    __tablename__ = "user_kb_grant"

    # 与 `users.id` / `knowledge_bases.id` 同为 GUID（MySQL BINARY(16)）：
    # 用 sa.Uuid() 会渲染成 CHAR(32)，外键因类型不匹配被 MySQL 拒绝（error 3780）
    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("users.id", name="fk_user_kb_grant_user_id"),
        primary_key=True,
    )
    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("knowledge_bases.id", name="fk_user_kb_grant_kb_id"),
        primary_key=True,
    )
    role: Mapped[KbRole] = mapped_column(
        SQLEnum(
            KbRole,
            name="kb_role",
            native_enum=False,
            length=16,
            validate_strings=True,
        ),
        nullable=False,
        default=KbRole.VIEWER,
    )

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<UserKbGrant user={self.user_id} kb={self.kb_id} role={self.role}>"

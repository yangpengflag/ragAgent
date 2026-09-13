"""用户账号模型。

`Account` 是项目里**首个业务实体**，因此它同时承担两件事：

1. 承载账号字段：用户名、显示名、密码哈希、启用状态、系统角色、会话纪元
2. 落地「软删与唯一约束兼容」的机制（`database-conventions.md` 与
   `notes/scaffold/residual-risks.md` 第 5 条要求在首个业务实体上一次性解决）

关于用户名的唯一性：MySQL **不支持部分（带 WHERE 的）索引**，因此无法直接写
`UNIQUE(username) WHERE deleted_at IS NULL`。这里改用**虚拟生成列 + 唯一索引**：
生成列在账号活跃时等于 `username`、软删后为 `NULL`，而唯一索引允许多个 `NULL`——
于是"活跃账号唯一、软删账号让位"同时成立，且 MySQL 与 SQLite（测试库）都支持。
"""

from __future__ import annotations

import enum

from sqlalchemy import Boolean, Computed, Index, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

USERNAME_MAX_LENGTH = 64
DISPLAY_NAME_MAX_LENGTH = 128
PASSWORD_HASH_MAX_LENGTH = 255


class SystemRole(enum.StrEnum):
    """系统级角色（账号维度）。

    与**库级**角色（`KB_ADMIN` / `EDITOR` / `VIEWER`）是两层，见 `project.md`；
    库级角色随知识库能力引入，本模型不承载。
    """

    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


# 派生列表达式：用 CASE WHEN 而非 MySQL 的 IF()，以便 SQLite 上同样可建表（测试）
USERNAME_ACTIVE_EXPRESSION = "CASE WHEN deleted_at IS NULL THEN username ELSE NULL END"


class Account(BaseModel):
    """用户账号。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(USERNAME_MAX_LENGTH), nullable=False)
    display_name: Mapped[str] = mapped_column(String(DISPLAY_NAME_MAX_LENGTH), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(PASSWORD_HASH_MAX_LENGTH), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    system_role: Mapped[SystemRole] = mapped_column(
        SQLEnum(
            SystemRole,
            name="system_role",
            native_enum=False,
            length=16,
            validate_strings=True,
        ),
        nullable=False,
        default=SystemRole.MEMBER,
    )
    # 会话纪元：递增即让该账号已签发的全部刷新令牌失效
    # （重置密码、停用、软删、改角色时 +1，见 design D14）
    session_epoch: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # 仅供唯一约束使用的派生列：活跃 = username，软删 = NULL。
    # 不对外暴露（响应模型只取显式字段）。
    username_active: Mapped[str | None] = mapped_column(
        String(USERNAME_MAX_LENGTH),
        Computed(USERNAME_ACTIVE_EXPRESSION, persisted=False),
        nullable=True,
    )

    __table_args__ = (
        Index("uk_users_username_active", "username_active", unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<Account {self.username} role={self.system_role} active={self.is_active}>"

"""users

Revision ID: c4f1b8d29e57
Revises: a628827479f5
Create Date: 2026-09-13 12:40:00.000000

首个业务实体（账号）。两处需要说明：

1. **用户名唯一性**：MySQL 不支持带 `WHERE` 的部分索引，因此不能写
   `UNIQUE(username) WHERE deleted_at IS NULL`。这里用虚拟生成列
   `username_active = CASE WHEN deleted_at IS NULL THEN username ELSE NULL END`
   + 其上的唯一索引实现"活跃账号唯一、软删账号让位"（唯一索引允许多个 NULL）。
2. 表达式用标准 `CASE WHEN`（而非 MySQL 专有的 `IF()`），使同一份模型能在
   SQLite 内存库上建表（单元测试不依赖 MySQL）。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f1b8d29e57"
down_revision: str | Sequence[str] | None = "a628827479f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 与 `app/models/user.py::USERNAME_ACTIVE_EXPRESSION` 保持一致
_USERNAME_ACTIVE_EXPRESSION = "CASE WHEN deleted_at IS NULL THEN username ELSE NULL END"


def upgrade() -> None:
    """建 users 表。"""
    op.create_table(
        "users",
        sa.Column("username", sa.String(length=64), nullable=False),
        sa.Column("display_name", sa.String(length=128), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("system_role", sa.String(length=16), nullable=False, server_default="MEMBER"),
        sa.Column("session_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("id", sa.BINARY(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        # 生成列放最后：它引用同表的 username 与 deleted_at
        sa.Column(
            "username_active",
            sa.String(length=64),
            sa.Computed(_USERNAME_ACTIVE_EXPRESSION, persisted=False),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.CheckConstraint("system_role IN ('ADMIN', 'MEMBER')", name="ck_users_system_role"),
    )
    op.create_index("uk_users_username_active", "users", ["username_active"], unique=True)
    op.create_index("idx_users_deleted_at", "users", ["deleted_at"], unique=False)


def downgrade() -> None:
    """回退：删索引后删表。"""
    op.drop_index("idx_users_deleted_at", table_name="users")
    op.drop_index("uk_users_username_active", table_name="users")
    op.drop_table("users")

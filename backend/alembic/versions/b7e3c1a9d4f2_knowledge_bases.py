"""knowledge_bases + user_kb_grant

Revision ID: b7e3c1a9d4f2
Revises: c4f1b8d29e57
Create Date: 2026-09-13 13:20:00.000000

知识库（权限与检索的隔离单元）与库级授权表。

1. **knowledge_bases**：名称唯一沿用 `users` 的同款方案——虚拟生成列
   `name_active = CASE WHEN deleted_at IS NULL THEN name ELSE NULL END`
   + 唯一索引（MySQL 不支持部分索引；唯一索引允许多个 NULL，于是
   "活跃库唯一、软删库让位"成立）。表达式用标准 `CASE WHEN`，
   SQLite 内存库（单元测试）同样可建表。
2. **user_kb_grant**：复合主键 `(user_id, kb_id)` 直接表达"一用户一库一角色"，
   不带代理主键也不带软删字段——撤销授权是**删行**，软删行若漏过滤就是越权窗口。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c1a9d4f2"
down_revision: str | Sequence[str] | None = "c4f1b8d29e57"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 与 `app/models/knowledge_base.py::KB_NAME_ACTIVE_EXPRESSION` 保持一致
_KB_NAME_ACTIVE_EXPRESSION = "CASE WHEN deleted_at IS NULL THEN name ELSE NULL END"


def upgrade() -> None:
    """建 knowledge_bases 与 user_kb_grant。"""
    op.create_table(
        "knowledge_bases",
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("description", sa.Text(length=512), nullable=True),
        sa.Column("embedding_model", sa.String(length=64), nullable=False),
        sa.Column("embed_dim", sa.Integer(), nullable=False),
        sa.Column("id", sa.BINARY(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        # 生成列放最后：引用同表的 name 与 deleted_at
        sa.Column(
            "name_active",
            sa.String(length=128),
            sa.Computed(_KB_NAME_ACTIVE_EXPRESSION, persisted=False),
            nullable=True,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_knowledge_bases"),
    )
    op.create_index(
        "uk_knowledge_bases_name_active",
        "knowledge_bases",
        ["name_active"],
        unique=True,
    )
    op.create_index(
        "idx_knowledge_bases_deleted_at",
        "knowledge_bases",
        ["deleted_at"],
        unique=False,
    )

    op.create_table(
        "user_kb_grant",
        # 与 users.id / knowledge_bases.id 同为 BINARY(16)（项目 GUID 类型），
        # 用 sa.Uuid() 会渲染 CHAR(32)，外键因类型不匹配被 MySQL 拒绝（error 3780）
        sa.Column("user_id", sa.BINARY(length=16), nullable=False),
        sa.Column("kb_id", sa.BINARY(length=16), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="VIEWER"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_kb_grant_user_id"
        ),
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], name="fk_user_kb_grant_kb_id"
        ),
        sa.PrimaryKeyConstraint("user_id", "kb_id", name="pk_user_kb_grant"),
        sa.CheckConstraint(
            "role IN ('KB_ADMIN', 'EDITOR', 'VIEWER')", name="ck_user_kb_grant_role"
        ),
    )
    op.create_index(
        "idx_user_kb_grant_kb_id", "user_kb_grant", ["kb_id"], unique=False
    )


def downgrade() -> None:
    """回退：先删授权表（外键依赖），再删知识库表。

    授权表上的索引由外键约束依赖，MySQL 不允许单独 drop（error 1553）；
    直接删表会连带释放其索引与外键，因此这里不做 drop_index。
    """
    op.drop_table("user_kb_grant")
    op.drop_index("idx_knowledge_bases_deleted_at", table_name="knowledge_bases")
    op.drop_index("uk_knowledge_bases_name_active", table_name="knowledge_bases")
    op.drop_table("knowledge_bases")

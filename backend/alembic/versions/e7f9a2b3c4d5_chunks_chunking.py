"""chunks + documents.status 追加 CHUNKING

Revision ID: e7f9a2b3c4d5
Revises: d0c5a28e6b13
Create Date: 2026-09-14 00:00:00.000000

1. **chunks**：切分后的检索单元（Child / Parent 同表）。字段与 `RetrievedChunk`
   契约对齐（`content`/`page_idx`/`bbox`）；`parent_id` 自关联（Child→Parent）；
   `bbox` 为 JSON 列（仅整体读写、不参与查询）；外键列用项目 `GUID`（MySQL
   `BINARY(16)`），避免与 `knowledge_bases`/`documents`/`chunks` 主键类型不配。
2. **documents.status**：SQLAlchemy 枚举（native_enum=False，VARCHAR+CHECK）
   MODIFY 追加 `CHUNKING`（切分中瞬态），随同一次迁移规避分片风险；
   `downgrade` 还原为不含 `CHUNKING` 的枚举。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7f9a2b3c4d5"
down_revision: str | Sequence[str] | None = "d0c5a28e6b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# documents.status 追加 CHUNKING 前/后的合法值
_STATUS_BEFORE = ["UPLOADED", "PARSING", "PARSED", "FAILED"]
_STATUS_AFTER = ["UPLOADED", "PARSING", "PARSED", "CHUNKING", "FAILED"]


def upgrade() -> None:
    """建 chunks 表；documents.status 枚举追加 CHUNKING。"""
    op.create_table(
        "chunks",
        sa.Column("kb_id", sa.BINARY(length=16), nullable=False),
        sa.Column("document_id", sa.BINARY(length=16), nullable=False),
        sa.Column("parent_id", sa.BINARY(length=16), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("section_path", sa.String(length=512), nullable=False),
        sa.Column("page_idx", sa.Integer(), nullable=True),
        sa.Column("bbox", sa.JSON(), nullable=True),
        sa.Column("block_type", sa.String(length=32), nullable=False),
        sa.Column("is_recallable", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BINARY(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], name="fk_chunks_kb_id"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_chunks_document_id"
        ),
        sa.ForeignKeyConstraint(
            ["parent_id"], ["chunks.id"], name="fk_chunks_parent_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
    )
    op.create_index("idx_chunks_kb_id", "chunks", ["kb_id"], unique=False)
    op.create_index("idx_chunks_document_id", "chunks", ["document_id"], unique=False)
    op.create_index("idx_chunks_parent_id", "chunks", ["parent_id"], unique=False)
    op.create_index("idx_chunks_deleted_at", "chunks", ["deleted_at"], unique=False)

    _alter_status_enum(_STATUS_AFTER)


def downgrade() -> None:
    """回滚：还原 documents.status 枚举；删 chunks（先删外键索引无碍）。"""
    _alter_status_enum(_STATUS_BEFORE)
    op.drop_table("chunks")


def _alter_status_enum(values: list[str]) -> None:
    """MODIFY documents.status，只改枚举值集合（native_enum=False VARCHAR+CHECK）。

    MySQL 的 `MODIFY COLUMN` 不会自动重建已**命名**的列级 CHECK 约束
    （`ck_documents_document_status`，见 base.py naming_convention）；必须先显式
    删除旧 CHECK，再改列类型（新枚举在列定义里生成同名新 CHECK）。
    用原始 SQL 按真实约束名删除，避免 op.drop_constraint 再次套用 naming_convention
    导致约束名被双写（`ck_documents_ck_documents_...`）。
    """
    op.execute("ALTER TABLE documents DROP CHECK ck_documents_document_status")
    op.alter_column(
        "documents",
        "status",
        existing_type=sa.Enum(
            *values,
            name="document_status",
            native_enum=False,
            length=16,
            create_constraint=True,
        ),
        existing_nullable=False,
    )
    # alter_column 只改列类型（VARCHAR(16)）不重建命名 CHECK，这里按真实约束名补回
    quoted = ", ".join(f"'{v}'" for v in values)
    op.create_check_constraint(
        "document_status",
        "documents",
        f"status IN ({quoted})",
    )
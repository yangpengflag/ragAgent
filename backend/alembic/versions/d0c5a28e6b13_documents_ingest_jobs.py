"""documents + ingest_jobs

Revision ID: d0c5a28e6b13
Revises: b7e3c1a9d4f2
Create Date: 2026-09-14 00:00:00.000000

文档（解析段状态机）与入库任务表。

1. **documents**：归属一个知识库；`status ∈ {UPLOADED, PARSING, PARSED, FAILED}`
   用 SQLAlchemy 枚举（native_enum=False，存字符串）。外键列用项目 `GUID`
   （MySQL `BINARY(16)`）——`sa.Uuid()` 会渲染成 `CHAR(32)`，让外键因类型不匹配
   被 MySQL 拒绝（error 3780），与 `user_kb_grant` 同一教训。
2. **ingest_jobs**：与文档 1:1（`document_id` 唯一）；`status ∈ {PENDING, RUNNING,
   SUCCESS, FAILED}`。MySQL 为入库任务真相来源。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d0c5a28e6b13"
down_revision: str | Sequence[str] | None = "b7e3c1a9d4f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """建 documents 与 ingest_jobs。"""
    op.create_table(
        "documents",
        sa.Column("kb_id", sa.BINARY(length=16), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("file_hash", sa.String(length=64), nullable=False),
        sa.Column("file_size", sa.Integer(), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "PARSING",
                "PARSED",
                "FAILED",
                name="document_status",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("raw_path", sa.String(length=1024), nullable=True),
        sa.Column("artifact_path", sa.String(length=1024), nullable=True),
        sa.Column("id", sa.BINARY(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], name="fk_documents_kb_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_documents"),
    )
    op.create_index("idx_documents_kb_id", "documents", ["kb_id"], unique=False)
    op.create_index("idx_documents_deleted_at", "documents", ["deleted_at"], unique=False)

    op.create_table(
        "ingest_jobs",
        sa.Column("document_id", sa.BINARY(length=16), nullable=False),
        sa.Column("kb_id", sa.BINARY(length=16), nullable=False),
        sa.Column("stage", sa.String(length=32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "RUNNING",
                "SUCCESS",
                "FAILED",
                name="ingest_job_status",
                native_enum=False,
                length=16,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("progress_current", sa.Integer(), nullable=False),
        sa.Column("progress_total", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BINARY(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"], ["documents.id"], name="fk_ingest_jobs_document_id"
        ),
        sa.ForeignKeyConstraint(
            ["kb_id"], ["knowledge_bases.id"], name="fk_ingest_jobs_kb_id"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ingest_jobs"),
    )
    op.create_index("idx_ingest_jobs_document_id", "ingest_jobs", ["document_id"], unique=True)
    op.create_index("idx_ingest_jobs_kb_id", "ingest_jobs", ["kb_id"], unique=False)
    op.create_index("idx_ingest_jobs_deleted_at", "ingest_jobs", ["deleted_at"], unique=False)


def downgrade() -> None:
    """回退：先删 ingest_jobs（外键依赖文档），再删 documents。"""
    op.drop_table("ingest_jobs")
    op.drop_table("documents")
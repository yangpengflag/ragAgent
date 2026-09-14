"""documents.status 追加 EMBEDDING / READY

Revision ID: f1a2b3c4d5e6
Revises: e7f9a2b3c4d5
Create Date: 2026-09-14 00:00:00.000000

`document-embedding-index`：向量化 change 需要在既有解析/切分状态机上追加
"向量化进行中"（`EMBEDDING`）与"可检索终态"（`READY`）。无新表（chunks 已建）。

`documents.status` 仍为 SQLAlchemy 枚举（native_enum=False → VARCHAR + CHECK）。
MODIFY 只改枚举值集合，需按真实约束名（`ck_documents_document_status`）先删旧 CHECK
再改列类型、补回新 CHECK——与 `e7f9a2b3c4d5`（切分 change）同款操作；
`downgrade` 还原为不含这两个值的枚举。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "e7f9a2b3c4d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# documents.status 追加 EMBEDDING/READY 前/后的合法值
_STATUS_BEFORE = ["UPLOADED", "PARSING", "PARSED", "CHUNKING", "FAILED"]
_STATUS_AFTER = [
    "UPLOADED",
    "PARSING",
    "PARSED",
    "CHUNKING",
    "EMBEDDING",
    "READY",
    "FAILED",
]


def upgrade() -> None:
    """documents.status 枚举追加 EMBEDDING / READY。"""
    _alter_status_enum(_STATUS_AFTER)


def downgrade() -> None:
    """回滚：documents.status 枚举还原为不含 EMBEDDING / READY。"""
    _alter_status_enum(_STATUS_BEFORE)


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
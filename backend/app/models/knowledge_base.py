"""知识库模型。

知识库是**权限与检索的隔离单元**（`project.md`）：库与库之间数据与检索隔离，
Milvus 侧按 `kb_id` 分区/过滤，MySQL 侧按授权行决定谁能访问。

名称唯一沿用账号的同款方案（虚拟生成列 + 唯一索引）：MySQL 不支持带 `WHERE`
的部分索引，而生成列在软删后为 NULL、唯一索引允许多个 NULL，于是
"活跃库唯一、软删库让位"同时成立，且 SQLite 内存库（测试）也能建表。
"""

from __future__ import annotations

from sqlalchemy import Computed, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel

NAME_MAX_LENGTH = 128
DESCRIPTION_MAX_LENGTH = 512
EMBEDDING_MODEL_MAX_LENGTH = 64

# 派生列表达式：活跃库 = name，软删库 = NULL（与 users.username_active 同款）
KB_NAME_ACTIVE_EXPRESSION = "CASE WHEN deleted_at IS NULL THEN name ELSE NULL END"


class KnowledgeBase(BaseModel):
    """知识库。"""

    __tablename__ = "knowledge_bases"

    name: Mapped[str] = mapped_column(String(NAME_MAX_LENGTH), nullable=False)
    description: Mapped[str | None] = mapped_column(
        Text(DESCRIPTION_MAX_LENGTH), nullable=True
    )
    # 向量化配置：同一 collection 内禁止混模型 / 混维度（project.md「向量库约束」）
    embedding_model: Mapped[str] = mapped_column(
        String(EMBEDDING_MODEL_MAX_LENGTH), nullable=False
    )
    embed_dim: Mapped[int] = mapped_column(Integer, nullable=False)

    # 仅供唯一约束使用的派生列：不对外暴露
    name_active: Mapped[str | None] = mapped_column(
        String(NAME_MAX_LENGTH),
        Computed(KB_NAME_ACTIVE_EXPRESSION, persisted=False),
        nullable=True,
    )

    __table_args__ = (
        Index("uk_knowledge_bases_name_active", "name_active", unique=True),
    )

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<KnowledgeBase {self.name} dim={self.embed_dim}>"

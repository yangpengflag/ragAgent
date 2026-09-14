"""chunks 模型：切分后的检索单元。

Child（`is_recallable=true`，供向量化召回）与 Parent（供生成引用）同表存，
`parent_id` 自关联（Child→Parent；无父子语义的块 `parent_id=NULL` 自立为自身父块）。
字段名与检索契约 `RetrievedChunk` 对齐（`chunk_id/kb_id/document_id/parent_id/
content/page_idx/bbox`），下游零转换消费。`bbox`/`section_path`/`block_type`/`is_recallable`
为切分语义特有。

`bbox` 存 JSON：仅整体读写、不参与查询条件（database-conventions JSON 列约定），
读取时返回原始结构或 None（`bbox` 容错读取见 `bbox_value` 属性，缺失键/非法不炸）。
"""

from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import GUID, BaseModel

SECTION_PATH_MAX_LENGTH = 512
BLOCK_TYPE_MAX_LENGTH = 32


class Chunk(BaseModel):
    """切分后的检索单元（Child / Parent 同表）。"""

    __tablename__ = "chunks"

    kb_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("knowledge_bases.id", name="fk_chunks_kb_id"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        GUID,
        ForeignKey("documents.id", name="fk_chunks_document_id"),
        nullable=False,
        index=True,
    )
    # 自关联：Child→Parent；无父子语义的块为 None（自身即父，直接可召回）
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID,
        ForeignKey("chunks.id", name="fk_chunks_parent_id"),
        nullable=True,
        index=True,
    )
    # 大字段：列表/查询路径必须用 load_only 排除，禁 SELECT *
    content: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[str] = mapped_column(
        String(SECTION_PATH_MAX_LENGTH), nullable=False, default=""
    )
    page_idx: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 定位坐标 (x0,y0,x1,y1)，JSON 列；读取容错见 `bbox_value`
    bbox: Mapped[Any | None] = mapped_column(JSON, nullable=True)
    block_type: Mapped[str] = mapped_column(String(BLOCK_TYPE_MAX_LENGTH), nullable=False)
    is_recallable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    @property
    def bbox_value(self) -> tuple[float, float, float, float] | None:
        """bbox 容错读取：缺失 / 非四元组 / 元素不可转数值一律返回 None，不炸。

        历史/异常数据可能把 bbox 存成非法结构（缺键、错类型），下游（检索高亮）
        只消费合法四元组；这里做隔离，避免一次脏数据拖垮整条查询。
        """
        return _coerce_bbox(self.bbox)

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return (
            f"<Chunk doc={self.document_id} block_type={self.block_type} "
            f"recallable={self.is_recallable}>"
        )


def _coerce_bbox(value: Any) -> tuple[float, float, float, float] | None:
    """把 JSON 列读出的值规整为四元组浮动坐标；失败返回 None。"""
    if value is None:
        return None
    # JSON 列也可能被应用层以 dict（{x0,y0,x1,y1}）形态写入，容错兼容
    if isinstance(value, dict):
        try:
            value = [
                value["x0"],
                value["y0"],
                value["x1"],
                value["y1"],
            ]
        except (KeyError, TypeError):
            return None
    try:
        items = list(value)
    except TypeError:
        return None
    if len(items) != 4:
        return None
    try:
        return (float(items[0]), float(items[1]), float(items[2]), float(items[3]))
    except (TypeError, ValueError):
        return None
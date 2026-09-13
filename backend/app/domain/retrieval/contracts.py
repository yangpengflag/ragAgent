"""检索层领域契约。

`RetrievedChunk` 是检索组件与上层（生成/API）之间的唯一数据契约：
LangChain 类型不得越过 integrations 边界，检索结果一律先转换为本契约再向上传递
（design D2）。纯数据定义，零 I/O、零框架依赖。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """一次检索命中的知识块。

    Attributes:
        chunk_id: 子块唯一标识（向量库 PK），引用溯源的锚点。
        kb_id: 所属知识库标识。权限过滤与二次鉴权的依据，缺失即非法。
        document_id: 归属文档标识。
        parent_id: 父块标识（small-to-big：召回子块、以父块供生成）；可为空。
        content: 子块正文（含注入的 Section Path 前缀，与入库态一致）。
        score: 检索得分（COSINE 相似度，范围 [-1, 1]）。
        page_idx: 原文页码（MinerU `page_idx`）；无页码语义时为 None。
        bbox: 原文区域坐标 (x0, y0, x1, y1)，用于前端高亮定位；无定位时为 None。
    """

    chunk_id: str
    kb_id: str
    document_id: str
    parent_id: str | None
    content: str
    score: float
    page_idx: int | None = None
    bbox: tuple[float, float, float, float] | None = None

    def __post_init__(self) -> None:
        if not self.chunk_id:
            raise ValueError("chunk_id 不能为空")
        if not self.kb_id:
            raise ValueError("kb_id 不能为空")
        if not -1.0 <= self.score <= 1.0:
            raise ValueError("score 必须在 [-1, 1] 范围内（COSINE 相似度）")
        if self.bbox is not None and len(self.bbox) != 4:
            raise ValueError("bbox 必须为 (x0, y0, x1, y1) 四元组")

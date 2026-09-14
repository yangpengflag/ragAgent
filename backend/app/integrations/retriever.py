"""带权限过滤的检索执行（tasks 5.2 / 5.3，design D4）。

语义（spec「检索阶段完成知识库级权限过滤」）：
- 授权 kb_id 集合由调用方（services 层经 KbAccessResolver）传入，
  过滤以 Milvus expr 随查询下推，**禁止先检索后过滤**
- 空授权集合短路返回空结果，不触碰向量库
- 返回值统一转换为 `RetrievedChunk` 领域契约，LangChain 类型不出本模块

COSINE 分数换算：Milvus COSINE 索引直接返回余弦相似度（相同向量 = 1.0，
越大越相似），score 即该距离本身，与 RetrievedChunk.score 的 [-1, 1] 契约对齐。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from langchain_core.documents import Document

from app.core.exceptions import SecurityViolationError
from app.core.logging import get_logger
from app.domain.retrieval.contracts import RetrievedChunk


def build_kb_filter_expr(kb_ids: Sequence[str]) -> str:
    """把授权 kb_id 集合组装为 Milvus 过滤表达式（纯函数）。

    Raises:
        ValueError: 集合为空——空集合短路是 `retrieve` 的职责，
            expr 构造对空集合无意义，显式拒绝以免生成 `kb_id in []` 歧义语法。
    """
    if not kb_ids:
        raise ValueError("kb_ids 不能为空：空授权应由调用方短路，不进入检索")
    # 先转义反斜杠再转义引号：只转义引号会让 `\` 成为 expr 的转义符，
    # 破坏字符串字面量边界（权限过滤表达式的注入面）
    escaped = (kb_id.replace("\\", "\\\\").replace('"', '\\"') for kb_id in kb_ids)
    return 'kb_id in ["' + '", "'.join(escaped) + '"]'


class _VectorStoreLike(Protocol):
    """Milvus VectorStore 的最小结构化接口（便于替身测试）。

    注：langchain-milvus 0.4.0 的过滤参数名为 `expr`（非 `filter`）。
    """

    def similarity_search_with_score(
        self, query: str, k: int, expr: str | None = None
    ) -> list[tuple[Document, float]]: ...


def _to_retrieved_chunk(doc: Document, distance: float) -> RetrievedChunk:
    """向量库文档 → 领域契约。缺 kb_id 的结果无法二次鉴权，显式失败。"""
    metadata: dict[str, Any] = doc.metadata or {}
    kb_id = metadata.get("kb_id")
    if not kb_id:
        raise ValueError("检索结果元数据缺少 kb_id，无法进行权限归属判定")
    for required in ("chunk_id", "document_id"):
        if not metadata.get(required):
            raise ValueError(f"检索结果元数据缺少 {required}，无法溯源")
    bbox = metadata.get("bbox")
    return RetrievedChunk(
        chunk_id=str(metadata["chunk_id"]),
        kb_id=str(kb_id),
        document_id=str(metadata["document_id"]),
        parent_id=(
            str(metadata["parent_id"]) if metadata.get("parent_id") is not None else None
        ),
        content=doc.page_content,
        score=float(distance),
        page_idx=(
            int(metadata["page_idx"]) if metadata.get("page_idx") is not None else None
        ),
        bbox=tuple(float(v) for v in bbox) if bbox is not None else None,  # type: ignore[arg-type]
    )


def retrieve(
    query: str,
    *,
    store: _VectorStoreLike,
    kb_ids: Sequence[str],
    top_k: int,
) -> list[RetrievedChunk]:
    """执行一次带知识库级权限过滤的向量检索。

    Args:
        query: 用户查询文本。
        store: 向量库实例（生产为 langchain-milvus）。
        kb_ids: 当前用户的授权知识库集合（真相源为业务 MySQL）。
        top_k: 召回条数上限。

    Returns:
        按相似度降序的 `RetrievedChunk` 列表；空授权集合返回空列表。
    """
    if not kb_ids:
        return []
    results = store.similarity_search_with_score(
        query, k=top_k, expr=build_kb_filter_expr(kb_ids)
    )
    chunks = [_to_retrieved_chunk(doc, distance) for doc, distance in results]
    # 纵深防御：权限边界不依赖单一机制。expr 是主机制（在检索阶段完成），
    # 此处再校验一次——万一 expr 被上游忽略或语义漂移，未授权内容也绝不下发。
    authorized = set(kb_ids)
    leaked = [c.chunk_id for c in chunks if c.kb_id not in authorized]
    if leaked:
        # 安全事件：越权 chunk_id 只进日志（带 request_id，供告警）。
        # 注意不带 details —— 统一错误信封会把 details 原样写进响应体，
        # 不能把内部标识（其他库的 chunk_id）回给调用方。
        get_logger().error(
            "retrieval leaked unauthorized chunks",
            leaked_chunk_ids=leaked,
            authorized_kb_ids=sorted(authorized),
        )
        raise SecurityViolationError("检索结果包含未授权内容，已中断本次检索")
    return chunks

"""向量库装配（design D1/D2/D4）。

Milvus（langchain-milvus）短期内无替换计划，**不建自有 protocol**，
直接暴露 VectorStore 实例。参数组装抽为纯函数 `build_milvus_kwargs`，
可离线单测；`build_vectorstore` 只做 splat 转发。
写入统一走 `write_chunk_vectors`（见 design D1/D5）：调用前 **必须先** `ensure_collection`
显式建表，使 langchain-milvus 在读写时发现 collection 已存在、**不再触发自动建表**
（自动建表的字段推导不可依赖，风险 R6）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_milvus import Milvus

from app.core.config import Settings
from app.domain.retrieval.embedding_semantics import TEXT_TYPE_DOCUMENT
from app.integrations.embeddings import build_embeddings


@dataclass(frozen=True, slots=True)
class ChunkVectorRow:
    """一条待写入 Milvus 的 chunk 向量行（与 schema 字段对齐）。"""

    chunk_id: str
    content: str
    kb_id: str
    document_id: str


def build_milvus_kwargs(settings: Settings) -> dict[str, Any]:
    """组装 Milvus VectorStore 构造参数（纯函数，无 I/O）。

    字段名与入库 schema 的契约（design D4）：
    - PK = `chunk_id`（溯源锚点，由入库侧指定，非 Milvus 自动生成）
    - 正文 = `content`，向量 = `vector`
    - `kb_id` 同时是 partition key（KB 级隔离剪枝）与标量过滤字段
    """
    connection_args: dict[str, Any] = {
        "uri": settings.milvus_uri,
        "db_name": settings.milvus_database,
    }
    if settings.milvus_token:
        connection_args["token"] = settings.milvus_token
    return {
        "collection_name": settings.milvus_collection,
        "connection_args": connection_args,
        "auto_id": False,
        "primary_field": "chunk_id",
        "text_field": "content",
        "vector_field": "vector",
        "partition_key_field": settings.milvus_partition_key,
        "timeout": settings.milvus_timeout_sec,
        # 动态字段显式关闭（langchain-milvus 0.4.0 默认即 False，防上游默认漂移）。
        # schema 由 ingest change 显式创建（可选字段用 nullable 定义）：
        # 实测 langchain-milvus 自动建表路径（a）不应用 enable_dynamic_field=True，
        # （b）以首个 batch 的 metadata 键推导字段——两条都不可依赖。
        "enable_dynamic_field": False,
    }


def build_vectorstore(
    settings: Settings, embeddings: Embeddings
) -> Milvus:
    """构造 VectorStore 实例。真实连接延迟到首次读写（由健康检查承接探测）。

    collection 必须已由 `ensure_collection` 显式建好，以避免 langchain 自动建表路径
    （`_init` 仅在 `has_collection` 为 False 时触发 `_create_collection`）。
    """
    return Milvus(embedding_function=embeddings, **build_milvus_kwargs(settings))


def write_chunk_vectors(
    settings: Settings,
    rows: list[ChunkVectorRow],
) -> None:
    """把一批 chunk 向量写入 Milvus（design D1，写侧；删除走 pymilvus）。

    前置：`ensure_collection` 已显式建 collection（D5），否则 langchain 会走自动建表
    路径，从而绕过显式 schema——违反"以我为准"的约定。
    主键 `chunk_id` / 分区键 `kb_id` / `document_id` 全部落在 metadata（实体字段），
    与 schema 对齐；正文经 `texts` 参数落到 `content`。
    """
    embeddings = build_embeddings(settings, text_type=TEXT_TYPE_DOCUMENT)
    store = build_vectorstore(settings, embeddings)
    store.add_texts(
        texts=[row.content for row in rows],
        metadatas=[
            {
                "chunk_id": row.chunk_id,
                "kb_id": row.kb_id,
                "document_id": row.document_id,
            }
            for row in rows
        ],
    )

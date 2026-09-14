"""Milvus 集成：显式建表 + 删除（design D1/D3/D4/D5）。

写入走既有 langchain-milvus（`vectorstore.py`）；本模块负责 **schema 权威** 与 **删除侧**，
规避 langchain-milvus 自动建表的不可靠推导（风险 R6）：

- `ensure_collection`：pymilvus 显式按约定 schema 建 collection，幂等（存在即返回）。
- `delete_document_vectors`：按 `expr`（`kb_id == ... and document_id == ...`）删同文档全部
  向量，删空幂等（无 collection / 无匹配行都安全返回）。

所有操作走 `connections.connect`（显式 `db_name`），超时由 `MILVUS_TIMEOUT_SEC` 提供，
符合 backend-conventions「外部集成必须显式超时」。
"""

from __future__ import annotations

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
    utility,
)

from app.core.config import Settings
from app.core.logging import get_logger

logger = get_logger()

# 向量字段索引（检索 change 定稿 metric；此处先建可用的 dense 检索索引，保证 collection 可 load）
# 说明：index 参数属检索性能契约，`qa`/检索 change 可重建（drop index + create_index）。
_INDEX_PARAMS = {
    "metric_type": "COSINE",
    "index_type": "HNSW",
    "params": {"M": 16, "efConstruction": 200},
}

_ALIAS = "default"

# 主键 / 分区键 / 文档 id 的标量长度上限（UUID 字符串 + 余量）
_ID_MAX_LENGTH = 64
# content 大字段：VARCHAR 上限 65535（chunk 上限远低于此，见切分阈值）
_CONTENT_MAX_LENGTH = 65535


def _connect(settings: Settings) -> None:
    """建立到 Milvus 的连接（幂等：同 alias 重复 connect 由 pymilvus 处理）。"""
    connections.connect(
        alias=_ALIAS,
        uri=settings.milvus_uri,
        token=settings.milvus_token or "",
        db_name=settings.milvus_database,
    )


def _build_fields(settings: Settings) -> list[FieldSchema]:
    """按约定 schema 组装字段（与 `build_milvus_kwargs` / `RetrievedChunk` 契约对齐）。

    - 主键 `chunk_id`（UUID 字符串，`auto_id=False`，溯源锚点可控）
    - 正文 `content`、向量 `vector`【FloatVector dim=embed_dim】
    - `kb_id` 作 partition key（KB 级隔离剪枝）、`document_id` 作标量过滤
    """
    return [
        FieldSchema(
            name="chunk_id",
            dtype=DataType.VARCHAR,
            max_length=_ID_MAX_LENGTH,
            is_primary=True,
            auto_id=False,
        ),
        FieldSchema(
            name="content",
            dtype=DataType.VARCHAR,
            max_length=_CONTENT_MAX_LENGTH,
        ),
        FieldSchema(
            name="vector",
            dtype=DataType.FLOAT_VECTOR,
            dim=settings.dashscope_embed_dim,
        ),
        FieldSchema(
            name="kb_id",
            dtype=DataType.VARCHAR,
            max_length=_ID_MAX_LENGTH,
            is_partition_key=True,
        ),
        FieldSchema(
            name="document_id",
            dtype=DataType.VARCHAR,
            max_length=_ID_MAX_LENGTH,
        ),
    ]


def ensure_collection(settings: Settings) -> None:
    """collection 不存在时按约定 schema 显式创建；然后 **确保已加载**（design D5 + D3）。

    显式建表规避 langchain 自动建表（D5）；`load()` 使集合可插入与检索——
    否则刚建/重启后的 collection 处于未加载态，langchain 写入报 `collection not loaded`。
    load 幂等：已加载集合重复 load 安全。
    """
    _connect(settings)
    if not utility.has_collection(settings.milvus_collection, using=_ALIAS):
        schema = CollectionSchema(_build_fields(settings))
        collection = Collection(
            name=settings.milvus_collection,
            schema=schema,
            using=_ALIAS,
        )
        collection.create_index(field_name="vector", index_params=_INDEX_PARAMS)
    collection = Collection(name=settings.milvus_collection, using=_ALIAS)
    collection.load(timeout=settings.milvus_timeout_sec)


def delete_document_vectors(
    settings: Settings, kb_id: str, document_id: str
) -> None:
    """删除某文档在 Milvus 中的全部向量；删空幂等、无异常（design D4）。

    首次写入前 call 以清旧向量（先删后写 → 重放收敛为"只剩本批次"）；
    软删提交后 call 以同步清索引。collection 不存在即无可删向量，直接返回。
    """
    _connect(settings)
    if not utility.has_collection(settings.milvus_collection, using=_ALIAS):
        return
    collection = Collection(name=settings.milvus_collection, using=_ALIAS)
    expr = f'kb_id == "{kb_id}" and document_id == "{document_id}"'
    collection.delete(expr, timeout=settings.milvus_timeout_sec)
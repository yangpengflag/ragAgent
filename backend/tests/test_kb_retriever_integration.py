"""真实 Milvus 集成验证（任务 5.4，可选：中间件不在时自动跳过）。

端到端验证 langchain-milvus 栈上 spec「未授权库内容不可见」场景：
partition_key + expr 过滤双保险、Document→RetrievedChunk 转换。
不在离线测试套件的门禁范围内（scaffold R8：套件不得依赖本机中间件）。
"""

import math
import os

import pytest
from langchain_core.embeddings.fake import DeterministicFakeEmbedding

from app.domain.retrieval.contracts import RetrievedChunk
from app.integrations.retriever import retrieve
from app.integrations.vectorstore import build_milvus_kwargs


class _NormalizedFakeEmbedding(DeterministicFakeEmbedding):
    """归一化的确定性伪嵌入。

    Milvus COSINE 假定输入为单位向量，未归一化向量会使得分越界 (-1,1)。
    真实 DashScope 输出已归一化，此处模拟同理，使集成测试不存在于合同语义外。
    """

    def embed_documents(self, texts):
        return [_normalize(v) for v in super().embed_documents(texts)]

    def embed_query(self, text):
        return _normalize(super().embed_query(text))


def _normalize(vec):
    norm = math.sqrt(sum(c * c for c in vec)) or 1.0
    return [c / norm for c in vec]

try:
    from pymilvus import DataType, MilvusClient
except ImportError:  # pragma: no cover
    pytest.skip("pymilvus 未安装", allow_module_level=True)


COLLECTION = "spike_kb_retriever_e2e"
EMBED_DIM = 8


# 可覆盖地址：便于在"中间件不在"的环境验证跳过逻辑（scaffold R8）
MILVUS_URI = os.getenv("MILVUS_URI", "http://localhost:19530")


def _milvus_available() -> bool:
    try:
        client = MilvusClient(uri=MILVUS_URI, timeout=2)
        client.list_collections()
    except Exception:  # noqa: BLE001
        return False
    return True


pytestmark = pytest.mark.skipif(
    not _milvus_available(), reason="Milvus 19530 不可达"
)


@pytest.fixture
def store():
    from langchain_milvus import Milvus

    settings_like = type("S", (), {
        "milvus_uri": "http://localhost:19530",
        "milvus_token": None,
        "milvus_database": "ragagent",
        "milvus_collection": COLLECTION,
        "milvus_partition_key": "kb_id",
        "milvus_timeout_sec": 5,
    })()

    embeddings = _NormalizedFakeEmbedding(size=EMBED_DIM)
    # 清理上次运行残留（langchain-milvus 以首个 batch 推导 schema，残留会污染本轮）
    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)

    # 生产职责模型（design）：collection schema 由 ingest 侧显式创建，
    # 可选字段用 nullable 定义——本测试模拟同样的预建 schema
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    schema.add_field("chunk_id", DataType.VARCHAR, max_length=64, is_primary=True)
    schema.add_field("content", DataType.VARCHAR, max_length=4096)
    schema.add_field("vector", DataType.FLOAT_VECTOR, dim=EMBED_DIM)
    schema.add_field("kb_id", DataType.VARCHAR, max_length=64, is_partition_key=True)
    schema.add_field("document_id", DataType.VARCHAR, max_length=64)
    schema.add_field("parent_id", DataType.VARCHAR, max_length=64, nullable=True)
    schema.add_field("page_idx", DataType.INT64, nullable=True)
    schema.add_field("bbox", DataType.JSON, nullable=True)
    index_params = client.prepare_index_params()
    index_params.add_index(field_name="vector", index_type="AUTOINDEX",
                           metric_type="COSINE")
    client.create_collection(collection_name=COLLECTION, schema=schema,
                             index_params=index_params)

    kwargs = build_milvus_kwargs(settings_like)  # type: ignore[arg-type]
    store = Milvus(embedding_function=embeddings, **kwargs)
    yield store
    client = MilvusClient(uri=MILVUS_URI)
    if client.has_collection(COLLECTION):
        client.drop_collection(COLLECTION)


def test_unauthorized_kb_content_is_invisible(store):
    """授权 kb-a 时，kb-b 的内容不得出现在任何检索结果中。

    注意：langchain-milvus 以首个 batch 的 metadata 键推导 collection 字段，
    因此入库侧必须保证全 collection 元数据键同构（ingest change 的职责）。
    """
    store.add_texts(
        texts=[f"kb-a-doc-{i}" for i in range(3)],
        ids=[f"a-chunk-{i}" for i in range(3)],
        metadatas=[
            {"kb_id": "kb-a", "document_id": "doc-a", "parent_id": f"pa-{i}",
             "page_idx": i}
            for i in range(3)
        ],
    )
    store.add_texts(
        texts=[f"kb-b-doc-{i}" for i in range(3)],
        ids=[f"b-chunk-{i}" for i in range(3)],
        metadatas=[
            {"kb_id": "kb-b", "document_id": "doc-b", "parent_id": f"pb-{i}",
             "page_idx": i}
            for i in range(3)
        ],
    )

    chunks = retrieve("kb-a-doc", store=store, kb_ids=["kb-a"], top_k=10)

    assert len(chunks) > 0
    assert all(isinstance(c, RetrievedChunk) for c in chunks)
    assert {c.kb_id for c in chunks} == {"kb-a"}
    assert all(c.document_id == "doc-a" for c in chunks)


def test_empty_grants_returns_empty_without_error(store):
    """空授权集合短路（不打向量库），端到端语义一致。"""
    chunks = retrieve("anything", store=store, kb_ids=[], top_k=5)

    assert chunks == []


def test_wide_grant_returns_superset_of_single_grant(store):
    """授权扩大后可见集合单调不减（权限模型的基本一致性）。"""
    store.add_texts(
        texts=["shared-doc"],
        ids=["shared-chunk"],
        metadatas=[{"kb_id": "kb-a", "document_id": "doc-a", "parent_id": "pa-shared",
                    "page_idx": 0}],
    )

    single = retrieve("shared-doc", store=store, kb_ids=["kb-a"], top_k=5)
    wide = retrieve("shared-doc", store=store, kb_ids=["kb-a", "kb-b"], top_k=5)

    assert single and wide
    assert {c.chunk_id for c in single} <= {c.chunk_id for c in wide}

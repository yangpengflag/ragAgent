"""Vectorstore 装配红灯（任务 4.3）。

测试策略：参数组装为纯函数（不依赖真实 Milvus，scaffold R8）；
构造函数只做 splat 转发，用 monkeypatch 替身断言透传。
真实连通性由可选集成验证（任务 5.4）与健康检查承接。
"""

import pytest

from app.integrations.vectorstore import build_milvus_kwargs, build_vectorstore


@pytest.fixture
def milvus_env(isolated_env):
    return isolated_env(
        MILVUS_URI="http://127.0.0.1:19530",
        MILVUS_TOKEN="",
        MILVUS_DATABASE="ragagent",
        MILVUS_COLLECTION="kb_chunks",
        MILVUS_PARTITION_KEY="kb_id",
    )


def test_kwargs_bind_uri_database_collection(milvus_env):
    kwargs = build_milvus_kwargs(milvus_env)

    assert kwargs["collection_name"] == "kb_chunks"
    assert kwargs["connection_args"]["uri"] == "http://127.0.0.1:19530"
    # 项目级 database 隔离（project.md：所有 collection 建在 ragagent database 下）
    assert kwargs["connection_args"]["db_name"] == "ragagent"


def test_kwargs_partition_key_and_schema_fields(milvus_env):
    """KB 级隔离：partition_key=kb_id；主键/正文/向量字段名与入库 schema 对齐。"""
    kwargs = build_milvus_kwargs(milvus_env)

    assert kwargs["partition_key_field"] == "kb_id"
    assert kwargs["primary_field"] == "chunk_id"
    assert kwargs["text_field"] == "content"
    assert kwargs["vector_field"] == "vector"
    # 动态字段显式关闭（design：schema 由 ingest 显式创建，可选字段用 nullable）
    assert kwargs["enable_dynamic_field"] is False
    # PK 由入库侧（chunk_id）指定，非 Milvus 自动生成——溯源锚点必须可控
    assert kwargs["auto_id"] is False


def test_kwargs_token_omitted_when_unset(isolated_env):
    settings = isolated_env(MILVUS_URI="http://127.0.0.1:19530", MILVUS_TOKEN="")

    kwargs = build_milvus_kwargs(settings)

    assert "token" not in kwargs["connection_args"]


def test_kwargs_includes_explicit_timeout(isolated_env):
    """document-embedding-index：Milvus 操作显式超时，禁无限等待。"""
    settings = isolated_env(
        MILVUS_URI="http://127.0.0.1:19530", MILVUS_TIMEOUT_SEC="8"
    )

    kwargs = build_milvus_kwargs(settings)

    assert kwargs["timeout"] == 8.0


def test_build_vectorstore_passes_kwargs_and_embeddings(milvus_env, monkeypatch):
    captured: dict = {}

    class FakeMilvus:
        def __init__(self, embedding_function=None, **kwargs):
            captured["embedding_function"] = embedding_function
            captured.update(kwargs)

    monkeypatch.setattr(
        "app.integrations.vectorstore.Milvus", FakeMilvus, raising=True
    )

    sentinel_embeddings = object()
    store = build_vectorstore(milvus_env, embeddings=sentinel_embeddings)  # type: ignore[arg-type]

    assert store is not None
    assert captured["embedding_function"] is sentinel_embeddings
    assert captured["collection_name"] == "kb_chunks"
    assert captured["partition_key_field"] == "kb_id"


def test_collection_name_default_matches_example(isolated_env):
    """默认 collection 与 .env.example 声明一致，避免两种默认值漂移。"""
    settings = isolated_env(MILVUS_URI="http://127.0.0.1:19530")

    assert build_milvus_kwargs(settings)["collection_name"] == "kb_chunks"

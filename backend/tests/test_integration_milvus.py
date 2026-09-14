"""Milvus 集成红灯（document-embedding-index 任务 2.1 / 2.2）。

策略：mock `pymilvus` 层（connections.connect / utility.has_collection / Collection /
FieldSchema / CollectionSchema），验证 `ensure_collection` 的显式建表 schema 契约、
幂等返回，以及 `delete_document_vectors` 的 expr 删除与删空幂等。不连真实 Milvus。
"""

from __future__ import annotations

import pytest

import app.integrations.milvus as milvus_mod
from app.core.config import Settings


@pytest.fixture
def milvus_env(isolated_env) -> Settings:
    return isolated_env(
        MILVUS_URI="http://127.0.0.1:19530",
        MILVUS_TOKEN="",
        MILVUS_DATABASE="ragagent",
        MILVUS_COLLECTION="kb_chunks",
        MILVUS_PARTITION_KEY="kb_id",
        DASHSCOPE_EMBED_DIM="1024",
        MILVUS_TIMEOUT_SEC="8",
    )


class _FakeCollection:
    """记录构造参数、create_index 与 load 调用的 Collection 替身。"""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self.created_index: tuple[str, dict] | None = None
        self.loaded: list[dict] = []

    def create_index(self, **kwargs) -> None:
        self.created_index = kwargs

    def load(self, **kwargs) -> None:
        """ensure_collection 建表后须确保已加载（design D5）。"""
        self.loaded.append(kwargs)


def _patch_connect(monkeypatch: pytest.MonkeyPatch) -> dict:
    calls: list[dict] = []

    def fake_connect(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr(milvus_mod.connections, "connect", fake_connect)
    return calls


def test_ensure_collection_creates_with_explicit_schema(
    milvus_env: Settings, monkeypatch: pytest.MonkeyPatch
):
    connect_calls = _patch_connect(monkeypatch)
    field_names: list[str] = []
    schema_kwargs: dict = {}

    class FakeFieldSchema:
        def __init__(self, name=None, dtype=None, **kwargs) -> None:
            field_names.append(name)
            schema_kwargs.setdefault(f"field_{name}", kwargs)

    class FakeCollectionSchema:
        def __init__(self, fields=None) -> None:
            schema_kwargs["fields"] = fields

    fake_collection = _FakeCollection()

    monkeypatch.setattr(milvus_mod.utility, "has_collection", lambda *a, **k: False)
    monkeypatch.setattr(milvus_mod, "Collection", lambda **k: fake_collection)
    monkeypatch.setattr(milvus_mod, "FieldSchema", FakeFieldSchema)
    monkeypatch.setattr(milvus_mod, "CollectionSchema", FakeCollectionSchema)

    milvus_mod.ensure_collection(milvus_env)

    assert connect_calls and connect_calls[0]["db_name"] == "ragagent"
    assert "chunk_id" in field_names
    assert "content" in field_names
    assert "vector" in field_names
    assert "kb_id" in field_names
    assert "document_id" in field_names
    # 主键 auto_id=False（溯源锚点可控）
    assert schema_kwargs["field_chunk_id"]["auto_id"] is False
    # kb_id 为 partition key（KB 级隔离剪枝）
    assert schema_kwargs["field_kb_id"]["is_partition_key"] is True
    # 向量维度来自配置（同库同维度，禁混维度）
    assert schema_kwargs["field_vector"]["dim"] == 1024
    # 建出后可加载（dense 检索索引）
    assert fake_collection.created_index is not None
    assert fake_collection.created_index["field_name"] == "vector"


def test_ensure_collection_idempotent_when_exists(
    milvus_env: Settings, monkeypatch: pytest.MonkeyPatch
):
    _patch_connect(monkeypatch)
    created_index: list[dict] = []

    class _RecordingCollection(_FakeCollection):
        def create_index(self, **kwargs) -> None:
            created_index.append(kwargs)

    monkeypatch.setattr(milvus_mod.utility, "has_collection", lambda *a, **k: True)
    monkeypatch.setattr(milvus_mod, "Collection", lambda **k: _RecordingCollection())

    milvus_mod.ensure_collection(milvus_env)

    # 已存在时不重复建表/建索引；为 `load()` 取句柄属预期行为
    assert created_index == [], "collection 已存在时不应再次建表"


def test_delete_document_vectors_uses_expr(
    milvus_env: Settings, monkeypatch: pytest.MonkeyPatch
):
    _patch_connect(monkeypatch)
    deleted: list[dict] = []

    class _DelCollection(_FakeCollection):
        def delete(self, expr, **kwargs) -> None:
            deleted.append({"expr": expr, **kwargs})

    monkeypatch.setattr(milvus_mod.utility, "has_collection", lambda *a, **k: True)
    monkeypatch.setattr(milvus_mod, "Collection", lambda **k: _DelCollection())

    milvus_mod.delete_document_vectors(milvus_env, "kb-1", "doc-1")

    assert len(deleted) == 1
    assert 'kb_id == "kb-1"' in deleted[0]["expr"]
    assert 'document_id == "doc-1"' in deleted[0]["expr"]
    assert deleted[0]["timeout"] == 8.0


def test_delete_document_vectors_noop_when_collection_missing(
    milvus_env: Settings, monkeypatch: pytest.MonkeyPatch
):
    _patch_connect(monkeypatch)
    constructed: list = []

    monkeypatch.setattr(milvus_mod.utility, "has_collection", lambda *a, **k: False)
    monkeypatch.setattr(
        milvus_mod, "Collection", lambda **k: constructed.append(k) or _FakeCollection()
    )

    milvus_mod.delete_document_vectors(milvus_env, "kb-1", "doc-1")

    assert constructed == [], "无 collection 即无可删向量，不应构造 Collection"
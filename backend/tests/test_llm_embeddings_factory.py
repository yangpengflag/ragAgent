"""LLM / Embeddings 工厂红灯（任务 4.1 / 4.2 + fix-ingest-state-and-embedding-contract）。

工厂只做「配置注入 + 构造」，不发起网络请求（构造 ChatOpenAI / OpenAIEmbeddings
不会连接远端）；真实连通性由后续集成验证与健康检查承接。

`text_type` 透传用 `MockTransport` 断言**请求体**（不打真实网络）：
兼容端点未声明该字段时按 `query` 处理（实测），故必须确认它真的发出去了。
"""

from __future__ import annotations

import json

import httpx
import pytest
from openai import OpenAIError

from app.core.config import load_settings
from app.core.exceptions import MissingConfigurationError
from app.domain.retrieval.embedding_semantics import (
    TEXT_TYPE_DOCUMENT,
    TEXT_TYPE_QUERY,
)
from app.integrations.embeddings import build_embeddings
from app.integrations.llm import build_chat_model

_DASHSCOPE = {
    "DASHSCOPE_API_KEY": "sk-test-not-real",
    "DASHSCOPE_BASE_URL": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "DASHSCOPE_CHAT_MODEL": "qwen-plus",
    "DASHSCOPE_EMBED_MODEL": "qwen3.7-text-embedding",
    "DASHSCOPE_EMBED_DIM": "1024",
    "DASHSCOPE_EMBED_BATCH_SIZE": "20",
}


@pytest.fixture
def dashscope_env(isolated_env):
    return isolated_env(**_DASHSCOPE)


def _capturing_client(captured: dict) -> httpx.Client:
    """返回把请求体记进 `captured["body"]` 的客户端（零真实网络）。"""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["body"] = body
        inputs = body.get("input") or []
        return httpx.Response(
            200,
            json={
                "data": [
                    {"embedding": [0.0] * 8, "index": i, "object": "embedding"}
                    for i in range(len(inputs))
                ],
                "model": "probe",
                "object": "list",
                "usage": {"total_tokens": 1},
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler))


# ---------------------------------------------------------------- 4.1 ChatModel


def test_chat_model_binds_dashscope_compatible_mode(dashscope_env):
    llm = build_chat_model(dashscope_env)

    assert llm.model_name == "qwen-plus"
    # base_url 指向 DashScope OpenAI 兼容端点（design D1：不引入 DashScope 专用 SDK）
    assert str(llm.root_client.base_url).rstrip("/") == (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def test_chat_model_missing_api_key_fails_with_variable_name(isolated_env):
    """缺 key 时必须报出变量名（scaffold：错误信息指出缺失配置项）。"""
    with pytest.raises(MissingConfigurationError) as exc_info:
        build_chat_model(isolated_env())

    assert "DASHSCOPE_API_KEY" in str(exc_info.value)


# ---------------------------------------------------------------- 4.2 Embeddings


def test_embeddings_bind_model_and_dimensions(dashscope_env):
    emb = build_embeddings(dashscope_env, text_type=TEXT_TYPE_DOCUMENT)

    assert emb.model == "qwen3.7-text-embedding"
    # 1024 维随 KB 配置（project.md：qwen3.7-text-embedding 1024 维）
    assert emb.dimensions == 1024
    # 批量上限来自配置（DashScope 单次 20 条）
    assert emb.chunk_size == 20


def test_embeddings_missing_api_key_fails_with_variable_name(isolated_env):
    with pytest.raises(MissingConfigurationError) as exc_info:
        build_embeddings(isolated_env(), text_type=TEXT_TYPE_DOCUMENT)

    assert "DASHSCOPE_API_KEY" in str(exc_info.value)


def test_settings_must_not_construct_openai_client_without_key(isolated_env):
    """构造参数错误（如空 key）应被 OpenAI 客户端层拒绝，而非静默构造。"""
    with pytest.raises((MissingConfigurationError, OpenAIError)):
        build_embeddings(
            load_settings(_env_file=None), text_type=TEXT_TYPE_DOCUMENT
        )


# ------------------------------------------- text_type：必传 + 确实进入请求体


def test_embeddings_text_type_is_required(dashscope_env):
    """漏传 text_type 必须报错：服务端默认与文档侧语义相反，静默漏传即错。"""
    with pytest.raises(TypeError):
        build_embeddings(dashscope_env)  # type: ignore[call-arg]


def test_ingest_embeddings_send_document_text_type(dashscope_env):
    """入库编码请求体必须携带 `text_type=document`（spec：不得依赖默认值）。"""
    captured: dict = {}
    emb = build_embeddings(
        dashscope_env,
        text_type=TEXT_TYPE_DOCUMENT,
        http_client=_capturing_client(captured),
    )

    emb.embed_documents(["差旅费报销标准"])

    assert captured["body"]["text_type"] == "document"
    assert captured["body"]["dimensions"] == 1024


def test_query_embeddings_send_query_text_type(dashscope_env):
    """查询侧使用另一侧取值，且取自同一处定义（spec：两侧不得混用）。"""
    captured: dict = {}
    emb = build_embeddings(
        dashscope_env,
        text_type=TEXT_TYPE_QUERY,
        http_client=_capturing_client(captured),
    )

    emb.embed_documents(["差旅费标准是什么？"])

    assert captured["body"]["text_type"] == "query"

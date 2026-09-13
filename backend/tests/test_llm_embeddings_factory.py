"""LLM / Embeddings 工厂红灯（任务 4.1 / 4.2）。

工厂只做「配置注入 + 构造」，不发起网络请求（构造 ChatOpenAI / OpenAIEmbeddings
不会连接远端）；真实连通性由后续集成验证与健康检查承接。
"""

import pytest
from openai import OpenAIError

from app.core.config import load_settings
from app.core.exceptions import MissingConfigurationError
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
    emb = build_embeddings(dashscope_env)

    assert emb.model == "qwen3.7-text-embedding"
    # 1024 维随 KB 配置（project.md：qwen3.7-text-embedding 1024 维）
    assert emb.dimensions == 1024
    # 批量上限来自配置（DashScope 单次 20 条）
    assert emb.chunk_size == 20


def test_embeddings_missing_api_key_fails_with_variable_name(isolated_env):
    with pytest.raises(MissingConfigurationError) as exc_info:
        build_embeddings(isolated_env())

    assert "DASHSCOPE_API_KEY" in str(exc_info.value)


def test_settings_must_not_construct_openai_client_without_key(isolated_env):
    """构造参数错误（如空 key）应被 OpenAI 客户端层拒绝，而非静默构造。"""
    with pytest.raises((MissingConfigurationError, OpenAIError)):
        build_embeddings(load_settings(_env_file=None))

"""向量化工厂（design D1/D2）。

与 llm.py 同源：OpenAI 兼容模式 + DashScope embeddings 端点。
批量上限与维度随配置走（KB 级 embed_dim 已在 project.md 定稿为 1024）。
"""

from __future__ import annotations

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import MissingConfigurationError


def build_embeddings(settings: Settings) -> OpenAIEmbeddings:
    """按配置构造向量化客户端（构造期不发起网络请求）。

    Raises:
        MissingConfigurationError: `DASHSCOPE_API_KEY` 未配置时报出变量名。
    """
    if not settings.dashscope_api_key:
        raise MissingConfigurationError("缺少必需配置项: DASHSCOPE_API_KEY")
    return OpenAIEmbeddings(
        model=settings.dashscope_embed_model,
        api_key=SecretStr(settings.dashscope_api_key),
        base_url=settings.dashscope_base_url,
        dimensions=settings.dashscope_embed_dim,
        chunk_size=settings.dashscope_embed_batch_size,
        timeout=60,
        max_retries=2,
    )

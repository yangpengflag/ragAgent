"""生成模型工厂（design D1/D2）。

DashScope 经 OpenAI 兼容模式接入：chat 与 embeddings 共用同一入口，
不引入 DashScope 专用 SDK。薄工厂——不建自有 protocol（换模型是真实预期，
收口在工厂函数即可）。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import MissingConfigurationError


def build_chat_model(settings: Settings) -> ChatOpenAI:
    """按配置构造生成模型客户端（构造期不发起网络请求）。

    Raises:
        MissingConfigurationError: `DASHSCOPE_API_KEY` 未配置时报出变量名。
    """
    if not settings.dashscope_api_key:
        raise MissingConfigurationError("缺少必需配置项: DASHSCOPE_API_KEY")
    return ChatOpenAI(
        model=settings.dashscope_chat_model,
        api_key=SecretStr(settings.dashscope_api_key),
        base_url=settings.dashscope_base_url,
        timeout=60,
        max_retries=2,
    )

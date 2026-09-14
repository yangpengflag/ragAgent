"""向量化工厂（design D1/D2；`vector-index` spec：入库 `text_type=document`）。

与 llm.py 同源：OpenAI 兼容模式 + DashScope embeddings 端点。
批量上限与维度随配置走（KB 级 embed_dim 已在 project.md 定稿为 1024）。

**文本类型标记必需显式传入**（`text_type`，取值见
`app.domain.retrieval.embedding_semantics`）：实测兼容端点在未声明时按 `query` 处理，
与官方原生文档所述的默认值 `document` 相反，漏传会静默改变语义（无报错）。

透传走 `model_kwargs={"extra_body": {...}}`——`extra_body` 是 openai SDK 的标准透传口；
若直接把 `text_type` 放进 `model_kwargs`，会被展开成 `client.create()` 的 kwargs，
而该方法为强类型签名，实测抛 `TypeError: unexpected keyword argument 'text_type'`。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from langchain_openai import OpenAIEmbeddings
from pydantic import SecretStr

from app.core.config import Settings
from app.core.exceptions import MissingConfigurationError

if TYPE_CHECKING:
    import httpx


def build_embeddings(
    settings: Settings,
    *,
    text_type: str,
    http_client: httpx.Client | None = None,
) -> OpenAIEmbeddings:
    """按配置构造向量化客户端（构造期不发起网络请求）。

    Args:
        text_type: 文本类型标记（`TEXT_TYPE_DOCUMENT` / `TEXT_TYPE_QUERY`）。**必传**：
            两侧语义不同，且服务端默认值与文档侧语义相反，漏传即静默错误。
        http_client: 可选的 HTTP 客户端，仅供测试注入 `MockTransport` 断言请求体。

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
        model_kwargs={"extra_body": {"text_type": text_type}},
        http_client=http_client,
    )

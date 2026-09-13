"""问答生成链（tasks 7.2，design D3/D6）。

LCEL 组合：检索（已绑定授权集合）→ prompt → llm → 字符串解析，
输出 {"answer": str, "sources": list[RetrievedChunk]}：
- `sources` 与答案同源同批次透出，供引用脚注渲染与 API 层二次鉴权
- **检索只调用一次**（一次召回，渲染与溯源共用同一份结果）
- 流式：`chain.astream()` 逐 token 产出，末段给出 sources

位置说明：本模块属于 integrations 层——LangChain 类型不得进入 services/（D2）。
"""

from __future__ import annotations

from collections.abc import Callable
from operator import itemgetter
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import Runnable, RunnableLambda, RunnableParallel

from app.domain.generation.prompts import SYSTEM_PROMPT, USER_TEMPLATE, render_context
from app.domain.retrieval.contracts import RetrievedChunk


def _build_prepare(
    retrieve_fn: Callable[[str], list[RetrievedChunk]],
) -> Callable[[str], dict[str, Any]]:
    """检索 → 渲染上下文 + 保留溯源来源（单次召回，两处复用）。"""

    def prepare(question: str) -> dict[str, Any]:
        chunks = retrieve_fn(question)
        context = render_context(
            [(index + 1, chunk.content) for index, chunk in enumerate(chunks)]
        )
        return {"question": question, "context": context, "sources": chunks}

    return prepare


def build_qa_chain(
    *,
    llm: BaseChatModel,
    retrieve_fn: Callable[[str], list[RetrievedChunk]],
) -> Runnable[str, dict[str, Any]]:
    """组装问答链。

    Args:
        llm: 生成模型（生产由 `integrations/llm.py` 工厂构造）。
        retrieve_fn: 已绑定授权 kb 集合的检索函数（single-arg：query → chunks），
            由调用方闭包注入（权限过滤发生在检索阶段，spec 硬要求）。

    Returns:
        Runnable：输入 str（问题），输出 `{"answer": str, "sources": list}`。
    """
    prompt = ChatPromptTemplate.from_messages(
        [("system", SYSTEM_PROMPT), ("human", USER_TEMPLATE)]
    )
    return RunnableLambda(_build_prepare(retrieve_fn)) | RunnableParallel(
        answer=prompt | llm | StrOutputParser(),
        sources=itemgetter("sources"),
    )

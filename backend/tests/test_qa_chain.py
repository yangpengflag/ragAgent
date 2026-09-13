"""问答链红灯（任务 7.2 / 7.3）。

7.2：LCEL 链组装（检索 → prompt → llm → parser），输出答案 + 溯源来源；
     检索只调用一次；流式可用。
7.3：除模型 API 外无任何外网依赖（禁用 socket 后链路仍可用，spec 对应场景）。
"""

import socket

import pytest
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from app.domain.generation.prompts import SYSTEM_PROMPT, USER_TEMPLATE
from app.domain.retrieval.contracts import RetrievedChunk
from app.integrations.qa_chain import build_qa_chain


def _chunk(index: int, kb_id: str = "kb-a") -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"chunk-{index}",
        kb_id=kb_id,
        document_id="doc-1",
        parent_id=f"parent-{index}",
        content=f"片段正文 {index}",
        score=0.9 - index * 0.1,
        page_idx=index,
        bbox=(1.0, 2.0, 3.0, 4.0),
    )


@pytest.fixture
def fake_retriever():
    calls: list[str] = []

    def retrieve(query: str) -> list[RetrievedChunk]:
        calls.append(query)
        return [_chunk(1), _chunk(2)]

    retrieve.calls = calls  # type: ignore[attr-defined]
    return retrieve


@pytest.fixture
def fake_llm():
    """固定输出的假模型（构造期与运行期均不发起网络请求）。"""
    return GenericFakeChatModel(messages=iter([AIMessage(content="答案正文[1]")]))


# ---------------------------------------------------------------- 7.2 链组装


def test_chain_returns_answer_and_sources(fake_retriever, fake_llm):
    chain = build_qa_chain(llm=fake_llm, retrieve_fn=fake_retriever)

    result = chain.invoke("差旅费标准？")

    assert result["answer"] == "答案正文[1]"
    assert [c.chunk_id for c in result["sources"]] == ["chunk-1", "chunk-2"]


def test_retriever_called_exactly_once(fake_retriever, fake_llm):
    """检索昂贵且需权限过滤：一次问答只允许一次召回。"""
    chain = build_qa_chain(llm=fake_llm, retrieve_fn=fake_retriever)

    chain.invoke("问题")

    assert fake_retriever.calls == ["问题"]  # type: ignore[attr-defined]


def test_prompt_uses_in_repo_template(fake_retriever, fake_llm, monkeypatch):
    """spec「提示词模板入仓」：链使用的正是仓库常量，非运行时外部拉取。"""
    captured: dict = {}
    import app.integrations.qa_chain as chain_module

    original = chain_module.ChatPromptTemplate.from_messages

    def spy(messages):
        captured["messages"] = messages
        return original(messages)

    monkeypatch.setattr(chain_module.ChatPromptTemplate, "from_messages", staticmethod(spy))
    chain = build_qa_chain(llm=fake_llm, retrieve_fn=fake_retriever)

    chain.invoke("问题")

    messages = captured["messages"]
    assert messages[0][1] == SYSTEM_PROMPT
    assert messages[1][1] == USER_TEMPLATE


def test_streaming_yields_answer_chunks(fake_retriever, fake_llm):
    """SSE 流式依赖 astream：答案逐段产出，来源随末段给出。"""
    import asyncio

    async def _run() -> list[object]:
        chain = build_qa_chain(llm=fake_llm, retrieve_fn=fake_retriever)
        return [item async for item in chain.astream("问题")]

    events = asyncio.run(_run())

    assert events, "astream 必须产出行（SSE 流式依赖）"
    answer_fragments = [
        event["answer"] for event in events if isinstance(event, dict) and "answer" in event
    ]
    assert answer_fragments, "流式产出必须包含 answer 分片"
    assert "答案正文[1]".startswith("".join(answer_fragments).strip()[:4])
    # 末段必须给出 sources，供前端渲染引用脚注
    sources = [event.get("sources") for event in events if isinstance(event, dict)]
    assert any(sources)


# ---------------------------------------------------------------- 7.3 离线验收


def test_chain_works_without_any_network(fake_retriever, fake_llm, monkeypatch):
    """spec「无外网提示词服务时链路可用」：禁用 socket 后链路仍正常完成。"""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise AssertionError("链路不应发起任何真实网络请求")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)

    chain = build_qa_chain(llm=fake_llm, retrieve_fn=fake_retriever)
    result = chain.invoke("问题")

    assert result["answer"]
    assert result["sources"]

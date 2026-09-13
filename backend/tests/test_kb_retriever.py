"""权限过滤检索红灯（任务 5.2 / 5.3）。

覆盖 spec「检索阶段完成知识库级权限过滤」：
- 空授权集合短路，不触发向量库查询
- 过滤条件随查询下推（不在应用侧丢弃）
- 向量库 Document → RetrievedChunk 契约转换
- COSINE distance → similarity 换算
"""

import pytest
from langchain_core.documents import Document

from app.core.exceptions import SecurityViolationError
from app.domain.retrieval.contracts import RetrievedChunk
from app.integrations.retriever import build_kb_filter_expr, retrieve

# ---------------------------------------------------------------- 5.2 expr 构造


def test_expr_single_kb():
    assert build_kb_filter_expr(["kb-a"]) == 'kb_id in ["kb-a"]'


def test_expr_multiple_kbs():
    expr = build_kb_filter_expr(["kb-a", "kb-b", "kb-c"])

    assert expr == 'kb_id in ["kb-a", "kb-b", "kb-c"]'


def test_expr_escapes_quotes():
    """kb_id 含引号时转义，防 expr 注入（防御性：id 应为 UUID，但不信任上游）。"""
    assert build_kb_filter_expr(['kb"x']) == 'kb_id in ["kb\\"x"]'


def test_expr_escapes_backslash():
    """反斜杠必须先于引号转义：只转义引号会让 `\\` 成为 expr 的转义符，
    破坏字符串边界（权限过滤表达式的注入面）。"""
    expr = build_kb_filter_expr(['kb\\x'])

    assert '\\\\' in expr
    assert build_kb_filter_expr(['kb\\"x']) == 'kb_id in ["kb\\\\\\"x"]'


def test_backslash_and_quote_combination_is_balanced():
    """转义后表达式仍为合法的字面量：反斜杠自成一对，引号被转义而非截断字符串。"""
    assert build_kb_filter_expr(["a\\", 'b"c']) == r'kb_id in ["a\\", "b\"c"]'


def test_expr_empty_raises():
    """空集合的短路是 retrieve 层的职责；expr 构造对空集合直接拒绝。"""
    with pytest.raises(ValueError, match="kb_id"):
        build_kb_filter_expr([])


# ---------------------------------------------------------------- 5.3 检索执行


class FakeVectorStore:
    """向量库替身：记录调用参数，返回预置结果。"""

    def __init__(self, results: list[tuple[Document, float]]) -> None:
        self._results = results
        self.calls: list[dict] = []

    def similarity_search_with_score(self, query: str, k: int, expr: str):  # noqa: A002
        self.calls.append({"query": query, "k": k, "expr": expr})
        return self._results


def _doc(chunk_id: str, kb_id: str, **extra: object) -> tuple[Document, float]:
    metadata: dict = {
        "chunk_id": chunk_id,
        "kb_id": kb_id,
        "document_id": "doc-1",
        "parent_id": "parent-1",
        "page_idx": 3,
        "bbox": [10.0, 20.0, 30.0, 40.0],
    }
    metadata.update(extra)
    return (Document(page_content="正文内容", metadata=metadata), 0.15)


def test_empty_kb_ids_short_circuits_without_store_query():
    """spec：无授权 → 返回空结果且不执行向量库查询。"""
    store = FakeVectorStore(results=[_doc("c1", "kb-x")])

    out = retrieve("query", store=store, kb_ids=[], top_k=5)  # type: ignore[arg-type]

    assert out == []
    assert store.calls == []


def test_filter_is_pushed_down_with_query():
    store = FakeVectorStore(results=[_doc("c1", "kb-a")])

    retrieve("q", store=store, kb_ids=["kb-a", "kb-b"], top_k=7)  # type: ignore[arg-type]

    assert len(store.calls) == 1
    call = store.calls[0]
    assert call["query"] == "q"
    assert call["k"] == 7
    # 过滤条件随查询下推（不是检索后应用侧丢弃）
    assert call["expr"] == 'kb_id in ["kb-a", "kb-b"]'


def test_results_converted_to_contract():
    store = FakeVectorStore(results=[_doc("c1", "kb-a"), _doc("c2", "kb-a", parent_id=None)])

    out = retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]

    assert all(isinstance(chunk, RetrievedChunk) for chunk in out)
    first = out[0]
    assert first.chunk_id == "c1"
    assert first.kb_id == "kb-a"
    assert first.content == "正文内容"
    assert first.score == pytest.approx(0.85)  # COSINE: 1 - distance(0.15)
    assert first.page_idx == 3
    assert first.bbox == (10.0, 20.0, 30.0, 40.0)
    second = out[1]
    assert second.parent_id is None


def test_all_results_belong_to_authorized_kbs():
    """替身结果的 kb_id 均在授权集合内（真实库由 expr 保证，此处守契约转换不破坏）。"""
    store = FakeVectorStore(results=[_doc("c1", "kb-a"), _doc("c2", "kb-b")])

    out = retrieve("q", store=store, kb_ids=["kb-a", "kb-b"], top_k=5)  # type: ignore[arg-type]

    assert {chunk.kb_id for chunk in out} <= {"kb-a", "kb-b"}


def test_unauthorized_result_is_rejected_even_if_filter_bypassed():
    """纵深防御：万一 expr 被上游忽略/版本语义漂移，未授权库内容必须显式阻断，
    绝不静默返回（spec：结果 MUST NOT 包含未授权库内容）。"""
    store = FakeVectorStore(results=[_doc("c-leak", "kb-secret")])

    with pytest.raises(SecurityViolationError):
        retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]


def test_security_violation_is_distinguishable_from_internal_error():
    """安全事件必须可监控识别：500 + security_violation，而非普通 internal_error。"""
    store = FakeVectorStore(results=[_doc("c-leak", "kb-secret")])

    with pytest.raises(SecurityViolationError) as exc_info:
        retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]

    assert exc_info.value.status_code == 500
    assert exc_info.value.error_code == "security_violation"
    # 响应体不得携带内部标识：统一错误信封会把 details 原样写出，故此处必须为 None
    assert exc_info.value.details is None
    assert "c-leak" not in exc_info.value.message


def test_security_violation_is_logged_with_leaked_ids(capsys):
    """日志必须带越权 chunk_id（带 request_id，由 logging 层自动附加）。"""
    store = FakeVectorStore(results=[_doc("c-leak", "kb-secret")])

    with pytest.raises(SecurityViolationError):
        retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]

    assert "c-leak" in capsys.readouterr().out


def test_metadata_missing_chunk_id_gives_clear_error():
    """缺 chunk_id 报明确错误（KeyError 会变成难以定位的 500）。"""
    doc, distance = _doc("c1", "kb-a")
    del doc.metadata["chunk_id"]
    store = FakeVectorStore(results=[(doc, distance)])

    with pytest.raises(ValueError, match="chunk_id"):
        retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]


def test_metadata_missing_kb_id_is_rejected():
    """元数据缺 kb_id 的结果无法二次鉴权，必须显式失败而非静默放行。"""
    doc, distance = _doc("c1", "kb-a")
    del doc.metadata["kb_id"]
    store = FakeVectorStore(results=[(doc, distance)])

    with pytest.raises(ValueError, match="kb_id"):
        retrieve("q", store=store, kb_ids=["kb-a"], top_k=5)  # type: ignore[arg-type]

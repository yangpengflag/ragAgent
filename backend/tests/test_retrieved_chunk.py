"""领域契约红灯（任务 3.1）。

覆盖 spec「检索阶段完成知识库级权限过滤」对返回契约的承载需求：
RetrievedChunk 携带 chunk 标识、正文、kb_id、文档/页码定位元数据与得分，
供 API 层二次鉴权与引用溯源使用。纯函数层，零框架依赖。
"""

import dataclasses

import pytest

from app.domain.retrieval.contracts import RetrievedChunk


def _make(**overrides: object) -> RetrievedChunk:
    defaults: dict[str, object] = {
        "chunk_id": "01936b2a-7f30-7000-8000-000000000001",
        "kb_id": "kb-hr",
        "document_id": "01936b2a-1111-7000-8000-000000000002",
        "parent_id": "01936b2a-2222-7000-8000-000000000003",
        "content": "差旅费报销标准：火车硬席……",
        "score": 0.87,
        "page_idx": 12,
        "bbox": (72.0, 120.5, 540.0, 160.0),
    }
    defaults.update(overrides)
    return RetrievedChunk(**defaults)  # type: ignore[arg-type]


def test_holds_core_fields():
    chunk = _make()

    assert chunk.chunk_id == "01936b2a-7f30-7000-8000-000000000001"
    assert chunk.kb_id == "kb-hr"
    assert chunk.document_id == "01936b2a-1111-7000-8000-000000000002"
    assert chunk.parent_id == "01936b2a-2222-7000-8000-000000000003"
    assert chunk.content == "差旅费报销标准：火车硬席……"
    assert chunk.score == pytest.approx(0.87)


def test_citation_fields_optional():
    """page_idx / bbox 为可选定位元数据（无页码的 Markdown 文档等场景）。"""
    chunk = _make(page_idx=None, bbox=None)

    assert chunk.page_idx is None
    assert chunk.bbox is None


def test_parent_id_optional():
    """非父子块配置（或父块本身被召回）时 parent_id 可为空。"""
    chunk = _make(parent_id=None)

    assert chunk.parent_id is None


def test_is_immutable():
    """契约对象必须不可变：检索结果在链路中传递时不允许被中途篡改。"""
    chunk = _make()

    with pytest.raises(dataclasses.FrozenInstanceError):
        chunk.kb_id = "kb-other"  # type: ignore[misc]


def test_empty_chunk_id_is_rejected():
    """无标识的检索结果无法溯源，视为非法。"""
    with pytest.raises(ValueError, match="chunk_id"):
        _make(chunk_id="")


def test_empty_kb_id_is_rejected():
    """kb_id 是权限过滤与二次鉴权的依据，缺失即非法。"""
    with pytest.raises(ValueError, match="kb_id"):
        _make(kb_id="")


def test_score_out_of_range_is_rejected():
    """COSINE 相似度得分为 [-1, 1]，超出范围说明上游装配有误。"""
    with pytest.raises(ValueError, match="score"):
        _make(score=1.5)

    with pytest.raises(ValueError, match="score"):
        _make(score=-1.5)


def test_bbox_must_be_four_coordinates():
    """MinerU bbox 为 [x0, y0, x1, y1] 四元组，其他长度视为非法。"""
    with pytest.raises(ValueError, match="bbox"):
        _make(bbox=(1.0, 2.0, 3.0))

    with pytest.raises(ValueError, match="bbox"):
        _make(bbox=(1.0, 2.0, 3.0, 4.0, 5.0))

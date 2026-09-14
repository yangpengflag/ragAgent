"""文档解析产物切分纯域红灯（document-chunking 任务 2.1–2.4）。

`domain/chunking` 是零 I/O、零框架依赖的纯函数层；所有测试用确定性
`FakeTokenCounter`（按空格分词计数）替代 tiktoken，保证可精确断言。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.chunking.builder import build_chunks
from app.domain.chunking.models import Block, ChunkConfig, TokenCounter, blocks_from_artifact

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _block(item: dict | None = None, **kw: object) -> Block:
    """把 dict-ish 元素转成纯 domain Block（tests 直接构造）。"""
    src = dict(item or {})
    src.update(kw)
    return Block(
        type=str(src.get("type", "text")),
        text=str(src.get("text", "")),
        text_level=int(src.get("text_level", 0)),
        page_idx=src.get("page_idx"),  # type: ignore[arg-type]
        bbox=None,  # 测试不关心 bbox 精确值
        images=tuple(src.get("images") or ()),
    )


def _blocks(*items: object) -> list[Block]:
    return [_block(item) for item in items]  # type: ignore[arg-type]


class WordCounter(TokenCounter):
    """确定性计数：token = 按空白切分的词数。"""

    def count(self, text: str) -> int:
        return len(text.split())


@pytest.fixture
def counter() -> TokenCounter:
    return WordCounter()


@pytest.fixture
def cfg() -> ChunkConfig:
    # 缩小阈值便于测试：text/list 目标 8 / 上限 10；atomic 同理
    return ChunkConfig(
        text_target_tokens=8,
        text_max_tokens=10,
        list_target_tokens=8,
        list_max_tokens=10,
        table_target_tokens=16,
        table_max_tokens=20,
        code_target_tokens=12,
        code_max_tokens=16,
        equation_target_tokens=4,
        equation_max_tokens=6,
    )


# ---------------------------------------------------------------- 2.1 blocks_from_artifact


def test_blocks_from_artifact_parses_fields(counter: TokenCounter):
    blocks = blocks_from_artifact(str(FIXTURES / "content_list.json"))

    assert blocks[0].type == "text"
    assert blocks[0].text_level == 1
    assert blocks[0].page_idx == 0
    assert blocks[0].bbox == (0, 0, 100, 20)
    assert blocks[-1].type == "equation"
    assert len(blocks) == 6


def test_blocks_from_artifact_bad_json_raises(tmp_path: Path):
    bad = tmp_path / "bad.json"
    bad.write_text("not json {{{", encoding="utf-8")

    with pytest.raises(ValueError):
        blocks_from_artifact(str(bad))


def test_blocks_from_artifact_wrong_shape_raises(tmp_path: Path):
    bad = tmp_path / "shape.json"
    bad.write_text(json.dumps({"not": "a list"}), encoding="utf-8")

    with pytest.raises(ValueError):
        blocks_from_artifact(str(bad))


# ---------------------------------------------------------------- 2.2 确定性 + 贪心打包 + 降级
# pylint: disable=redefined-outer-name


def test_build_chunks_is_deterministic(counter: TokenCounter, cfg: ChunkConfig):
    blocks = blocks_from_artifact(str(FIXTURES / "content_list.json"))

    first = build_chunks(blocks, cfg, counter)
    second = build_chunks(blocks, cfg, counter)

    assert first == second
    assert [c.content for c in first] == [c.content for c in second]


def test_long_text_recursively_split(counter: TokenCounter, cfg: ChunkConfig):
    # 一个超长 text 块（50 词 > text_max 10），应降级切成多个 chunk，不漏不重
    blocks = [
        {
            "type": "text",
            "text_level": 0,
            "page_idx": 0,
            "bbox": None,
            "text": " ".join(f"w{i}" for i in range(50)),
            "images": [],
        }
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    assert len(chunks) > 1
    # 逐个判断：每块本身不超上限
    text_chunks = [c for c in chunks if c.block_type == "text"]
    for c in text_chunks:
        assert counter.count(c.content) <= cfg.text_max_tokens
    # 不全量合并（被降级）
    assert all(counter.count(c.content) <= cfg.text_max_tokens for c in text_chunks)
    # 无父子语境单块长文本：降级后仍可召回，自身即父
    assert all(c.parent_id is None for c in text_chunks)
    assert all(c.is_recallable is True for c in text_chunks)


def test_greedy_pack_same_type_in_section(counter: TokenCounter, cfg: ChunkConfig):
    # 三个 4 词 text 块同节相邻，text_target=8：前两个合并，第三个被逐出
    blocks = [
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "a b c d", "images": []},
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "e f g h", "images": []},
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "i j k l", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    text_chunks = [c for c in chunks if c.block_type == "text"]
    joined = " ".join(c.content for c in text_chunks)
    tokens = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l"]
    assert all(w in joined for w in tokens)
    # 至少切出两块（前两块合并 + 第三块）
    assert len(text_chunks) >= 2


def test_greedy_not_cross_parent(counter: TokenCounter, cfg: ChunkConfig):
    """不跨父节点打包：不同标题下的 text 不得合并进同一 chunk。"""
    blocks = [
        {"type": "text", "text_level": 1, "page_idx": 0, "bbox": None,
         "text": "SECTION A", "images": []},
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "a1 a2", "images": []},
        {"type": "text", "text_level": 1, "page_idx": 1, "bbox": None,
         "text": "SECTION B", "images": []},
        {"type": "text", "text_level": 0, "page_idx": 1, "bbox": None,
         "text": "b1 b2", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    # 两个 section 的 content 块不得合并：存在含 a1 与含 b1 的不同 chunk
    a_chunks = [c for c in chunks if "a2" in c.content]
    b_chunks = [c for c in chunks if "b1" in c.content]
    assert a_chunks and b_chunks
    assert all("b1" not in c.content for c in a_chunks)
    assert all("a2" not in c.content for c in b_chunks)
    # Section Path 注入：content 块应带面包屑前缀
    assert any("SECTION A" in c.content for c in chunks)
    assert any("SECTION B" in c.content for c in chunks)


# ---------------------------------------------------------------- 2.3 表格双表示 / 代码 / 公式


def test_table_dual_representation(counter: TokenCounter, cfg: ChunkConfig):
    blocks = [
        {"type": "table", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "| 姓名 | 部门 |\n| --- | --- |\n| 张三 | 研发 |", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    table_chunks = [c for c in chunks if c.block_type == "table"]
    # 双表示：至少两块，一块含原文 Markdown，一块含口语化摘要
    markdown = [c for c in table_chunks if "| 姓名 | 部门 |" in c.content]
    assert markdown, "应有 Markdown 原文 chunk"
    summary = [c for c in table_chunks if "姓 名" in c.content or "姓名" in c.content]
    assert summary, "应有口语化摘要 chunk"
    # 原子成块，不与相邻文本合并（此处仅 table，验证独立成块）
    assert len(table_chunks) >= 2


def test_code_boundary_split_preserves_source(counter: TokenCounter, cfg: ChunkConfig):
    code = "\n".join(
        [
            "def func_a():",
            "    return 1",
            "",
            "class Klass:",
            "    def method():",
            "        pass",
        ]
    )
    blocks = [
        {"type": "code", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": code, "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    code_chunks = [c for c in chunks if c.block_type == "code"]
    assert code_chunks
    assert any("def func_a" in c.content for c in code_chunks)
    assert any("class Klass" in c.content for c in code_chunks)
    # 若被边界拆分，各自保留语义（此处代码词数可能超限才拆）
    for c in code_chunks:
        # 拆出的裸分句不得破坏源码（函数/类边界优先）
        out = c.content
        assert "def " in out or "class " in out or len(out.split()) <= cfg.code_max_tokens
    assert all(counter.count(c.content) <= cfg.code_max_tokens for c in code_chunks)


def test_equation_preserves_latex(counter: TokenCounter, cfg: ChunkConfig):
    blocks = [
        {"type": "equation", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "f(x) = \\int_{0}^{1} x^2 dx", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    eq = [c for c in chunks if c.block_type == "equation"]
    assert eq
    assert any("\\int_{0}^{1}" in c.content for c in eq)


# ---------------------------------------------------------------- 2.4 父子块 small-to-big


def test_section_child_and_parent(counter: TokenCounter, cfg: ChunkConfig):
    """有章节语境：产出 recallable child（带面包屑）+ 非 recallable parent，parent_id 关联。"""
    blocks = [
        {"type": "text", "text_level": 1, "page_idx": 0, "bbox": None,
         "text": "SECTION A", "images": []},
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "c1 c2 c3 c4 c5 c6 c7 c8 c9 c10 c11 c12", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    recallable = [c for c in chunks if c.is_recallable]
    parents = [c for c in chunks if not c.is_recallable]
    assert recallable, "应有可召回 child"
    assert parents, "应有 parent"
    for child in recallable:
        assert child.parent_id is not None
        assert any(chunk.id == child.parent_id for chunk in parents)
    # 面包屑注入 child 前缀
    assert all("SECTION A" in c.content for c in recallable)


def test_flat_single_block_self_as_parent(counter: TokenCounter, cfg: ChunkConfig):
    """无层级语境单块：自身即父与子合一，parent_id 为空且可召回。"""
    blocks = [
        {"type": "text", "text_level": 0, "page_idx": 0, "bbox": None,
         "text": "只用一句话", "images": []},
    ]

    chunks = build_chunks(_blocks(*blocks), cfg, counter)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.is_recallable is True
    assert chunk.parent_id is None
    assert chunk.content == "只用一句话"
    assert chunk.id  # 确定性 id 非空
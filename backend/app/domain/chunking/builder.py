"""结构感知切分器：`list[Block]` → `list[Chunk]`（纯函数，零 I/O、零框架依赖）。

流程：按标题（text_level>0）还原章节树 → 每个"父节点"（section）内按块类型
贪心打包出可召回 Child 块（包装面包屑前缀）并聚合出一个 Parent 块（供生成），
Child 经 `parent_id` 关联回 Parent。长文本超上限按 段落→句→子句→词 递归降级，
不漏不重；table 双表示（口语化摘要 + Markdown 原文）、code 按函数/类边界切、
equation 保留 LaTeX。全程确定性（id 由内容派生 UUID5，同输入重放逐块相等）。
"""

from __future__ import annotations

import re
from collections.abc import Callable

from app.domain.chunking.models import (
    Block,
    Chunk,
    ChunkConfig,
    TiktokenTokenCounter,
    TokenCounter,
    _is_heading,
    _split_by_chars,
    deterministic_chunk_id,
)

# 可打包合并的类型（text/list 共享 mutable 贪心）；其余为原子块
_MUTABLE = frozenset({"text", "list"})
_ATOMIC = frozenset({"table", "code", "equation"})

# (text, block_type, page_idx, bbox)
_RawItem = tuple[str, str, int | None, tuple[float, float, float, float] | None]
# (text, page_idx, bbox) —— 原子块切分结果（类型由调用方补全）
_AtomicItem = tuple[str, int | None, tuple[float, float, float, float] | None]
_Splitter = Callable[[str], list[str]]


def build_chunks(
    blocks: list[Block],
    cfg: ChunkConfig,
    counter: TokenCounter | None = None,
) -> list[Chunk]:
    """把解析块切分为检索单元（Child + Parent），返回 Chunk 序列（顺序确定）。"""
    token_counter: TokenCounter = counter if counter is not None else TiktokenTokenCounter()
    out: list[Chunk] = []
    for path, content_blocks in _group_sections(blocks):
        _emit_section(path, content_blocks, cfg, token_counter, out)
    return out


# ------------------------------------------------------------------ 章节树


def _group_sections(blocks: list[Block]) -> list[tuple[tuple[str, ...], list[Block]]]:
    """把块归入「父节点」：每个标题及其下行正文构成一个 section。

    返回 `[(section_path_elements_ordered, content_blocks), ...]`，保持原始顺序。
    """
    gathered: dict[tuple[str, ...], list[Block]] = {}
    order: list[tuple[str, ...]] = []
    heading_levels: list[int] = []
    current_path: list[str] = []

    def ensure(path: tuple[str, ...]) -> None:
        if path not in gathered:
            gathered[path] = []
            order.append(path)

    for block in blocks:
        if _is_heading(block):
            level = block.text_level
            while heading_levels and heading_levels[-1] >= level:
                heading_levels.pop()
                current_path.pop()
            heading_levels.append(level)
            current_path.append(block.text)
            ensure(tuple(current_path))
        else:
            ensure(tuple(current_path))
            gathered[tuple(current_path)].append(block)
    return [(path, gathered[path]) for path in order]


def _emit_section(
    path: tuple[str, ...],
    content_blocks: list[Block],
    cfg: ChunkConfig,
    counter: TokenCounter,
    out: list[Chunk],
) -> None:
    section_path = " / ".join(path)
    prefix = f"{section_path} / " if section_path else ""

    if not content_blocks:
        # 有标题但无正文：标题本身作为可召回单元
        if path:
            out.append(
                Chunk(
                    id=deterministic_chunk_id(section_path, "heading"),
                    content=path[-1],
                    parent_id=None,
                    section_path=section_path,
                    block_type="text",
                    is_recallable=True,
                )
            )
        return

    # 无层级且单块 → 自身即父（可能降级为多块，各自 parent=None 可直接召回）
    if not path and len(content_blocks) == 1:
        _emit_flat_self(content_blocks[0], cfg, counter, out)
        return

    parent_content = _build_parent_content(path, content_blocks)
    parent = Chunk(
        id=deterministic_chunk_id(section_path, "parent", parent_content),
        content=parent_content,
        parent_id=None,
        section_path=section_path,
        block_type="parent",
        is_recallable=False,
    )
    out.append(parent)

    for text, btype, page_idx, bbox in _collect_children(
        content_blocks, prefix, cfg, counter
    ):
        out.append(
            Chunk(
                id=deterministic_chunk_id(text),
                content=text,
                parent_id=parent.id,
                section_path=section_path,
                block_type=btype,
                is_recallable=True,
                page_idx=page_idx,
                bbox=bbox,
            )
        )


def _emit_flat_self(
    block: Block, cfg: ChunkConfig, counter: TokenCounter, out: list[Chunk]
) -> None:
    btype = block.type
    max_t = cfg.max_tokens(btype)
    if btype in _MUTABLE:
        pieces = _degrade_text(block.text, counter, max_t)
    else:
        pieces = [text for text, _, _ in _atomic_pieces(block, btype, max_t, counter)]
    for piece in pieces:
        out.append(
            Chunk(
                id=deterministic_chunk_id(piece),
                content=piece,
                parent_id=None,
                page_idx=block.page_idx,
                bbox=block.bbox,
                block_type=btype,
                is_recallable=True,
            )
        )


def _build_parent_content(path: tuple[str, ...], content_blocks: list[Block]) -> str:
    """Parent 聚合内容：面包屑 + 本章标题 + 全部正文（供生成引用）。"""
    section_path = " / ".join(path)
    heading = path[-1] if path else ""
    body = "\n".join(block.text for block in content_blocks if block.text)
    parts = [section_path] if section_path else []
    if heading:
        parts.append(heading)
    parts.append(body)
    return "\n".join(part for part in parts if part)


def _collect_children(
    blocks: list[Block], prefix: str, cfg: ChunkConfig, counter: TokenCounter
) -> list[_RawItem]:
    """把一个 section 的正文块切为可召回 Child 的原文（含面包屑前缀）。"""
    raw: list[_RawItem] = []
    cur: list[str] = []
    cur_type: str | None = None
    cur_tokens = 0
    cur_meta: tuple[int | None, tuple[float, float, float, float] | None] = (None, None)

    def flush() -> None:
        nonlocal cur, cur_type, cur_tokens, cur_meta
        if cur and cur_type:
            text = prefix + " ".join(cur)
            raw.append((text, cur_type, cur_meta[0], cur_meta[1]))
        cur, cur_type, cur_tokens = [], None, 0
        cur_meta = (None, None)

    for block in blocks:
        btype = block.type
        if btype in _MUTABLE:
            if cur_type is not None and cur_type != btype:
                flush()
            if cur_type is None:
                cur_type = btype
            max_t = cfg.max_tokens(btype)
            for piece in _degrade_text(block.text, counter, max_t):
                t = counter.count(piece)
                if cur and cur_tokens + t > max_t:
                    flush()
                    cur_type = btype
                cur.append(piece)
                cur_tokens += t
                cur_meta = (block.page_idx, block.bbox)
        else:
            flush()
            if btype not in _ATOMIC:
                continue  # 未知类型兜底忽略（不产生块）
            max_t = cfg.max_tokens(btype)
            for text, page_idx, bbox in _atomic_pieces(block, btype, max_t, counter):
                raw.append((prefix + text, btype, page_idx, bbox))
    flush()
    return raw


# ------------------------------------------------------------------ 原子块


def _atomic_pieces(
    block: Block, btype: str, max_tokens: int, counter: TokenCounter
) -> list[_AtomicItem]:
    """table/code/equation 原子块 → 若干 Child 原文（含各自定位）。"""
    page: int | None = block.page_idx
    bbox: tuple[float, float, float, float] | None = block.bbox
    if btype == "table":
        return [(table_summary(block.text), page, bbox), (block.text, page, bbox)]
    if btype == "code":
        return [(code, page, bbox) for code in _split_code(block.text, counter, max_tokens)]
    return [(block.text, page, bbox)]  # equation 保留 LaTeX 原文


def table_summary(markdown: str) -> str:
    """表格口语化摘要（确定性启发式）：列名 + 行数，检索可命中。"""
    lines = [ln for ln in markdown.strip().splitlines() if ln.strip()]
    if not lines:
        return "空表格"
    header_raw = lines[0].strip().strip("|")
    headers = [c.strip() for c in header_raw.split("|") if c.strip()]
    data_rows = [
        ln
        for ln in lines[2:]
        if not ln.lstrip().startswith("|---") and not ln.lstrip().startswith("|--")
    ]
    header_str = "、".join(headers) or "未知列"
    return f"表格包含列：{header_str}，数据约 {len(data_rows)} 行。"


_CODE_BOUNDARY = re.compile(r"^\s*(async\s+def|def|class)\b")


def _split_code(code: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """按函数/类边界切代码；超大单元再按行降级。保留源码可编译结构。"""
    if not code:
        return [code] if code else []
    units: list[str] = []
    cur: list[str] = []
    for ln in code.split("\n"):
        if cur and _CODE_BOUNDARY.match(ln):
            units.append("\n".join(cur))
            cur = []
        cur.append(ln)
    if cur:
        units.append("\n".join(cur))

    out: list[str] = []
    buf = ""
    for unit in units:
        if counter.count(unit) > max_tokens:
            if buf:
                out.append(buf)
                buf = ""
            out.extend(_degrade_code_lines(unit, counter, max_tokens))
            continue
        if buf and counter.count(buf) + counter.count(unit) > max_tokens:
            out.append(buf)
            buf = ""
        buf = unit if not buf else buf + "\n" + unit
    if buf:
        out.append(buf)
    return out or [code]


def _degrade_code_lines(code: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    lines = code.split("\n")
    out: list[str] = []
    buf: list[str] = []
    tokens = 0
    for ln in lines:
        t = counter.count(ln)
        if t > max_tokens:
            if buf:
                out.append("\n".join(buf))
                buf, tokens = [], 0
            out.append(ln)
            continue
        if buf and tokens + t > max_tokens:
            out.append("\n".join(buf))
            buf, tokens = [], 0
        buf.append(ln)
        tokens += t
    if buf:
        out.append("\n".join(buf))
    return out or [code]


# ------------------------------------------------------------------ 长文本递归降级


def _split_spectrum(text: str) -> list[tuple[str, _Splitter]]:
    """返回 [(连接符, 切分器), ...]，优先级 段落→句→子句→词。"""
    return [
        ("\n\n", lambda t: [p for p in t.split("\n\n") if p]),
        ("", lambda t: _split_by_chars(t, ("。", "！", "？", ".", "!"))),
        ("", lambda t: _split_by_chars(t, ("，", "；", ",", ";", "、"))),
        (" ", lambda t: [w for w in t.split() if w]),
    ]


def _degrade_text(text: str, counter: TokenCounter, max_tokens: int) -> list[str]:
    """把超限文本降级为若干 ≤max 的块：段落→句→子句→词，不漏不重。"""
    if not text:
        return []
    if counter.count(text) <= max_tokens:
        return [text]
    for sep, splitter in _split_spectrum(text):
        parts = [p for p in splitter(text) if p]
        if len(parts) <= 1:
            continue
        groups = _group_fragments(parts, sep, counter, max_tokens)
        if groups:
            return groups
    return [text]


def _group_fragments(
    parts: list[str], sep: str, counter: TokenCounter, max_tokens: int
) -> list[str]:
    out: list[str] = []
    cur: list[str] = []
    cur_tokens = 0
    for part in parts:
        t = counter.count(part)
        if t > max_tokens:
            if cur:
                out.append(sep.join(cur))
                cur, cur_tokens = [], 0
            out.extend(_degrade_text(part, counter, max_tokens))
            continue
        if cur and cur_tokens + t > max_tokens:
            out.append(sep.join(cur))
            cur, cur_tokens = [], 0
        cur.append(part)
        cur_tokens += t
    if cur:
        out.append(sep.join(cur))
    return out
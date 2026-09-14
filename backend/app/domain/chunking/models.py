"""切分领域的数据契约与配置（`domain/chunking` 纯函数层，零 I/O、零框架依赖）。

- `Block`：MinerU `content_list.json` 的一个元素（type/text_level/text/page_idx/bbox/images）。
- `Chunk`：检索单元，字段与 `RetrievedChunk` 契约对齐（chunk_id/kb_id/document_id/parent_id/
  content/page_idx/bbox），另加 `section_path`（结构面包屑）、`block_type`、`is_recallable`
  （真=Child，可召回；假=Parent，供生成）。
- `ChunkConfig`：各类型 target/max token 档位 + `overlap_ratio`（默认 0 关）。
- `TokenCounter` 可插拔；默认 `TiktokenTokenCounter`（cl100k_base × 安全系数 1.15）。
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Protocol

# 确定性 id 命名空间（RFC 4122 UUID5）：同输入产出同 id（可重放）
_ID_NAMESPACE = uuid.UUID("6ba7b811-9dad-11d1-80b4-00c04fd430c8")


class TokenCounter(Protocol):
    """token 计数抽象（可插拔，默认 tiktoken，测试注入确定性实现）。"""

    def count(self, text: str) -> int: ...


class TiktokenTokenCounter:
    """默认计数：tiktoken `cl100k_base`，乘 1.15 安全系数（project 定稿）。"""

    def __init__(self, safety_factor: float = 1.15) -> None:
        self._safety_factor = safety_factor
        self._encoding: Any | None = None

    def count(self, text: str) -> int:
        if self._encoding is None:
            import tiktoken

            self._encoding = tiktoken.get_encoding("cl100k_base")
        factor = self._safety_factor
        return int(round(len(self._encoding.encode(text)) * factor))


class Block:
    """MinerU `content_list.json` 的一个解析元素。

    `bbox` 为 (x0,y0,x1,y1) 或 None；`images` 保留图元信息（本 change 不消费内容）。
    text_level：0 = 正文；>0 = 标题层级（越界块视为正文）。
    """

    __slots__ = ("type", "text", "text_level", "page_idx", "bbox", "images")

    def __init__(
        self,
        *,
        type: str,
        text: str,
        text_level: int = 0,
        page_idx: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        images: tuple[Any, ...] = (),
    ) -> None:
        self.type = type
        self.text = text
        self.text_level = text_level if isinstance(text_level, int) else 0
        self.page_idx = page_idx
        self.bbox = bbox
        self.images = images

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<Block type={self.type} level={self.text_level} t={self.text[:16]!r}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Block):
            return NotImplemented
        return (
            self.type == other.type
            and self.text == other.text
            and self.text_level == other.text_level
            and self.page_idx == other.page_idx
            and self.bbox == other.bbox
            and self.images == other.images
        )

    def __hash__(self) -> int:
        return hash((self.type, self.text, self.text_level, self.page_idx, self.bbox, self.images))


class Chunk:
    """检索单元（Child/Parent 同结构，`is_recallable` 区分；`parent_id` 自关联）。

    设计 D1：`id` 以 **UUID hex 字符串** 呈现，与 `RetrievedChunk.chunk_id` 及
    Milvus pk 复用链路对齐；由内容确定性派生（UUID5），同输入重放产出同 id 与同关联。
    """

    __slots__ = (
        "id",
        "kb_id",
        "document_id",
        "parent_id",
        "content",
        "page_idx",
        "bbox",
        "section_path",
        "block_type",
        "is_recallable",
    )

    def __init__(
        self,
        *,
        id: str,
        content: str,
        kb_id: str | None = None,
        document_id: str | None = None,
        parent_id: str | None = None,
        page_idx: int | None = None,
        bbox: tuple[float, float, float, float] | None = None,
        section_path: str = "",
        block_type: str = "text",
        is_recallable: bool = False,
    ) -> None:
        self.id = id
        self.content = content
        self.kb_id = kb_id
        self.document_id = document_id
        self.parent_id = parent_id
        self.page_idx = page_idx
        self.bbox = bbox
        self.section_path = section_path
        self.block_type = block_type
        self.is_recallable = is_recallable

    def __repr__(self) -> str:  # pragma: no cover - 排障辅助
        return f"<Chunk {self.id[:8]} t={self.block_type} rec={self.is_recallable}>"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Chunk):
            return NotImplemented
        return (
            self.id == other.id
            and self.kb_id == other.kb_id
            and self.document_id == other.document_id
            and self.parent_id == other.parent_id
            and self.content == other.content
            and self.page_idx == other.page_idx
            and self.bbox == other.bbox
            and self.section_path == other.section_path
            and self.block_type == other.block_type
            and self.is_recallable == other.is_recallable
        )


class ChunkConfig:
    """切分档位：各类型 target/max token；`overlap_ratio` 默认 0（关闭）。

    project 定稿：text/list 512/768、table 1024/2048、code 768/1024、equation 256/512。
    """

    __slots__ = (
        "text_target_tokens",
        "text_max_tokens",
        "list_target_tokens",
        "list_max_tokens",
        "table_target_tokens",
        "table_max_tokens",
        "code_target_tokens",
        "code_max_tokens",
        "equation_target_tokens",
        "equation_max_tokens",
        "overlap_ratio",
    )

    def __init__(
        self,
        *,
        text_target_tokens: int = 512,
        text_max_tokens: int = 768,
        list_target_tokens: int = 512,
        list_max_tokens: int = 768,
        table_target_tokens: int = 1024,
        table_max_tokens: int = 2048,
        code_target_tokens: int = 768,
        code_max_tokens: int = 1024,
        equation_target_tokens: int = 256,
        equation_max_tokens: int = 512,
        overlap_ratio: float = 0.0,
    ) -> None:
        self.text_target_tokens = text_target_tokens
        self.text_max_tokens = text_max_tokens
        self.list_target_tokens = list_target_tokens
        self.list_max_tokens = list_max_tokens
        self.table_target_tokens = table_target_tokens
        self.table_max_tokens = table_max_tokens
        self.code_target_tokens = code_target_tokens
        self.code_max_tokens = code_max_tokens
        self.equation_target_tokens = equation_target_tokens
        self.equation_max_tokens = equation_max_tokens
        self.overlap_ratio = max(0.0, overlap_ratio)

    def target_tokens(self, block_type: str) -> int:
        return self._bucket_tokens(block_type, "target")

    def max_tokens(self, block_type: str) -> int:
        return self._bucket_tokens(block_type, "max")

    def _bucket_tokens(self, block_type: str, suffix: str) -> int:
        name = f"{block_type}_{suffix}_tokens" if block_type != "list" else f"list_{suffix}_tokens"
        return int(getattr(self, name))


def _is_heading(block: Block) -> bool:
    """是否标题块（text_level > 0 且属于 text 类型）。"""
    return block.type == "text" and block.text_level > 0


def deterministic_chunk_id(*parts: str) -> str:
    """由内容派生确定性 UUID5（hex 字符串）：同输入同 id，可重放。"""
    digest = "|".join(parts)
    return str(uuid.uuid5(_ID_NAMESPACE, digest))


def _coerce_bbox(raw: Any) -> tuple[float, float, float, float] | None:
    """把 artifact 的 bbox 规整为四元组；非法/缺失返回 None（容错）。"""
    if raw is None:
        return None
    try:
        items = list(raw)
    except TypeError:
        return None
    if len(items) != 4:
        return None
    try:
        return (float(items[0]), float(items[1]), float(items[2]), float(items[3]))
    except (TypeError, ValueError):
        return None


def blocks_from_artifact(path: str) -> list[Block]:
    """读取 `content_list.json`（MinerU 产物）并解析为 `list[Block]`。

    坏 JSON 或结构非法（顶层不是 list、元素缺 type/text）抛 `ValueError`。
    """
    with open(path, encoding="utf-8") as fh:
        return blocks_from_json(fh.read())


def blocks_from_json(data: str | bytes) -> list[Block]:
    """从 JSON 字节串/文本解析为 `list[Block]`（服务层复用：产物经 storage 读为 bytes）。

    与 `blocks_from_artifact` 共用同一解析逻辑与容错语义。
    """
    parsed = json.loads(data)
    if not isinstance(parsed, list):
        raise ValueError("content_list.json 顶层必须是 JSON 数组")
    return [_to_block(item) for item in parsed]


def _to_block(item: Any) -> Block:
    if not isinstance(item, dict):
        raise ValueError("content_list 元素必须是对象")
    text = item.get("text")
    if not isinstance(text, str):
        raise ValueError("content_list 元素缺少 text 字段")
    return Block(
        type=str(item.get("type", "text")),
        text=text,
        text_level=item.get("text_level", 0),
        page_idx=item.get("page_idx"),
        bbox=_coerce_bbox(item.get("bbox")),
        images=tuple(item.get("images") or ()),
    )


def _split_text_by_sentences(text: str) -> list[str]:
    """按句号/问号/叹号切分（保留标点），用于长文本降级。"""
    return _split_by_chars(text, ("。", "！", "？", "!", "?"))


def _split_text_by_clauses(text: str) -> list[str]:
    """按逗号/分号切分（保留标点），进一步降级。"""
    return _split_by_chars(text, ("，", "；", ",", ";", "、"))


def _split_by_chars(text: str, chars: tuple[str, ...]) -> list[str]:
    """把 text 按给定标点切成带结束标点的片段；不丢字（残句并入前片）。

    无标点或空串时返回整串（单元素），交由上层决定是否需要进一步降级。
    """
    if not text:
        return [text] if text else []
    pieces: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        if ch in chars:
            pieces.append(buf)
            buf = ""
    if buf:
        if pieces:
            pieces[-1] += buf
        else:
            pieces.append(buf)
    return pieces or [text]
"""`domain/chunking` 纯函数切分域（零 I/O、零框架依赖，全仓 TDD 主战场）。"""

from app.domain.chunking.builder import build_chunks
from app.domain.chunking.models import (
    Block,
    Chunk,
    ChunkConfig,
    TiktokenTokenCounter,
    TokenCounter,
    blocks_from_artifact,
)

__all__ = [
    "Block",
    "Chunk",
    "ChunkConfig",
    "TiktokenTokenCounter",
    "TokenCounter",
    "blocks_from_artifact",
    "build_chunks",
]
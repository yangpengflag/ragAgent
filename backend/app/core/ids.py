"""ID 生成。

主键统一使用 UUID v7：时间有序，`BINARY(16)` 存储下索引局部性远优于随机 UUID。
Python 3.12 标准库无 uuid7，此处按 RFC 9562 自实现。
"""

from __future__ import annotations

import os
import time
import uuid


def uuid7() -> uuid.UUID:
    """生成 UUID v7：48 位毫秒时间戳 + 版本/变体位 + 随机位。"""
    milliseconds = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = int.from_bytes(os.urandom(2), "big") & 0x0FFF
    rand_b = int.from_bytes(os.urandom(8), "big") & 0x3FFFFFFFFFFFFFFF
    value = (milliseconds << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)

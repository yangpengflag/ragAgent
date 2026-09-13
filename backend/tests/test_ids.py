"""UUID v7 红线（任务 5.2 附带）。

design D7 承诺的"时间有序 + 全局唯一"必须可验证；
注意：**同毫秒内不保证递增**（低 74 位为随机位），故只断言跨毫秒有序。
"""

from __future__ import annotations

import time
import uuid

from app.core.ids import uuid7


def test_uuid7_has_correct_version_and_variant():
    value = uuid7()

    assert value.version == 7
    assert value.variant == uuid.RFC_4122


def test_uuid7_is_time_ordered_across_milliseconds():
    first = uuid7()
    time.sleep(0.005)
    second = uuid7()

    assert first.int < second.int, "跨毫秒必须单调递增（索引局部性依赖此性质）"


def test_uuid7_is_unique():
    assert len({uuid7() for _ in range(1000)}) == 1000

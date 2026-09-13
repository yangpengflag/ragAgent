"""知识库授权解析服务（tasks 5.1，design D4）。

授权数据的唯一真相源是业务 MySQL 的 `user_kb_grant` 表——但该表的 schema
归 knowledge-base-crud change 所有，此处面向窄端口 `KbGrantReader` 编程：
端口落位后由真实仓储实现接线，本服务逻辑（直查/TTL 缓存/fail-closed）
先行落地并可离线测试。

语义（spec「授权数据以业务数据库为唯一真相源」）：
- 默认直查不缓存：新增/撤销授权下一次调用即时生效
- 可选 TTL 缓存：构造期强制 `cache_ttl_seconds <= 5`（spec 上限结构化）
- 读取失败 fail-closed：`StoreUnavailableError` 冒泡（→ 503），
  绝不降级为空授权（空授权 = 拒绝访问，是安全方向，但静默吞错不是）
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

# spec 硬上限：撤销授权后的生效延迟默认不得超过 5 秒
MAX_CACHE_TTL_SECONDS = 5.0
# 缓存条数上限：长跑服务按用户累积 = 内存泄漏；超出时淘汰最旧条目
MAX_CACHE_ENTRIES = 10_000


@runtime_checkable
class KbGrantReader(Protocol):
    """授权读取端口：按用户返回其被授权的知识库标识集合。"""

    def kb_ids_for_user(self, user_id: str) -> list[str]:
        """返回用户当前持有的全部 kb_id（含全部库级角色）。"""
        ...


class KbAccessResolver:
    """把「user_id → 授权 kb_id 集合」解析为可注入检索层的稳定列表。"""

    def __init__(
        self,
        reader: KbGrantReader,
        *,
        cache_ttl_seconds: float | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        """
        Args:
            reader: 授权读取端口（默认模式每次调用透传，不缓存）。
            cache_ttl_seconds: 可选 TTL 缓存窗口；None = 直查。
                MUST 满足 `0 < ttl <= MAX_CACHE_TTL_SECONDS`。
            clock: 可注入时钟（单测用），默认 `time.monotonic`。
        """
        if cache_ttl_seconds is not None:
            if cache_ttl_seconds <= 0:
                raise ValueError("cache_ttl_seconds 必须为正数")
            if cache_ttl_seconds > MAX_CACHE_TTL_SECONDS:
                raise ValueError(
                    f"cache_ttl_seconds 不得超过 {MAX_CACHE_TTL_SECONDS}"
                    "（spec：撤销授权生效延迟上限）"
                )
        self._reader = reader
        self._ttl = cache_ttl_seconds
        self._clock = clock or __import__("time").monotonic
        self._cache: dict[str, tuple[list[str], float]] = {}

    @property
    def cached_entries(self) -> int:
        """当前缓存条目数（可观测性 / 单测断言用）。"""
        return len(self._cache)

    def _purge_expired(self, now: float) -> None:
        """清理过期条目后按需淘汰最旧条目，保证缓存有界。"""
        expired = [
            user_id
            for user_id, (_, at) in self._cache.items()
            if now - at >= (self._ttl or 0)
        ]
        for user_id in expired:
            self._cache.pop(user_id, None)
        overflow = len(self._cache) - MAX_CACHE_ENTRIES
        if overflow > 0:
            # dict 保序：最早插入的排在最前，直接淘汰最旧的一批
            for user_id in list(self._cache)[:overflow]:
                self._cache.pop(user_id, None)

    def authorized_kb_ids(self, user_id: str) -> list[str]:
        """解析用户的授权 kb_id 集合（排序输出，保证可重复性）。"""
        if self._ttl is not None:
            now = self._clock()
            cached = self._cache.get(user_id)
            if cached is not None and now - cached[1] < self._ttl:
                return list(cached[0])
            kb_ids = sorted(self._reader.kb_ids_for_user(user_id))
            self._cache[user_id] = (kb_ids, now)
            # 先插入再清理：保证条目数严格不超过上限（插入后淘汰最旧）
            self._purge_expired(now)
            return list(kb_ids)
        return sorted(self._reader.kb_ids_for_user(user_id))

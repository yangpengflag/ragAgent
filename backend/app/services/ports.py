"""认证服务的可注入端口（design D4 / D9，tasks 5.0）。

服务层只依赖本模块的 Protocol，不触碰 Redis 客户端——单测用内存替身，
生产行 `app/integrations/redis_stores.py` 的 Redis 实现。先有 seam 再写用例，
红灯因此不依赖任何真实中间件。

两个端口对应 design D9 的**相反**失败语义：
- `RevocationStore`（撤销名单）：不可用时 fail-closed，异常直接冒泡成 503
- `RateLimitStore`（限流计数）：不可用时 fail-open，服务层捕获后放行并告警

存储实现统一以 `StoreUnavailableError` 表达"后端不可达/超时"，
让服务层能用同一个异常类型区分"存储坏了"与"业务拒绝"。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Protocol

from app.core.exceptions import AppError, ErrorCode


class StoreUnavailableError(AppError):
    """撤销/限流存储不可用（Redis 宕机、超时等）。

    冒泡后由全局处理器转为 503 `upstream_unavailable`；
    仅限流路径会捕获它（fail-open），撤销路径一律放行冒泡（fail-closed）。
    """

    status_code = 503  # HTTPStatus.SERVICE_UNAVAILABLE
    error_code = ErrorCode.UPSTREAM_UNAVAILABLE


class RevocationStore(Protocol):
    """刷新令牌撤销名单（design D4：黑名单 + 轮换）。"""

    def revoke(self, jti: str, *, ttl_seconds: int) -> None:
        """把 jti 拉黑；ttl_seconds 后自然过期（令牌自身寿命已到，无需再拉黑）。"""
        ...

    def is_revoked(self, jti: str) -> bool:
        """jti 是否已在黑名单。不可用时抛 `StoreUnavailableError`（fail-closed）。"""
        ...


class RateLimitStore(Protocol):
    """登录失败计数（键 = 用户名 + 来源地址）。

    语义：`increment` 原子加一并返回当前计数，首次写入时设置窗口过期
    （Redis 用 INCR + EXPIRE NX 的等价组合）；窗口内继续累加，窗口过后归零。
    """

    def count(self, key: str) -> int: ...

    def increment(self, key: str, *, window_seconds: int) -> int: ...

    def reset(self, key: str) -> None: ...


class InMemoryRevocationStore:
    """内存替身：单测用，无过期语义（ttl 仅记录）。线程不安全，勿用于生产。"""

    def __init__(self) -> None:
        self._revoked: dict[str, int] = {}

    def revoke(self, jti: str, *, ttl_seconds: int) -> None:
        self._revoked[jti] = ttl_seconds

    def is_revoked(self, jti: str) -> bool:
        return jti in self._revoked


class InMemoryRateLimitStore:
    """内存替身：窗口语义用可注入时钟模拟；默认真实时钟。"""

    def __init__(self, now: Callable[[], float] | None = None) -> None:
        self._now = now or time.monotonic
        self._entries: dict[str, tuple[int, float]] = {}

    def _live(self, key: str) -> int:
        entry = self._entries.get(key)
        if entry is None:
            return 0
        count, expires_at = entry
        if self._now() >= expires_at:
            del self._entries[key]
            return 0
        return count

    def count(self, key: str) -> int:
        return self._live(key)

    def increment(self, key: str, *, window_seconds: int) -> int:
        current = self._live(key)
        count = current + 1
        expires_at = self._now() + window_seconds
        # 窗口从首次失败起算：已有未过期窗口则保持原过期点
        entry = self._entries.get(key)
        if current > 0 and entry is not None and self._now() < entry[1]:
            expires_at = entry[1]
        self._entries[key] = (count, expires_at)
        return count

    def reset(self, key: str) -> None:
        self._entries.pop(key, None)

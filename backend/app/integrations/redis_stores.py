"""撤销名单与限流计数的 Redis 实现（`services/ports.py` 的生产实现）。

Redis 操作失败一律包装为 `StoreUnavailableError`——服务层据此实现
design D9 的两向取舍（撤销 fail-closed / 限流 fail-open）。
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache

import redis

from app.core.config import get_settings
from app.services.ports import StoreUnavailableError

# 键前缀：撤销名单与限流计数共用一个 Redis db，前缀避免与其他用途冲突
_REVOKED_PREFIX = "auth:revoked:"
_LOGIN_FAIL_PREFIX = "auth:login-fail:"


@lru_cache
def build_redis_client() -> redis.Redis:
    """进程内共享的 Redis 客户端（惰性连接）。

    超时收紧到 2s：撤销/限流路径若 Redis 卡死，宁可快速失败也不要拖住请求。
    """
    settings = get_settings()
    return redis.Redis(
        host=settings.redis_host,
        port=settings.redis_port,
        password=settings.redis_password,
        db=settings.redis_db,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )


def _execute[T](operation: Callable[[], T]) -> T:
    try:
        return operation()
    except redis.RedisError as exc:
        raise StoreUnavailableError(f"redis 不可用: {type(exc).__name__}") from exc


class RedisRevocationStore:
    """黑名单：SET + EX（TTL = 令牌剩余寿命，自然过期后无需再拉黑）。"""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def revoke(self, jti: str, *, ttl_seconds: int) -> None:
        _execute(
            lambda: self._client.set(
                _REVOKED_PREFIX + jti, 1, ex=max(ttl_seconds, 1)
            )
        )

    def is_revoked(self, jti: str) -> bool:
        return bool(_execute(lambda: self._client.exists(_REVOKED_PREFIX + jti)))


class RedisRateLimitStore:
    """登录失败计数：INCR + EXPIRE NX（窗口从首次失败起算，且不会漏设过期）。"""

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def _key(self, key: str) -> str:
        return _LOGIN_FAIL_PREFIX + key

    def count(self, key: str) -> int:
        value = _execute(lambda: self._client.get(self._key(key)))
        return int(value) if value else 0

    def increment(self, key: str, *, window_seconds: int) -> int:
        name = self._key(key)

        def _incr_and_expire() -> int:
            count = int(self._client.incr(name))
            # NX：仅当键尚无过期时间时设置——窗口从首次失败起算；
            # 每次都补设可避免 INCR 与 EXPIRE 之间崩溃导致的"永久锁死"
            self._client.expire(name, window_seconds, nx=True)
            return count

        return _execute(_incr_and_expire)

    def reset(self, key: str) -> None:
        _execute(lambda: self._client.delete(self._key(key)))

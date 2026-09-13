"""授权解析服务红灯（任务 5.1）。

覆盖 spec「授权数据以业务数据库为唯一真相源」：
- 默认直查：新增/撤销授权下一次调用即时生效
- 可选 TTL 缓存：撤销后生效延迟有界（构造期强制 ≤ 5s）
- 读取失败 fail-closed：存储异常冒泡（503），不降级为空授权
"""

import pytest

from app.services.kb_access import MAX_CACHE_ENTRIES, KbAccessResolver, KbGrantReader
from app.services.ports import StoreUnavailableError


class FakeGrantReader:
    """授权读取替身：可编程返回值与异常。"""

    def __init__(self) -> None:
        self._grants: dict[str, list[str]] = {}

    def set_grants(self, user_id: str, kb_ids: list[str]) -> None:
        self._grants[user_id] = list(kb_ids)

    def kb_ids_for_user(self, user_id: str) -> list[str]:
        return list(self._grants.get(user_id, []))


class ExplodingReader:
    """存储不可用替身。"""

    def kb_ids_for_user(self, user_id: str) -> list[str]:
        raise StoreUnavailableError("mysql down")


# ---------------------------------------------------------------- 直查模式


def test_direct_mode_reflects_grant_immediately():
    reader = FakeGrantReader()
    resolver = KbAccessResolver(reader)
    reader.set_grants("u1", ["kb-a"])

    assert resolver.authorized_kb_ids("u1") == ["kb-a"]

    # 新增授权：下一次调用即时生效（spec：授权即时生效）
    reader.set_grants("u1", ["kb-a", "kb-b"])
    assert resolver.authorized_kb_ids("u1") == ["kb-a", "kb-b"]

    # 撤销授权：同样即时生效（spec：撤销后不可再检索）
    reader.set_grants("u1", ["kb-a"])
    assert resolver.authorized_kb_ids("u1") == ["kb-a"]


def test_unknown_user_yields_empty_grants():
    resolver = KbAccessResolver(FakeGrantReader())

    assert resolver.authorized_kb_ids("nobody") == []


def test_reader_failure_propagates_fail_closed():
    """存储不可用时异常冒泡（fail-closed），绝不静默降级为空授权。"""
    resolver = KbAccessResolver(ExplodingReader())

    with pytest.raises(StoreUnavailableError):
        resolver.authorized_kb_ids("u1")


# ---------------------------------------------------------------- TTL 缓存模式


def test_ttl_cache_serves_within_window():
    now = {"t": 1000.0}
    reader = FakeGrantReader()
    resolver = KbAccessResolver(
        reader, cache_ttl_seconds=5.0, clock=lambda: now["t"]
    )
    reader.set_grants("u1", ["kb-a"])
    assert resolver.authorized_kb_ids("u1") == ["kb-a"]

    # 窗口内撤销不生效（缓存期）
    reader.set_grants("u1", [])
    now["t"] += 1.0
    assert resolver.authorized_kb_ids("u1") == ["kb-a"]


def test_ttl_cache_converges_after_expiry():
    """缓存过期后撤销生效——延迟 ≤ TTL（spec ≤ 5s 上限）。"""
    now = {"t": 1000.0}
    reader = FakeGrantReader()
    resolver = KbAccessResolver(
        reader, cache_ttl_seconds=5.0, clock=lambda: now["t"]
    )
    reader.set_grants("u1", ["kb-a"])
    resolver.authorized_kb_ids("u1")

    reader.set_grants("u1", [])
    now["t"] += 5.0
    assert resolver.authorized_kb_ids("u1") == []


def test_ttl_above_five_seconds_is_rejected():
    """spec 硬上限：TTL > 5s 在构造期拒绝（结构化保证，不靠纪律）。"""
    with pytest.raises(ValueError, match="5"):
        KbAccessResolver(FakeGrantReader(), cache_ttl_seconds=6.0)


def test_cache_is_bounded_and_expires_entries():
    """TTL 缓存必须有界：长跑服务按用户累积条目 = 内存泄漏。"""
    now = {"t": 1000.0}
    reader = FakeGrantReader()
    resolver = KbAccessResolver(reader, cache_ttl_seconds=5.0, clock=lambda: now["t"])

    for i in range(MAX_CACHE_ENTRIES + 50):
        reader.set_grants(f"u{i}", ["kb-a"])
        resolver.authorized_kb_ids(f"u{i}")

    assert resolver.cached_entries <= MAX_CACHE_ENTRIES
    # 被驱逐的旧条目不会导致错误结果：重新查询即回源
    reader.set_grants("u0", ["kb-z"])
    assert resolver.authorized_kb_ids("u0") == ["kb-z"]


def test_ttl_must_be_positive():
    with pytest.raises(ValueError):
        KbAccessResolver(FakeGrantReader(), cache_ttl_seconds=0.0)


def test_port_protocol_is_runtime_checkable():
    """FakeGrantReader 满足端口协议（结构化类型的回归守卫）。"""
    reader = FakeGrantReader()

    assert isinstance(reader, KbGrantReader)

"""真实探针红线（任务 6.4）。

目标不可达时必须在显式超时内返回 down，而不是挂起或抛异常。
使用 127.0.0.1:1（必被拒绝）以保证快速、确定性。
"""

from __future__ import annotations

import threading
import time

from sqlalchemy import URL

from app.integrations.health_probes import MilvusProbe, MysqlProbe, RedisProbe


def test_mysql_probe_reports_down_for_unreachable_endpoint():
    probe = MysqlProbe(
        URL.create(
            "mysql+pymysql",
            username="root",
            password="x",
            host="127.0.0.1",
            port=1,
            database="nonexistent",
        ),
        timeout=2.0,
    )

    status = probe.check()

    assert status.name == "mysql"
    assert status.ok is False
    assert status.error


def test_redis_probe_reports_down_for_unreachable_endpoint():
    probe = RedisProbe(host="127.0.0.1", port=1, password=None, db=0, timeout=2.0)

    status = probe.check()

    assert status.name == "redis"
    assert status.ok is False
    assert status.error


def test_milvus_probe_returns_within_timeout_when_probe_hangs(monkeypatch):
    """黑洞场景：探测不返回时必须在超时内判 down，且在飞期间不再新建探测。"""
    probe = MilvusProbe(
        uri="http://127.0.0.1:1", database="ragagent", token=None, timeout=0.2
    )
    release = threading.Event()
    monkeypatch.setattr(probe, "_probe", lambda: release.wait(5))

    started = time.monotonic()
    first = probe.check()
    elapsed = time.monotonic() - started

    assert first.ok is False
    assert "exceeded" in (first.error or "")
    assert elapsed < 1.0, f"未在超时内返回，耗时 {elapsed:.2f}s"

    second = probe.check()
    assert second.ok is False
    assert "still running" in (second.error or "")

    release.set()  # 放行后台线程，避免影响其它用例


def test_milvus_probe_recovers_after_stale_window(monkeypatch):
    """陈旧窗口之后必须允许接管，否则一次卡死会让 Milvus 永久判 down。

    用 `_stale_after()` 推导陈旧时刻，避免与窗口常量隐式耦合。
    """
    probe = MilvusProbe(
        uri="http://127.0.0.1:1", database="ragagent", token=None, timeout=0.2
    )
    probe._in_flight_since = time.monotonic() - probe._stale_after() - 1
    monkeypatch.setattr(probe, "_probe", lambda: None)

    status = probe.check()

    assert status.ok is True


def test_milvus_probe_bounds_live_workers(monkeypatch):
    """卡住的探测线程必须封顶，否则依赖长期不可达会无界累积（spec R7）。"""
    probe = MilvusProbe(
        uri="http://127.0.0.1:1", database="ragagent", token=None, timeout=0.1
    )
    release = threading.Event()
    monkeypatch.setattr(probe, "_probe", lambda: release.wait(5))

    errors: list[str] = []
    try:
        for _ in range(probe.MAX_LIVE_WORKERS + 3):
            # 强制允许接管，绕过陈旧窗口等待
            probe._in_flight_since = time.monotonic() - probe._stale_after() - 1
            errors.append(probe.check().error or "")
            assert probe._live_workers <= probe.MAX_LIVE_WORKERS
    finally:
        release.set()

    assert any("exhausted" in error for error in errors), (
        f"达到线程上限后必须直接拒绝，实际错误序列: {errors}"
    )


def test_milvus_probe_stays_down_when_thread_cannot_start(monkeypatch):
    """线程启动失败时不得抛异常（端点须仍返回 200），也不得永久污染在飞标记。"""
    probe = MilvusProbe(
        uri="http://127.0.0.1:1", database="ragagent", token=None, timeout=0.2
    )

    def _boom(*args, **kwargs):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(threading, "Thread", _boom)

    status = probe.check()

    assert status.ok is False
    assert probe._in_flight_since is None, "启动失败后必须释放在飞标记"


def test_milvus_probe_reports_down_within_timeout():
    probe = MilvusProbe(
        uri="http://127.0.0.1:1", database="ragagent", token=None, timeout=2.0
    )

    started = time.monotonic()
    status = probe.check()
    elapsed = time.monotonic() - started

    assert status.name == "milvus"
    assert status.ok is False
    assert status.error
    assert elapsed < 15, f"探针未在超时内返回，耗时 {elapsed:.1f}s"

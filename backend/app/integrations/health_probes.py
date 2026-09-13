"""真实健康探针：MySQL / Redis / Milvus。

每个探针显式设置超时，保证依赖无响应时快速返回而不是挂起。
探针实现放这里，编排逻辑在 `app/domain/health.py`。
"""

from __future__ import annotations

import threading
import time
from contextlib import suppress
from functools import lru_cache
from typing import TYPE_CHECKING

import redis
from redis.backoff import NoBackoff
from redis.retry import Retry
from sqlalchemy import URL, create_engine, text
from sqlalchemy.engine import Engine

from app.core.config import Settings, get_settings
from app.core.db import build_database_url
from app.domain.health import ComponentStatus

if TYPE_CHECKING:
    from pymilvus import MilvusClient

MAX_ERROR_LEN = 200


def _message(exc: Exception) -> str:
    return f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LEN]


class MysqlProbe:
    name = "mysql"

    def __init__(self, url: URL, timeout: float) -> None:
        self._engine: Engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"connect_timeout": max(1, int(timeout))},
        )

    def check(self) -> ComponentStatus:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception as exc:  # noqa: BLE001 - 任何失败都归为不可用
            return ComponentStatus(name=self.name, ok=False, error=_message(exc))
        return ComponentStatus(name=self.name, ok=True)


class RedisProbe:
    name = "redis"

    def __init__(
        self,
        *,
        host: str,
        port: int,
        password: str | None,
        db: int,
        timeout: float,
    ) -> None:
        # 显式关闭重试：redis-py 默认重试会把 2s 连接超时放大到 26s，
        # 健康检查只做单次尝试，快速失败比"努力重连"更重要。
        self._client = redis.Redis(
            host=host,
            port=port,
            password=password,
            db=db,
            socket_timeout=timeout,
            socket_connect_timeout=timeout,
            retry=Retry(NoBackoff(), 0),
            retry_on_error=[],
        )

    def check(self) -> ComponentStatus:
        try:
            self._client.ping()
        except Exception as exc:  # noqa: BLE001
            return ComponentStatus(name=self.name, ok=False, error=_message(exc))
        return ComponentStatus(name=self.name, ok=True)


class MilvusProbe:
    """Milvus 探针。

    pymilvus 的连接重试没有可靠上限（实测不可达时挂 40s+），仅靠 `timeout`
    参数无法保证不挂起，因此探测在**守护线程**中执行并以 `Event.wait` 硬性兜底。

    线程模型的三条硬约束（都对应 spec R7「不得挂起且不得无界累积」）：

    1. **并发**：用实例级"在飞"状态（带代次 token）限制同时只有一代探测在飞；
       代次校验保证"陈旧接管后旧线程返回"不会误清掉新线程的标记。
    2. **有界**：卡住的线程无法被取消，因此对**存活 worker 数**硬性封顶
       （`MAX_LIVE_WORKERS`）——依赖长期不可达时最多累积这么多个线程，
       达到上限后直接返回 down，不再新建。
    3. **可恢复**：在飞状态带时间戳，超过陈旧窗口即允许接管，避免一次卡死
       导致永久判 down。用守护线程而非 `ThreadPoolExecutor`：后者工作线程
       为非守护线程，解释器退出时会被 join 而卡住进程。
    """

    name = "milvus"

    STALE_FACTOR = 5.0
    MIN_STALE_SECONDS = 30.0
    MAX_LIVE_WORKERS = 2

    def __init__(
        self,
        *,
        uri: str,
        database: str,
        token: str | None,
        timeout: float,
    ) -> None:
        self._uri = uri
        self._database = database
        self._token = token or ""
        self._timeout = timeout
        self._client: MilvusClient | None = None
        self._client_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._in_flight_since: float | None = None
        self._in_flight_token: float | None = None
        self._live_workers = 0
        # 预热：MilvusClient() 构造本身就是一次建连，把它移出探测的计时窗口，
        # 否则"首次检查"的构造耗时会计入 `_timeout`，导致可达时也误报超时。
        # 失败不影响功能（客户端保持 None，探测时会重试并如实报 down）。
        with suppress(Exception):
            self._client_or_create()

    # ---------------------------------------------------------------- 在飞状态
    def _stale_after(self) -> float:
        return max(self._timeout * self.STALE_FACTOR, self.MIN_STALE_SECONDS)

    def _try_acquire(self) -> tuple[float | None, str]:
        """尝试获取探测许可。

        返回 `(token, 拒绝原因)`；token 为 None 表示未获取到。
        """
        with self._state_lock:
            now = time.monotonic()
            if (
                self._in_flight_since is not None
                and now - self._in_flight_since < self._stale_after()
            ):
                return None, "previous probe still running"
            if self._live_workers >= self.MAX_LIVE_WORKERS:
                # 硬上限：旧线程可能永远不返回，不能再无限新建
                return None, "probe workers exhausted"
            self._live_workers += 1
            self._in_flight_since = now
            self._in_flight_token = now
            return now, ""

    def _release(self, token: float) -> None:
        """释放一次探测许可；仅当代次匹配时才清空在飞标记。

        每次成功 `_try_acquire` 后必须恰好调用一次
        （由 worker 线程结束时，或线程启动失败时调用）。
        """
        with self._state_lock:
            self._live_workers = max(0, self._live_workers - 1)
            if self._in_flight_token == token:
                self._in_flight_since = None
                self._in_flight_token = None

    # ---------------------------------------------------------------- 探测
    def _client_or_create(self) -> MilvusClient:
        # 加锁：陈旧接管可能让两代探测同时到达这里，避免重复构造客户端
        with self._client_lock:
            if self._client is None:
                # 懒加载：pymilvus 导入较重，且客户端构造会尝试建连
                from pymilvus import MilvusClient as _MilvusClient

                self._client = _MilvusClient(
                    uri=self._uri,
                    db_name=self._database,
                    token=self._token,
                    timeout=self._timeout,
                )
            return self._client

    def _probe(self) -> None:
        self._client_or_create().list_collections(timeout=self._timeout)

    def _run_bounded(self, token: float) -> str | None:
        """在守护线程中执行探测；超时返回错误描述，成功返回 None。"""
        outcome: dict[str, str | None] = {"error": None}
        finished = threading.Event()

        def _target() -> None:
            try:
                self._probe()
            except Exception as exc:  # noqa: BLE001 - 任何失败都归为不可用
                outcome["error"] = _message(exc)
            finally:
                # 先释放再唤醒调用方，避免调用方被唤醒后仍看到"在飞"而误判
                self._release(token)
                finished.set()

        threading.Thread(target=_target, name="milvus-probe", daemon=True).start()
        if not finished.wait(self._timeout):
            # 线程未返回：此处不释放，交由线程结束时释放；
            # 若线程彻底丢失，则由陈旧窗口接管（且受 MAX_LIVE_WORKERS 封顶）
            return f"TimeoutError: probe exceeded {self._timeout}s"
        return outcome["error"]

    def check(self) -> ComponentStatus:
        token, reason = self._try_acquire()
        if token is None:
            return ComponentStatus(
                name=self.name, ok=False, error=f"TimeoutError: {reason}"
            )
        try:
            error = self._run_bounded(token)
        except Exception as exc:  # noqa: BLE001 - 线程无法启动等：必须释放许可
            self._release(token)
            return ComponentStatus(name=self.name, ok=False, error=_message(exc))
        if error is not None:
            return ComponentStatus(name=self.name, ok=False, error=error)
        return ComponentStatus(name=self.name, ok=True)


@lru_cache
def build_probes() -> tuple[MysqlProbe | RedisProbe | MilvusProbe, ...]:
    """按配置构造三个真实探针（缓存，避免每次请求重建客户端）。"""
    settings: Settings = get_settings()
    timeout = settings.health_check_timeout_sec
    return (
        MysqlProbe(build_database_url(), timeout),
        RedisProbe(
            host=settings.redis_host,
            port=settings.redis_port,
            password=settings.redis_password,
            db=settings.redis_db,
            timeout=timeout,
        ),
        MilvusProbe(
            uri=settings.milvus_uri,
            database=settings.milvus_database,
            token=settings.milvus_token,
            timeout=timeout,
        ),
    )

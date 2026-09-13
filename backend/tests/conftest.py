"""pytest 共享 fixture。

配置隔离、探针替身等通用 fixture 由任务 1.7 / 1.8 逐步补充。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator

import pytest
from dotenv import dotenv_values
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import ENV_FILE, Settings, get_settings, load_settings
from app.domain.health import ComponentStatus

# 需要清空的进程环境变量前缀，避免污染测试
_MANAGED_PREFIXES = (
    "APP_",
    "MYSQL_",
    "REDIS_",
    "MILVUS_",
    "CELERY_",
    "DASHSCOPE_",
    "MINERU_",
    "LOG_",
    "HEALTH_",
)

# 构造 Settings 所需的最小必填集（仅测试用，不连接真实服务）
_REQUIRED_VALUES = {
    "APP_SECRET_KEY": "test-secret",
    "MYSQL_HOST": "127.0.0.1",
    "MYSQL_USER": "root",
    "MYSQL_DATABASE": "ragagent",
}


def _keys_declared_in_dotenv() -> set[str]:
    """仓库根 `.env` 中声明过的键名（只看键，不读值），统一大写比较。

    用 python-dotenv 解析，正确处理 `export` 前缀、引号、BOM、行内注释与大小写；
    手写按 `=` 切分会在这些情况下漏判，进而又去注入占位值、重新遮蔽真实配置。
    """
    if not ENV_FILE.exists():
        return set()
    return {key.upper() for key in dotenv_values(ENV_FILE)}


@pytest.fixture(autouse=True, scope="session")
def _ensure_configurable_without_dotenv() -> Iterator[None]:
    """让测试套件在**没有仓库根 `.env`** 的机器上也能构造应用（spec R8）。

    只为"进程环境与 `.env` 都没有"的必填项注入占位值。
    若 `.env` 已声明该键则**不注入**——环境变量优先级高于 `.env`，
    贸然注入会遮蔽开发者本机的真实配置（曾导致迁移集成测试被静默跳过）。
    """
    declared = _keys_declared_in_dotenv()
    injected: list[str] = []
    for key, value in _REQUIRED_VALUES.items():
        if key not in os.environ and key.upper() not in declared:
            os.environ[key] = value
            injected.append(key)
    try:
        yield
    finally:
        for key in injected:
            os.environ.pop(key, None)


@pytest.fixture
def isolated_env(monkeypatch: pytest.MonkeyPatch) -> Callable[..., Settings]:
    """返回 Settings 构造工厂，保证不读取仓库根 `.env`。

    流程：清空受管前缀的进程环境变量 → 注入最小必填集与覆盖值 →
    以 `_env_file=None` 构造，使 `.env` 完全不参与。
    """
    for name in list(os.environ):
        if name.startswith(_MANAGED_PREFIXES):
            monkeypatch.delenv(name, raising=False)
    # 清掉缓存，避免先前用例构造的 Settings 影响本次断言
    get_settings.cache_clear()

    def build(**overrides: str) -> Settings:
        values = dict(_REQUIRED_VALUES)
        values.update(overrides)
        for key, value in values.items():
            monkeypatch.setenv(key, value)
        return load_settings(_env_file=None)

    return build


class FakeProbe:
    """探针替身：返回预置状态，不做任何 I/O。"""

    def __init__(self, name: str, ok: bool = True, error: str | None = None) -> None:
        self.name = name
        self._ok = ok
        self._error = error

    def check(self) -> ComponentStatus:
        return ComponentStatus(name=self.name, ok=self._ok, error=self._error)


def _probes(*specs: tuple[str, bool, str | None]) -> list[FakeProbe]:
    return [FakeProbe(name, ok, error) for name, ok, error in specs]


@pytest.fixture
def healthy_probes() -> list[FakeProbe]:
    """三组件全部可用。"""
    return _probes(
        ("mysql", True, None), ("redis", True, None), ("milvus", True, None)
    )


@pytest.fixture
def milvus_down_probes() -> list[FakeProbe]:
    """Milvus 不可用，其余正常。"""
    return _probes(
        ("mysql", True, None),
        ("redis", True, None),
        ("milvus", False, "ConnectionRefusedError: milvus unreachable"),
    )


@pytest.fixture
def hanging_probes() -> list[FakeProbe]:
    """探针超时（模拟依赖无响应）。"""
    return _probes(
        ("mysql", True, None),
        ("redis", True, None),
        ("milvus", False, "TimeoutError: probe exceeded 2.0s"),
    )


@pytest.fixture
def sqlite_engine() -> Iterator[Engine]:
    """内存 SQLite 引擎：用于验证模型层行为，不依赖 MySQL。"""
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture
def sqlite_session(sqlite_engine: Engine) -> Iterator[Session]:
    """在内存 SQLite 上建表并返回会话。

    测试模块内定义的模型会在导入期注册进 Base.metadata。
    """
    from app.models.base import Base

    Base.metadata.create_all(sqlite_engine)
    factory = sessionmaker(bind=sqlite_engine, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()

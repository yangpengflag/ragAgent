"""pytest 共享 fixture。

配置隔离、探针替身等通用 fixture 由任务 1.7 / 1.8 逐步补充。
"""

from __future__ import annotations

import os
from collections.abc import Callable

import pytest

from app.core.config import Settings, get_settings, load_settings

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

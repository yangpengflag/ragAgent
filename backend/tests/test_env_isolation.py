"""配置隔离红灯（任务 1.7）。

目标：测试不得受仓库根 `.env` 影响。
为避免断言依赖开发者本机的 `.env` 内容，这里采用「哨兵文件正对照 + 隔离构造反对照」：
先证明指定 env 文件时读取路径确实生效，再证明隔离构造读不到任何 env 文件的值。
"""

from __future__ import annotations

import pytest

from app.core.config import ENV_FILE, Settings, load_settings


def _repo_env_sets_mysql_password() -> bool:
    """仓库根 .env 是否设置了非空 MYSQL_PASSWORD（否则反对照无从成立）。"""
    if not ENV_FILE.exists():
        return False
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        if line.startswith("MYSQL_PASSWORD=") and line.split("=", 1)[1].strip():
            return True
    return False


def test_isolated_env_reads_specified_env_file(tmp_path, isolated_env):
    """正对照：显式指定 env 文件时，其中的值必须被读到。"""
    isolated_env()  # 先注入最小必填集（来源为进程环境，非文件）
    sentinel = tmp_path / "sentinel.env"
    sentinel.write_text("MYSQL_PASSWORD=sentinel-value\n", encoding="utf-8")

    settings = load_settings(_env_file=sentinel)

    assert settings.mysql_password == "sentinel-value"


@pytest.mark.skipif(
    not _repo_env_sets_mysql_password(),
    reason="仓库根 .env 未设置非空 MYSQL_PASSWORD，反对照无从成立",
)
def test_isolated_env_does_not_leak_repo_dotenv(isolated_env):
    """反对照：隔离构造不得读到仓库根 .env 的密码。"""
    settings = isolated_env()

    assert isinstance(settings, Settings)
    assert settings.mysql_password is None
    assert settings.app_secret_key == "test-secret"


def test_isolated_env_can_override_values(isolated_env):
    settings = isolated_env(MYSQL_DATABASE="other_db", REDIS_PORT="6380")

    assert settings.mysql_database == "other_db"
    assert settings.redis_port == 6380

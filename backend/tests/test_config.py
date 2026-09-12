"""配置层红灯（任务 2.1）。

覆盖 spec Requirement「配置集中加载且缺失必填项时启动失败」的第一个场景：
缺少 MYSQL_HOST 时必须失败，且错误信息中指出该变量名。
"""

import pytest

from app.core.config import (
    ENV_FILE,
    InvalidConfigurationError,
    MissingConfigurationError,
    load_settings,
)


def test_env_file_locates_repo_root():
    """`.env` 必须定位到仓库根，而非 backend/（parents 层级错误的守卫）。"""
    assert ENV_FILE.name == ".env"
    assert (ENV_FILE.parent / ".gitignore").exists()


def test_missing_required_config_raises_with_variable_name(monkeypatch):
    monkeypatch.delenv("MYSQL_HOST", raising=False)

    with pytest.raises(MissingConfigurationError) as exc_info:
        load_settings(_env_file=None)

    assert "MYSQL_HOST" in str(exc_info.value)


def test_missing_config_is_logged_with_variable_name(monkeypatch, capsys):
    """spec MUST：缺失项必须同时出现在错误信息与日志中。"""
    monkeypatch.delenv("MYSQL_HOST", raising=False)

    with pytest.raises(MissingConfigurationError):
        load_settings(_env_file=None)

    assert "MYSQL_HOST" in capsys.readouterr().out


def test_invalid_value_raises_with_parsing_detail(isolated_env):
    """非 missing 类错误不得退化为空消息（任务 2.2 附带）。"""
    with pytest.raises(InvalidConfigurationError) as exc_info:
        isolated_env(REDIS_PORT="not-a-number")

    assert "REDIS_PORT" in str(exc_info.value)


def test_numeric_config_is_parsed_as_number(isolated_env):
    settings = isolated_env(REDIS_PORT="6380", HEALTH_CHECK_TIMEOUT_SEC="1.5")

    assert settings.redis_port == 6380
    assert settings.health_check_timeout_sec == 1.5


def test_optional_config_falls_back_to_defaults(isolated_env):
    settings = isolated_env()

    assert settings.redis_host == "127.0.0.1"
    assert settings.redis_db == 0
    assert settings.health_check_timeout_sec == 2.0
    assert settings.mysql_test_database == "ragagent_test"


def test_empty_password_is_treated_as_unset(isolated_env):
    """空串密码必须归一化为 None，避免以空密码发起 AUTH（任务 2.5）。"""
    settings = isolated_env(REDIS_PASSWORD="", MILVUS_TOKEN="", MYSQL_PASSWORD="")

    assert settings.redis_password is None
    assert settings.milvus_token is None
    assert settings.mysql_password is None

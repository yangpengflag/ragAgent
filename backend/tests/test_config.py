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


def test_short_secret_key_is_rejected(isolated_env):
    """认证 R1 前置：签名密钥长度不足时启动失败，且错误信息指出配置项名。"""
    with pytest.raises(InvalidConfigurationError) as exc_info:
        isolated_env(APP_SECRET_KEY="too-short")

    assert "APP_SECRET_KEY" in str(exc_info.value)


def test_secret_key_at_minimum_length_is_accepted(isolated_env):
    """边界：恰好达到下限必须被接受（避免把下限写偏）。"""
    settings = isolated_env(APP_SECRET_KEY="x" * 32)

    assert settings.app_secret_key == "x" * 32


def test_auth_defaults_match_documented_values(isolated_env):
    """认证相关配置的默认值必须与 design.md 的决策一致。"""
    settings = isolated_env()

    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_access_token_expire_min == 15
    assert settings.jwt_refresh_token_expire_days == 7
    assert settings.refresh_cookie_path == "/api/v1/auth"
    assert settings.refresh_cookie_secure is False
    assert settings.refresh_cookie_samesite == "lax"
    assert settings.rate_limit_login_max_failures == 5
    assert settings.rate_limit_login_window_min == 15
    assert settings.bootstrap_admin_username is None


def test_empty_bootstrap_password_is_treated_as_unset(isolated_env):
    """空串的引导密码必须归一化为 None，避免创建"空密码管理员"。"""
    settings = isolated_env(BOOTSTRAP_ADMIN_PASSWORD="")

    assert settings.bootstrap_admin_password is None

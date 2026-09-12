"""应用配置。

约定见 `design.md` D3：单一 Settings 对象、启动期 fail-fast、`.env` 路径由文件位置推导、
密码类空串归一化为未设置、敏感字段不出现在 repr 中。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# backend/app/core/config.py → parents: [0]=core [1]=app [2]=backend [3]=仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"


class ConfigurationError(Exception):
    """配置错误基类。"""


class MissingConfigurationError(ConfigurationError):
    """必需配置缺失。错误消息中列出缺失的环境变量名。"""


class InvalidConfigurationError(ConfigurationError):
    """配置存在但无法解析（如端口写成非数字）。"""


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- 应用
    app_env: str = "dev"
    app_debug: bool = True
    app_secret_key: str = Field(repr=False)
    app_port: int = 8000
    app_cors_origins: str = "http://localhost:5173"

    # ---------------------------------------------------------------- 数据库
    mysql_host: str
    mysql_port: int = 3306
    mysql_user: str
    mysql_password: str | None = Field(default=None, repr=False)
    mysql_database: str
    mysql_test_database: str = "ragagent_test"

    # ---------------------------------------------------------------- Redis
    redis_host: str = "127.0.0.1"
    redis_port: int = 6379
    redis_password: str | None = Field(default=None, repr=False)
    redis_db: int = 0

    # ---------------------------------------------------------------- Milvus
    milvus_uri: str = "http://localhost:19530"
    milvus_token: str | None = Field(default=None, repr=False)
    milvus_database: str = "ragagent"

    # ---------------------------------------------------------------- 日志与健康检查
    log_level: str = "INFO"
    health_check_timeout_sec: float = 2.0

    @field_validator("mysql_password", "redis_password", "milvus_token", mode="before")
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """密码/令牌类配置为空串或纯空白时归一化为 None（避免以空密码发起认证）。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value


class _Unset:
    """哨兵类型：区分「未传 _env_file」与「显式传 None（禁用 env 文件）」。"""


_UNSET = _Unset()


def load_settings(_env_file: object = _UNSET) -> Settings:
    """构造 Settings。

    `_env_file` 省略时使用模块级 `ENV_FILE`（可被测试替换）；显式传 `None` 则完全不读 env 文件。

    缺失必填项时记 error 日志并抛 MissingConfigurationError（列出变量名）；
    存在但无法解析时抛 InvalidConfigurationError（不内嵌原始异常文本，避免带出 input 值）。
    """
    env_file = ENV_FILE if isinstance(_env_file, _Unset) else _env_file
    try:
        # pydantic-settings 通过 __init__ 注入 _env_file，mypy 无法识别该签名
        return Settings(_env_file=env_file)  # type: ignore[call-arg]
    except ValidationError as exc:
        errors = exc.errors()
        missing = sorted(
            {str(err["loc"][0]).upper() for err in errors if err["type"] == "missing"}
        )
        if missing:
            # 延迟导入：避免 config → logging 的模块级循环依赖
            from app.core.logging import get_logger

            get_logger().error("startup configuration missing", missing=missing)
            raise MissingConfigurationError(f"缺少必需配置项: {', '.join(missing)}") from exc
        invalid = sorted({str(err["loc"][0]).upper() for err in errors})
        details = "; ".join(
            f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in errors
        )
        raise InvalidConfigurationError(
            f"配置项校验失败: {', '.join(invalid)}; 详情: {details}"
        ) from exc


@lru_cache
def get_settings() -> Settings:
    """进程内共享的 Settings 实例。"""
    return load_settings()

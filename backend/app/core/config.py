"""应用配置。

约定见 `design.md` D3：单一 Settings 对象、启动期 fail-fast、`.env` 路径由文件位置推导、
密码类空串归一化为未设置、敏感字段不出现在 repr 中。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.exceptions import InvalidConfigurationError, MissingConfigurationError

if TYPE_CHECKING:
    from app.domain.chunking.models import ChunkConfig

# backend/app/core/config.py → parents: [0]=core [1]=app [2]=backend [3]=仓库根
REPO_ROOT = Path(__file__).resolve().parents[3]
ENV_FILE = REPO_ROOT / ".env"

# 签名密钥最小长度（HS256 下低于此长度的密钥存在被暴力枚举的现实风险）
MIN_SECRET_KEY_LENGTH = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ---------------------------------------------------------------- 应用
    app_env: str = "dev"
    # 默认 False：debug 模式会绕过异常处理器并泄漏堆栈，不应成为默认值
    app_debug: bool = False
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
    milvus_collection: str = "kb_chunks"
    # KB 级隔离的 partition key 字段名（与入库 schema 对齐，design D4）
    milvus_partition_key: str = "kb_id"
    # 单次 Milvus 建表 / 删除操作超时（秒）；显式超时，禁无限等待（backend-conventions）
    milvus_timeout_sec: float = 10.0

    # ---------------------------------------------------------------- DashScope（OpenAI 兼容模式）
    # 与 Milvus/Redis 不同：key 缺失不阻止应用启动（RAG 链路之外的端点照常服务），
    # 由 integrations 工厂在构造模型客户端时报出缺失变量名（lazy fail-fast）。
    dashscope_api_key: str | None = Field(default=None, repr=False)
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_chat_model: str = "qwen-plus"
    dashscope_embed_model: str = "qwen3.7-text-embedding"
    dashscope_embed_dim: int = 1024
    dashscope_embed_batch_size: int = 20
    dashscope_rerank_model: str | None = None

    # ---------------------------------------------------------------- 日志与健康检查
    log_level: str = "INFO"
    health_check_timeout_sec: float = 2.0

    # ---------------------------------------------------------------- 认证与令牌
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_min: int = 15
    jwt_refresh_token_expire_days: int = 7
    # 刷新令牌只走 HttpOnly Cookie；Path 必须同时覆盖刷新与登出端点，
    # 收窄到刷新端点自身会导致登出请求收不到 Cookie、无法撤销（见 design D3）。
    refresh_cookie_name: str = "refresh_token"
    refresh_cookie_path: str = "/api/v1/auth"
    # 本地 http 环境为 False；生产（https）必须置 True
    refresh_cookie_secure: bool = False
    refresh_cookie_samesite: str = "lax"

    # ---------------------------------------------------------------- 文档上传 / 存储 / 解析
    # env 名与 .env.example 既有约定对齐（STORAGE_LOCAL_ROOT / MINERU_API_* / MINERU_POLL_*）
    storage_local_root: str = Field(default="storage", validation_alias="STORAGE_LOCAL_ROOT")
    # 上传大小上限（MB）
    upload_max_size_mb: int = 50
    # MinerU 云 API v4；token 可留空（lazy fail-fast，与 DashScope 同款语义）
    mineru_api_base: str = Field(default="https://mineru.net", validation_alias="MINERU_API_BASE")
    mineru_api_token: str | None = Field(
        default=None, repr=False, validation_alias="MINERU_API_TOKEN"
    )
    mineru_model_version: str = "vlm"
    mineru_http_timeout_sec: float = Field(
        default=60.0, validation_alias="MINERU_HTTP_TIMEOUT_SEC"
    )
    mineru_poll_interval_sec: float = Field(
        default=5.0, validation_alias="MINERU_POLL_INTERVAL_SEC"
    )
    mineru_poll_timeout_sec: float = Field(
        default=900.0, validation_alias="MINERU_POLL_TIMEOUT_SEC"
    )

    # ---------------------------------------------------------------- Celery（长任务 broker）
    celery_broker_url: str = "redis://127.0.0.1:6379/1"

    # ---------------------------------------------------------------- 切分阈值（可配，不硬编码）
    chunk_target_tokens_text: int = 512
    chunk_max_tokens_text: int = 768
    chunk_target_tokens_list: int = 512
    chunk_max_tokens_list: int = 768
    chunk_target_tokens_table: int = 1024
    chunk_max_tokens_table: int = 2048
    chunk_target_tokens_code: int = 768
    chunk_max_tokens_code: int = 1024
    chunk_target_tokens_equation: int = 256
    chunk_max_tokens_equation: int = 512
    # D6：overlap 默认关（0 直通，不为开关铺全参数面）
    chunk_overlap_ratio: float = 0.0

    # 登录失败限流（键 = 小写用户名 + 对端地址）
    rate_limit_login_max_failures: int = 5
    rate_limit_login_window_min: int = 15

    # 初始管理员引导：仅当账号表为空时生效
    bootstrap_admin_username: str | None = None
    bootstrap_admin_password: str | None = Field(default=None, repr=False)

    # ---------------------------------------------------------------- 观测（LangSmith，默认关闭）
    # 直接采用 SDK 原生 LANGSMITH_* 变量名作为单一来源（design D5），
    # 不建 OBS_* 翻译层；生效判定见 obs_tracing_effective。
    obs_tracing: bool = Field(default=False, validation_alias="LANGSMITH_TRACING")
    obs_endpoint: str | None = Field(
        default=None, validation_alias="LANGSMITH_ENDPOINT"
    )
    obs_api_key: str | None = Field(
        default=None, repr=False, validation_alias="LANGSMITH_API_KEY"
    )
    obs_project: str = Field(default="ragagent", validation_alias="LANGSMITH_PROJECT")
    # 可选：收敛后台上报的重试/连接窗口（spike R2）
    obs_timeout_ms: int | None = Field(default=None, validation_alias="LANGSMITH_TIMEOUT_MS")

    @field_validator(
        "mysql_password",
        "redis_password",
        "milvus_token",
        "bootstrap_admin_password",
        "obs_endpoint",
        "obs_api_key",
        "dashscope_api_key",
        "dashscope_rerank_model",
        "mineru_api_token",
        mode="before",
    )
    @classmethod
    def _blank_to_none(cls, value: object) -> object:
        """密码/令牌类配置为空串或纯空白时归一化为 None（避免以空密码发起认证）。"""
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("app_secret_key")
    @classmethod
    def _secret_key_must_be_strong(cls, value: str) -> str:
        """签名密钥是会话安全的根：过短一律拒绝启动（spec：启动期 fail-fast）。

        不在这里做"仅警告"处理——弱密钥意味着任何人都能伪造访问令牌。
        """
        if len(value) < MIN_SECRET_KEY_LENGTH:
            raise ValueError(f"长度必须 ≥ {MIN_SECRET_KEY_LENGTH} 个字符")
        return value

    @property
    def obs_tracing_effective(self) -> bool:
        """观测生效判定：开关打开且上报目标与凭证齐全（spec：未配置目标 = 视为关闭）。"""
        return bool(
            self.obs_tracing and self.obs_endpoint and self.obs_api_key
        )


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


def chunk_config_from_settings(settings: Settings) -> ChunkConfig:
    """把 Settings 的 `CHUNK_*` 组装为 `domain/chunking` 的 `ChunkConfig`。

    design D5：阈值可配、不硬编码；`domain` 层不 import Settings，由本函数承担装配。
    """
    from app.domain.chunking.models import ChunkConfig

    return ChunkConfig(
        text_target_tokens=settings.chunk_target_tokens_text,
        text_max_tokens=settings.chunk_max_tokens_text,
        list_target_tokens=settings.chunk_target_tokens_list,
        list_max_tokens=settings.chunk_max_tokens_list,
        table_target_tokens=settings.chunk_target_tokens_table,
        table_max_tokens=settings.chunk_max_tokens_table,
        code_target_tokens=settings.chunk_target_tokens_code,
        code_max_tokens=settings.chunk_max_tokens_code,
        equation_target_tokens=settings.chunk_target_tokens_equation,
        equation_max_tokens=settings.chunk_max_tokens_equation,
        overlap_ratio=settings.chunk_overlap_ratio,
    )

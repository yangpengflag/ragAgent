"""FastAPI 应用装配与入口。

配置在工厂首行加载：缺失必填项时立即失败，不进入可服务状态（design D3）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings, load_settings
from app.core.db import get_engine
from app.core.error_handlers import register_exception_handlers
from app.core.exceptions import InvalidConfigurationError
from app.core.logging import configure_logging, get_logger
from app.core.request_id import REQUEST_ID_HEADER, RequestIdMiddleware

_logger = get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """启动/关闭时释放资源与记录日志。"""
    logger = _logger
    logger.info("application starting")
    _bootstrap_initial_admin()
    try:
        yield
    finally:
        # 仅在引擎已被创建时释放，避免无谓建连
        if get_engine.cache_info().currsize:
            get_engine().dispose()
        logger.info("application stopped")


def _bootstrap_initial_admin() -> None:
    """启动阶段引导初始管理员（design D10，tasks 5.17/5.18）。

    全部分支判断与并发处理都在 `bootstrap_admin` 内；
    引导失败（除已存在）不应阻断启动——DB 故障时健康检查会如实暴露。
    """
    from sqlalchemy import text

    from app.core.db import get_session_factory
    from app.core.security import PasswordPolicyError
    from app.services.auth_service import bootstrap_admin

    settings = load_settings()
    session = get_session_factory()()
    try:
        # 探活：DB 不可达时跳过引导而非崩溃（首次迁移可能尚未执行）
        session.execute(text("SELECT 1"))
    except Exception as exc:
        _logger.warning(
            "bootstrap admin skipped: database unreachable", error=type(exc).__name__
        )
        return
    finally:
        session.close()
    bootstrap_session = get_session_factory()()
    try:
        bootstrap_admin(
            bootstrap_session,
            username=settings.bootstrap_admin_username,
            password=settings.bootstrap_admin_password,
        )
    except PasswordPolicyError:
        # 引导密码不符合强度策略：告警并跳过，不阻断启动（与上方"不阻断"注释一致）
        _logger.warning(
            "bootstrap admin skipped: configured password violates strength policy"
        )
    finally:
        bootstrap_session.close()


def _cors_origins(settings: Settings) -> list[str]:
    origins = [
        origin.strip()
        for origin in settings.app_cors_origins.split(",")
        if origin.strip()
    ]
    # allow_credentials=True 与通配源不能同时生效（浏览器会拒绝），启动期直接拒绝误配
    if "*" in origins:
        raise InvalidConfigurationError(
            "APP_CORS_ORIGINS 不允许配置为 *（与 allow_credentials 冲突），请列出明确来源"
        )
    return origins


def create_app() -> FastAPI:
    """创建并返回一个 FastAPI 应用实例。"""
    settings: Settings = load_settings()  # 启动期 fail-fast
    configure_logging(settings.log_level)

    # 注意：不传 debug=app_debug。Starlette 在 debug=True 时会用 traceback 响应
    # 绕过自定义异常处理器，既泄漏堆栈也丢失 X-Request-ID（违反统一错误信封约定）。
    app = FastAPI(
        title="RAG Agent API",
        description="企业知识库与智能问答系统 - 后端服务",
        version="0.1.0",
        lifespan=lifespan,
    )

    app.add_middleware(RequestIdMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(settings),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[REQUEST_ID_HEADER],
    )

    register_exception_handlers(app)
    # 只挂载 v1 聚合器：新增能力在 app/api/v1/router.py 登记，不必改本文件
    app.include_router(api_router)
    return app


def create_server_config() -> tuple[str, int]:
    """服务器监听地址与端口（端口取自配置，禁止硬编码）。"""
    settings: Settings = load_settings()
    return "0.0.0.0", settings.app_port


def main() -> None:
    """本地/容器启动入口：`uv run python -m app.main`。"""
    import uvicorn

    host, port = create_server_config()
    uvicorn.run(create_app(), host=host, port=port)


if __name__ == "__main__":
    main()

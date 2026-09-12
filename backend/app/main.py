"""FastAPI 应用工厂。

配置在工厂首行加载：缺失必填项时立即失败，不进入可服务状态（design D3）。
本模块只提供最小可测的装配入口；lifespan 资源管理、中间件、异常处理器、
路由注册与 CORS 由任务 7.1 补齐。
"""

from fastapi import FastAPI

from app.core.config import Settings, load_settings
from app.core.logging import configure_logging
from app.core.request_id import RequestIdMiddleware


def create_app() -> FastAPI:
    """创建并返回一个 FastAPI 应用实例。"""
    settings: Settings = load_settings()  # 启动期 fail-fast
    configure_logging(settings.log_level)

    app = FastAPI(
        title="RAG Agent API",
        description="企业知识库与智能问答系统 - 后端服务",
        version="0.1.0",
        debug=settings.app_debug,
    )
    app.add_middleware(RequestIdMiddleware)
    return app

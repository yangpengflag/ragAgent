"""数据库引擎与会话。

引擎与会话工厂惰性创建并缓存：导入本模块不产生连接，便于测试与启动期解耦。
"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import URL, Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_database_url(*, test: bool = False) -> URL:
    """由配置拼装数据库 URL（使用 URL.create 以正确转义密码）。"""
    settings = get_settings()
    return URL.create(
        "mysql+pymysql",
        username=settings.mysql_user,
        password=settings.mysql_password or "",
        host=settings.mysql_host,
        port=settings.mysql_port,
        database=settings.mysql_test_database if test else settings.mysql_database,
    )


@lru_cache
def get_engine() -> Engine:
    """进程内共享的引擎（带连接预检）。"""
    return create_engine(build_database_url(), pool_pre_ping=True, future=True)


@lru_cache
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False, class_=Session)


def get_db() -> Iterator[Session]:
    """FastAPI 依赖：每请求一个会话，请求结束（含异常）必关闭。"""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()

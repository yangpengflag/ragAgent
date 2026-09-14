"""v1 路由聚合器。

`main.py` 只挂载这一个聚合器；后续每个能力（auth / users / knowledge-base /
documents / chat / search）只需在此登记，避免应用装配文件变成路由清单。
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.health import router as health_router
from app.api.v1.knowledge_bases import router as knowledge_bases_router
from app.api.v1.users import router as users_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(knowledge_bases_router)

__all__ = ["api_router"]

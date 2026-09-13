"""健康检查端点。"""

from __future__ import annotations

from collections.abc import Sequence

from fastapi import APIRouter, Depends, Request

from app.core.request_context import request_id_var
from app.domain.health import HealthProbe, collect_health
from app.integrations.health_probes import build_probes
from app.schemas.health import ComponentHealth, HealthResponse

router = APIRouter(prefix="/api/v1", tags=["health"])


def get_probes() -> Sequence[HealthProbe]:
    """探针提供者；测试可通过 dependency_overrides 替换为替身。"""
    return build_probes()


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="依赖组件健康检查",
    description="报告 MySQL / Redis / Milvus 连通性；任一不可用时仍返回 200 并在 components 标注。",
)
async def health(
    request: Request,
    probes: Sequence[HealthProbe] = Depends(get_probes),
) -> HealthResponse:
    report = collect_health(probes)
    request_id = getattr(request.state, "request_id", None) or request_id_var.get() or ""
    return HealthResponse(
        request_id=request_id,
        status=report.status,
        components={
            item.name: ComponentHealth(status=item.status, error=item.error)
            for item in report.components
        },
    )

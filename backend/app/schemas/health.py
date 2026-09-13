"""健康检查响应模型。

契约见 `openspec/changes/project-scaffold/design.md` D8。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ComponentHealth(BaseModel):
    status: str = Field(description="组件状态：ok / down")
    error: str | None = Field(default=None, description="不可用原因；可用时为 null")


class HealthResponse(BaseModel):
    request_id: str = Field(description="请求追踪 ID")
    status: str = Field(description="整体状态：ok / degraded")
    components: dict[str, ComponentHealth] = Field(description="各依赖组件明细")

"""成功响应统一携带 `request_id`（auth-and-users 任务 2.4/2.5）。

`project-scaffold` R2 要求 `request_id` 出现在日志、响应头与响应体中（成功与错误
均包含）。此前只有 `/health` 手工带上该字段，本组用例把它变成**由基类强制**的契约。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.request_id import REQUEST_ID_HEADER
from app.main import create_app
from app.schemas.base import ApiResponse
from app.schemas.health import HealthResponse


def test_health_response_shape_is_unchanged():
    """收敛到统一基类后，`/health` 的对外形状必须保持不变。"""
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert set(response.json()) == {"request_id", "status", "components"}


def test_health_request_id_matches_header_and_body():
    """响应体与响应头中的 `request_id` 必须一致（同一请求同一标识）。"""
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.json()["request_id"] == response.headers[REQUEST_ID_HEADER]
    assert response.json()["request_id"]


def test_response_base_requires_request_id():
    """基类把 `request_id` 设为必填：漏传即在构造期失败，而不是悄悄返回不合规响应。"""
    with pytest.raises(ValidationError):
        HealthResponse(status="ok", components={})  # type: ignore[call-arg]


def test_api_response_is_the_single_entry_point():
    """所有成功响应模型都应继承统一基类（新端点接入时的守卫）。"""
    assert issubclass(HealthResponse, ApiResponse)

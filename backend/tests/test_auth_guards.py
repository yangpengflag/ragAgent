"""认证改造的守护测试（auth-and-users §1）。

本文件中的断言在改造前后都必须成立，作用是防止"引入鉴权"与"调整 CORS"时误伤既有行为：

- 健康检查必须保持**匿名可访问**（鉴权不得误伤既有接口）
- 跨源凭据支持必须保持开启、且不得回退为通配符来源——一旦回退，
  浏览器会丢弃登录响应里的 `Set-Cookie`，表现为"登录后立刻掉线"，很难定位
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app


def test_health_is_accessible_without_any_token():
    """任务 1.5：未携带 Authorization 时 `/health` 仍须可访问。"""
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert "authorization" not in {
        key.lower() for key in response.request.headers
    }


def test_cross_origin_request_is_allowed_to_carry_credentials():
    """任务 1.6：白名单来源的跨源请求必须允许携带凭据，并回显具体来源。"""
    origin = load_settings().app_cors_origins.split(",")[0].strip()
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-credentials") == "true"
    assert response.headers.get("access-control-allow-origin") == origin


def test_unknown_origin_is_not_echoed():
    """任务 1.6：非白名单来源不得被回显，浏览器侧因此无法携带凭据访问。"""
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"Origin": "http://evil.example"})

    assert "access-control-allow-origin" not in response.headers

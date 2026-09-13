"""端到端冒烟（任务 7.3）。

使用**完整装配 + 真实探针**：环境可用时三组件为 ok，不可用时为 degraded，
两种情况下端点都必须返回 200 —— 因此本用例不依赖本机中间件是否运行（spec R8）。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.core.exceptions import InvalidConfigurationError
from app.core.request_id import REQUEST_ID_HEADER
from app.main import create_app, create_server_config


def test_health_endpoint_smoke():
    client = TestClient(create_app())

    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert set(body["components"]) == {"mysql", "redis", "milvus"}
    assert body["status"] in {"ok", "degraded"}
    assert body["request_id"]


def test_error_envelope_applies_to_unknown_route():
    client = TestClient(create_app())

    response = client.get("/api/v1/definitely-not-here")

    assert response.status_code == 404
    assert response.json()["error_code"] == "not_found"


def test_cors_allows_configured_origin():
    """期望值取自配置，避免依赖本机 .env 的具体取值。"""
    origin = load_settings().app_cors_origins.split(",")[0].strip()
    client = TestClient(create_app())

    response = client.get("/api/v1/health", headers={"Origin": origin})

    assert response.headers.get("access-control-allow-origin") == origin
    assert REQUEST_ID_HEADER in response.headers.get("access-control-expose-headers", "")


def test_cors_rejects_wildcard_origin(isolated_env):
    isolated_env(APP_CORS_ORIGINS="*")

    with pytest.raises(InvalidConfigurationError):
        create_app()


def test_server_port_comes_from_settings(isolated_env):
    isolated_env(APP_PORT="9001")

    host, port = create_server_config()

    assert port == 9001
    assert host

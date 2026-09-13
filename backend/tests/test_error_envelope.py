"""统一错误信封红灯（任务 4.1 / 4.3 / 4.5 / 4.8）。

覆盖 spec Requirement「错误响应使用统一信封」的三个场景，
以及异常路径下 X-Request-ID 响应头不得丢失（任务 4.8）。

测试路由只在测试内挂载，避免污染生产应用。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from fastapi import FastAPI, Query
from fastapi.testclient import TestClient

from app.core.exceptions import NotFoundError
from app.main import create_app


@pytest.fixture
def build_client() -> Callable[..., TestClient]:
    """返回一个工厂：在 create_app() 基础上挂载测试路由。"""

    def _build(path: str, handler: Callable[..., Any]) -> TestClient:
        app: FastAPI = create_app()
        app.add_api_route(path, handler, methods=["GET"])
        return TestClient(app, raise_server_exceptions=False)

    return _build


def test_not_found_returns_unified_envelope(build_client):
    def raise_not_found() -> None:
        raise NotFoundError("knowledge base does not exist")

    client = build_client("/test/not-found", raise_not_found)
    response = client.get("/test/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["error_code"] == "not_found"
    assert body["message"] == "knowledge base does not exist"
    assert body["request_id"]


def test_validation_error_returns_field_details(build_client):
    def needs_query(limit: int = Query(..., ge=1)) -> dict[str, int]:
        return {"limit": limit}

    client = build_client("/test/validated", needs_query)
    response = client.get("/test/validated", params={"limit": 0})

    assert response.status_code == 422
    body = response.json()
    assert body["error_code"] == "validation_error"
    assert body["request_id"]
    assert "limit" in body["details"]


def test_unhandled_exception_returns_internal_error_without_stack(build_client, capsys):
    def boom() -> None:
        raise RuntimeError("secret internal detail")

    client = build_client("/test/boom", boom)
    response = client.get("/test/boom")

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert "Traceback" not in response.text
    assert "secret internal detail" not in body["message"]

    # 堆栈只应出现在日志中
    assert "Traceback" in capsys.readouterr().out


def test_error_response_carries_request_id_header(build_client):
    """任务 4.8：异常路径同样必须带 X-Request-ID 响应头。"""

    def boom() -> None:
        raise RuntimeError("boom")

    client = build_client("/test/boom-header", boom)
    response = client.get("/test/boom-header", headers={"X-Request-ID": "rid-err"})

    assert response.status_code == 500
    assert response.headers["X-Request-ID"] == "rid-err"
    assert response.json()["request_id"] == "rid-err"

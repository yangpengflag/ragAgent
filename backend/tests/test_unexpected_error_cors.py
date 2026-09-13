"""§7.7 红灯：未处理异常的 500 响应必须带统一信封与 CORS 头。

residual-risks 第 3 条：未处理异常由最外层 ServerErrorMiddleware 产出，
绕过 CORSMiddleware，浏览器读不到 500 的响应体。修复方式：加一层
"意外异常兜底"中间件（位于 CORS 之外），把 500 变成普通响应交回
CORS 中间件补头，浏览器侧即可统一错误兜底。
"""

from __future__ import annotations

from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.core.config import load_settings
from app.main import create_app


def test_unhandled_exception_returns_envelope_with_cors_headers() -> None:
    app = create_app()
    probe = APIRouter()

    @probe.get("/api/v1/_probe/boom")
    def boom() -> None:
        raise RuntimeError("boom for test")

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    origin = load_settings().app_cors_origins.split(",")[0].strip()
    response = client.get("/api/v1/_probe/boom", headers={"Origin": origin})

    assert response.status_code == 500
    body = response.json()
    assert body["error_code"] == "internal_error"
    assert body["message"] == "Internal server error"
    assert body["request_id"]
    # 关键：500 也要带 CORS 头，浏览器侧才能读到统一错误信封
    assert response.headers.get("access-control-allow-origin") == origin
    assert "boom for test" not in response.text  # 不泄漏内部信息


def test_unhandled_exception_without_origin_has_no_cors_header() -> None:
    app = create_app()
    probe = APIRouter()

    @probe.get("/api/v1/_probe/boom")
    def boom() -> None:
        raise RuntimeError("boom for test")

    app.include_router(probe)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.get("/api/v1/_probe/boom")
    assert response.status_code == 500
    assert "access-control-allow-origin" not in response.headers

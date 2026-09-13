"""健康检查红灯（任务 6.0 / 6.2）。

覆盖 spec Requirement「健康检查端点报告各依赖组件状态」：
探针可注入（编排层只依赖接口）、三种状态、依赖不可用时仍返回 200。
同时补齐 request_id **响应体**字段（spec R2 的延后项）。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from app.api.v1.health import get_probes
from app.main import create_app


@pytest.fixture
def client_factory() -> Callable[[list], TestClient]:
    """构造注入了指定探针的 TestClient。"""

    def _build(probes: list) -> TestClient:
        app = create_app()
        app.dependency_overrides[get_probes] = lambda: probes
        return TestClient(app)

    return _build


def test_reports_ok_when_all_components_healthy(client_factory, healthy_probes):
    response = client_factory(healthy_probes).get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert {name: item["status"] for name, item in body["components"].items()} == {
        "mysql": "ok",
        "redis": "ok",
        "milvus": "ok",
    }
    assert all(item["error"] is None for item in body["components"].values())


def test_reports_degraded_when_one_component_down(client_factory, milvus_down_probes):
    response = client_factory(milvus_down_probes).get("/api/v1/health")

    assert response.status_code == 200, "依赖不可用时仍须返回 200"
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["milvus"]["status"] == "down"
    assert "unreachable" in body["components"]["milvus"]["error"]
    assert body["components"]["mysql"]["status"] == "ok"


def test_marks_component_down_on_probe_timeout(client_factory, hanging_probes):
    response = client_factory(hanging_probes).get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["components"]["milvus"]["status"] == "down"
    assert "Timeout" in body["components"]["milvus"]["error"]


def test_health_response_carries_request_id_in_body(client_factory, healthy_probes):
    """spec R2：request_id 必须出现在成功响应体中。"""
    response = client_factory(healthy_probes).get(
        "/api/v1/health", headers={"X-Request-ID": "rid-health"}
    )

    assert response.json()["request_id"] == "rid-health"
    assert response.headers["X-Request-ID"] == "rid-health"


def test_orchestration_only_depends_on_probe_interface(client_factory):
    """编排层不得自行构造真实客户端：注入空探针时应返回 ok 且无组件。"""

    class _OnlyInterface:
        name = "stub"

        def check(self):
            from app.domain.health import ComponentStatus

            return ComponentStatus(name=self.name, ok=True)

    body = client_factory([_OnlyInterface()]).get("/api/v1/health").json()

    assert body["status"] == "ok"
    assert list(body["components"]) == ["stub"]

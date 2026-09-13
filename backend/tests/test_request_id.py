"""request_id 红灯（任务 3.3 / 3.5）。

覆盖 spec Requirement「每个请求携带唯一 request_id」：
入站读取 X-Request-ID（大小写不敏感），缺失时生成，出站写入响应头，
且该请求产生的日志条目携带同一个值。
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


def test_generates_request_id_when_absent():
    client = TestClient(create_app())

    response = client.get("/openapi.json")

    assert response.headers.get("X-Request-ID")


def test_reuses_upstream_request_id():
    client = TestClient(create_app())

    response = client.get("/openapi.json", headers={"X-Request-ID": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


def test_request_id_header_is_case_insensitive():
    client = TestClient(create_app())

    response = client.get("/openapi.json", headers={"x-request-id": "abc-123"})

    assert response.headers["X-Request-ID"] == "abc-123"


@pytest.mark.parametrize(
    "malformed",
    [
        "bad id with spaces",  # 空格
        "a" * 129,  # 超长
        "id/with/slash",  # 白名单外字符
        "a\tb",  # 控制字符（\t；\r\n 会被 HTTP 层先拒）
    ],
)
def test_malformed_request_id_is_replaced(malformed):
    """非法上游值（空格 / 超长 / 白名单外字符）必须被丢弃并重新生成。"""
    client = TestClient(create_app())

    response = client.get("/openapi.json", headers={"X-Request-ID": malformed})

    regenerated = response.headers["X-Request-ID"]
    assert regenerated != malformed
    assert len(regenerated) <= 128


def test_log_entries_carry_request_id(capsys):
    """同一请求产生的日志条目必须携带该请求的 request_id（任务 3.5）。"""
    client = TestClient(create_app())

    response = client.get("/openapi.json", headers={"X-Request-ID": "rid-42"})
    request_id = response.headers["X-Request-ID"]

    lines = [line for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert lines, "请求处理过程中应产生日志输出"

    payloads = [json.loads(line) for line in lines]
    assert all(p.get("request_id") == request_id for p in payloads)

"""MinerU 云 API v4 客户端红灯（document-upload-and-parse 任务 2.3）。

用 `httpx.MockTransport` 拦截，覆盖：
- 提交 /file-urls/batch 拿到预签名上传 URL → PUT 上传 → 轮询 /file/batch 到 done
  → 下载结果 zip → 提取 *_content_list.json
- 提交期 HTTP 错误 → 内部 `UpstreamError`
- 轮询超上限 / 任务 failed → `UpstreamError`（不泄漏 httpx 异常）
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest

from app.core.exceptions import UpstreamError
from app.integrations.mineru import MineruClient


def _zip_with_content_list() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("demo_content_list.json", '{"blocks": [{"type": "text"}]}')
    return buf.getvalue()


def _client(handler, *, max_polls: int = 3) -> MineruClient:
    transport = httpx.MockTransport(handler)
    return MineruClient(
        base_url="https://mineru.test",
        token="t-123",
        transport=transport,
        max_polls=max_polls,
        poll_interval_sec=0,
    )


def test_parse_success_returns_content_list():
    zip_bytes = _zip_with_content_list()
    state = {"poll": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/v4/file-urls/batch":
            assert request.headers["Authorization"] == "Bearer t-123"
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {"batch_id": "B1", "file_urls": ["http://up/upload"]},
                },
            )
        if request.method == "PUT" and request.url.host == "up":
            assert request.content == b"%PDF-1.4"
            return httpx.Response(200)
        if request.method == "GET" and request.url.path == "/api/v4/extract-results/batch/B1":
            state["poll"] += 1
            if state["poll"] == 1:
                return httpx.Response(
                    200,
                    json={"code": 0, "data": {"extract_result": [{"state": "running"}]}},
                )
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "extract_result": [
                            {"state": "done", "full_zip_url": "http://cdn/r.zip"}
                        ]
                    },
                },
            )
        if request.method == "GET" and request.url.host == "cdn":
            return httpx.Response(200, content=zip_bytes)
        return httpx.Response(404)

    result = _client(handler).parse(filename="demo.pdf", data=b"%PDF-1.4")

    assert result.content_list == b'{"blocks": [{"type": "text"}]}'
    assert result.page_count is None


def test_submit_http_error_raises_upstream():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"code": -1, "msg": "bad gateway"})

    with pytest.raises(UpstreamError):
        _client(handler).parse(filename="a.pdf", data=b"x")


def test_poll_timeout_raises_upstream():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200, json={"code": 0, "data": {"batch_id": "B", "file_urls": ["http://up/u"]}}
            )
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(
            200, json={"code": 0, "data": {"extract_result": [{"state": "running"}]}}
        )

    with pytest.raises(UpstreamError):
        _client(handler, max_polls=2).parse(filename="a.pdf", data=b"x")


def test_task_failed_raises_upstream():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(
                200, json={"code": 0, "data": {"batch_id": "B", "file_urls": ["http://up/u"]}}
            )
        if request.method == "PUT":
            return httpx.Response(200)
        return httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "extract_result": [{"state": "failed", "err_msg": "格式不支持"}]
                },
            },
        )

    with pytest.raises(UpstreamError):
        _client(handler).parse(filename="a.pdf", data=b"x")
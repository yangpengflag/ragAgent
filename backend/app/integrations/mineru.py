"""MinerU 云 API v4 客户端（HTTP 直连，不装 MinerU SDK）。

对接 `mineru.net/api/v4` 精准解析 API（`model_version=vlm`），用于本地文件：

1. `POST /file-urls/batch` 携带 `{files, model_version}` 申请**预签名上传 URL**，
   返回 `batch_id` + `file_urls`
2. `PUT` 预签名 URL 写入文件字节（**不设 Content-Type**，与上游约定一致；上传后
   系统自动提交解析，无需再调用提交任务接口）
3. `GET /extract-results/batch/{batch_id}` 轮询批次至 `done` / `failed`
   （响应为 `data.extract_result[]` 数组，取首项状态与结果链接）
4. 下载 `full_zip_url` 结果包，解压提取 `*_content_list.json`

第三方网络/HTTP/解析失败一律包装为内部 `UpstreamError`（503），不泄漏 httpx 类型
（`backend-conventions.md` 外部集成铁律）。design D5。
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.exceptions import UpstreamError

# 相对路径（无前导斜杠）：经 `httpx.Client(base_url=.../api/v4)` 追加，
# 否则前导 `/` 会被 urljoin 重置到 host 根
_FILE_URLS_PATH = "file-urls/batch"
_BATCH_PATH = "extract-results/batch"
# 云 API 的版本前缀；`base_url` 传 API 根（scheme://host[:port]），v4 前缀在此拼
_API_PREFIX = "/api/v4"


@dataclass(frozen=True, slots=True)
class ParseResult:
    """一次解析的产物：`content_list.json` 的原始字节。

    `page_count` 一期不承诺（上游批量的页数字段存在性随结果形态变化），
    暂为 None，待切分 change 有真实消费方时再回填。
    """

    content_list: bytes
    page_count: int | None = None


class MineruClient:
    """MinerU 云 API v4 客户端。"""

    def __init__(
        self,
        *,
        base_url: str,
        token: str,
        model_version: str = "vlm",
        timeout_sec: float = 60.0,
        max_polls: int = 300,
        poll_interval_sec: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        # 归一化 API 根：兼容 `https://mineru.net` 与已含 `/api/v4` 的两种配置，
        # 避免后缀重复导致 404（base_path 已是 `/api/v4` 则不再追加）
        base = base_url.rstrip("/")
        if not base.endswith(_API_PREFIX):
            base += _API_PREFIX
        self._base = base
        self._token = token
        self._model_version = model_version
        self._max_polls = max_polls
        self._poll_interval_sec = poll_interval_sec
        # 上传的 PUT 不能带 Content-Type（上游约定），因此认证头只按需附加在
        # MinerU API 调用上，不设客户端级全局默认头
        self._client = httpx.Client(base_url=self._base, timeout=timeout_sec, transport=transport)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"}

    def _request_json(self, path: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.post(
                path, json=payload, headers=self._auth_headers()
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError("MinerU 任务提交失败") from exc
        body = response.json()
        if not isinstance(body, dict):
            raise UpstreamError("MinerU 返回格式异常")
        return body

    def parse(self, *, filename: str, data: bytes) -> ParseResult:
        """执行一次文档解析，返回 `content_list.json` 内容。"""
        batch_id, upload_url = self._apply_upload_url(filename)
        self._upload(upload_url, data)
        zip_bytes = self._wait_for_done(batch_id)
        return ParseResult(content_list=self._extract_content_list(zip_bytes))

    def _apply_upload_url(self, filename: str) -> tuple[str, str]:
        body = self._request_json(
            _FILE_URLS_PATH,
            payload={
                "files": [{"name": filename, "data_id": filename}],
                "model_version": self._model_version,
            },
        )
        if body.get("code") != 0:
            raise UpstreamError(f"MinerU 申请上传地址失败: {body.get('msg', 'unknown')}")
        data = body.get("data") or {}
        urls = data.get("file_urls") or []
        if not urls:
            raise UpstreamError("MinerU 未返回上传地址")
        return data["batch_id"], urls[0]

    def _upload(self, upload_url: str, data: bytes) -> None:
        try:
            response = self._client.put(upload_url, content=data)  # 不设 Content-Type
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise UpstreamError("MinerU 文件上传失败") from exc

    def _wait_for_done(self, batch_id: str) -> bytes:
        path = f"{_BATCH_PATH}/{batch_id}"
        for _ in range(self._max_polls):
            if self._poll_interval_sec:
                import time

                time.sleep(self._poll_interval_sec)
            try:
                response = self._client.get(path, headers=self._auth_headers())
                response.raise_for_status()
                body = response.json()
            except httpx.HTTPError as exc:
                raise UpstreamError("MinerU 任务查询失败") from exc
            if body.get("code") != 0:
                raise UpstreamError(f"MinerU 任务查询失败: {body.get('msg', 'unknown')}")
            results = (body.get("data") or {}).get("extract_result") or []
            if not results:
                continue
            result = results[0]
            state = result.get("state")
            if state == "done":
                return self._download_zip(result.get("full_zip_url"))
            if state == "failed":
                raise UpstreamError(
                    f"MinerU 解析失败: {result.get('err_msg', 'unknown')}"
                )
        raise UpstreamError("MinerU 解析超时")

    def _download_zip(self, full_zip_url: str | None) -> bytes:
        if not full_zip_url:
            raise UpstreamError("MinerU 未返回结果下载地址")
        try:
            response = self._client.get(full_zip_url)
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as exc:
            raise UpstreamError("MinerU 结果下载失败") from exc

    @staticmethod
    def _extract_content_list(zip_bytes: bytes) -> bytes:
        try:
            with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                name = next(n for n in zf.namelist() if n.endswith("_content_list.json"))
                return zf.read(name)
        except (zipfile.BadZipFile, StopIteration) as exc:
            raise UpstreamError("MinerU 结果包缺少 content_list.json") from exc
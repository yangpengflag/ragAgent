"""错误码映射红线（第 5 轮 P1-3）。

P2-E 的核心语义是「状态码与错误码必须一致，503 不得给 internal_error」，
必须有回归锁定，否则改动映射表不会被察觉。
映射目标见 `<harness>/rules/api-conventions.md` 的错误码表。
"""

from __future__ import annotations

import pytest

from app.core.error_handlers import _error_code_for_status
from app.core.exceptions import ErrorCode


@pytest.mark.parametrize(
    ("status_code", "expected"),
    [
        (400, ErrorCode.BAD_REQUEST),
        (401, ErrorCode.UNAUTHORIZED),
        (403, ErrorCode.ACCESS_DENIED),
        (404, ErrorCode.NOT_FOUND),
        (405, ErrorCode.METHOD_NOT_ALLOWED),
        (409, ErrorCode.CONFLICT),
        (413, ErrorCode.FILE_TOO_LARGE),
        (415, ErrorCode.UNSUPPORTED_FILE_TYPE),
        (422, ErrorCode.VALIDATION_ERROR),
        (429, ErrorCode.RATE_LIMITED),
        (503, ErrorCode.UPSTREAM_UNAVAILABLE),
    ],
)
def test_mapped_status_codes_follow_api_conventions(status_code, expected):
    assert _error_code_for_status(status_code) == expected


@pytest.mark.parametrize("status_code", [402, 418, 451])
def test_unmapped_client_errors_fall_back_to_bad_request(status_code):
    assert _error_code_for_status(status_code) == ErrorCode.BAD_REQUEST


@pytest.mark.parametrize("status_code", [500, 502, 504])
def test_unmapped_server_errors_fall_back_to_internal_error(status_code):
    assert _error_code_for_status(status_code) == ErrorCode.INTERNAL_ERROR


def test_upstream_unavailable_never_reported_as_internal_error():
    """上游熔断若被当成服务端 bug，会把排查方向带偏 —— 单独锁定这条。"""
    assert _error_code_for_status(503) != ErrorCode.INTERNAL_ERROR

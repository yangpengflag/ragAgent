"""敏感字段脱敏红灯（任务 3.7）。

覆盖 spec Requirement「日志结构化且不含敏感信息」的第二个场景。
"""

from __future__ import annotations

import json

from app.core.logging import get_logger

_MASKED = "***"


def test_password_like_fields_are_masked(capsys):
    logger = get_logger()
    logger.info("login attempt", password="p@ssw0rd", user="alice")

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["password"] == _MASKED
    assert payload["user"] == "alice"  # 非敏感字段不受影响


def test_nested_sensitive_fields_are_masked(capsys):
    """嵌套结构内的敏感字段同样必须脱敏，非敏感字段保留。"""
    logger = get_logger()
    logger.info(
        "upstream call",
        payload={"api_key": "sk-nested", "user": "alice"},
        items=[{"milvus_token": "tok-in-list"}],
    )

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["payload"]["api_key"] == _MASKED
    assert payload["payload"]["user"] == "alice"
    assert payload["items"][0]["milvus_token"] == _MASKED


def test_token_and_api_key_are_masked(capsys):
    logger = get_logger()
    logger.info(
        "upstream call", api_key="sk-abcdef", access_token="tok-123", milvus_token="t"
    )

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["api_key"] == _MASKED
    assert payload["access_token"] == _MASKED
    assert payload["milvus_token"] == _MASKED

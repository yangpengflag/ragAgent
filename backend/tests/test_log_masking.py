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


def test_camel_case_and_plural_keys_are_masked(capsys):
    """常见命名变体（camelCase / 复数 / private_key / credential）也须命中。"""
    logger = get_logger()
    logger.info(
        "variants",
        secretKey="s1",
        apiKey="k1",
        refreshToken="t1",
        passwords="p1",
        private_key="pk1",
        credentials="c1",
    )

    payload = json.loads(capsys.readouterr().out.strip())

    for key in (
        "secretKey",
        "apiKey",
        "refreshToken",
        "passwords",
        "private_key",
        "credentials",
    ):
        assert payload[key] == _MASKED, f"{key} 未被脱敏"


def test_non_credential_token_and_key_fields_are_preserved(capsys):
    """计数/额度类字段不得被误伤，否则会掩盖排障所需数值。"""
    logger = get_logger()
    logger.info(
        "counters",
        max_tokens=4096,
        target_tokens=512,
        token_count=10,
        partition_key="kb_id",
    )

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["max_tokens"] == 4096
    assert payload["target_tokens"] == 512
    assert payload["token_count"] == 10
    assert payload["partition_key"] == "kb_id"


def test_token_usage_metrics_are_preserved(capsys):
    """LLM 用量指标是排障刚需，不得因含 token 而被误伤。"""
    logger = get_logger()
    logger.info(
        "usage",
        input_tokens=1200,
        output_tokens=340,
        tokens_used=1540,
        usage_tokens=1540,
        tokens_remaining=8500,
    )

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["input_tokens"] == 1200
    assert payload["output_tokens"] == 340
    assert payload["tokens_used"] == 1540
    assert payload["usage_tokens"] == 1540
    assert payload["tokens_remaining"] == 8500


def test_dsn_without_scheme_is_scrubbed(capsys):
    """`user:pass@host` 这种不带 scheme 的拼串同样必须打码。"""
    logger = get_logger()
    logger.info("connect failed", detail="appuser:S3cr3t@db.internal:5432")

    payload = json.loads(capsys.readouterr().out.strip())

    assert "S3cr3t" not in payload["detail"]
    assert _MASKED in payload["detail"]


def test_dsn_credentials_are_scrubbed_in_string_values(capsys):
    """异常堆栈常内嵌连接串，字符串里的凭据必须兜底打码。"""
    logger = get_logger()
    logger.info(
        "dsn",
        empty_user="redis://:secret-pwd@host:6379/0",
        with_user="mysql://root:secret-pwd@host:3306/db",
        at_in_password="mysql://u:p@ss@host/db",
    )

    payload = json.loads(capsys.readouterr().out.strip())

    for key in ("empty_user", "with_user", "at_in_password"):
        assert "secret-pwd" not in payload[key], f"{key} 泄漏了口令"
        assert "p@ss" not in payload[key], f"{key} 泄漏了含 @ 的口令"
        assert _MASKED in payload[key]


def test_token_and_api_key_are_masked(capsys):
    logger = get_logger()
    logger.info(
        "upstream call", api_key="sk-abcdef", access_token="tok-123", milvus_token="t"
    )

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["api_key"] == _MASKED
    assert payload["access_token"] == _MASKED
    assert payload["milvus_token"] == _MASKED

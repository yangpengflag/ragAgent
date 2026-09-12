"""结构化日志红灯（任务 3.1）。

覆盖 spec Requirement「日志结构化且不含敏感信息」的第一个场景：
每条日志必须是可解析的 JSON，并包含时间戳、级别、消息字段。
"""

from __future__ import annotations

import json

from app.core.logging import get_logger


def test_log_output_is_json(capsys):
    logger = get_logger()
    logger.info("scaffold smoke")

    payload = json.loads(capsys.readouterr().out.strip())

    assert payload["event"] == "scaffold smoke"
    assert payload["level"] == "info"


def test_log_contains_timestamp(capsys):
    logger = get_logger()
    logger.info("with timestamp")

    payload = json.loads(capsys.readouterr().out.strip())

    assert "timestamp" in payload

"""结构化日志。

统一输出 JSON，自动携带 request_id（由 contextvar 注入），并对敏感字段递归脱敏。
"""

from __future__ import annotations

import logging
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import FilteringBoundLogger

from app.core.request_context import request_id_var

# 命中任一子串即视为敏感字段（对 key 做小写匹配）
SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "access_key",
    "authorization",
)
MASK = "***"


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in SENSITIVE_KEY_PARTS)


def _walk(value: Any, key: str = "") -> Any:
    """递归脱敏：命中敏感 key 直接掩码，否则下钻 dict / list。"""
    if _is_sensitive_key(key):
        return MASK
    if isinstance(value, MutableMapping):
        return {k: _walk(v, str(k)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_walk(item) for item in value]
    return value


def _mask_sensitive(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """把敏感字段的值替换为掩码，避免密钥/口令进入日志（含嵌套结构）。"""
    return cast("MutableMapping[str, Any]", _walk(event_dict))


def _add_request_id(
    logger: Any, method_name: str, event_dict: MutableMapping[str, Any]
) -> MutableMapping[str, Any]:
    """把当前请求的 request_id 注入日志字段（由 contextvar 传递）。"""
    request_id = request_id_var.get()
    if request_id:
        event_dict["request_id"] = request_id
    return event_dict


def _level_to_int(level: str) -> int:
    """把配置里的日志级别字符串转换为 logging 数值级别。"""
    value = logging.getLevelName(level.upper())
    return value if isinstance(value, int) else logging.INFO


def configure_logging(level: str = "INFO") -> None:
    """配置 structlog：注入 request_id → 加级别 → 加时间戳 → 脱敏 → JSON 输出。"""
    structlog.configure(
        processors=[
            _add_request_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _mask_sensitive,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(_level_to_int(level)),
        # 不绑定 sys.stdout：PrintLogger 在每次构造时解析当前 sys.stdout。
        # 若在此处传入，导入期的 stdout 会被固化，pytest capsys 将抓不到输出。
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> FilteringBoundLogger:
    """获取结构化 logger。"""
    return cast(FilteringBoundLogger, structlog.get_logger(name))


# 导入即完成默认配置，保证任意入口拿到的 logger 行为一致
configure_logging()

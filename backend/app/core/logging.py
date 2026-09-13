"""结构化日志。

统一输出 JSON，自动携带 request_id（由 contextvar 注入），并对敏感字段递归脱敏。
"""

from __future__ import annotations

import logging
import re
from collections.abc import MutableMapping
from typing import Any, cast

import structlog
from structlog.typing import FilteringBoundLogger

from app.core.request_context import request_id_var

# 词段匹配：先把 camelCase 拆成 snake_case，再按词段判断，
# 这样 secretKey / apiKey / refreshToken 这类命名也能命中。
_CAMEL_BOUNDARY = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_WORD_SPLIT = re.compile(r"[^a-z0-9]+")

# 出现即视为敏感的词段（含复数形）
_SENSITIVE_SEGMENTS = frozenset(
    {
        "password",
        "passwords",
        "passwd",
        "passphrase",
        "pwd",
        "secret",
        "secrets",
        "credential",
        "credentials",
        "authorization",
        "bearer",
    }
)
# `*_key` 仅在带这些前缀时视为敏感（避免误伤 partition_key / dedup_key）
_SENSITIVE_KEY_PREFIXES = frozenset(
    {"api", "access", "private", "secret", "signing", "encryption"}
)
# `token(s)` 在这些前缀/后缀下是计数或额度，不是凭据。
# ⚠️ 权衡：命中白名单的键**永不脱敏**——若有人把凭据放进 `prompt_tokens`
# 之类的字段，会直接落盘。这里选择"可观测性优先"，因为 LLM 用量指标极其常用。
_TOKEN_SAFE_PREFIXES = frozenset(
    {
        "max",
        "min",
        "target",
        "total",
        "prompt",
        "completion",
        "budget",
        "input",
        "output",
        "used",
        "usage",
        "remaining",
        "available",
        "reserved",
        "consumed",
    }
)
_TOKEN_SAFE_SUFFIXES = frozenset(
    {"count", "budget", "limit", "size", "length", "used", "usage", "remaining"}
)

# 字符串里的凭据型 URL。两条模式：
# ① 带 scheme：用户名可空（redis://:pwd@host），口令可含 `@`（在最后一个 @ 收口）
# ② 不带 scheme：`user:pass@host`（f-string 拼日志的常见形态）
_DSN_WITH_SCHEME = re.compile(r"://([^/\s@]*):[^/\s]*@")
_DSN_BARE = re.compile(r"(?<![\w/])([A-Za-z0-9_.\-]+):([^\s/@:]+)@([A-Za-z0-9_.\-]+)")
MASK = "***"


def _segments(key: str) -> list[str]:
    normalized = _CAMEL_BOUNDARY.sub("_", key)
    return [segment for segment in _WORD_SPLIT.split(normalized.lower()) if segment]


def _is_sensitive_key(key: str) -> bool:
    segments = _segments(key)
    if not segments:
        return False
    if any(segment in _SENSITIVE_SEGMENTS for segment in segments):
        return True
    for index, segment in enumerate(segments):
        previous = segments[index - 1] if index else ""
        following = segments[index + 1] if index + 1 < len(segments) else ""
        if segment in {"token", "tokens"}:
            if previous in _TOKEN_SAFE_PREFIXES or following in _TOKEN_SAFE_SUFFIXES:
                continue
            return True
        if segment == "key" and previous in _SENSITIVE_KEY_PREFIXES:
            return True
    return False


def _scrub_credentials(text: str) -> str:
    """兜底：字符串值中的连接串凭据打码（异常堆栈常内嵌 DSN）。"""
    scrubbed = _DSN_WITH_SCHEME.sub(r"://\1:***@", text)
    return _DSN_BARE.sub(r"\1:***@\3", scrubbed)


def _walk(value: Any, key: str = "") -> Any:
    """递归脱敏：命中敏感 key 直接掩码，字符串做凭据兜底，再下钻 dict / list。"""
    if _is_sensitive_key(key):
        return MASK
    if isinstance(value, str):
        return _scrub_credentials(value)
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

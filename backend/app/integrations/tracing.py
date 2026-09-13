"""观测（LangSmith）开关装配（tasks 6.1 / 6.2，design D5）。

配置即环境变量（`LANGSMITH_*` 是 SDK 与 Settings 的共同单一来源，design D5），
因此进程级装配的职责是 **fail-safe 校正**：开关打开但目标/凭证不全时，
强制把 `LANGSMITH_TRACING` 置 false——宁可不上报，不可误报出网。

请求级开关（spec：请求级 MUST 覆盖进程级默认值）走 langsmith 的
`tracing_context`，仅做「追加开启」：进程级关闭 + 调试会话标记 → 该请求开启；
进程级开启则全量开启。决策逻辑抽为纯函数 `resolve_request_tracing`。
"""

from __future__ import annotations

import os

from app.core.config import Settings


def apply_tracing_config(settings: Settings) -> None:
    """启动期装配：按生效判定校正进程环境的 tracing 开关（幂等）。

    spec「观测数据出网目标受配置约束」：未配置目标 = 视为关闭。
    """
    if settings.obs_tracing_effective:
        os.environ["LANGSMITH_TRACING"] = "true"
        if settings.obs_timeout_ms is not None:
            os.environ["LANGSMITH_TIMEOUT_MS"] = str(settings.obs_timeout_ms)
    else:
        os.environ["LANGSMITH_TRACING"] = "false"
        # 连目标与凭证一并清除：关闭态下任何代码路径都不可能外发（spec 6.4）
        os.environ.pop("LANGSMITH_ENDPOINT", None)
        os.environ.pop("LANGSMITH_API_KEY", None)
        os.environ.pop("LANGSMITH_TIMEOUT_MS", None)


def resolve_request_tracing(*, process_on: bool, request_flag: bool) -> bool:
    """单请求的最终 tracing 决策（纯函数）。

    进程级开启是基线；请求级标记只做追加开启（管理员调试会话语境），
    不提供「进程开、单请求关」的关闭路径——保持调试语义单向。
    """
    return process_on or request_flag

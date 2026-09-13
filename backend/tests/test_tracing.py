"""观测开关红灯（任务 6.1 / 6.2）。

覆盖 spec：
- 「观测追踪默认关闭且可多粒度开启」：进程级 fail-safe + 请求级覆盖
- 「观测数据出网目标受配置约束」：未配置目标时绝不启用上报
- fail-open 决策函数为纯函数
"""

import os

from app.integrations.tracing import apply_tracing_config, resolve_request_tracing

_LS_FULL = {
    "LANGSMITH_TRACING": "true",
    "LANGSMITH_ENDPOINT": "http://ls.internal",
    "LANGSMITH_API_KEY": "lsv2_pt_x",
}


# ---------------------------------------------------------------- 6.1 进程级装配


def test_off_by_default_no_tracing(isolated_env):
    """缺省：进程环境不得请求 SDK 启用上报（spec：关闭时零外发）。"""
    apply_tracing_config(isolated_env())

    assert os.environ.get("LANGSMITH_TRACING") != "true"


def test_enabled_with_full_config_keeps_tracing_on(isolated_env):
    apply_tracing_config(isolated_env(**_LS_FULL))

    assert os.environ.get("LANGSMITH_TRACING") == "true"


def test_enabled_but_incomplete_config_fails_safe(isolated_env):
    """开关 true 但 endpoint 缺失 → 强制关闭（fail-safe：宁不上报不误报）。"""
    apply_tracing_config(isolated_env(LANGSMITH_TRACING="true", LANGSMITH_API_KEY="lsv2_pt_x"))

    assert os.environ.get("LANGSMITH_TRACING") == "false"


def test_timeout_synced_from_settings(isolated_env):
    """配置了 TIMEOUT 时同步给 SDK（spike R2：收敛后台重试窗口）。"""
    apply_tracing_config(isolated_env(**_LS_FULL, LANGSMITH_TIMEOUT_MS="5000"))

    assert os.environ.get("LANGSMITH_TIMEOUT_MS") == "5000"


# ---------------------------------------------------------------- 6.2 请求级决策


def test_request_flag_cannot_disable_process_level():
    """进程级开启是基线：请求级标记只允许「追加开启」（调试语义单向）。"""
    assert resolve_request_tracing(process_on=True, request_flag=False) is True
    assert resolve_request_tracing(process_on=True, request_flag=True) is True


def test_request_flag_can_enable_when_process_off():
    """spec 请求级覆盖：进程关闭 + 调试会话标记 → 该请求开启。"""
    assert resolve_request_tracing(process_on=False, request_flag=True) is True
    assert resolve_request_tracing(process_on=False, request_flag=False) is False

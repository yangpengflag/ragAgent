"""观测 fail-open / 出网目标红灯（任务 6.3 / 6.4）。

6.3：观测开启但后端不可达（快速拒绝 + 网络黑洞）时，业务链路结果、
异常语义与观测关闭时一致（spec「上报失败不得影响业务链路」）。
6.4：观测关闭时不得启用任何上报通道（SDK 侧 tracing 状态为关闭）。
"""

import os
import time

import pytest

from app.integrations.tracing import apply_tracing_config

# 不可达端点：端口 9（discard，Windows 上瞬间拒绝连接）
REFUSED_ENDPOINT = "http://127.0.0.1:9"
# 网络黑洞：非路由私有地址，TCP 连接超时（不返回 RST）
BLACKHOLE_ENDPOINT = "http://10.255.255.1:8080"


@pytest.fixture(autouse=True)
def _restore_langsmith_env():
    """`apply_tracing_config` 直接写进程环境；用例结束后还原，避免污染后续测试。"""
    snapshot = {
        name: value
        for name, value in os.environ.items()
        if name.startswith("LANGSMITH_")
    }
    yield
    for name in list(os.environ):
        if name.startswith("LANGSMITH_") and name not in snapshot:
            del os.environ[name]
    os.environ.update(snapshot)


def _business_function(x: int) -> str:
    """模拟一次被 trace 的业务调用（不触碰任何外部模型）。"""
    return f"answer:{x}"


@pytest.mark.parametrize(
    "endpoint", [REFUSED_ENDPOINT, BLACKHOLE_ENDPOINT], ids=["refused", "blackhole"]
)
def test_tracing_failure_does_not_affect_business(endpoint, isolated_env):
    """spec：观测后端不可达/认证失效时，业务结果与响应语义不变。"""
    settings = isolated_env(
        LANGSMITH_TRACING="true",
        LANGSMITH_ENDPOINT=endpoint,
        LANGSMITH_API_KEY="lsv2_pt_fake",
        LANGSMITH_TIMEOUT_MS="1000",
    )
    apply_tracing_config(settings)

    from langsmith import traceable

    traced = traceable(_business_function)

    # 首帧之外的后台上报线程不得拖慢业务主链路（spike R2：主线程零阻塞）
    started = time.perf_counter()
    results = [traced(i) for i in range(5)]
    elapsed_ms = (time.perf_counter() - started) * 1000

    assert results == [f"answer:{i}" for i in range(5)]
    assert elapsed_ms < 2000


def test_no_egress_credentials_when_off(isolated_env):
    """6.4：关闭态下环境不残留目标/凭证——任何代码路径都无法外发。

    注：未直接断言 SDK 全局状态：langsmith 的 pytest 插件会在测试会话内
    全局开启 tracing，`utils.tracing_is_enabled()` 不反映应用配置。
    因此断言落在应用侧契约（开关 + 目标/凭证）上。
    """
    apply_tracing_config(isolated_env())

    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGSMITH_ENDPOINT") is None
    assert os.environ.get("LANGSMITH_API_KEY") is None


def test_no_egress_credentials_when_target_missing(isolated_env):
    """6.4：未配置上报目标 = 视为关闭（spec：出网目标受配置约束）。"""
    apply_tracing_config(isolated_env(LANGSMITH_TRACING="true", LANGSMITH_API_KEY="k"))

    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGSMITH_API_KEY") is None

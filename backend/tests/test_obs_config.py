"""观测配置红灯（任务 2.2）。

覆盖 spec「观测追踪默认关闭且可多粒度开启」的配置层行为：
缺省关闭、LANGSMITH_* 原生变量名为单一来源、空串归一化、
生效推导（未配置目标 = 视为关闭）。
"""


def test_tracing_defaults_to_off(isolated_env):
    """缺省启动：观测关闭，无 endpoint、无 key（spec：默认 MUST 关闭）。"""
    settings = isolated_env()

    assert settings.obs_tracing is False
    assert settings.obs_endpoint is None
    assert settings.obs_api_key is None
    assert settings.obs_tracing_effective is False


def test_langsmith_env_names_are_single_source(isolated_env):
    """直接采用 SDK 原生 LANGSMITH_* 变量名，不做 OBS_* 翻译层（design D5）。"""
    settings = isolated_env(
        LANGSMITH_TRACING="true",
        LANGSMITH_ENDPOINT="http://langsmith.internal:1984",
        LANGSMITH_API_KEY="lsv2_pt_test",
        LANGSMITH_PROJECT="ekb-prod",
    )

    assert settings.obs_tracing is True
    assert settings.obs_endpoint == "http://langsmith.internal:1984"
    assert settings.obs_api_key == "lsv2_pt_test"
    assert settings.obs_project == "ekb-prod"
    assert settings.obs_tracing_effective is True


def test_blank_endpoint_and_key_are_treated_as_unset(isolated_env):
    """空串 endpoint/key 归一化为未设置 → 生效推导为关闭（spec：未配置目标 = 关闭）。"""
    settings = isolated_env(
        LANGSMITH_TRACING="true",
        LANGSMITH_ENDPOINT="",
        LANGSMITH_API_KEY="",
    )

    assert settings.obs_endpoint is None
    assert settings.obs_api_key is None
    assert settings.obs_tracing_effective is False


def test_effective_tracing_requires_endpoint_and_key(isolated_env):
    """开关打开但目标/凭证不全 → 生效为关闭（fail-safe，宁可不上报不可误报）。"""
    enabled_only = isolated_env(LANGSMITH_TRACING="true")
    assert enabled_only.obs_tracing_effective is False

    no_key = isolated_env(
        LANGSMITH_TRACING="true", LANGSMITH_ENDPOINT="http://ls.internal"
    )
    assert no_key.obs_tracing_effective is False

    no_endpoint = isolated_env(LANGSMITH_TRACING="true", LANGSMITH_API_KEY="lsv2_pt_x")
    assert no_endpoint.obs_tracing_effective is False


def test_api_key_never_appears_in_repr(isolated_env):
    """凭证字段不进 repr（scaffold：敏感字段不出现在 repr 中）。"""
    settings = isolated_env(LANGSMITH_API_KEY="lsv2_pt_secret_value")

    assert "lsv2_pt_secret_value" not in repr(settings)


def test_timeout_is_numeric(isolated_env):
    """LANGSMITH_TIMEOUT_MS 为可选数值配置（spike R2：收敛后台重试窗口）。"""
    settings = isolated_env(LANGSMITH_TIMEOUT_MS="5000")

    assert settings.obs_timeout_ms == 5000

    defaults = isolated_env()
    assert defaults.obs_timeout_ms is None

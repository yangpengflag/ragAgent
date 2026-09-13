"""应用工厂的最小契约（任务 1.5 红灯）。

后续所有需要 HTTP 请求-响应周期的红绿灯统一使用 TestClient(create_app())。
"""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import config as config_module
from app.core.config import MissingConfigurationError


def test_create_app_returns_fastapi_instance():
    from app.main import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_openapi_schema_is_accessible():
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["info"]["title"]


def test_unknown_path_returns_404():
    from app.main import create_app

    client = TestClient(create_app())
    response = client.get("/definitely-not-a-route")

    assert response.status_code == 404


@pytest.fixture
def clean_langsmith_env(monkeypatch):
    """清掉观测相关环境变量，避免用例间相互污染。"""
    import os

    for name in list(os.environ):
        if name.startswith("LANGSMITH_"):
            monkeypatch.delenv(name, raising=False)
    yield


def test_create_app_enables_tracing_when_fully_configured(
    clean_langsmith_env, monkeypatch
):
    """配置齐全时，启动必须真正把开关打开（否则观测是死代码）。"""
    import os

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_ENDPOINT", "http://langsmith.internal")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")
    # timeout 的同步只发生在"启用"分支：用它证明启动确实跑了装配，而不是空过
    monkeypatch.setenv("LANGSMITH_TIMEOUT_MS", "3000")

    from app.main import create_app

    create_app()

    assert os.environ.get("LANGSMITH_TRACING") == "true"
    assert os.environ.get("LANGSMITH_TIMEOUT_MS") == "3000"


def test_create_app_disables_tracing_when_target_missing(
    clean_langsmith_env, monkeypatch
):
    """开关 true 但目标缺失：启动必须校正为关闭并清除凭证。"""
    import os

    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test")

    from app.main import create_app

    create_app()

    assert os.environ.get("LANGSMITH_TRACING") == "false"
    assert os.environ.get("LANGSMITH_API_KEY") is None


def test_create_app_leaves_tracing_off_by_default(clean_langsmith_env):
    """未配置观测时保持关闭，且不残留目标/凭证。"""
    import os

    from app.main import create_app

    create_app()

    assert os.environ.get("LANGSMITH_TRACING") != "true"
    assert os.environ.get("LANGSMITH_ENDPOINT") is None


def test_create_app_fails_when_required_config_missing(monkeypatch, tmp_path):
    """启动阶段缺少必需配置时必须失败，不进入可服务状态（任务 2.3）。"""
    monkeypatch.setattr(config_module, "ENV_FILE", tmp_path / "absent.env")
    monkeypatch.delenv("MYSQL_HOST", raising=False)

    from app.main import create_app

    with pytest.raises(MissingConfigurationError) as exc_info:
        create_app()

    assert "MYSQL_HOST" in str(exc_info.value)

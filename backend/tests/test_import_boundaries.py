"""集成边界守卫（任务 4.4）。

design D2 硬规则：LangChain / LangSmith 类型不得越过 integrations 边界
进入 domain/（纯函数层）或 services/（编排层）。用可执行的扫描测试固化，
替代仅靠 review 的口头约定。
"""

import re
from pathlib import Path

import pytest

# 后端 app/ 目录
APP_DIR = Path(__file__).resolve().parents[1] / "app"

# 被禁越界的框架模块前缀（后续引入新的集成 SDK 时在此追加）
BANNED_PREFIXES = (
    "langchain",
    "langsmith",
    "langgraph",
)

_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+([.\w]+)", re.MULTILINE)


def _py_files(layer: str) -> list[Path]:
    return sorted((APP_DIR / layer).rglob("*.py"))


def _banned_imports(path: Path) -> list[str]:
    source = path.read_text(encoding="utf-8")
    return [
        module
        for module in _IMPORT_RE.findall(source)
        if module.startswith(BANNED_PREFIXES)
    ]


@pytest.mark.parametrize("layer", ["domain", "services"])
def test_framework_types_stay_inside_integrations(layer: str):
    """domain/ 与 services/ 不得 import 任何 LangChain 生态模块。"""
    violations = {
        str(path.relative_to(APP_DIR)): _banned_imports(path)
        for path in _py_files(layer)
    }
    offenders = {path: mods for path, mods in violations.items() if mods}

    assert not offenders, (
        f"LangChain 生态模块越过 integrations 边界泄漏进 {layer}/：{offenders}"
        "（design D2：类型转换只在 integrations/ 内完成）"
    )

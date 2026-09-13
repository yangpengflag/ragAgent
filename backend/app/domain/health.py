"""健康检查领域模型与编排。

纯函数、零 I/O：只依赖 `HealthProbe` 协议，不构造任何真实客户端，
因此可用替身在单测中覆盖"全部可用 / 部分不可用 / 超时"三种状态。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

STATUS_OK = "ok"
STATUS_DOWN = "down"
OVERALL_OK = "ok"
OVERALL_DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ComponentStatus:
    """单个依赖组件的探测结果。"""

    name: str
    ok: bool
    error: str | None = None

    @property
    def status(self) -> str:
        return STATUS_OK if self.ok else STATUS_DOWN


class HealthProbe(Protocol):
    """探针契约：实现方自行保证超时，绝不允许无限阻塞。"""

    name: str

    def check(self) -> ComponentStatus:  # pragma: no cover - 协议声明
        ...


@dataclass(frozen=True, slots=True)
class HealthReport:
    """整体健康报告。"""

    components: tuple[ComponentStatus, ...]

    @property
    def status(self) -> str:
        return OVERALL_OK if all(item.ok for item in self.components) else OVERALL_DEGRADED


def collect_health(probes: Sequence[HealthProbe]) -> HealthReport:
    """依次执行各探针并汇总结果（不做判定之外的逻辑）。"""
    return HealthReport(components=tuple(probe.check() for probe in probes))

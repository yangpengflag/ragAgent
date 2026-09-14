"""嵌入文本类型标记的单一来源（`vector-index` spec：两侧取值 MUST 同源）。

DashScope 文本向量模型是**非对称检索**模型：入库内容与查询文本使用不同的类型标记。
兼容端点实测（2026-09-14）：未声明该标记时服务端按 `query` 处理，与官方原生文档所称的
默认值 `document` 相反，且不产生任何报错——因此两侧调用点 MUST 显式传入此处定义的常量，
不得依赖任何默认值。

本模块是零依赖纯常量，不违反 `domain/` 的零 I/O、零框架铁律；`integrations/` 可直接消费。
"""

from __future__ import annotations

from typing import Final

TEXT_TYPE_DOCUMENT: Final = "document"
"""入库内容（被检索的底库文本）。"""

TEXT_TYPE_QUERY: Final = "query"
"""查询文本（用户问题）。"""

__all__ = ["TEXT_TYPE_DOCUMENT", "TEXT_TYPE_QUERY"]

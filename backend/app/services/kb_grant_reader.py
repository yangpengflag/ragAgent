"""把授权集合查询适配成 `KbGrantReader` 端口。

`KbAccessResolver`（`rag-orchestration-langchain` 交付）面向端口编程，
此前只有内存替身可用；这里补上读业务库的真实实现，使检索阶段的权限过滤
第一次拿到**真数据**。

端口契约要求 `kb_ids_for_user(user_id: str) -> list[str]`：字符串进、字符串出
（Milvus 侧 `kb_id` 是字符串过滤字段），UUID 与字符串之间的转换收在本适配器里。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.services import kb_grant_service
from app.services.kb_access import KbAccessResolver


class SessionKbGrantReader:
    """按会话读取授权集合的 `KbGrantReader` 实现。"""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self._session_factory = session_factory

    def kb_ids_for_user(self, user_id: str) -> list[str]:
        """返回该用户的全部有效授权知识库标识。

        Raises:
            ValueError: `user_id` 不是合法 UUID——静默返回空集合会让"参数错误"
                表现成"无授权"，排查方向完全相反。
        """
        try:
            parsed = uuid.UUID(user_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"user_id 不是合法 UUID: {user_id!r}") from exc

        with self._session_factory() as session:
            return kb_grant_service.kb_ids_for_user(session, user_id=parsed)


def build_kb_access_resolver() -> KbAccessResolver:
    """装配一个读真实业务库的 `KbAccessResolver`（缓存保持默认关闭）。

    延迟导入会话工厂：一是避免导入本模块就建引擎，二是便于测试替换。
    """
    from app.core.db import get_session_factory  # 延迟导入：避免导入期建引擎

    return KbAccessResolver(SessionKbGrantReader(get_session_factory()))

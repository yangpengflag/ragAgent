"""知识库权限依赖。

路由层只做"能不能"，业务动作由服务层负责。两条规则（design K3）：

- 系统级 `ADMIN`：对全部知识库有管理权
- 库级 `KB_ADMIN`：仅对**其被授予 KB_ADMIN 且未软删**的库有管理权

撤销角色后管理权立即失效（每次请求现查授权表，不缓存）。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import Depends, Path

from app.api.deps import CurrentUserDep, SessionDep
from app.core.exceptions import AccessDeniedError
from app.models.user_kb_grant import KbRole
from app.services import kb_grant_service


def require_kb_manager(
    kb_id: Annotated[uuid.UUID, Path(description="知识库 ID")],
    session: SessionDep,
    account: CurrentUserDep,
) -> uuid.UUID:
    """校验当前账号可管理该知识库，返回该库 ID（供路由继续使用）。"""
    if account.system_role != "ADMIN":
        # can_access_kb 同时排除已软删库：软删后管理权一并失效
        role = kb_grant_service.role_of(session, user_id=account.id, kb_id=kb_id)
        if role != KbRole.KB_ADMIN or not kb_grant_service.can_access_kb(
            session, user_id=account.id, kb_id=kb_id
        ):
            raise AccessDeniedError("权限不足")
    return kb_id


KbManagerDep = Annotated[uuid.UUID, Depends(require_kb_manager)]

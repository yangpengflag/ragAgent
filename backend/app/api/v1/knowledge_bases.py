"""知识库路由（CRUD + 成员授权）。

路由层只做参数声明、依赖装配与响应组装；业务逻辑在 `kb_service` /
`kb_grant_service`。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.deps import SessionDep, current_request_id, require_role
from app.api.v1.dependency_kb import KbManagerDep
from app.core.exceptions import NotFoundError
from app.models.user_kb_grant import KbRole
from app.schemas.knowledge_base import (
    CreateKnowledgeBaseRequest,
    GrantMemberRequest,
    KnowledgeBaseResponse,
    ListKnowledgeBasesResponse,
    ListMembersResponse,
    MemberResponse,
    UpdateKnowledgeBaseRequest,
)
from app.services import kb_grant_service, kb_service

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["knowledge-bases"])

RequestIdDep = Annotated[str, Depends(current_request_id)]


def _kb_payload(kb: object, request_id: str) -> KnowledgeBaseResponse:
    return KnowledgeBaseResponse(
        request_id=request_id,
        id=str(kb.id),  # type: ignore[attr-defined]
        name=kb.name,  # type: ignore[attr-defined]
        description=kb.description,  # type: ignore[attr-defined]
        embedding_model=kb.embedding_model,  # type: ignore[attr-defined]
        embed_dim=kb.embed_dim,  # type: ignore[attr-defined]
    )


@router.post(
    "",
    status_code=201,
    response_model=KnowledgeBaseResponse,
    dependencies=[Depends(require_role("ADMIN"))],
)
def create_knowledge_base(
    payload: CreateKnowledgeBaseRequest,
    session: SessionDep,
    request_id: RequestIdDep,
) -> KnowledgeBaseResponse:
    kb = kb_service.create_kb(
        session,
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
        embed_dim=payload.embed_dim,
    )
    return _kb_payload(kb, request_id)


@router.get(
    "",
    response_model=ListKnowledgeBasesResponse,
    dependencies=[Depends(require_role("ADMIN"))],
)
def list_knowledge_bases(
    session: SessionDep, request_id: RequestIdDep
) -> ListKnowledgeBasesResponse:
    items = [
        {
            "id": str(kb.id),
            "name": kb.name,
            "description": kb.description,
            "embedding_model": kb.embedding_model,
            "embed_dim": kb.embed_dim,
        }
        for kb in kb_service.list_kbs(session)
    ]
    return ListKnowledgeBasesResponse(request_id=request_id, items=items)  # type: ignore[arg-type]


@router.get("/{kb_id}", response_model=KnowledgeBaseResponse)
def get_knowledge_base(
    kb_id: KbManagerDep, session: SessionDep, request_id: RequestIdDep
) -> KnowledgeBaseResponse:
    return _kb_payload(kb_service.get_kb(session, kb_id), request_id)


@router.patch("/{kb_id}", response_model=KnowledgeBaseResponse)
def update_knowledge_base(
    payload: UpdateKnowledgeBaseRequest,
    kb_id: KbManagerDep,
    session: SessionDep,
    request_id: RequestIdDep,
) -> KnowledgeBaseResponse:
    kb = kb_service.update_kb(
        session,
        kb_id,
        name=payload.name,
        description=payload.description,
        embedding_model=payload.embedding_model,
        embed_dim=payload.embed_dim,
    )
    return _kb_payload(kb, request_id)


@router.delete("/{kb_id}", status_code=200)
def delete_knowledge_base(
    kb_id: KbManagerDep, session: SessionDep, request_id: RequestIdDep
) -> dict[str, object]:
    kb_service.soft_delete_kb(session, kb_id)
    return {"request_id": request_id, "id": str(kb_id), "deleted": True}


# ---------------------------------------------------------------- 成员授权


@router.get("/{kb_id}/members", response_model=ListMembersResponse)
def list_members(
    kb_id: KbManagerDep, session: SessionDep, request_id: RequestIdDep
) -> ListMembersResponse:
    items = [
        {
            "user_id": str(user.id),
            "username": user.username,
            "display_name": user.display_name,
            "role": str(role),
        }
        for user, role in kb_grant_service.list_members(session, kb_id)
    ]
    return ListMembersResponse(request_id=request_id, items=items)  # type: ignore[arg-type]


@router.put("/{kb_id}/members", status_code=200, response_model=MemberResponse)
def grant_member(
    payload: GrantMemberRequest,
    kb_id: KbManagerDep,
    session: SessionDep,
    request_id: RequestIdDep,
) -> MemberResponse:
    return _member_response(
        session,
        kb_id=kb_id,
        user_id=_parse_uuid(payload.user_id),
        role=KbRole(payload.role),
        request_id=request_id,
    )


@router.delete("/{kb_id}/members/{user_id}", status_code=200)
def revoke_member(
    kb_id: KbManagerDep,
    user_id: uuid.UUID,
    session: SessionDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    kb_grant_service.revoke_grant(session, user_id=user_id, kb_id=kb_id)
    return {"request_id": request_id, "user_id": str(user_id), "revoked": True}


def _member_response(
    session: Session,
    *,
    kb_id: uuid.UUID,
    user_id: uuid.UUID,
    role: KbRole,
    request_id: str,
) -> MemberResponse:
    grant = kb_grant_service.grant_role(
        session, user_id=user_id, kb_id=kb_id, role=role
    )
    account = kb_grant_service.get_member(session, user_id=grant.user_id)
    return MemberResponse(
        request_id=request_id,
        user_id=str(account.id),
        username=account.username,
        display_name=account.display_name,
        role=str(grant.role),
    )


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        # 路径/请求体里的非法 UUID 属参数错误：422 比 404 更准确
        raise NotFoundError("用户不存在") from exc

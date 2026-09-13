"""账号管理路由（§6.7–6.8），全部仅限 ADMIN（require_role）。

路由层只做参数声明、依赖装配与响应组装；业务逻辑在 `user_service`（6.13）。
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.deps import current_request_id, require_role
from app.core.db import get_db
from app.schemas.base import ApiResponse
from app.schemas.user import (
    AccountResponse,
    AccountSummary,
    CreateAccountRequest,
    ListAccountsResponse,
    ResetPasswordRequest,
    UpdateAccountRequest,
)
from app.services import user_service

router = APIRouter(
    prefix="/api/v1/users",
    tags=["users"],
    dependencies=[Depends(require_role("ADMIN"))],
)

SessionDep = Annotated[Session, Depends(get_db)]
RequestIdDep = Annotated[str, Depends(current_request_id)]


def _to_summary(account: object) -> AccountSummary:
    return AccountSummary(
        id=str(account.id),  # type: ignore[attr-defined]
        username=account.username,  # type: ignore[attr-defined]
        display_name=account.display_name,  # type: ignore[attr-defined]
        is_active=account.is_active,  # type: ignore[attr-defined]
        system_role=account.system_role,  # type: ignore[attr-defined]
    )


def _to_response(account: object) -> AccountResponse:
    return AccountResponse(
        request_id="",
        **_to_summary(account).model_dump(),
    )


@router.post("", status_code=201, response_model=AccountResponse)
def create_account(
    payload: CreateAccountRequest, session: SessionDep, request_id: RequestIdDep
) -> AccountResponse:
    account = user_service.create_account(
        session,
        username=payload.username,
        display_name=payload.display_name,
        password=payload.password,
        system_role=payload.system_role,
    )
    response = _to_response(account)
    response.request_id = request_id
    return response


@router.get("", response_model=ListAccountsResponse)
def list_accounts(
    session: SessionDep,
    request_id: RequestIdDep,
    page: int = Query(default=1, ge=1),
    size: int = Query(default=20, ge=1, le=100),
) -> ListAccountsResponse:
    items, total = user_service.list_accounts(session, page=page, size=size)
    return ListAccountsResponse(
        request_id=request_id,
        items=[_to_summary(item) for item in items],
        page=page,
        size=size,
        total=total,
        has_more=page * size < total,
    )


@router.get("/{account_id}", response_model=AccountResponse)
def get_account(
    account_id: uuid.UUID, session: SessionDep, request_id: RequestIdDep
) -> AccountResponse:
    account = user_service.get_account(session, account_id)
    response = _to_response(account)
    response.request_id = request_id
    return response


@router.patch("/{account_id}", response_model=AccountResponse)
def update_account(
    account_id: uuid.UUID,
    payload: UpdateAccountRequest,
    session: SessionDep,
    request_id: RequestIdDep,
) -> AccountResponse:
    account = user_service.update_account(
        session,
        account_id,
        display_name=payload.display_name,
        system_role=payload.system_role,
    )
    response = _to_response(account)
    response.request_id = request_id
    return response


@router.post("/{account_id}/deactivate", response_model=AccountResponse)
def deactivate_account(
    account_id: uuid.UUID, session: SessionDep, request_id: RequestIdDep
) -> AccountResponse:
    account = user_service.set_account_active(session, account_id, active=False)
    response = _to_response(account)
    response.request_id = request_id
    return response


@router.post("/{account_id}/activate", response_model=AccountResponse)
def activate_account(
    account_id: uuid.UUID, session: SessionDep, request_id: RequestIdDep
) -> AccountResponse:
    account = user_service.set_account_active(session, account_id, active=True)
    response = _to_response(account)
    response.request_id = request_id
    return response


@router.delete("/{account_id}", response_model=ApiResponse)
def delete_account(
    account_id: uuid.UUID, session: SessionDep, request_id: RequestIdDep
) -> ApiResponse:
    """软删成功返回仅含 `request_id` 的确认（账号随后在列表/详情中不可见）。"""
    user_service.soft_delete_account(session, account_id)
    return ApiResponse(request_id=request_id)


@router.post("/{account_id}/reset-password", response_model=AccountResponse)
def reset_password(
    account_id: uuid.UUID,
    payload: ResetPasswordRequest,
    session: SessionDep,
    request_id: RequestIdDep,
) -> AccountResponse:
    user_service.reset_password(session, account_id, new_password=payload.new_password)
    account = user_service.get_account(session, account_id)
    response = _to_response(account)
    response.request_id = request_id
    return response

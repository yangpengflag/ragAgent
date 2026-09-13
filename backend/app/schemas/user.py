"""账号管理请求/响应模型（§6.7）。

契约见 `specs/identity/spec.md`：任何响应不含密码或哈希；
列表用统一分页信封（`request_id` + `items` / `page` / `size` / `total` / `has_more`）。
`UpdateAccountRequest` 不定义 `username` 字段——请求体携带也会被忽略（spec：用户名不可改）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import ApiResponse


class AccountSummary(BaseModel):
    """账号摘要（管理视角，含启用状态）。永不含密码字段。"""

    id: str
    username: str
    display_name: str
    is_active: bool
    system_role: str


class CreateAccountRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    # display_name 上限与模型列宽对齐（128）
    display_name: str = Field(min_length=1, max_length=128)
    # 密码不加 Field 长度约束：统一交给 validate_password_strength，
    # 保证 422 的 details 永远携带 rule 标识（spec 要求），而非字段路径
    password: str
    system_role: str = Field(default="MEMBER", pattern="^(ADMIN|MEMBER)$")


class UpdateAccountRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    system_role: str | None = Field(default=None, pattern="^(ADMIN|MEMBER)$")


class ResetPasswordRequest(BaseModel):
    new_password: str


class ListQuery(BaseModel):
    page: int = Field(default=1, ge=1)
    size: int = Field(default=20, ge=1, le=100)


class AccountResponse(ApiResponse):
    """单个账号的响应（创建 / 详情 / 更新 / 状态变更共用）。"""

    id: str
    username: str
    display_name: str
    is_active: bool
    system_role: str


class ListAccountsResponse(ApiResponse):
    """分页信封（design D16 指向 api-conventions 的统一形状）。"""

    items: list[AccountSummary]
    page: int
    size: int
    total: int
    has_more: bool

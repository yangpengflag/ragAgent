"""认证相关请求/响应模型。

契约见 `specs/authentication/spec.md`：登录响应含 `user` 摘要，
刷新响应**不含** `user`；刷新令牌只走 HttpOnly Cookie，永不出现在响应体。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import ApiResponse


class UserSummary(BaseModel):
    """账号摘要（`user` 字段）。永不含密码/哈希字段。"""

    id: str
    username: str
    display_name: str
    system_role: str


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class LoginResponse(ApiResponse):
    access_token: str
    token_type: str
    expires_in: int = Field(description="访问令牌有效期（秒）")
    user: UserSummary


class RefreshResponse(ApiResponse):
    access_token: str
    token_type: str
    expires_in: int


class LogoutResponse(ApiResponse):
    pass

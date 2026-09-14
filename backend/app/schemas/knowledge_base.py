"""知识库与成员授权的请求/响应模型。

字段名与后端 JSON 一致（snake_case），响应不含任何内部字段（如 `name_active` 派生列）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.base import ApiResponse

KB_ROLE_PATTERN = "^(KB_ADMIN|EDITOR|VIEWER)$"


class KnowledgeBaseSummary(BaseModel):
    """知识库摘要。"""

    id: str
    name: str
    description: str | None
    embedding_model: str
    embed_dim: int


class CreateKnowledgeBaseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    embedding_model: str = Field(min_length=1, max_length=64)
    embed_dim: int = Field(gt=0)


class UpdateKnowledgeBaseRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=128)
    description: str | None = Field(default=None, max_length=512)
    embedding_model: str | None = Field(default=None, min_length=1, max_length=64)
    embed_dim: int | None = Field(default=None, gt=0)


class KnowledgeBaseResponse(ApiResponse):
    """单个知识库响应（创建 / 详情 / 更新共用）。"""

    id: str
    name: str
    description: str | None
    embedding_model: str
    embed_dim: int


class ListKnowledgeBasesResponse(ApiResponse):
    items: list[KnowledgeBaseSummary]


class GrantMemberRequest(BaseModel):
    user_id: str = Field(min_length=1)
    role: str = Field(pattern=KB_ROLE_PATTERN)


class MemberSummary(BaseModel):
    user_id: str
    username: str
    display_name: str
    role: str


class MemberResponse(ApiResponse):
    """单个成员响应（授予 / 改角色共用）。"""

    user_id: str
    username: str
    display_name: str
    role: str


class ListMembersResponse(ApiResponse):
    items: list[MemberSummary]

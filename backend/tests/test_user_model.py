"""账号模型红灯（auth-and-users 任务 3.1 / 3.4）。

在 SQLite 内存库上验证模型行为（不依赖 MySQL）：
- 公共字段与账号默认值
- 用户名的唯一性语义：**活跃账号唯一、软删账号让位**
- 软删账号对默认查询不可见（登录路径依赖这一点）
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.base import INCLUDE_SOFT_DELETED
from app.models.user import Account, SystemRole


def _new_account(username: str = "alice", **overrides: object) -> Account:
    payload: dict[str, object] = {
        "username": username,
        "display_name": username.title(),
        "password_hash": "$argon2id$placeholder",
    }
    payload.update(overrides)
    return Account(**payload)  # type: ignore[arg-type]


def _with_soft_deleted(session: Session, account_id: uuid.UUID) -> Account | None:
    return (
        session.execute(
            select(Account)
            .where(Account.id == account_id)
            .execution_options(**{INCLUDE_SOFT_DELETED: True})
        )
        .scalars()
        .one_or_none()
    )


def test_account_public_fields_and_defaults(sqlite_session):
    """主键/时间戳自动填充；账号默认值符合契约（成员、启用、纪元 0）。"""
    account = _new_account()
    sqlite_session.add(account)
    sqlite_session.commit()

    assert isinstance(account.id, uuid.UUID)
    assert account.created_at is not None
    assert account.updated_at is not None
    assert account.deleted_at is None
    assert account.is_active is True
    assert account.system_role is SystemRole.MEMBER
    assert account.session_epoch == 0


def test_system_role_is_stored_as_string(sqlite_session):
    """规约要求用字符串存枚举（禁止存 ordinal）。"""
    account = _new_account(username="root", system_role=SystemRole.ADMIN)
    sqlite_session.add(account)
    sqlite_session.commit()

    stored = sqlite_session.execute(
        select(Account.system_role).where(Account.id == account.id)
    ).scalar_one()

    assert stored == "ADMIN"


def test_duplicate_active_username_is_rejected(sqlite_session):
    """两个活跃账号不得同名（并发创建依赖数据库约束，而非"先查后插"）。"""
    sqlite_session.add(_new_account(username="dup"))
    sqlite_session.commit()

    sqlite_session.add(_new_account(username="dup"))
    with pytest.raises(IntegrityError):
        sqlite_session.commit()
    sqlite_session.rollback()


def test_username_active_follows_soft_delete(sqlite_session):
    """派生列语义：活跃 = username，软删 = NULL。"""
    account = _new_account(username="bob")
    sqlite_session.add(account)
    sqlite_session.commit()

    assert _with_soft_deleted(sqlite_session, account.id).username_active == "bob"  # type: ignore[union-attr]

    account.soft_delete()
    sqlite_session.commit()

    assert _with_soft_deleted(sqlite_session, account.id).username_active is None  # type: ignore[union-attr]


def test_soft_deleted_username_can_be_reused(sqlite_session):
    """软删后同名可重建，且默认查询命中的是新账号（任务 3.4）。"""
    first = _new_account(username="carol")
    sqlite_session.add(first)
    sqlite_session.commit()
    first_id = first.id

    first.soft_delete()
    sqlite_session.commit()

    second = _new_account(username="carol", display_name="Carol II")
    sqlite_session.add(second)
    sqlite_session.commit()  # 不应冲突

    visible = sqlite_session.execute(
        select(Account).where(Account.username == "carol")
    ).scalars().all()

    assert [row.id for row in visible] == [second.id]
    assert first_id != second.id


def test_soft_deleted_account_is_invisible_to_default_queries(sqlite_session):
    """登录/列表路径必须看不到软删账号（否则等于"删了还能登录"）。

    注意：`session.get()` 命中的是身份映射缓存，因此必须先 `expire_all()`
    模拟"新请求 = 新查询"的真实路径；否则同一个 Session 内 `get()` 会直接
    返回已加载的软删对象，把全局过滤器绕过去。

    经过身份映射刷新后，`get()` 找不到行会抛 `ObjectDeletedError`——这是 SA 2.0
    在"行已被过滤掉、但实例已加载"时的标准行为，比返回 `None` 更明确地表达
    "该 PK 已不存在"。
    """
    from sqlalchemy.orm.exc import ObjectDeletedError

    account = _new_account(username="dave")
    sqlite_session.add(account)
    sqlite_session.commit()
    account.soft_delete()
    sqlite_session.commit()

    sqlite_session.expire_all()  # 迫使下一次查询走数据库、重过 SELECT 过滤器

    assert sqlite_session.execute(select(Account)).scalars().all() == []
    with pytest.raises(ObjectDeletedError):
        sqlite_session.get(Account, account.id)

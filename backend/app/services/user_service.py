"""账号管理服务（§6.7–6.10）。

所有写操作遵循 design D14：重置密码 / 停用 / 软删 / 改角色都会
`session_epoch += 1`，使该账号既有刷新令牌立即失效。
「最后一个已启用 ADMIN」保护用事务内 `SELECT ... FOR UPDATE` 串行化（6.10）。
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.security import hash_password, validate_password_strength
from app.models.user import Account, SystemRole

logger = get_logger()


def _guard_not_last_active_admin(session: Session, account: Account) -> None:
    """目标是唯一已启用 ADMIN 且本次操作会使其失去管理员能力 → 409。

    `FOR UPDATE` 把"数其他管理员"与后续写操作放进同一把锁，
    并发停用/降级时后到者会阻塞至前者提交，再数到 0 而被拒。
    （SQLite 方言忽略 FOR UPDATE，仅影响并发测试真实性，语义单测已覆盖。）
    """
    if account.system_role != "ADMIN" or not account.is_active:
        return
    others = session.execute(
        select(func.count())
        .select_from(Account)
        .where(
            Account.system_role == "ADMIN",
            Account.is_active.is_(True),
            Account.id != account.id,
        )
        .with_for_update()
    ).scalar_one()
    if others == 0:
        raise ConflictError("不能停用、降级或删除最后一个已启用的管理员")


def create_account(
    session: Session,
    *,
    username: str,
    display_name: str,
    password: str,
    system_role: str = "MEMBER",
) -> Account:
    """创建账号；用户名冲突与弱密码分别转为 409 / 422。"""
    validate_password_strength(password, username=username)
    account = Account(
        username=username,
        display_name=display_name,
        password_hash=hash_password(password),
        system_role=system_role,
    )
    session.add(account)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        # 用户名不是敏感信息，错误信息可指名；密码只以规则标识出现在 422
        raise ConflictError(f"用户名已存在: {username}") from exc
    logger.info(
        "account created",
        username=account.username,
        account_id=str(account.id),
        system_role=account.system_role,
    )
    return account


def list_accounts(
    session: Session, *, page: int, size: int
) -> tuple[list[Account], int]:
    """分页列出账号；全局软删过滤自动排除已删行，total 亦不含。"""
    total = session.execute(select(func.count()).select_from(Account)).scalar_one()
    items = list(
        session.execute(
            select(Account)
            .order_by(Account.created_at.desc(), Account.id)
            .offset((page - 1) * size)
            .limit(size)
        ).scalars()
    )
    return items, total


def get_account(session: Session, account_id: uuid.UUID) -> Account:
    """按 ID 取账号；不存在或已软删 → 404（软删行被全局过滤挡住，与不存在同路）。"""
    account = session.execute(
        select(Account).where(Account.id == account_id)
    ).scalar_one_or_none()
    if account is None:
        raise NotFoundError("账号不存在")
    return account


def update_account(
    session: Session,
    account_id: uuid.UUID,
    *,
    display_name: str | None = None,
    system_role: str | None = None,
) -> Account:
    """修改显示名与/或系统角色；用户名不可改（请求模型中根本没有该字段）。"""
    account = get_account(session, account_id)
    if display_name is not None:
        account.display_name = display_name
    if system_role is not None and system_role != account.system_role:
        # 降级（ADMIN → MEMBER）前先做最后一个管理员保护
        _guard_not_last_active_admin(session, account)
        account.system_role = SystemRole(system_role)
        account.session_epoch += 1  # design D14：改角色使既有刷新令牌失效
    session.commit()
    logger.info(
        "account updated",
        username=account.username,
        account_id=str(account.id),
        system_role=account.system_role,
    )
    return account


def set_account_active(
    session: Session, account_id: uuid.UUID, *, active: bool
) -> Account:
    """停用 / 重新启用；停用走最后一个管理员保护。"""
    account = get_account(session, account_id)
    if account.is_active == active:
        return account  # 幂等：重复停用/启用不再重复 bump 纪元
    if not active:
        _guard_not_last_active_admin(session, account)
    account.is_active = active
    account.session_epoch += 1  # design D14：停用使既有刷新令牌失效
    session.commit()
    logger.info(
        "account activated" if active else "account deactivated",
        username=account.username,
        account_id=str(account.id),
    )
    return account


def soft_delete_account(session: Session, account_id: uuid.UUID) -> None:
    """标记式删除；幂等（已删则直接返回）。"""
    account = get_account(session, account_id)
    if account.deleted_at is not None:
        return
    _guard_not_last_active_admin(session, account)
    account.soft_delete()
    account.session_epoch += 1  # design D14：软删使既有刷新令牌失效
    session.commit()
    logger.info("account deleted", username=account.username, account_id=str(account.id))


def reset_password(session: Session, account_id: uuid.UUID, *, new_password: str) -> None:
    """管理员重置密码；受强度策略约束，成功后旧密码与既有刷新令牌立即失效。"""
    account = get_account(session, account_id)
    validate_password_strength(new_password, username=account.username)
    account.password_hash = hash_password(new_password)
    account.session_epoch += 1  # design D14
    session.commit()
    # 日志不含密码原文（审计要求 6.11）
    logger.info(
        "account password reset", username=account.username, account_id=str(account.id)
    )

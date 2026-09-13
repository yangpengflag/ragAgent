"""数据库骨架红灯（任务 5.1 / 5.3）。

覆盖 spec Requirement「通用实体字段由基类统一提供」（用 SQLite 内存库验证，
不触碰 MySQL）与「数据库会话按请求生命周期管理」。
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import get_db
from app.models.base import INCLUDE_SOFT_DELETED, BaseModel


class Widget(BaseModel):
    """仅测试用的具体模型，用于验证公共 mixin 行为。"""

    __tablename__ = "widgets"

    name: Mapped[str] = mapped_column(nullable=False)


def test_public_fields_are_auto_filled(sqlite_session):
    widget = Widget(name="alpha")
    sqlite_session.add(widget)
    sqlite_session.commit()

    assert isinstance(widget.id, uuid.UUID)
    assert widget.created_at is not None
    assert widget.updated_at is not None
    assert widget.deleted_at is None


def test_timestamps_are_naive_utc(sqlite_session):
    widget = Widget(name="beta")
    sqlite_session.add(widget)
    sqlite_session.commit()

    assert widget.created_at.tzinfo is None
    drift = abs(datetime.now(UTC).replace(tzinfo=None) - widget.created_at)
    assert drift.total_seconds() < 60, "时间戳应为 UTC，而非本机时区时间"


def test_created_at_is_not_updated(sqlite_session):
    widget = Widget(name="gamma")
    sqlite_session.add(widget)
    sqlite_session.commit()
    created_before = widget.created_at
    updated_before = widget.updated_at

    time.sleep(0.01)
    widget.name = "gamma-renamed"
    sqlite_session.commit()

    assert widget.created_at == created_before
    assert widget.updated_at > updated_before


def test_soft_delete_keeps_row(sqlite_session):
    """软删只写标记，行仍在表中（auth-and-users §2 起默认查询会过滤它）。"""
    widget = Widget(name="delta")
    sqlite_session.add(widget)
    sqlite_session.commit()
    widget_id = widget.id

    widget.soft_delete()
    sqlite_session.commit()
    sqlite_session.expire_all()

    stored = (
        sqlite_session.execute(
            select(Widget)
            .where(Widget.id == widget_id)
            .execution_options(**{INCLUDE_SOFT_DELETED: True})
        )
        .scalars()
        .one()
    )
    assert stored.deleted_at is not None, "软删不得物理删除行"


def test_soft_deleted_rows_are_excluded_by_default(sqlite_session):
    """全局软删过滤：默认查询查不到已软删行（auth-and-users 任务 2.1）。"""
    kept = Widget(name="keep")
    removed = Widget(name="gone")
    sqlite_session.add_all([kept, removed])
    sqlite_session.commit()

    removed.soft_delete()
    sqlite_session.commit()

    names = [row.name for row in sqlite_session.execute(select(Widget)).scalars()]
    assert names == ["keep"]


def test_statement_level_escape_hatch_includes_soft_deleted(sqlite_session):
    """逃生通道（语句级）：显式声明后能查到已软删行。"""
    widget = Widget(name="epsilon")
    sqlite_session.add(widget)
    sqlite_session.commit()
    widget.soft_delete()
    sqlite_session.commit()

    rows = (
        sqlite_session.execute(
            select(Widget).execution_options(**{INCLUDE_SOFT_DELETED: True})
        )
        .scalars()
        .all()
    )

    assert [row.name for row in rows] == ["epsilon"]


def test_soft_delete_is_idempotent(sqlite_session):
    """重复软删不得覆盖首次删除时间（auth-and-users 任务 2.3）。"""
    widget = Widget(name="eta")
    sqlite_session.add(widget)
    sqlite_session.commit()

    widget.soft_delete()
    first = widget.deleted_at
    time.sleep(0.01)
    widget.soft_delete()
    sqlite_session.commit()

    assert widget.deleted_at == first


def test_session_get_is_also_filtered(sqlite_session):
    """`Session.get()` 同样受软删过滤（实测确认，非假设）。

    这条很重要：如果按主键加载能绕过过滤，"软删账号被当成有效账号"就会从
    `get()` 这条路径漏出来。用另一个会话验证，避免命中身份映射看不出真实行为。
    """
    widget = Widget(name="theta")
    sqlite_session.add(widget)
    sqlite_session.commit()
    widget_id = widget.id
    widget.soft_delete()
    sqlite_session.commit()

    other = Session(bind=sqlite_session.get_bind())
    try:
        assert other.get(Widget, widget_id) is None
    finally:
        other.close()


def _spy_on_session_close(monkeypatch) -> list[Session]:
    """记录被关闭的会话（Session.close() 后对象仍可复用，不能用 is_active 判断）。"""
    closed: list[Session] = []
    original_close = Session.close

    def _close(self: Session) -> None:
        closed.append(self)
        original_close(self)

    monkeypatch.setattr(Session, "close", _close)
    return closed


def test_get_db_closes_session_on_success(monkeypatch):
    closed = _spy_on_session_close(monkeypatch)

    generator = get_db()
    session = next(generator)
    generator.close()  # 模拟请求正常结束

    assert closed == [session], "请求结束后必须关闭会话"


def test_get_db_closes_session_on_error(monkeypatch):
    closed = _spy_on_session_close(monkeypatch)

    generator = get_db()
    session = next(generator)

    with pytest.raises(RuntimeError):
        generator.throw(RuntimeError("boom"))

    assert closed == [session], "异常路径同样必须关闭会话"

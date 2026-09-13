"""数据库骨架红灯（任务 5.1 / 5.3）。

覆盖 spec Requirement「通用实体字段由基类统一提供」（用 SQLite 内存库验证，
不触碰 MySQL）与「数据库会话按请求生命周期管理」。
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.orm import Mapped, Session, mapped_column

from app.core.db import get_db
from app.models.base import BaseModel


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
    widget = Widget(name="delta")
    sqlite_session.add(widget)
    sqlite_session.commit()
    widget_id = widget.id

    widget.soft_delete()
    sqlite_session.commit()
    sqlite_session.expire_all()

    stored = sqlite_session.get(Widget, widget_id)
    assert stored is not None, "软删不得物理删除行"
    assert stored.deleted_at is not None


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
